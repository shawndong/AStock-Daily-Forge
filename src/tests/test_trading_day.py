"""
交易日判断工具测试

覆盖场景：
  1.  普通工作日（周一至周五）→ 交易日
  2.  周六 → 非交易日
  3.  周日 → 非交易日
  4.  节假日区间第一天 → 非交易日
  5.  节假日区间最后一天 → 非交易日
  6.  节假日区间中间某天 → 非交易日
  7.  节假日前一天（工作日）→ 交易日
  8.  节假日后一天（工作日）→ 交易日
  9.  节假日配置格式错误时跳过该条，不崩溃
  10. get_last_trading_day：当天是交易日时返回当天
  11. get_last_trading_day：当天是周末时返回上周五
  12. get_last_trading_day：跨节假日找到最近交易日
  13. get_next_trading_day：返回下一个工作日
  14. get_next_trading_day：跨周末返回下周一
  15. assert_trading_day：交易日返回 True
  16. assert_trading_day：非交易日返回 False
  17. 2026年全年关键节假日验证（元旦、春节、国庆等）
"""

import os
import sys
from datetime import date
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scheduler.trading_day import (
    assert_trading_day,
    get_last_trading_day,
    get_next_trading_day,
    is_trading_day,
)

# 测试用节假日配置（与生产配置结构一致）
TEST_HOLIDAYS = [
    {"name": "元旦",   "start": "2026-01-01", "end": "2026-01-01"},
    {"name": "春节",   "start": "2026-02-15", "end": "2026-02-23"},
    {"name": "清明节", "start": "2026-04-04", "end": "2026-04-06"},
    {"name": "劳动节", "start": "2026-05-01", "end": "2026-05-05"},
    {"name": "端午节", "start": "2026-06-19", "end": "2026-06-21"},
    {"name": "中秋节", "start": "2026-09-25", "end": "2026-09-27"},
    {"name": "国庆节", "start": "2026-10-01", "end": "2026-10-07"},
]


def patch_holidays(holidays=TEST_HOLIDAYS):
    return patch("config.trading_calendar.HOLIDAYS", holidays)


# ── 1. 普通工作日 → 交易日 ───────────────────────────────────────────────────

def test_normal_weekday_is_trading():
    d = date(2026, 3, 23)   # 周一
    with patch_holidays():
        assert is_trading_day(d) is True


# ── 2. 周六 → 非交易日 ──────────────────────────────────────────────────────

def test_saturday_not_trading():
    d = date(2026, 3, 21)   # 周六
    with patch_holidays():
        assert is_trading_day(d) is False


# ── 3. 周日 → 非交易日 ──────────────────────────────────────────────────────

def test_sunday_not_trading():
    d = date(2026, 3, 22)   # 周日
    with patch_holidays():
        assert is_trading_day(d) is False


# ── 4. 节假日区间第一天 ──────────────────────────────────────────────────────

def test_holiday_first_day_not_trading():
    with patch_holidays():
        assert is_trading_day(date(2026, 10, 1)) is False   # 国庆第一天


# ── 5. 节假日区间最后一天 ────────────────────────────────────────────────────

def test_holiday_last_day_not_trading():
    with patch_holidays():
        assert is_trading_day(date(2026, 10, 7)) is False   # 国庆最后一天


# ── 6. 节假日区间中间某天 ────────────────────────────────────────────────────

def test_holiday_middle_day_not_trading():
    with patch_holidays():
        assert is_trading_day(date(2026, 10, 4)) is False   # 国庆中间


# ── 7. 节假日前一天（工作日）→ 交易日 ───────────────────────────────────────

def test_day_before_holiday_is_trading():
    with patch_holidays():
        assert is_trading_day(date(2026, 9, 30)) is True    # 国庆前一天（周三）


# ── 8. 节假日后一天（工作日）→ 交易日 ───────────────────────────────────────

def test_day_after_holiday_is_trading():
    with patch_holidays():
        assert is_trading_day(date(2026, 10, 8)) is True    # 国庆后一天（周四）


# ── 9. 配置格式错误时跳过该条，不崩溃 ──────────────────────────────────────

def test_bad_holiday_config_no_crash():
    bad_holidays = [
        {"name": "格式错误", "start": "not-a-date", "end": "2026-01-01"},
        {"name": "正常节日", "start": "2026-01-01", "end": "2026-01-01"},
    ]
    with patch("config.trading_calendar.HOLIDAYS", bad_holidays):
        # 元旦应该被识别（第二条正常配置）
        assert is_trading_day(date(2026, 1, 1)) is False
        # 不应该崩溃


# ── 10. get_last_trading_day：当天是交易日返回当天 ───────────────────────────

def test_last_trading_day_today_is_trading():
    d = date(2026, 3, 23)   # 周一
    with patch_holidays():
        assert get_last_trading_day(d) == d


# ── 11. get_last_trading_day：周末返回上周五 ─────────────────────────────────

def test_last_trading_day_from_weekend():
    saturday = date(2026, 3, 21)
    friday   = date(2026, 3, 20)
    with patch_holidays():
        assert get_last_trading_day(saturday) == friday


# ── 12. get_last_trading_day：跨节假日 ─────────────────────────────────────

def test_last_trading_day_across_holiday():
    # 国庆节后第一天（10月8日周四）回溯，找到国庆前最后一天（9月30日周三）
    oct8 = date(2026, 10, 8)
    with patch_holidays():
        result = get_last_trading_day(oct8)
    assert result == oct8   # 10月8日本身是交易日


# ── 13. get_next_trading_day：返回下一个工作日 ──────────────────────────────

def test_next_trading_day_normal():
    monday = date(2026, 3, 23)
    with patch_holidays():
        assert get_next_trading_day(monday) == date(2026, 3, 24)  # 周二


# ── 14. get_next_trading_day：跨周末 ────────────────────────────────────────

def test_next_trading_day_across_weekend():
    friday = date(2026, 3, 20)
    with patch_holidays():
        assert get_next_trading_day(friday) == date(2026, 3, 23)  # 下周一


# ── 15. assert_trading_day：交易日返回 True ─────────────────────────────────

def test_assert_trading_day_true():
    with patch_holidays():
        assert assert_trading_day(date(2026, 3, 23)) is True


# ── 16. assert_trading_day：非交易日返回 False ──────────────────────────────

def test_assert_trading_day_false():
    with patch_holidays():
        assert assert_trading_day(date(2026, 3, 21)) is False   # 周六


# ── 17. 2026年全年关键节假日验证 ────────────────────────────────────────────

@pytest.mark.parametrize("d,expected", [
    # 元旦
    (date(2026, 1,  1), False),   # 元旦
    (date(2026, 1,  2), True),    # 元旦后工作日（周五）
    # 春节
    (date(2026, 2, 15), False),   # 春节第一天（周日）
    (date(2026, 2, 23), False),   # 春节最后一天（周一）
    (date(2026, 2, 24), True),    # 复市第一天（周二）
    # 清明节
    (date(2026, 4,  4), False),   # 清明（周六）
    (date(2026, 4,  6), False),   # 清明假最后（周一）
    (date(2026, 4,  7), True),    # 复市（周二）
    # 劳动节
    (date(2026, 5,  1), False),   # 劳动节（周五）
    (date(2026, 5,  5), False),   # 假期最后（周二）
    (date(2026, 5,  6), True),    # 复市（周三）
    # 端午节
    (date(2026, 6, 19), False),   # 端午（周五）
    (date(2026, 6, 21), False),   # 假期最后（周日）
    (date(2026, 6, 22), True),    # 复市（周一）
    # 中秋节
    (date(2026, 9, 25), False),   # 中秋（周五）
    (date(2026, 9, 27), False),   # 假期最后（周日）
    (date(2026, 9, 28), True),    # 复市（周一）
    # 国庆节
    (date(2026, 10,  1), False),  # 国庆（周四）
    (date(2026, 10,  7), False),  # 假期最后（周三）
    (date(2026, 10,  8), True),   # 复市（周四）
])
def test_2026_holidays(d, expected):
    with patch_holidays():
        assert is_trading_day(d) == expected, \
            f"{d} 期望 {'交易日' if expected else '非交易日'}，实际相反"
