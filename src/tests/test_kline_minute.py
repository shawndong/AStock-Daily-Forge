"""
个股分钟线采集层测试

覆盖场景：
  数据解析
  1.  正常 JSON 完整解析（全部字段）
  2.  成交量从股转换为手（÷100）
  3.  时间字段解析为 datetime 对象，日期字段正确提取
  4.  JSON 为空列表时返回空列表
  5.  接口返回非列表格式（如错误 dict）时返回空列表
  6.  接口返回错误页面（/* ... */）时返回空列表
  7.  JSON 解析失败时返回空列表，不崩溃
  8.  单条记录字段缺失时跳过该条，其他记录正常解析
  9.  单条 day 字段格式错误时跳过该条，不崩溃

  市场前缀
  10. 600/601/603/688 开头 → sh 前缀
  11. 000/002/300 开头 → sz 前缀

  按日期分组
  12. 多天数据正确按日期分组
  13. 同一天的数据按时间顺序保留

  重试机制
  14. curl 失败时按配置次数重试
  15. 重试间隔符合 RETRY_DELAY 配置
  16. 第二次重试成功时返回正确数据

  存储
  17. 每个交易日写一个独立文件
  18. 文件名为 YYYYMMDD.md，内容包含正确表头
  19. 时间列只显示 HH:MM，不含日期
  20. 超出 KEEP_DAYS 的旧文件被自动清理
  21. 无数据时不写文件，不报错
"""

import json
import os
import sys
from datetime import date, datetime
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from collector.kline_minute import (
    KEEP_DAYS,
    RETRY_DELAY,
    _cleanup_old_files,
    _parse_minute_json,
    _parse_one_record,
    fetch_kline_minute,
    group_by_date,
    save_kline_minute,
    to_sina_symbol,
)

# ── 测试数据工厂 ──────────────────────────────────────────────────────────────

def make_raw_json(records: list[dict] = None) -> str:
    """构造新浪接口格式的 JSON 字符串"""
    if records is None:
        records = [
            {"day": "2026-03-19 09:35:00", "open": "10.92", "high": "10.97",
             "low": "10.91", "close": "10.95", "volume": "123400"},
            {"day": "2026-03-19 09:40:00", "open": "10.95", "high": "10.98",
             "low": "10.93", "close": "10.96", "volume": "98700"},
        ]
    return json.dumps(records)


def make_record(dt_str: str = "2026-03-19 09:35:00", **kwargs) -> dict:
    """构造单条解析后的分钟线记录"""
    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
    defaults = {
        "datetime": dt,
        "date":     dt.date(),
        "open":     10.92,
        "high":     10.97,
        "low":      10.91,
        "close":    10.95,
        "volume":   1234.0,
    }
    return {**defaults, **kwargs}


# ── 1. 正常 JSON 完整解析 ─────────────────────────────────────────────────────

def test_parse_normal_all_fields():
    raw = make_raw_json()
    result = _parse_minute_json(raw, "000001")
    assert len(result) == 2
    r = result[0]
    assert r["datetime"] == datetime(2026, 3, 19, 9, 35, 0)
    assert r["date"]     == date(2026, 3, 19)
    assert r["open"]     == pytest.approx(10.92)
    assert r["high"]     == pytest.approx(10.97)
    assert r["close"]    == pytest.approx(10.95)


# ── 2. 成交量从股转换为手 ────────────────────────────────────────────────────

def test_parse_volume_stock_to_hand():
    raw = make_raw_json([
        {"day": "2026-03-19 09:35:00", "open": "10.92", "high": "10.97",
         "low": "10.91", "close": "10.95", "volume": "123400"},   # 1234手
    ])
    r = _parse_minute_json(raw, "000001")[0]
    assert r["volume"] == pytest.approx(1234.0)


# ── 3. 时间字段解析正确 ──────────────────────────────────────────────────────

def test_parse_datetime_and_date():
    raw = make_raw_json([
        {"day": "2026-03-19 14:30:00", "open": "10.82", "high": "10.83",
         "low": "10.81", "close": "10.82", "volume": "50000"},
    ])
    r = _parse_minute_json(raw, "000001")[0]
    assert r["datetime"] == datetime(2026, 3, 19, 14, 30, 0)
    assert r["date"]     == date(2026, 3, 19)


# ── 4. 空列表返回空列表 ──────────────────────────────────────────────────────

def test_parse_empty_list_returns_empty():
    result = _parse_minute_json("[]", "000001")
    assert result == []


# ── 5. 非列表格式返回空列表 ──────────────────────────────────────────────────

def test_parse_non_list_returns_empty():
    result = _parse_minute_json('{"error": "bad"}', "000001")
    assert result == []


# ── 6. 错误页面返回空列表 ────────────────────────────────────────────────────

def test_parse_error_page_returns_empty():
    result = _parse_minute_json('/*<script>location.href=</script>*/', "000001")
    assert result == []


# ── 7. JSON 解析失败返回空列表 ──────────────────────────────────────────────

def test_parse_invalid_json_returns_empty():
    result = _parse_minute_json("not valid json{{", "000001")
    assert result == []


# ── 8. 单条字段缺失时跳过，其余正常 ─────────────────────────────────────────

def test_parse_skips_bad_record_keeps_good():
    raw = json.dumps([
        {"day": "2026-03-19 09:35:00", "open": "10.92", "high": "10.97",
         "low": "10.91", "close": "10.95", "volume": "123400"},
        {"day": "bad-date-format", "open": "10.95"},   # 格式错误，应跳过
    ])
    result = _parse_minute_json(raw, "000001")
    assert len(result) == 1
    assert result[0]["close"] == pytest.approx(10.95)


# ── 9. day 格式错误时跳过 ────────────────────────────────────────────────────

def test_parse_one_record_bad_day_returns_none():
    item = {"day": "2026/03/19 09:35", "open": "10.92", "high": "10.97",
            "low": "10.91", "close": "10.95", "volume": "123400"}
    assert _parse_one_record(item, "000001") is None


# ── 10. sh 市场前缀 ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("code", ["600001", "601001", "603001", "688001"])
def test_sina_symbol_sh_prefix(code):
    assert to_sina_symbol(code).startswith("sh")
    assert to_sina_symbol(code).endswith(code)


# ── 11. sz 市场前缀 ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("code", ["000001", "002001", "300001"])
def test_sina_symbol_sz_prefix(code):
    assert to_sina_symbol(code).startswith("sz")
    assert to_sina_symbol(code).endswith(code)


# ── 12. 多天数据正确分组 ─────────────────────────────────────────────────────

def test_group_by_date_multiple_days():
    records = [
        make_record("2026-03-17 09:35:00"),
        make_record("2026-03-17 09:40:00"),
        make_record("2026-03-18 09:35:00"),
        make_record("2026-03-19 09:35:00"),
        make_record("2026-03-19 09:40:00"),
    ]
    groups = group_by_date(records)
    assert len(groups) == 3
    assert len(groups[date(2026, 3, 17)]) == 2
    assert len(groups[date(2026, 3, 18)]) == 1
    assert len(groups[date(2026, 3, 19)]) == 2


# ── 13. 同一天记录顺序保留 ──────────────────────────────────────────────────

def test_group_by_date_preserves_order():
    records = [
        make_record("2026-03-19 09:35:00"),
        make_record("2026-03-19 14:30:00"),
        make_record("2026-03-19 11:00:00"),
    ]
    groups = group_by_date(records)
    times = [r["datetime"].hour for r in groups[date(2026, 3, 19)]]
    assert times == [9, 14, 11]   # 顺序与输入一致（不排序）


# ── 14. curl 失败时按配置次数重试 ───────────────────────────────────────────

def test_fetch_retry_count():
    with patch("collector.kline_minute.subprocess.run",
               side_effect=RuntimeError("超时")) as mock_run, \
         patch("collector.kline_minute.time.sleep"):
        result = fetch_kline_minute("000001", retries=3)
    assert result is None
    assert mock_run.call_count == 3


# ── 15. 重试间隔符合配置 ─────────────────────────────────────────────────────

def test_fetch_retry_delay():
    with patch("collector.kline_minute.subprocess.run",
               side_effect=RuntimeError("超时")), \
         patch("collector.kline_minute.time.sleep") as mock_sleep:
        fetch_kline_minute("000001", retries=2)
    for c in mock_sleep.call_args_list:
        assert c == call(RETRY_DELAY)


# ── 16. 第二次重试成功时返回数据 ────────────────────────────────────────────

def test_fetch_succeeds_on_second_attempt():
    good_output = make_raw_json().encode("utf-8")
    mock_result = MagicMock()
    mock_result.returncode  = 0
    mock_result.stdout      = good_output

    with patch("collector.kline_minute.subprocess.run",
               side_effect=[RuntimeError("第一次失败"), mock_result]) as mock_run, \
         patch("collector.kline_minute.time.sleep"):
        result = fetch_kline_minute("000001", retries=3)

    assert result is not None
    assert len(result) == 2
    assert mock_run.call_count == 2


# ── 17. 每个交易日写一个独立文件 ────────────────────────────────────────────

def test_save_one_file_per_day(tmp_path):
    records = [
        make_record("2026-03-18 09:35:00"),
        make_record("2026-03-19 09:35:00"),
        make_record("2026-03-19 09:40:00"),
    ]
    with patch("config.settings.STOCKS_DIR", str(tmp_path)):
        save_kline_minute("000001", records)

    minute_dir = tmp_path / "000001" / "minute_kline"
    assert (minute_dir / "20260318.md").exists()
    assert (minute_dir / "20260319.md").exists()


# ── 18. 文件包含正确表头 ─────────────────────────────────────────────────────

def test_save_has_correct_headers(tmp_path):
    records = [make_record("2026-03-19 09:35:00")]
    with patch("config.settings.STOCKS_DIR", str(tmp_path)):
        save_kline_minute("000001", records)

    content = (tmp_path / "000001" / "minute_kline" / "20260319.md").read_text(encoding="utf-8")
    for col in ["时间", "开盘", "最高", "最低", "收盘", "成交量(手)"]:
        assert col in content


# ── 19. 时间列只显示 HH:MM ──────────────────────────────────────────────────

def test_save_time_column_format(tmp_path):
    records = [make_record("2026-03-19 09:35:00")]
    with patch("config.settings.STOCKS_DIR", str(tmp_path)):
        save_kline_minute("000001", records)

    content = (tmp_path / "000001" / "minute_kline" / "20260319.md").read_text(encoding="utf-8")
    assert "09:35" in content
    assert "2026-03-19 09:35" not in content   # 不含日期部分


# ── 20. 超出 KEEP_DAYS 的旧文件被清理 ────────────────────────────────────────

def test_cleanup_removes_old_files(tmp_path):
    minute_dir = tmp_path / "minute_kline"
    minute_dir.mkdir(parents=True)

    # 创建 KEEP_DAYS + 2 个文件
    all_files = [f"2026031{i}.md" for i in range(1, KEEP_DAYS + 3)]
    for fname in all_files:
        (minute_dir / fname).write_text("content", encoding="utf-8")

    _cleanup_old_files(str(minute_dir), keep=KEEP_DAYS)

    remaining = sorted(f.name for f in minute_dir.glob("*.md"))
    assert len(remaining) == KEEP_DAYS
    # 保留的是最新的 KEEP_DAYS 个
    assert remaining == sorted(all_files)[-KEEP_DAYS:]


# ── 21. 无数据时不写文件 ─────────────────────────────────────────────────────

def test_save_empty_records_no_file(tmp_path):
    with patch("config.settings.STOCKS_DIR", str(tmp_path)):
        save_kline_minute("000001", [])

    minute_dir = tmp_path / "000001" / "minute_kline"
    assert not minute_dir.exists() or len(list(minute_dir.glob("*.md"))) == 0
