"""
全市场行情采集层测试

覆盖场景：
  解析层
  1.  正常数据完整解析（代码、名称、价格、成交额单位转换）
  2.  涨停股识别（close == limit_up_price）
  3.  跌停股识别（close == limit_down_price）
  4.  ST股涨跌停幅度使用 5%
  5.  字段不足（< 45）时返回 None，不崩溃
  6.  现价为 0 或空字符串时返回 None
  7.  昨收为 0 时返回 None（避免除零）
  8.  涨跌幅为负（外资净卖出场景）时正确解析
  9.  成交额从万元正确转换为亿元
  10. 腾讯行首格式 v_sz000001="..." 和 v_sh600000="..." 都能解析

  市场前缀
  11. 各开头数字映射到正确市场前缀（sz/sh/bj）

  统计汇总
  12. 涨停/跌停/上涨/下跌数量统计正确
  13. 全市场成交额汇总精度正确
  14. 无有效数据时汇总返回全零而非崩溃

  网络与重试
  15. curl 失败时按配置次数重试
  16. 重试间隔符合 RETRY_DELAY 配置
  17. 部分批次失败时，成功批次的数据仍正常返回

  存储
  18. 行情汇总文件包含核心指标和个股明细
  19. 涨停列表文件按成交额降序，且数量标注正确
  20. 无涨停股时涨停文件写入"共 0 只"而非空表格报错
"""

import os
import sys
from datetime import date
from unittest.mock import call, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from collector.market_quote import (
    BATCH_SIZE,
    MAX_RETRIES,
    RETRY_DELAY,
    _parse_tencent_line,
    fetch_market_quote,
    save_market_quote,
    summarize,
    to_tencent_symbol,
)

# ── 测试数据工厂 ──────────────────────────────────────────────────────────────

def make_tencent_line(
    name="平安银行", code="000001",
    close=10.88, pre_close=10.96, open_=10.92,
    high=10.97, low=10.86,
    change="-0.08", change_pct="-0.73",
    volume=624212, amount_wan=68108.65,
    pad_to=50
) -> str:
    """构造腾讯接口格式的单行数据（~分隔，45+字段）"""
    fields = ["51"] + [""] * (pad_to - 1)
    fields[1]  = name
    fields[2]  = code
    fields[3]  = str(close)
    fields[4]  = str(pre_close)
    fields[5]  = str(open_)
    fields[7]  = "266107"    # 外盘
    fields[8]  = "358105"    # 内盘
    fields[31] = change
    fields[32] = change_pct
    fields[33] = str(high)
    fields[34] = str(low)
    fields[36] = str(volume)
    fields[37] = str(amount_wan)
    fields[38] = "0.32"      # 换手率
    return f'v_sz{code}="' + "~".join(fields) + '";'


def make_stock(code="000001", name="平安银行", close=10.88, pre_close=10.96,
               change_pct=-0.73, amount=6.81,
               is_limit_up=False, is_limit_down=False) -> dict:
    return {
        "code": code, "name": name,
        "close": close, "pre_close": pre_close,
        "change_pct": change_pct, "amount": amount,
        "is_limit_up": is_limit_up, "is_limit_down": is_limit_down,
        "is_st": False,
        "open": 10.92, "high": 10.97, "low": 10.86,
        "volume": 624212,
        "limit_up_price": round(pre_close * 1.1, 2),
        "limit_down_price": round(pre_close * 0.9, 2),
    }


# ── 1. 正常数据完整解析 ───────────────────────────────────────────────────────

def test_parse_normal_fields():
    line = make_tencent_line(
        name="平安银行", code="000001",
        close=10.88, pre_close=10.96, open_=10.92,
        high=10.97, low=10.86, change_pct="-0.73", amount_wan=68108.65
    )
    result = _parse_tencent_line(line)
    assert result is not None
    assert result["code"]      == "000001"
    assert result["name"]      == "平安银行"
    assert result["close"]     == 10.88
    assert result["pre_close"] == 10.96
    assert result["open"]      == 10.92
    assert result["high"]      == 10.97
    assert result["low"]       == 10.86
    assert result["change_pct"] == pytest.approx(-0.73)


# ── 2. 涨停股识别 ────────────────────────────────────────────────────────────

def test_parse_identifies_limit_up():
    pre_close = 10.00
    limit_up  = round(pre_close * 1.1, 2)   # 11.00
    line = make_tencent_line(close=limit_up, pre_close=pre_close, change_pct="10.00")
    result = _parse_tencent_line(line)
    assert result["is_limit_up"]   is True
    assert result["is_limit_down"] is False


# ── 3. 跌停股识别 ────────────────────────────────────────────────────────────

def test_parse_identifies_limit_down():
    pre_close  = 10.00
    limit_down = round(pre_close * 0.9, 2)   # 9.00
    line = make_tencent_line(close=limit_down, pre_close=pre_close, change_pct="-10.00")
    result = _parse_tencent_line(line)
    assert result["is_limit_down"] is True
    assert result["is_limit_up"]   is False


# ── 4. ST 股使用 5% 幅度 ─────────────────────────────────────────────────────

def test_parse_st_uses_5pct_limit():
    pre_close = 10.00
    st_limit_up = round(pre_close * 1.05, 2)   # 10.50
    line = make_tencent_line(
        name="*ST测试", code="000999",
        close=st_limit_up, pre_close=pre_close, change_pct="5.00"
    )
    result = _parse_tencent_line(line)
    assert result["is_st"]          is True
    assert result["limit_up_price"] == st_limit_up
    assert result["is_limit_up"]    is True


# ── 5. 字段不足时返回 None ───────────────────────────────────────────────────

def test_parse_returns_none_when_fields_insufficient():
    short_line = 'v_sz000001="51~平安银行~000001~10.88";'
    assert _parse_tencent_line(short_line) is None


# ── 6. 现价为空时返回 None ───────────────────────────────────────────────────

def test_parse_returns_none_when_close_empty():
    line = make_tencent_line(close="", pre_close=10.96)
    assert _parse_tencent_line(line) is None


# ── 7. 昨收为 0 时返回 None ─────────────────────────────────────────────────

def test_parse_returns_none_when_pre_close_zero():
    line = make_tencent_line(close=10.88, pre_close=0)
    assert _parse_tencent_line(line) is None


# ── 8. 涨跌幅为负时正确解析 ─────────────────────────────────────────────────

def test_parse_negative_change_pct():
    line = make_tencent_line(change_pct="-3.45")
    result = _parse_tencent_line(line)
    assert result["change_pct"] == pytest.approx(-3.45)


# ── 9. 成交额从万元转换为亿元 ───────────────────────────────────────────────

def test_parse_amount_unit_conversion():
    line = make_tencent_line(amount_wan=10000.0)   # 1亿
    result = _parse_tencent_line(line)
    assert result["amount"] == pytest.approx(1.0, rel=1e-3)


# ── 10. sh 开头行也能解析 ────────────────────────────────────────────────────

def test_parse_sh_prefix_line():
    fields = ["51"] + [""] * 49
    fields[1] = "浦发银行"
    fields[2] = "600000"
    fields[3] = "10.32"
    fields[4] = "10.37"
    fields[5] = "10.32"
    fields[32] = "-0.48"
    fields[33] = "10.40"
    fields[34] = "10.25"
    fields[36] = "758672"
    fields[37] = "78446.18"
    line = 'v_sh600000="' + "~".join(fields) + '";'
    result = _parse_tencent_line(line)
    assert result is not None
    assert result["code"] == "600000"


# ── 11. 市场前缀映射 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("code,expected_prefix", [
    ("000001", "sz"), ("002001", "sz"), ("300001", "sz"), ("301001", "sz"),
    ("600001", "sh"), ("601001", "sh"), ("603001", "sh"), ("688001", "sh"),
    ("830001", "bj"), ("871001", "bj"),
])
def test_tencent_symbol_prefix(code, expected_prefix):
    sym = to_tencent_symbol(code)
    assert sym.startswith(expected_prefix), f"{code} 应映射到 {expected_prefix}，实际: {sym}"
    assert sym.endswith(code)


# ── 12. 涨停/上涨/下跌统计 ──────────────────────────────────────────────────

def test_summarize_counts():
    stocks = [
        make_stock("A", change_pct=10.0,  is_limit_up=True),
        make_stock("B", change_pct=3.0),
        make_stock("C", change_pct=-3.0),
        make_stock("D", change_pct=-10.0, is_limit_down=True),
        make_stock("E", change_pct=0.0),
    ]
    s = summarize(stocks)
    assert s["limit_up"]   == 1
    assert s["limit_down"] == 1
    assert s["up_count"]   == 2   # A(涨停) + B
    assert s["down_count"] == 2   # C + D(跌停)
    assert s["flat_count"] == 1


# ── 13. 成交额汇总精度 ───────────────────────────────────────────────────────

def test_summarize_total_amount():
    stocks = [
        make_stock("A", amount=12.345),
        make_stock("B", amount=8.765),
        make_stock("C", amount=None),   # 无成交额，不参与汇总
    ]
    # 修正 None 的 amount
    stocks[2]["amount"] = None
    s = summarize(stocks)
    assert s["total_amount"] == pytest.approx(21.11, rel=1e-3)


# ── 14. 无有效数据时汇总返回全零 ────────────────────────────────────────────

def test_summarize_empty_returns_zeros():
    s = summarize([])
    assert s["total"]      == 0
    assert s["limit_up"]   == 0
    assert s["total_amount"] == 0.0


# ── 15. curl 失败时按配置次数重试 ───────────────────────────────────────────

def test_batch_retry_count():
    with patch("collector.market_quote.subprocess.run",
               side_effect=RuntimeError("网络超时")) as mock_run, \
         patch("collector.market_quote.time.sleep"):
        with pytest.raises(RuntimeError):
            from collector.market_quote import _fetch_tencent_batch
            _fetch_tencent_batch(["sz000001"], retries=3)
    assert mock_run.call_count == 3


# ── 16. 重试间隔符合配置 ─────────────────────────────────────────────────────

def test_batch_retry_delay():
    with patch("collector.market_quote.subprocess.run",
               side_effect=RuntimeError("超时")), \
         patch("collector.market_quote.time.sleep") as mock_sleep:
        try:
            from collector.market_quote import _fetch_tencent_batch
            _fetch_tencent_batch(["sz000001"], retries=3)
        except RuntimeError:
            pass
    for c in mock_sleep.call_args_list:
        assert c == call(RETRY_DELAY)


# ── 17. 部分批次失败时成功批次数据仍返回 ─────────────────────────────────────

def test_fetch_market_partial_failure():
    good_line = make_tencent_line(code="000001", close=10.88, pre_close=10.96)

    call_count = {"n": 0}
    def mock_fetch(symbols, retries=MAX_RETRIES):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("第2批失败")
        return good_line

    stock_list = [{"code": f"{i:06d}", "name": f"股票{i}"} for i in range(1, BATCH_SIZE * 3 + 1)]

    with patch("collector.market_quote._fetch_tencent_batch", side_effect=mock_fetch), \
         patch("collector.market_quote.time.sleep"):
        results = fetch_market_quote(stock_list)

    assert len(results) > 0   # 成功批次的数据仍存在


# ── 18. 行情汇总文件包含核心字段 ─────────────────────────────────────────────

def test_save_market_quote_content(tmp_path):
    stocks = [
        make_stock("000001", "平安银行", close=10.88, change_pct=-0.73, amount=68.10),
        make_stock("000002", "万科A",    close=8.50,  change_pct=10.0,
                   is_limit_up=True, amount=120.5),
    ]
    with patch("config.settings.MARKET_QUOTE_DIR", str(tmp_path / "daily_quote")), \
         patch("config.settings.MARKET_QUOTE_LIMIT_UP_SNAPSHOT_DIR", str(tmp_path / "limit_up_snapshot")), \
         patch("config.settings.LIMIT_UP_DIR",     str(tmp_path / "limit_up")), \
         patch("config.settings.MARKET_STATE_DIR", str(tmp_path / "market_state")):
        save_market_quote(stocks, date(2026, 3, 19))

    content = (tmp_path / "daily_quote" / "20260319.md").read_text(encoding="utf-8")
    assert "涨停数量" in content
    assert "全市场成交额" in content
    assert "平安银行" in content
    assert "万科A" in content


# ── 19. 涨停列表按成交额降序 ────────────────────────────────────────────────

def test_save_limit_up_sorted_by_amount(tmp_path):
    stocks = [
        make_stock("000001", "低成交涨停", is_limit_up=True, amount=5.0,  change_pct=10.0),
        make_stock("000002", "高成交涨停", is_limit_up=True, amount=50.0, change_pct=10.0),
        make_stock("000003", "普通股",     is_limit_up=False, amount=20.0),
    ]
    with patch("config.settings.MARKET_QUOTE_DIR", str(tmp_path / "dq")), \
         patch("config.settings.MARKET_QUOTE_LIMIT_UP_SNAPSHOT_DIR", str(tmp_path / "lu")), \
         patch("config.settings.LIMIT_UP_DIR",     str(tmp_path / "lu")), \
         patch("config.settings.MARKET_STATE_DIR", str(tmp_path / "ms")):
        save_market_quote(stocks, date(2026, 3, 19))

    content = (tmp_path / "lu" / "20260319.md").read_text(encoding="utf-8")
    assert content.index("高成交涨停") < content.index("低成交涨停")
    assert "共 2 只" in content


# ── 20. 无涨停股时涨停文件正常写入 ──────────────────────────────────────────

def test_save_no_limit_up_writes_zero(tmp_path):
    stocks = [make_stock("000001", change_pct=-0.5)]
    with patch("config.settings.MARKET_QUOTE_DIR", str(tmp_path / "dq")), \
         patch("config.settings.MARKET_QUOTE_LIMIT_UP_SNAPSHOT_DIR", str(tmp_path / "lu")), \
         patch("config.settings.LIMIT_UP_DIR",     str(tmp_path / "lu")), \
         patch("config.settings.MARKET_STATE_DIR", str(tmp_path / "ms")):
        save_market_quote(stocks, date(2026, 3, 19))

    content = (tmp_path / "lu" / "20260319.md").read_text(encoding="utf-8")
    assert "共 0 只" in content
