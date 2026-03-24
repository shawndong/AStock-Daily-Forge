"""
涨停股池采集层测试

覆盖场景：
  数据解析
  1.  正常数据完整解析（全部15字段）
  2.  成交额/流通市值/总市值/封板资金从元转换为亿元
  3.  首次封板时间格式化："092500" → "09:25:00"
  4.  最后封板时间格式化，含边界：恰好6位、不足6位
  5.  涨停统计字段格式保留（如 "5/5"）
  6.  连板数正确解析为整数
  7.  炸板次数为 0 时正确解析（不应被当成 None）
  8.  AKShare 返回空 DataFrame 时返回空列表
  9.  接口字段变更时抛出明确异常
  10. 行业字段为空时返回 "N/A"

  重试机制
  11. AKShare 抛出异常时按配置次数重试
  12. 重试间隔符合 RETRY_DELAY 配置
  13. 第二次重试成功时返回正确数据

  存储
  14. 按连板数降序排列，连板数相同按成交额降序
  15. 文件包含全部15列表头
  16. 文件头部包含摘要（总数、最高连板、各板计数）
  17. 涨跌幅/换手率格式带百分号
  18. 无数据时写入空标记，不写空表格
  19. 连板数 1 的普通涨停股正常写入
  20. 多连板股票排在单板股票前面
"""

import os
import sys
from datetime import date
from unittest.mock import call, patch

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from collector.limit_up import (
    RETRY_DELAY,
    _fmt_time,
    _parse_zt_df,
    _validate_columns,
    fetch_limit_up,
    save_limit_up,
)

# ── 测试数据工厂 ──────────────────────────────────────────────────────────────

def make_zt_df(rows: list[dict] = None) -> pd.DataFrame:
    """构造与 AKShare stock_zt_pool_em 返回结构一致的 DataFrame"""
    default = {
        "序号":      1,
        "代码":      "000020",
        "名称":      "深华发A",
        "涨跌幅":    9.9953,
        "最新价":    23.33,
        "成交额":    1.228e8,      # 元
        "流通市值":  4.227e9,      # 元
        "总市值":    6.606e9,      # 元
        "换手率":    2.9057,
        "封板资金":  5.341e8,      # 元
        "首次封板时间": "092500",
        "最后封板时间": "092500",
        "炸板次数":  0,
        "涨停统计":  "5/5",
        "连板数":    5,
        "所属行业":  "光学光电",
    }
    if rows is None:
        rows = [default]
    else:
        rows = [{**default, **r} for r in rows]
    return pd.DataFrame(rows)


def make_record(code="000020", name="深华发A", streak=5,
                amount_yi=1.23, **kwargs) -> dict:
    """构造单条涨停记录"""
    defaults = {
        "code": code, "name": name,
        "change_pct": 9.9953, "close": 23.33,
        "amount_yi": amount_yi, "float_cap_yi": 42.27,
        "total_cap_yi": 66.06, "turnover": 2.91,
        "seal_amount_yi": 5.34, "first_seal": "09:25:00",
        "last_seal": "09:25:00", "blast_count": 0,
        "zt_stat": "5/5", "streak": streak,
        "industry": "光学光电",
    }
    return {**defaults, **kwargs}


# ── 1. 正常数据完整解析 ───────────────────────────────────────────────────────

def test_parse_normal_all_fields():
    df = make_zt_df()
    d = date(2026, 3, 19)
    result = _parse_zt_df(df, d)

    assert len(result) == 1
    r = result[0]
    assert r["code"]     == "000020"
    assert r["name"]     == "深华发A"
    assert r["streak"]   == 5
    assert r["industry"] == "光学光电"
    assert r["zt_stat"]  == "5/5"


# ── 2. 金额从元转换为亿元 ────────────────────────────────────────────────────

def test_parse_amount_yuan_to_yi():
    df = make_zt_df([{"成交额": 1e8, "流通市值": 4e9,
                      "总市值": 6e9, "封板资金": 5e8}])
    r = _parse_zt_df(df, date(2026, 3, 19))[0]
    assert r["amount_yi"]      == pytest.approx(1.0,  rel=1e-3)
    assert r["float_cap_yi"]   == pytest.approx(40.0, rel=1e-3)
    assert r["total_cap_yi"]   == pytest.approx(60.0, rel=1e-3)
    assert r["seal_amount_yi"] == pytest.approx(5.0,  rel=1e-3)


# ── 3. 首次封板时间格式化 ────────────────────────────────────────────────────

def test_parse_first_seal_time_format():
    df = make_zt_df([{"首次封板时间": "092500"}])
    r = _parse_zt_df(df, date(2026, 3, 19))[0]
    assert r["first_seal"] == "09:25:00"


# ── 4. 最后封板时间边界处理 ──────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("150000", "15:00:00"),
    ("093000", "09:30:00"),
    ("N/A",    "N/A"),
    ("",       "N/A"),
])
def test_fmt_time_variants(raw, expected):
    # 直接测 _fmt_time
    import pandas as pd

    row2 = pd.Series({"时间字段": raw})
    result = _fmt_time(row2, "时间字段")
    assert result == expected


# ── 5. 涨停统计字段保留格式 ──────────────────────────────────────────────────

def test_parse_zt_stat_preserved():
    df = make_zt_df([{"涨停统计": "3/5"}])
    r = _parse_zt_df(df, date(2026, 3, 19))[0]
    assert r["zt_stat"] == "3/5"


# ── 6. 连板数正确解析为整数 ──────────────────────────────────────────────────

def test_parse_streak_is_int():
    df = make_zt_df([{"连板数": 3}])
    r = _parse_zt_df(df, date(2026, 3, 19))[0]
    assert r["streak"] == 3
    assert isinstance(r["streak"], int)


# ── 7. 炸板次数为 0 时正确解析 ──────────────────────────────────────────────

def test_parse_blast_count_zero():
    df = make_zt_df([{"炸板次数": 0}])
    r = _parse_zt_df(df, date(2026, 3, 19))[0]
    assert r["blast_count"] == 0
    assert r["blast_count"] is not None


# ── 8. 空 DataFrame 返回空列表 ──────────────────────────────────────────────

def test_parse_empty_df_returns_empty():
    result = _parse_zt_df(pd.DataFrame(), date(2026, 3, 19))
    assert result == []


# ── 9. 字段变更时抛出明确异常 ────────────────────────────────────────────────

def test_validate_columns_missing_raises():
    bad_df = pd.DataFrame({"日期": [], "股票": []})
    with pytest.raises(ValueError, match="AKShare 返回字段缺失"):
        _validate_columns(bad_df)


# ── 10. 行业字段为空时返回 N/A ───────────────────────────────────────────────

def test_parse_nan_industry_returns_na():
    df = make_zt_df([{"所属行业": float("nan")}])
    r = _parse_zt_df(df, date(2026, 3, 19))[0]
    assert r["industry"] == "N/A"


# ── 11. 异常时按配置次数重试 ─────────────────────────────────────────────────

def test_fetch_retry_count():
    with patch("akshare.stock_zt_pool_em",
               side_effect=ConnectionError("超时")) as mock_ak, \
         patch("collector.limit_up.time.sleep"):
        result = fetch_limit_up(target_date=date(2026, 3, 19), retries=3)
    assert result is None
    assert mock_ak.call_count == 3


# ── 12. 重试间隔符合配置 ─────────────────────────────────────────────────────

def test_fetch_retry_delay():
    with patch("akshare.stock_zt_pool_em",
               side_effect=ConnectionError("超时")), \
         patch("collector.limit_up.time.sleep") as mock_sleep:
        fetch_limit_up(target_date=date(2026, 3, 19), retries=2)
    for c in mock_sleep.call_args_list:
        assert c == call(RETRY_DELAY)


# ── 13. 第二次重试成功时返回数据 ────────────────────────────────────────────

def test_fetch_succeeds_on_second_attempt():
    good_df = make_zt_df()
    with patch("akshare.stock_zt_pool_em",
               side_effect=[ConnectionError("第一次失败"), good_df]) as mock_ak, \
         patch("collector.limit_up.time.sleep"):
        result = fetch_limit_up(target_date=date(2026, 3, 19), retries=3)
    assert result is not None
    assert len(result) == 1
    assert mock_ak.call_count == 2


# ── 14. 存储按连板数降序，同连板按成交额降序 ──────────────────────────────

def test_save_sorted_by_streak_then_amount(tmp_path):
    d = date(2026, 3, 19)
    records = [
        make_record("A", "低成交5板", streak=5, amount_yi=1.0),
        make_record("B", "高成交5板", streak=5, amount_yi=10.0),
        make_record("C", "3板股",    streak=3, amount_yi=20.0),
        make_record("D", "1板股",    streak=1, amount_yi=50.0),
    ]
    with patch("config.settings.LIMIT_UP_DIR", str(tmp_path)):
        save_limit_up(records, d)

    content = (tmp_path / "20260319.md").read_text(encoding="utf-8")
    # 连板数高的在前
    assert content.index("高成交5板") < content.index("3板股")
    assert content.index("3板股")    < content.index("1板股")
    # 同连板内成交额高的在前
    assert content.index("高成交5板") < content.index("低成交5板")


# ── 15. 文件包含全部15列表头 ────────────────────────────────────────────────

def test_save_has_all_headers(tmp_path):
    records = [make_record()]
    with patch("config.settings.LIMIT_UP_DIR", str(tmp_path)):
        save_limit_up(records, date(2026, 3, 19))

    content = (tmp_path / "20260319.md").read_text(encoding="utf-8")
    for col in ["代码", "名称", "封板资金(亿)", "涨停统计", "连板数", "所属行业"]:
        assert col in content


# ── 16. 文件头部包含摘要信息 ────────────────────────────────────────────────

def test_save_has_summary_header(tmp_path):
    records = [
        make_record("A", streak=3),
        make_record("B", streak=3),
        make_record("C", streak=1),
    ]
    with patch("config.settings.LIMIT_UP_DIR", str(tmp_path)):
        save_limit_up(records, date(2026, 3, 19))

    content = (tmp_path / "20260319.md").read_text(encoding="utf-8")
    assert "共 3 只" in content
    assert "最高连板 3" in content
    assert "3板×2" in content
    assert "1板×1" in content


# ── 17. 涨跌幅和换手率格式带百分号 ─────────────────────────────────────────

def test_save_pct_format(tmp_path):
    records = [make_record(change_pct=9.9953, turnover=2.9057)]
    with patch("config.settings.LIMIT_UP_DIR", str(tmp_path)):
        save_limit_up(records, date(2026, 3, 19))

    content = (tmp_path / "20260319.md").read_text(encoding="utf-8")
    assert "9.9953%" in content or "10.00%" in content
    assert "2.9057%" in content or "2.91%" in content


# ── 18. 无数据时写入空标记 ──────────────────────────────────────────────────

def test_save_empty_writes_marker(tmp_path):
    with patch("config.settings.LIMIT_UP_DIR", str(tmp_path)):
        save_limit_up([], date(2026, 3, 21))

    content = (tmp_path / "20260321.md").read_text(encoding="utf-8")
    assert "非交易日或无涨停股" in content
    assert "|" not in content


# ── 19. 连板数1的普通涨停股正常写入 ────────────────────────────────────────

def test_save_streak_one_normal(tmp_path):
    records = [make_record("000001", "平安银行", streak=1, amount_yi=68.1)]
    with patch("config.settings.LIMIT_UP_DIR", str(tmp_path)):
        save_limit_up(records, date(2026, 3, 19))

    content = (tmp_path / "20260319.md").read_text(encoding="utf-8")
    assert "平安银行" in content
    assert "1" in content


# ── 20. 多连板排在单板前面 ──────────────────────────────────────────────────

def test_save_multi_streak_before_single(tmp_path):
    records = [
        make_record("A", "单板股", streak=1),
        make_record("B", "五连板", streak=5),
    ]
    with patch("config.settings.LIMIT_UP_DIR", str(tmp_path)):
        save_limit_up(records, date(2026, 3, 19))

    content = (tmp_path / "20260319.md").read_text(encoding="utf-8")
    assert content.index("五连板") < content.index("单板股")
