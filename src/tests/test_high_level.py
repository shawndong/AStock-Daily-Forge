"""
高位股筛选计算层测试

覆盖场景：
  5日涨幅计算
  1.  正常数据正确计算5日涨幅
  2.  上涨时为正值，下跌时为负值
  3.  文件数量不足2个时返回 None
  4.  收盘价字段为 N/A 时返回 None
  5.  基准日收盘价为 0 时返回 None（避免除零）

  高位股判断
  6.  连板数 >= 阈值时判定为高位股
  7.  5日涨幅 >= 阈值时判定为高位股
  8.  两个条件均不满足时不是高位股
  9.  5日涨幅为 None 时只用连板数判断
  10. 连板数恰好等于阈值时判定为高位股（边界值）

  筛选主逻辑
  11. 高位股被正确筛选出来，非高位股被排除
  12. 结果按连板数降序排列
  13. 无涨停池数据时返回空列表
  14. 涨停池有数据但所有股都不是高位股时返回空列表

  状态统计
  15. 涨停/跌停/大跌数量统计正确
  16. ST 股使用更低的涨跌停阈值
  17. 无K线数据时跳过该股，不崩溃
  18. 空高位股列表时各计数为 0
"""

import os
import sys
from datetime import date
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from calculator.high_level import (
    calc_5d_change,
    filter_high_level,
    get_high_level_state,
    is_high_level,
)

# ── 测试数据工厂 ──────────────────────────────────────────────────────────────

def make_kline_content(close: float) -> str:
    return (
        f"# 日K线\n\n"
        f"| 日期 | 开盘 | 收盘 | 最高 | 最低 | 成交量(手) | 成交额(亿) | 涨跌幅 |\n"
        f"| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        f"| 2026-03-19 | {close} | {close} | {close} | {close} | 10000 | 1.0 | +5.00% |\n"
    )


def make_kline_with_pct(pct: float) -> str:
    sign = "+" if pct >= 0 else ""
    return (
        f"# 日K线\n\n"
        f"| 日期 | 开盘 | 收盘 | 最高 | 最低 | 成交量(手) | 成交额(亿) | 涨跌幅 |\n"
        f"| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        f"| 2026-03-19 | 10.0 | 10.0 | 10.0 | 10.0 | 10000 | 1.0 | {sign}{pct:.2f}% |\n"
    )


def make_limit_up_content(rows: list[dict]) -> str:
    headers = ["代码", "名称", "涨跌幅", "最新价", "成交额(亿)", "流通市值(亿)",
               "总市值(亿)", "换手率", "封板资金(亿)", "首次封板", "最后封板",
               "炸板次数", "涨停统计", "连板数", "所属行业"]
    lines = ["# 涨停股池\n",
             "| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        cells = [str(row.get(h, "N/A")) for h in headers]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


# ── 1. 正常5日涨幅计算 ────────────────────────────────────────────────────────

def test_calc_5d_change_normal():
    base    = make_kline_content(20.0)
    latest  = make_kline_content(25.0)
    recent  = [(date(2026, 3, 12), base),
               (date(2026, 3, 13), base),
               (date(2026, 3, 17), base),
               (date(2026, 3, 18), base),
               (date(2026, 3, 19), base),
               (date(2026, 3, 20), latest)]
    with patch("storage.reader.read_recent_mds", return_value=recent):
        result = calc_5d_change("000020", date(2026, 3, 20))
    assert result == pytest.approx(0.25, rel=1e-3)


# ── 2. 下跌时为负值 ───────────────────────────────────────────────────────────

def test_calc_5d_change_negative():
    base    = make_kline_content(25.0)
    latest  = make_kline_content(20.0)
    recent  = [(date(2026, 3, 12), base)] * 5 + [(date(2026, 3, 20), latest)]
    with patch("storage.reader.read_recent_mds", return_value=recent):
        result = calc_5d_change("000020", date(2026, 3, 20))
    assert result == pytest.approx(-0.20, rel=1e-3)


# ── 3. 文件不足2个时返回 None ────────────────────────────────────────────────

def test_calc_5d_change_insufficient_data():
    recent = [(date(2026, 3, 19), make_kline_content(20.0))]
    with patch("storage.reader.read_recent_mds", return_value=recent):
        assert calc_5d_change("000020", date(2026, 3, 19)) is None


# ── 4. 收盘价为 N/A 时返回 None ─────────────────────────────────────────────

def test_calc_5d_change_na_close():
    bad = "# K\n| 收盘 |\n| --- |\n| N/A |\n"
    good = make_kline_content(20.0)
    with patch("storage.reader.read_recent_mds",
               return_value=[(date(2026, 3, 18), bad),
                             (date(2026, 3, 19), good)]):
        assert calc_5d_change("000020", date(2026, 3, 19)) is None


# ── 5. 基准日收盘为 0 时返回 None ────────────────────────────────────────────

def test_calc_5d_change_zero_base():
    base   = make_kline_content(0.0)
    latest = make_kline_content(20.0)
    with patch("storage.reader.read_recent_mds",
               return_value=[(date(2026, 3, 18), base),
                             (date(2026, 3, 19), latest)]):
        assert calc_5d_change("000020", date(2026, 3, 19)) is None


# ── 6. 连板数达阈值判定高位股 ────────────────────────────────────────────────

def test_is_high_level_by_streak():
    with patch("config.settings.HIGH_LEVEL_MIN_STREAK", 3), \
         patch("config.settings.HIGH_LEVEL_MIN_CHANGE_5D", 0.25):
        assert is_high_level("000020", streak=3, change_5d=0.0)  is True
        assert is_high_level("000020", streak=5, change_5d=0.0)  is True


# ── 7. 5日涨幅达阈值判定高位股 ──────────────────────────────────────────────

def test_is_high_level_by_5d_change():
    with patch("config.settings.HIGH_LEVEL_MIN_STREAK", 3), \
         patch("config.settings.HIGH_LEVEL_MIN_CHANGE_5D", 0.25):
        assert is_high_level("000020", streak=1, change_5d=0.25) is True
        assert is_high_level("000020", streak=1, change_5d=0.30) is True


# ── 8. 两条件均不满足 ────────────────────────────────────────────────────────

def test_is_high_level_not():
    with patch("config.settings.HIGH_LEVEL_MIN_STREAK", 3), \
         patch("config.settings.HIGH_LEVEL_MIN_CHANGE_5D", 0.25):
        assert is_high_level("000020", streak=2, change_5d=0.20) is False


# ── 9. 5日涨幅 None 时只用连板数 ─────────────────────────────────────────────

def test_is_high_level_none_change():
    with patch("config.settings.HIGH_LEVEL_MIN_STREAK", 3), \
         patch("config.settings.HIGH_LEVEL_MIN_CHANGE_5D", 0.25):
        assert is_high_level("000020", streak=3, change_5d=None) is True
        assert is_high_level("000020", streak=1, change_5d=None) is False


# ── 10. 边界值：连板数恰好等于阈值 ──────────────────────────────────────────

def test_is_high_level_streak_boundary():
    with patch("config.settings.HIGH_LEVEL_MIN_STREAK", 3), \
         patch("config.settings.HIGH_LEVEL_MIN_CHANGE_5D", 0.25):
        assert is_high_level("X", streak=3, change_5d=0.0) is True
        assert is_high_level("X", streak=2, change_5d=0.0) is False


# ── 11. 高位股筛选正确 ────────────────────────────────────────────────────────

def test_filter_high_level_correct():
    d = date(2026, 3, 19)
    content = make_limit_up_content([
        {"代码": "000020", "名称": "深华发A",  "连板数": "5", "所属行业": "光学光电"},
        {"代码": "000677", "名称": "恒天海龙", "连板数": "1", "所属行业": "化学纤维"},
    ])

    def mock_read(dir_path, d_):
        return content if d_ == d else None

    def mock_recent(dir_path, n, end_date=None):
        # 为 000020 提供涨幅 30% 的数据
        if "000020" in dir_path:
            return [(date(2026, 3, i), make_kline_content(15.0 + i * 0.5))
                    for i in range(14, 20)]
        return []

    with patch("storage.reader.read_md_by_date", side_effect=mock_read), \
         patch("storage.reader.read_recent_mds", side_effect=mock_recent), \
         patch("config.settings.HIGH_LEVEL_MIN_STREAK", 3), \
         patch("config.settings.HIGH_LEVEL_MIN_CHANGE_5D", 0.25):
        result = filter_high_level(d)

    codes = [r["code"] for r in result]
    assert "000020" in codes    # 5连板，高位股
    assert "000677" not in codes  # 1连板，非高位股


# ── 12. 结果按连板数降序排列 ─────────────────────────────────────────────────

def test_filter_high_level_sorted():
    d = date(2026, 3, 19)
    content = make_limit_up_content([
        {"代码": "A", "名称": "A股", "连板数": "3", "所属行业": "行业A"},
        {"代码": "B", "名称": "B股", "连板数": "5", "所属行业": "行业B"},
        {"代码": "C", "名称": "C股", "连板数": "4", "所属行业": "行业C"},
    ])
    with patch("storage.reader.read_md_by_date", return_value=content), \
         patch("storage.reader.read_recent_mds", return_value=[]), \
         patch("config.settings.HIGH_LEVEL_MIN_STREAK", 3), \
         patch("config.settings.HIGH_LEVEL_MIN_CHANGE_5D", 0.25):
        result = filter_high_level(d)

    streaks = [r["streak"] for r in result]
    assert streaks == sorted(streaks, reverse=True)


# ── 13. 无涨停池数据时返回空列表 ─────────────────────────────────────────────

def test_filter_high_level_no_data():
    with patch("storage.reader.read_md_by_date", return_value=None):
        assert filter_high_level(date(2026, 3, 19)) == []


# ── 14. 无高位股时返回空列表 ─────────────────────────────────────────────────

def test_filter_high_level_none_qualify():
    d = date(2026, 3, 19)
    content = make_limit_up_content([
        {"代码": "000001", "名称": "平安银行", "连板数": "1", "所属行业": "银行"},
    ])
    with patch("storage.reader.read_md_by_date", return_value=content), \
         patch("storage.reader.read_recent_mds", return_value=[]), \
         patch("config.settings.HIGH_LEVEL_MIN_STREAK", 3), \
         patch("config.settings.HIGH_LEVEL_MIN_CHANGE_5D", 0.25):
        assert filter_high_level(d) == []


# ── 15. 状态统计正确 ─────────────────────────────────────────────────────────

def test_get_high_level_state_counts():
    stocks = [
        {"code": "A", "name": "A股"},
        {"code": "B", "name": "B股"},
        {"code": "C", "name": "C股"},
        {"code": "D", "name": "D股"},
    ]
    klines = {
        "A": make_kline_with_pct(10.01),   # 涨停
        "B": make_kline_with_pct(-10.01),  # 跌停
        "C": make_kline_with_pct(-6.00),   # 大跌 >5%
        "D": make_kline_with_pct(3.00),    # 普通
    }

    def mock_recent(dir_path, n, end_date=None):
        for code, content in klines.items():
            if f"{os.sep}{code}{os.sep}" in dir_path:
                return [(date(2026, 3, 19), content)]
        return []

    with patch("storage.reader.read_recent_mds", side_effect=mock_recent), \
         patch("config.settings.BIG_DROP_THRESHOLD", 0.05):
        result = get_high_level_state(stocks)

    assert result["total"]            == 4
    assert result["limit_up_count"]   == 1
    assert result["limit_down_count"] == 1
    assert result["big_drop_count"]   == 1


# ── 16. ST 股使用更低的涨跌停阈值 ───────────────────────────────────────────

def test_get_high_level_state_st_threshold():
    stocks = [{"code": "A", "name": "*ST测试"}]
    # ST 股涨 4.8% 应视为涨停（>= 4.5%）
    kline = make_kline_with_pct(4.8)

    with patch("storage.reader.read_recent_mds",
               return_value=[(date(2026, 3, 19), kline)]), \
         patch("config.settings.BIG_DROP_THRESHOLD", 0.05):
        result = get_high_level_state(stocks)

    assert result["limit_up_count"] == 1


# ── 17. 无K线数据时跳过不崩溃 ───────────────────────────────────────────────

def test_get_high_level_state_no_kline():
    stocks = [{"code": "A", "name": "A股"}, {"code": "B", "name": "B股"}]
    with patch("storage.reader.read_recent_mds", return_value=[]), \
         patch("config.settings.BIG_DROP_THRESHOLD", 0.05):
        result = get_high_level_state(stocks)

    assert result["total"]          == 2
    assert result["limit_up_count"] == 0


# ── 18. 空列表时各计数为 0 ───────────────────────────────────────────────────

def test_get_high_level_state_empty():
    result = get_high_level_state([])
    assert result == {"total": 0, "limit_up_count": 0,
                      "limit_down_count": 0, "big_drop_count": 0}
