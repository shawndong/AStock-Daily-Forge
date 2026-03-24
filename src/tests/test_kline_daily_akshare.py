"""
个股日K线采集层测试

覆盖场景：
  数据解析
  1.  正常数据完整解析（全部字段）
  2.  成交额从元正确转换为亿元（÷1e8）
  3.  涨跌幅为正数时保留符号
  4.  涨跌幅为负数时保留符号
  5.  成交量为整数时正确解析（不损失精度）
  6.  某字段为 NaN 时解析为 None，不崩溃
  7.  接口返回空 DataFrame 时返回空列表
  8.  接口字段变更时抛出明确异常
  9.  日期字段为字符串格式时正确解析为 date 对象
  10. 多天数据按日期顺序全部解析

  重试机制
  11. AKShare 抛出异常时按配置次数重试
  12. 重试间隔符合 RETRY_DELAY 配置
  13. 第二次重试成功时返回正确数据

  存储
  14. 每个交易日写一个独立文件，文件名为 YYYYMMDD.md
  15. 多天数据写入多个文件
  16. 文件内容包含正确表头（11列）
  17. 涨跌幅格式带符号（+/-）
  18. 成交额精度保留4位小数
  19. skip_existing=True 时已存在的文件不被覆盖

  增量更新
  20. fetch_and_save 跳过已存在日期，只写新日期
"""

import os
import sys
from datetime import date
from unittest.mock import call, patch

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from collector.kline_daily_akshare import (
    REQUIRED_COLUMNS,
    RETRY_DELAY,
    _parse_kline_df,
    _validate_columns,
    fetch_and_save,
    fetch_kline_daily,
    save_kline_daily,
)

# ── 测试数据工厂 ──────────────────────────────────────────────────────────────

def make_kline_df(dates: list[date] = None, code: str = "000001") -> pd.DataFrame:
    """构造与 AKShare 返回结构一致的 DataFrame"""
    if dates is None:
        dates = [date(2026, 3, 19)]

    rows = []
    for i, d in enumerate(dates):
        rows.append({
            "日期":   str(d),
            "股票代码": code,
            "开盘":   10.92 + i * 0.1,
            "收盘":   10.88 + i * 0.1,
            "最高":   10.97 + i * 0.1,
            "最低":   10.86 + i * 0.1,
            "成交量": 624212,
            "成交额": 681086519.0,   # 元，约 6.81 亿
            "振幅":   1.00,
            "涨跌幅": -0.73 + i * 0.5,
            "涨跌额": -0.08,
            "换手率": 0.32,
        })
    return pd.DataFrame(rows)


def make_record(d: date = None, code: str = "000001", **kwargs) -> dict:
    """构造单条K线记录"""
    if d is None:
        d = date(2026, 3, 19)
    defaults = {
        "date": d, "code": code,
        "open": 10.92, "close": 10.88, "high": 10.97, "low": 10.86,
        "volume": 624212.0, "amount": 0.6811,
        "amplitude": 1.00, "change_pct": -0.73,
        "change_amt": -0.08, "turnover": 0.32,
    }
    return {**defaults, **kwargs}


# ── 1. 正常数据完整解析 ───────────────────────────────────────────────────────

def test_parse_normal_all_fields():
    d = date(2026, 3, 19)
    df = make_kline_df([d])
    result = _parse_kline_df(df, "000001")

    assert len(result) == 1
    r = result[0]
    assert r["date"]       == d
    assert r["code"]       == "000001"
    assert r["open"]       == pytest.approx(10.92)
    assert r["close"]      == pytest.approx(10.88)
    assert r["high"]       == pytest.approx(10.97)
    assert r["low"]        == pytest.approx(10.86)
    assert r["volume"]     == pytest.approx(624212.0)
    assert r["turnover"]   == pytest.approx(0.32)


# ── 2. 成交额元→亿元转换 ─────────────────────────────────────────────────────

def test_parse_amount_yuan_to_yi():
    d = date(2026, 3, 19)
    df = make_kline_df([d])
    df.at[0, "成交额"] = 1e8   # 恰好 1 亿
    r = _parse_kline_df(df, "000001")[0]
    assert r["amount"] == pytest.approx(1.0, rel=1e-4)


# ── 3. 涨跌幅为正时保留 ─────────────────────────────────────────────────────

def test_parse_positive_change_pct():
    d = date(2026, 3, 19)
    df = make_kline_df([d])
    df.at[0, "涨跌幅"] = 10.01
    r = _parse_kline_df(df, "000001")[0]
    assert r["change_pct"] == pytest.approx(10.01)


# ── 4. 涨跌幅为负时保留 ─────────────────────────────────────────────────────

def test_parse_negative_change_pct():
    d = date(2026, 3, 19)
    df = make_kline_df([d])
    df.at[0, "涨跌幅"] = -5.04
    r = _parse_kline_df(df, "000001")[0]
    assert r["change_pct"] == pytest.approx(-5.04)


# ── 5. 成交量为大整数时不损失精度 ────────────────────────────────────────────

def test_parse_large_volume():
    d = date(2026, 3, 19)
    df = make_kline_df([d])
    df.at[0, "成交量"] = 12345678
    r = _parse_kline_df(df, "000001")[0]
    assert r["volume"] == pytest.approx(12345678.0)


# ── 6. 某字段 NaN 时解析为 None ─────────────────────────────────────────────

def test_parse_nan_field_is_none():
    d = date(2026, 3, 19)
    df = make_kline_df([d])
    df.at[0, "换手率"] = float("nan")
    r = _parse_kline_df(df, "000001")[0]
    assert r["turnover"] is None


# ── 7. 空 DataFrame 返回空列表 ──────────────────────────────────────────────

def test_parse_empty_df_returns_empty():
    result = _parse_kline_df(pd.DataFrame(), "000001")
    assert result == []


# ── 8. 字段变更时抛出明确异常 ────────────────────────────────────────────────

def test_validate_columns_missing_raises():
    bad_df = pd.DataFrame({"日期": [], "价格": []})
    with pytest.raises(ValueError, match="AKShare 返回字段缺失"):
        _validate_columns(bad_df)


def test_validate_columns_ok():
    good_df = pd.DataFrame(columns=list(REQUIRED_COLUMNS) + ["其他列"])
    _validate_columns(good_df)  # 不应抛出


# ── 9. 日期为字符串时正确解析 ────────────────────────────────────────────────

def test_parse_date_string_format():
    df = make_kline_df([date(2026, 3, 19)])
    # 确认日期是字符串格式
    assert isinstance(df.at[0, "日期"], str)
    r = _parse_kline_df(df, "000001")[0]
    assert r["date"] == date(2026, 3, 19)
    assert isinstance(r["date"], date)


# ── 10. 多天数据全部解析 ─────────────────────────────────────────────────────

def test_parse_multiple_dates():
    dates = [date(2026, 3, 17), date(2026, 3, 18), date(2026, 3, 19)]
    df = make_kline_df(dates)
    result = _parse_kline_df(df, "000001")
    assert len(result) == 3
    assert [r["date"] for r in result] == dates


# ── 11. 异常时按配置次数重试 ─────────────────────────────────────────────────

def test_fetch_retry_count():
    with patch("akshare.stock_zh_a_hist",
               side_effect=ConnectionError("超时")) as mock_ak, \
         patch("collector.kline_daily.time.sleep"):
        result = fetch_kline_daily(
            "000001", date(2026, 3, 1), date(2026, 3, 19), retries=3
        )
    assert result is None
    assert mock_ak.call_count == 3


# ── 12. 重试间隔符合配置 ─────────────────────────────────────────────────────

def test_fetch_retry_delay():
    with patch("akshare.stock_zh_a_hist",
               side_effect=ConnectionError("超时")), \
         patch("collector.kline_daily.time.sleep") as mock_sleep:
        fetch_kline_daily("000001", date(2026, 3, 1), date(2026, 3, 19), retries=2)
    for c in mock_sleep.call_args_list:
        assert c == call(RETRY_DELAY)


# ── 13. 第二次重试成功时返回数据 ────────────────────────────────────────────

def test_fetch_succeeds_on_second_attempt():
    d = date(2026, 3, 19)
    good_df = make_kline_df([d])
    with patch("akshare.stock_zh_a_hist",
               side_effect=[ConnectionError("第一次失败"), good_df]) as mock_ak, \
         patch("collector.kline_daily.time.sleep"):
        result = fetch_kline_daily("000001", d, d, retries=3)
    assert result is not None
    assert len(result) == 1
    assert mock_ak.call_count == 2


# ── 14. 每个交易日写一个独立文件 ────────────────────────────────────────────

def test_save_one_file_per_day(tmp_path):
    records = [
        make_record(date(2026, 3, 17)),
        make_record(date(2026, 3, 18)),
        make_record(date(2026, 3, 19)),
    ]
    with patch("config.settings.STOCKS_DIR", str(tmp_path)):
        save_kline_daily("000001", records)

    kline_dir = tmp_path / "000001" / "daily_kline"
    files = list(kline_dir.glob("*.md"))
    assert len(files) == 3
    assert (kline_dir / "20260317.md").exists()
    assert (kline_dir / "20260318.md").exists()
    assert (kline_dir / "20260319.md").exists()


# ── 15. 多天数据写入多个文件内容正确 ────────────────────────────────────────

def test_save_file_content_correct(tmp_path):
    d = date(2026, 3, 19)
    records = [make_record(d, close=10.88, change_pct=-0.73, amount=0.6811)]
    with patch("config.settings.STOCKS_DIR", str(tmp_path)):
        save_kline_daily("000001", records)

    content = (tmp_path / "000001" / "daily_kline" / "20260319.md").read_text(encoding="utf-8")
    assert "000001" in content
    assert "2026-03-19" in content
    assert "10.880" in content   # 收盘价


# ── 16. 文件包含正确表头（11列）────────────────────────────────────────────

def test_save_has_correct_headers(tmp_path):
    records = [make_record(date(2026, 3, 19))]
    with patch("config.settings.STOCKS_DIR", str(tmp_path)):
        save_kline_daily("000001", records)

    content = (tmp_path / "000001" / "daily_kline" / "20260319.md").read_text(encoding="utf-8")
    for col in ["日期", "开盘", "收盘", "成交额(亿)", "涨跌幅", "换手率"]:
        assert col in content


# ── 17. 涨跌幅格式带符号 ─────────────────────────────────────────────────────

def test_save_change_pct_with_sign(tmp_path):
    records = [
        make_record(date(2026, 3, 18), change_pct=10.01),
        make_record(date(2026, 3, 19), change_pct=-0.73),
    ]
    with patch("config.settings.STOCKS_DIR", str(tmp_path)):
        save_kline_daily("000001", records)

    content_up = (tmp_path / "000001" / "daily_kline" / "20260318.md").read_text(encoding="utf-8")
    content_dn = (tmp_path / "000001" / "daily_kline" / "20260319.md").read_text(encoding="utf-8")
    assert "+10.01%" in content_up
    assert "-0.73%" in content_dn


# ── 18. 成交额精度保留4位小数 ────────────────────────────────────────────────

def test_save_amount_precision(tmp_path):
    records = [make_record(date(2026, 3, 19), amount=6.8109)]
    with patch("config.settings.STOCKS_DIR", str(tmp_path)):
        save_kline_daily("000001", records)

    content = (tmp_path / "000001" / "daily_kline" / "20260319.md").read_text(encoding="utf-8")
    assert "6.8109" in content


# ── 19. skip_existing 不覆盖已存在文件 ───────────────────────────────────────

def test_fetch_and_save_skips_existing(tmp_path):
    d = date(2026, 3, 19)
    # 预先创建文件
    kline_dir = tmp_path / "000001" / "daily_kline"
    kline_dir.mkdir(parents=True)
    existing_file = kline_dir / "20260319.md"
    existing_file.write_text("# 已存在的内容", encoding="utf-8")

    good_df = make_kline_df([d])
    with patch("akshare.stock_zh_a_hist", return_value=good_df), \
         patch("config.settings.STOCKS_DIR", str(tmp_path)), \
         patch("collector.kline_daily.time.sleep"):
        fetch_and_save("000001", d, d, skip_existing=True)

    # 文件内容应未被覆盖
    content = existing_file.read_text(encoding="utf-8")
    assert "已存在的内容" in content


# ── 20. fetch_and_save 只写新日期 ────────────────────────────────────────────

def test_fetch_and_save_writes_new_dates(tmp_path):
    dates = [date(2026, 3, 17), date(2026, 3, 18), date(2026, 3, 19)]

    # 预先存在 3-17 的文件
    kline_dir = tmp_path / "000001" / "daily_kline"
    kline_dir.mkdir(parents=True)
    (kline_dir / "20260317.md").write_text("# 已存在", encoding="utf-8")

    good_df = make_kline_df(dates)
    with patch("akshare.stock_zh_a_hist", return_value=good_df), \
         patch("config.settings.STOCKS_DIR", str(tmp_path)), \
         patch("collector.kline_daily.time.sleep"):
        fetch_and_save("000001", dates[0], dates[-1], skip_existing=True)

    # 只有 3-18 和 3-19 是新写入的
    assert (kline_dir / "20260318.md").exists()
    assert (kline_dir / "20260319.md").exists()
    # 3-17 的内容不被覆盖
    assert "已存在" in (kline_dir / "20260317.md").read_text(encoding="utf-8")
