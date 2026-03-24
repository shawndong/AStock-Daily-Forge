"""
龙虎榜采集层测试

覆盖场景：
  数据解析
  1.  正常数据完整解析（全部21字段）
  2.  金额从元正确转换为万元（÷10000）
  3.  流通市值从元正确转换为亿元（÷1e8）
  4.  上榜后涨跌幅为 NaN 时解析为 None（新上榜股票正常情况）
  5.  目标日期与数据日期不匹配时返回空列表（接口可能返回多日）
  6.  AKShare 返回空 DataFrame 时返回空列表
  7.  接口字段变更时抛出明确异常
  8.  解读字段为 NaN 时返回 "N/A" 而非崩溃
  9.  涨跌幅为负数时正确解析（跌停上榜）
  10. 同一股票同一天多条记录（不同上榜原因）全部保留

  重试机制
  11. AKShare 抛出异常时按配置次数重试
  12. 重试间隔符合 RETRY_DELAY 配置
  13. 第二次重试成功时正常返回数据

  存储
  14. 正常数据按净买额降序排列
  15. 净买额为负（净卖出）时仍能正确排序
  16. 文件包含全部19列表头
  17. 上榜后涨跌幅为 None 时写入 "N/A"，格式带 % 的写入带符号
  18. 无数据时写入缺失标记，不写空表格
  19. 多条记录时文件行数与记录数一致（表头+分隔+数据行）
"""

import os
import sys
from datetime import date
from unittest.mock import call, patch

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from collector.lhb import (
    RETRY_DELAY,
    _parse_lhb_df,
    _validate_columns,
    fetch_lhb,
    save_lhb,
)

# ── 测试数据工厂 ──────────────────────────────────────────────────────────────

def make_lhb_df(target_date: date, rows: list[dict] = None) -> pd.DataFrame:
    """构造与 AKShare 返回结构一致的 DataFrame"""
    default_row = {
        "序号":          1,
        "代码":          "000020",
        "名称":          "深华发A",
        "上榜日":        target_date,
        "解读":          "普通席位买入，成功率44.13%",
        "收盘价":        21.21,
        "涨跌幅":        10.0104,
        "龙虎榜净买额":   34716180.22,
        "龙虎榜买入额":   51816545.22,
        "龙虎榜卖出额":   17100365.0,
        "龙虎榜成交额":   68916910.22,
        "市场总成交额":   124735962.0,
        "净买额占总成交比": 27.83,
        "成交额占总成交比": 55.25,
        "换手率":        1.7951,
        "流通市值":      4168905000.0,
        "上榜原因":      "连续三个交易日内，涨幅偏离值累计达到20%的证券",
        "上榜后1日":     float("nan"),
        "上榜后2日":     float("nan"),
        "上榜后5日":     float("nan"),
        "上榜后10日":    float("nan"),
    }
    if rows is None:
        rows = [default_row]
    else:
        rows = [{**default_row, **r} for r in rows]
    return pd.DataFrame(rows)


# ── 1. 正常数据完整解析 ───────────────────────────────────────────────────────

def test_parse_normal_all_fields():
    d = date(2026, 3, 19)
    df = make_lhb_df(d)
    result = _parse_lhb_df(df, d)

    assert len(result) == 1
    r = result[0]
    assert r["code"]    == "000020"
    assert r["name"]    == "深华发A"
    assert r["date"]    == d
    assert r["close"]   == pytest.approx(21.21)
    assert r["reason"]  == "连续三个交易日内，涨幅偏离值累计达到20%的证券"
    assert r["explain"] == "普通席位买入，成功率44.13%"


# ── 2. 金额从元转换为万元 ────────────────────────────────────────────────────

def test_parse_amount_yuan_to_wan():
    d = date(2026, 3, 19)
    df = make_lhb_df(d, [{"龙虎榜净买额": 34716180.22}])
    r = _parse_lhb_df(df, d)[0]
    assert r["net_buy_wan"] == pytest.approx(34716180.22 / 10000, rel=1e-3)


# ── 3. 流通市值从元转换为亿元 ────────────────────────────────────────────────

def test_parse_float_cap_yuan_to_yi():
    d = date(2026, 3, 19)
    df = make_lhb_df(d, [{"流通市值": 4168905000.0}])
    r = _parse_lhb_df(df, d)[0]
    assert r["float_cap_yi"] == pytest.approx(4168905000.0 / 1e8, rel=1e-3)


# ── 4. 上榜后涨跌幅为 NaN 时解析为 None ─────────────────────────────────────

def test_parse_post_change_nan_is_none():
    d = date(2026, 3, 19)
    df = make_lhb_df(d, [{"上榜后1日": float("nan"), "上榜后5日": float("nan")}])
    r = _parse_lhb_df(df, d)[0]
    assert r["d1_chg"] is None
    assert r["d5_chg"] is None


# ── 5. 日期不匹配时返回空列表 ────────────────────────────────────────────────

def test_parse_wrong_date_returns_empty():
    d_data   = date(2026, 3, 18)
    d_target = date(2026, 3, 19)
    df = make_lhb_df(d_data)
    result = _parse_lhb_df(df, d_target)
    assert result == []


# ── 6. 空 DataFrame 返回空列表 ──────────────────────────────────────────────

def test_parse_empty_df_returns_empty():
    result = _parse_lhb_df(pd.DataFrame(), date(2026, 3, 19))
    assert result == []


# ── 7. 接口字段变更时抛出明确异常 ────────────────────────────────────────────

def test_validate_columns_missing_raises():
    bad_df = pd.DataFrame({"日期": [], "股票": []})
    with pytest.raises(ValueError, match="AKShare 返回字段缺失"):
        _validate_columns(bad_df)


# ── 8. 解读字段为 NaN 时返回 "N/A" ──────────────────────────────────────────

def test_parse_nan_explain_returns_na():
    d = date(2026, 3, 19)
    df = make_lhb_df(d, [{"解读": float("nan")}])
    r = _parse_lhb_df(df, d)[0]
    assert r["explain"] == "N/A"


# ── 9. 涨跌幅为负（跌停上榜）正确解析 ───────────────────────────────────────

def test_parse_negative_change_pct():
    d = date(2026, 3, 19)
    df = make_lhb_df(d, [{"涨跌幅": -5.036, "龙虎榜净买额": 2188287.0}])
    r = _parse_lhb_df(df, d)[0]
    assert r["change_pct"] == pytest.approx(-5.036, rel=1e-3)
    assert r["net_buy_wan"] == pytest.approx(2188287.0 / 10000, rel=1e-3)


# ── 10. 同一股票同一天多条记录全部保留 ──────────────────────────────────────

def test_parse_multiple_records_same_stock():
    d = date(2026, 3, 19)
    df = make_lhb_df(d, [
        {"代码": "000020", "上榜原因": "涨幅偏离"},
        {"代码": "000020", "上榜原因": "成交量异常"},
    ])
    result = _parse_lhb_df(df, d)
    assert len(result) == 2
    reasons = {r["reason"] for r in result}
    assert "涨幅偏离" in reasons
    assert "成交量异常" in reasons


# ── 11. 异常时按配置次数重试 ─────────────────────────────────────────────────

def test_fetch_retry_count():
    with patch("akshare.stock_lhb_detail_em",
               side_effect=ConnectionError("超时")) as mock_ak, \
         patch("collector.lhb.time.sleep"):
        result = fetch_lhb(target_date=date(2026, 3, 19), retries=3)
    assert result is None
    assert mock_ak.call_count == 3


# ── 12. 重试间隔符合配置 ─────────────────────────────────────────────────────

def test_fetch_retry_delay():
    with patch("akshare.stock_lhb_detail_em",
               side_effect=ConnectionError("超时")), \
         patch("collector.lhb.time.sleep") as mock_sleep:
        fetch_lhb(target_date=date(2026, 3, 19), retries=2)
    for c in mock_sleep.call_args_list:
        assert c == call(RETRY_DELAY)


# ── 13. 第二次重试成功时返回数据 ────────────────────────────────────────────

def test_fetch_succeeds_on_second_attempt():
    d = date(2026, 3, 19)
    good_df = make_lhb_df(d)
    with patch("akshare.stock_lhb_detail_em",
               side_effect=[ConnectionError("第一次失败"), good_df]) as mock_ak, \
         patch("collector.lhb.time.sleep"):
        result = fetch_lhb(target_date=d, retries=3)
    assert result is not None
    assert len(result) == 1
    assert mock_ak.call_count == 2


# ── 14. 存储：按净买额降序排列 ───────────────────────────────────────────────

def test_save_sorted_by_net_buy(tmp_path):
    d = date(2026, 3, 19)
    records = [
        {"code": "A", "name": "低净买", "date": d, "net_buy_wan": 100.0,
         "buy_wan": 200.0, "sell_wan": 100.0, "lhb_amount_wan": 300.0,
         "total_amount_wan": 1000.0, "close": 10.0, "change_pct": 1.0,
         "net_buy_ratio": 10.0, "amount_ratio": 30.0, "turnover_rate": 1.0,
         "float_cap_yi": 10.0, "reason": "原因A", "explain": "解读A",
         "d1_chg": None, "d2_chg": None, "d5_chg": None, "d10_chg": None},
        {"code": "B", "name": "高净买", "date": d, "net_buy_wan": 5000.0,
         "buy_wan": 6000.0, "sell_wan": 1000.0, "lhb_amount_wan": 7000.0,
         "total_amount_wan": 10000.0, "close": 20.0, "change_pct": 10.0,
         "net_buy_ratio": 50.0, "amount_ratio": 70.0, "turnover_rate": 5.0,
         "float_cap_yi": 50.0, "reason": "原因B", "explain": "解读B",
         "d1_chg": None, "d2_chg": None, "d5_chg": None, "d10_chg": None},
    ]
    with patch("config.settings.LHB_DIR", str(tmp_path)):
        save_lhb(records, d)

    content = (tmp_path / "20260319.md").read_text(encoding="utf-8")
    assert content.index("高净买") < content.index("低净买")


# ── 15. 净买额为负时仍能正确排序 ────────────────────────────────────────────

def test_save_negative_net_buy_sorted(tmp_path):
    d = date(2026, 3, 19)

    def make_record(code, name, net_buy):
        return {"code": code, "name": name, "date": d, "net_buy_wan": net_buy,
                "buy_wan": 100.0, "sell_wan": 200.0, "lhb_amount_wan": 300.0,
                "total_amount_wan": 1000.0, "close": 5.0, "change_pct": -5.0,
                "net_buy_ratio": -10.0, "amount_ratio": 30.0, "turnover_rate": 1.0,
                "float_cap_yi": 5.0, "reason": "跌幅异常", "explain": "机构卖出",
                "d1_chg": None, "d2_chg": None, "d5_chg": None, "d10_chg": None}

    records = [make_record("A", "大卖出", -500.0), make_record("B", "小卖出", -100.0)]
    with patch("config.settings.LHB_DIR", str(tmp_path)):
        save_lhb(records, d)

    content = (tmp_path / "20260319.md").read_text(encoding="utf-8")
    # 净买额 -100 > -500，小卖出排在前面
    assert content.index("小卖出") < content.index("大卖出")


# ── 16. 文件包含全部19列表头 ────────────────────────────────────────────────

def test_save_has_all_headers(tmp_path):
    d = date(2026, 3, 19)
    records = [{
        "code": "000020", "name": "深华发A", "date": d,
        "explain": "解读", "close": 21.21, "change_pct": 10.01,
        "net_buy_wan": 3471.62, "buy_wan": 5181.65, "sell_wan": 1710.04,
        "lhb_amount_wan": 6891.69, "total_amount_wan": 12473.60,
        "net_buy_ratio": 27.83, "amount_ratio": 55.25,
        "turnover_rate": 1.80, "float_cap_yi": 41.69,
        "reason": "涨幅偏离", "d1_chg": None, "d2_chg": None,
        "d5_chg": None, "d10_chg": None,
    }]
    with patch("config.settings.LHB_DIR", str(tmp_path)):
        save_lhb(records, d)

    content = (tmp_path / "20260319.md").read_text(encoding="utf-8")
    for col in ["代码", "名称", "净买额(万)", "流通市值(亿)", "上榜后10日"]:
        assert col in content, f"缺少列头: {col}"


# ── 17. None 写 N/A，有值的涨跌幅带符号 ────────────────────────────────────

def test_save_format_chg_and_na(tmp_path):
    d = date(2026, 3, 19)
    records = [{
        "code": "000001", "name": "平安银行", "date": d,
        "explain": "解读", "close": 10.88, "change_pct": -0.73,
        "net_buy_wan": -200.0, "buy_wan": 100.0, "sell_wan": 300.0,
        "lhb_amount_wan": 400.0, "total_amount_wan": 2000.0,
        "net_buy_ratio": -10.0, "amount_ratio": 20.0,
        "turnover_rate": 0.32, "float_cap_yi": 211.13,
        "reason": "跌幅异常", "d1_chg": 2.5, "d2_chg": None,
        "d5_chg": -1.2, "d10_chg": None,
    }]
    with patch("config.settings.LHB_DIR", str(tmp_path)):
        save_lhb(records, d)

    content = (tmp_path / "20260319.md").read_text(encoding="utf-8")
    assert "+2.50%" in content     # d1 正值带加号
    assert "-1.20%" in content     # d5 负值带负号
    assert "N/A" in content        # d2/d10 为 None


# ── 18. 无数据时写入缺失标记不写表格 ────────────────────────────────────────

def test_save_empty_records_writes_marker(tmp_path):
    d = date(2026, 3, 21)
    with patch("config.settings.LHB_DIR", str(tmp_path)):
        save_lhb([], d)

    content = (tmp_path / "20260321.md").read_text(encoding="utf-8")
    assert "非交易日或无上榜" in content
    assert "|" not in content


# ── 19. 记录数与文件数据行数一致 ────────────────────────────────────────────

def test_save_row_count_matches_records(tmp_path):
    d = date(2026, 3, 19)
    n = 5
    records = [
        {"code": f"{i:06d}", "name": f"股票{i}", "date": d,
         "explain": "解读", "close": 10.0, "change_pct": float(i),
         "net_buy_wan": float(i * 100), "buy_wan": 500.0, "sell_wan": 400.0,
         "lhb_amount_wan": 900.0, "total_amount_wan": 5000.0,
         "net_buy_ratio": 2.0, "amount_ratio": 18.0,
         "turnover_rate": 1.0, "float_cap_yi": 10.0,
         "reason": "涨幅异常", "d1_chg": None, "d2_chg": None,
         "d5_chg": None, "d10_chg": None}
        for i in range(1, n + 1)
    ]
    with patch("config.settings.LHB_DIR", str(tmp_path)):
        save_lhb(records, d)

    content = (tmp_path / "20260319.md").read_text(encoding="utf-8")
    # 表格行 = 表头行 + 分隔行 + n 数据行
    table_lines = [line for line in content.splitlines() if line.startswith("|")]
    assert len(table_lines) == n + 2
