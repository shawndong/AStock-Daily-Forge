"""
个股日K线采集层测试（新浪接口版）

覆盖场景：
  数据解析
  1.  正常 JSON 完整解析（全部字段）
  2.  成交量从股转换为手（÷100）
  3.  成交额估算正确（volume(手) × close ÷ 1e6）
  4.  涨跌幅从相邻收盘价正确派生
  5.  第一条记录涨跌幅为 None（无前日数据）
  6.  收盘价为 0 时记录被跳过（停牌/异常数据）
  7.  接口返回空列表时返回空列表
  8.  JSON 解析失败时返回空列表，不崩溃
  9.  接口返回错误页面时返回空列表
  10. 单条 day 格式错误时跳过，其余正常解析
  11. 多条记录按日期顺序保留

  市场前缀
  12. 600/601 开头 → sh 前缀
  13. 000/002/300 开头 → sz 前缀

  重试机制
  14. curl 失败时按配置次数重试
  15. 重试间隔符合 RETRY_DELAY 配置
  16. 第二次重试成功时返回正确数据

  存储
  17. 每个交易日写一个独立文件
  18. 文件包含正确8列表头
  19. 涨跌幅格式带符号（+/-），第一条为 N/A
  20. 成交额标注"（估）"字样
  21. skip_existing=True 时已存在文件不被覆盖
  22. 增量更新只写新日期文件
"""

import json
import os
import sys
from datetime import date
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from collector.kline_daily import (
    RETRY_DELAY,
    _parse_kline_json,
    fetch_and_save,
    fetch_kline_daily,
    save_kline_daily,
    to_sina_symbol,
)

# ── 测试数据工厂 ──────────────────────────────────────────────────────────────

def make_raw_json(records: list[dict] = None) -> str:
    if records is None:
        records = [
            {"day": "2026-03-17", "open": "19.28", "high": "19.50",
             "low": "19.10", "close": "19.28", "volume": "2892080"},
            {"day": "2026-03-18", "open": "19.28", "high": "20.00",
             "low": "19.20", "close": "19.50", "volume": "3100000"},
            {"day": "2026-03-19", "open": "21.21", "high": "21.21",
             "low": "21.21", "close": "21.21", "volume": "3252082"},
        ]
    return json.dumps(records)


def make_record(d: date = None, close: float = 21.21, **kwargs) -> dict:
    if d is None:
        d = date(2026, 3, 19)
    return {
        "date": d, "open": 21.21, "high": 21.21, "low": 21.21,
        "close": close, "volume": 32520.0,
        "amount_est": round(32520.0 * close / 1e6, 4),
        "change_pct": None, **kwargs
    }


# ── 1. 正常 JSON 完整解析 ─────────────────────────────────────────────────────

def test_parse_normal_all_fields():
    raw    = make_raw_json()
    result = _parse_kline_json(raw, "000020")
    assert len(result) == 3
    r = result[2]
    assert r["date"]  == date(2026, 3, 19)
    assert r["open"]  == pytest.approx(21.21)
    assert r["close"] == pytest.approx(21.21)
    assert r["high"]  == pytest.approx(21.21)


# ── 2. 成交量从股转换为手 ────────────────────────────────────────────────────

def test_parse_volume_stock_to_hand():
    raw    = make_raw_json([{"day": "2026-03-19", "open": "21.21", "high": "21.21",
                              "low": "21.21", "close": "21.21", "volume": "3252082"}])
    result = _parse_kline_json(raw, "000020")
    assert result[0]["volume"] == pytest.approx(32521.0)


# ── 3. 成交额估算正确 ─────────────────────────────────────────────────────────

def test_parse_amount_estimation():
    # volume=10000股=100手, close=20.0, amount=100×20÷1e6=0.002亿
    raw    = make_raw_json([{"day": "2026-03-19", "open": "20.0", "high": "20.0",
                              "low": "20.0", "close": "20.0", "volume": "10000"}])
    result = _parse_kline_json(raw, "000020")
    assert result[0]["amount_est"] == pytest.approx(100 * 20.0 / 1e6, rel=1e-3)


# ── 4. 涨跌幅从相邻收盘价派生 ───────────────────────────────────────────────

def test_parse_change_pct_derived():
    raw = make_raw_json([
        {"day": "2026-03-18", "open": "19.28", "high": "19.28",
         "low": "19.28", "close": "19.28", "volume": "2892080"},
        {"day": "2026-03-19", "open": "21.21", "high": "21.21",
         "low": "21.21", "close": "21.21", "volume": "3252082"},
    ])
    result = _parse_kline_json(raw, "000020")
    expected = (21.21 - 19.28) / 19.28 * 100
    assert result[1]["change_pct"] == pytest.approx(expected, rel=1e-3)


# ── 5. 第一条涨跌幅为 None ───────────────────────────────────────────────────

def test_parse_first_record_change_pct_none():
    raw    = make_raw_json()
    result = _parse_kline_json(raw, "000020")
    assert result[0]["change_pct"] is None


# ── 6. 收盘价为 0 时记录被跳过 ──────────────────────────────────────────────

def test_parse_zero_close_skipped():
    raw    = make_raw_json([{"day": "2026-03-19", "open": "0",
                              "high": "0", "low": "0", "close": "0", "volume": "0"}])
    result = _parse_kline_json(raw, "000020")
    assert result == []


# ── 7. 空列表返回空列表 ──────────────────────────────────────────────────────

def test_parse_empty_list_returns_empty():
    assert _parse_kline_json("[]", "000020") == []


# ── 8. JSON 解析失败返回空列表 ──────────────────────────────────────────────

def test_parse_invalid_json_returns_empty():
    assert _parse_kline_json("not valid json", "000020") == []


# ── 9. 错误页面返回空列表 ────────────────────────────────────────────────────

def test_parse_error_page_returns_empty():
    assert _parse_kline_json("/*<script>location.href=</script>*/", "000020") == []


# ── 10. 格式错误的 day 跳过，其余正常 ───────────────────────────────────────

def test_parse_bad_day_skips_keeps_others():
    raw = json.dumps([
        {"day": "2026-03-19", "open": "21.21", "high": "21.21",
         "low": "21.21", "close": "21.21", "volume": "100000"},
        {"day": "bad-date",   "open": "21.21", "high": "21.21",
         "low": "21.21", "close": "21.21", "volume": "100000"},
    ])
    result = _parse_kline_json(raw, "000020")
    assert len(result) == 1
    assert result[0]["date"] == date(2026, 3, 19)


# ── 11. 多条记录顺序保留 ─────────────────────────────────────────────────────

def test_parse_multiple_records_order():
    raw    = make_raw_json()
    result = _parse_kline_json(raw, "000020")
    dates  = [r["date"] for r in result]
    assert dates == sorted(dates)


# ── 12. sh 前缀 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("code", ["600001", "601001", "603001", "688001"])
def test_sina_symbol_sh(code):
    assert to_sina_symbol(code) == f"sh{code}"


# ── 13. sz 前缀 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("code", ["000001", "002001", "300001"])
def test_sina_symbol_sz(code):
    assert to_sina_symbol(code) == f"sz{code}"


# ── 14. curl 失败时按配置次数重试 ───────────────────────────────────────────

def test_fetch_retry_count():
    with patch("collector.kline_daily.subprocess.run",
               side_effect=RuntimeError("超时")) as mock_run, \
         patch("collector.kline_daily.time.sleep"):
        result = fetch_kline_daily("000020", retries=3)
    assert result is None
    assert mock_run.call_count == 3


# ── 15. 重试间隔符合配置 ─────────────────────────────────────────────────────

def test_fetch_retry_delay():
    with patch("collector.kline_daily.subprocess.run",
               side_effect=RuntimeError("超时")), \
         patch("collector.kline_daily.time.sleep") as mock_sleep:
        fetch_kline_daily("000020", retries=2)
    for c in mock_sleep.call_args_list:
        assert c == call(RETRY_DELAY)


# ── 16. 第二次重试成功时返回数据 ────────────────────────────────────────────

def test_fetch_succeeds_on_second_attempt():
    good_output = make_raw_json().encode("utf-8")
    mock_ok = MagicMock()
    mock_ok.returncode = 0
    mock_ok.stdout = good_output

    with patch("collector.kline_daily.subprocess.run",
               side_effect=[RuntimeError("第一次失败"), mock_ok]) as mock_run, \
         patch("collector.kline_daily.time.sleep"):
        result = fetch_kline_daily("000020", retries=3)

    assert result is not None
    assert len(result) == 3
    assert mock_run.call_count == 2


# ── 17. 每个交易日写一个独立文件 ────────────────────────────────────────────

def test_save_one_file_per_day(tmp_path):
    records = [
        make_record(date(2026, 3, 17), change_pct=None),
        make_record(date(2026, 3, 18), change_pct=10.01),
        make_record(date(2026, 3, 19), change_pct=-0.73),
    ]
    with patch("config.settings.STOCKS_DIR", str(tmp_path)):
        save_kline_daily("000020", records)

    kline_dir = tmp_path / "000020" / "daily_kline"
    assert (kline_dir / "20260317.md").exists()
    assert (kline_dir / "20260318.md").exists()
    assert (kline_dir / "20260319.md").exists()


# ── 18. 文件包含正确8列表头 ─────────────────────────────────────────────────

def test_save_has_correct_headers(tmp_path):
    records = [make_record(date(2026, 3, 19))]
    with patch("config.settings.STOCKS_DIR", str(tmp_path)):
        save_kline_daily("000020", records)

    content = (tmp_path / "000020" / "daily_kline" / "20260319.md").read_text(encoding="utf-8")
    for col in ["日期", "开盘", "收盘", "最高", "最低", "成交量(手)", "成交额(亿)", "涨跌幅"]:
        assert col in content


# ── 19. 涨跌幅格式带符号，None 显示 N/A ────────────────────────────────────

def test_save_change_pct_format(tmp_path):
    records = [
        make_record(date(2026, 3, 17), change_pct=None),
        make_record(date(2026, 3, 18), change_pct=10.01),
        make_record(date(2026, 3, 19), change_pct=-0.73),
    ]
    with patch("config.settings.STOCKS_DIR", str(tmp_path)):
        save_kline_daily("000020", records)

    kline_dir = tmp_path / "000020" / "daily_kline"
    assert "N/A" in (kline_dir / "20260317.md").read_text(encoding="utf-8")
    assert "+10.01%" in (kline_dir / "20260318.md").read_text(encoding="utf-8")
    assert "-0.73%" in (kline_dir / "20260319.md").read_text(encoding="utf-8")


# ── 20. 成交额标注"（估）" ──────────────────────────────────────────────────

def test_save_amount_has_estimate_label(tmp_path):
    records = [make_record(date(2026, 3, 19), amount_est=6.8109)]
    with patch("config.settings.STOCKS_DIR", str(tmp_path)):
        save_kline_daily("000020", records)

    content = (tmp_path / "000020" / "daily_kline" / "20260319.md").read_text(encoding="utf-8")
    assert "（估）" in content


# ── 21. skip_existing 不覆盖已存在文件 ───────────────────────────────────────

def test_fetch_and_save_skips_existing(tmp_path):
    kline_dir = tmp_path / "000020" / "daily_kline"
    kline_dir.mkdir(parents=True)
    existing_file = kline_dir / "20260319.md"
    existing_file.write_text("# 已存在的内容", encoding="utf-8")

    mock_ok = MagicMock()
    mock_ok.returncode = 0
    mock_ok.stdout = make_raw_json().encode("utf-8")

    with patch("collector.kline_daily.subprocess.run", return_value=mock_ok), \
         patch("config.settings.STOCKS_DIR", str(tmp_path)), \
         patch("collector.kline_daily.time.sleep"):
        fetch_and_save("000020", skip_existing=True)

    assert "已存在的内容" in existing_file.read_text(encoding="utf-8")


# ── 22. 增量更新只写新日期 ──────────────────────────────────────────────────

def test_fetch_and_save_writes_only_new_dates(tmp_path):
    kline_dir = tmp_path / "000020" / "daily_kline"
    kline_dir.mkdir(parents=True)
    (kline_dir / "20260317.md").write_text("# 已存在", encoding="utf-8")

    mock_ok = MagicMock()
    mock_ok.returncode = 0
    mock_ok.stdout = make_raw_json().encode("utf-8")  # 含 3/17, 3/18, 3/19

    with patch("collector.kline_daily.subprocess.run", return_value=mock_ok), \
         patch("config.settings.STOCKS_DIR", str(tmp_path)), \
         patch("collector.kline_daily.time.sleep"):
        fetch_and_save("000020", skip_existing=True)

    assert (kline_dir / "20260318.md").exists()
    assert (kline_dir / "20260319.md").exists()
    assert "已存在" in (kline_dir / "20260317.md").read_text(encoding="utf-8")
