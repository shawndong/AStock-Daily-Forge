"""
市场状态计算层测试

覆盖场景：
  1.  跌停比例 >= 30% → 崩溃
  2.  大跌比例 >= 50% → 大回撤
  3.  有涨停且有大跌 → 分歧
  4.  无跌停无大跌 → 强势
  5.  无高位股 → 无高位股
  6.  崩溃优先于大回撤（同时满足时）
  7.  run() 写入文件包含必要字段
"""

import os
import sys
from datetime import date
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from calculator.market_state import classify_market_state

# ── 1. 跌停比例 >= 30% → 崩溃 ───────────────────────────────────────────────

def test_classify_crash():
    state = {"total": 10, "limit_down_count": 3,
             "big_drop_count": 1, "limit_up_count": 2}
    with patch("config.settings.STATE_CRASH_LIMIT_DOWN_RATIO", 0.30), \
         patch("config.settings.STATE_RETREAT_BIG_DROP_RATIO", 0.50):
        assert classify_market_state(state) == "崩溃"


# ── 2. 大跌比例 >= 50% → 大回撤 ─────────────────────────────────────────────

def test_classify_retreat():
    state = {"total": 10, "limit_down_count": 1,
             "big_drop_count": 5, "limit_up_count": 2}
    with patch("config.settings.STATE_CRASH_LIMIT_DOWN_RATIO", 0.30), \
         patch("config.settings.STATE_RETREAT_BIG_DROP_RATIO", 0.50):
        assert classify_market_state(state) == "大回撤"


# ── 3. 有涨停且有大跌 → 分歧 ─────────────────────────────────────────────────

def test_classify_diverge():
    state = {"total": 10, "limit_down_count": 0,
             "big_drop_count": 2, "limit_up_count": 3}
    with patch("config.settings.STATE_CRASH_LIMIT_DOWN_RATIO", 0.30), \
         patch("config.settings.STATE_RETREAT_BIG_DROP_RATIO", 0.50):
        assert classify_market_state(state) == "分歧"


# ── 4. 无跌停无大跌 → 强势 ───────────────────────────────────────────────────

def test_classify_strong():
    state = {"total": 10, "limit_down_count": 0,
             "big_drop_count": 0, "limit_up_count": 5}
    with patch("config.settings.STATE_CRASH_LIMIT_DOWN_RATIO", 0.30), \
         patch("config.settings.STATE_RETREAT_BIG_DROP_RATIO", 0.50):
        assert classify_market_state(state) == "强势"


# ── 5. 无高位股 → 无高位股 ───────────────────────────────────────────────────

def test_classify_no_high_level():
    state = {"total": 0, "limit_down_count": 0,
             "big_drop_count": 0, "limit_up_count": 0}
    with patch("config.settings.STATE_CRASH_LIMIT_DOWN_RATIO", 0.30), \
         patch("config.settings.STATE_RETREAT_BIG_DROP_RATIO", 0.50):
        assert classify_market_state(state) == "无高位股"


# ── 6. 崩溃优先于大回撤 ──────────────────────────────────────────────────────

def test_classify_crash_priority_over_retreat():
    state = {"total": 10, "limit_down_count": 4,
             "big_drop_count": 6, "limit_up_count": 0}
    with patch("config.settings.STATE_CRASH_LIMIT_DOWN_RATIO", 0.30), \
         patch("config.settings.STATE_RETREAT_BIG_DROP_RATIO", 0.50):
        assert classify_market_state(state) == "崩溃"


# ── 7. run() 写入文件包含必要字段 ─────────────────────────────────────────────

def test_run_writes_file(tmp_path):
    with patch("calculator.high_level.filter_high_level", return_value=[]), \
         patch("calculator.high_level.get_high_level_state",
               return_value={"total": 0, "limit_up_count": 0,
                             "limit_down_count": 0, "big_drop_count": 0}), \
         patch("calculator.streak.get_max_streak", return_value=0), \
         patch("calculator.main_theme.get_main_themes", return_value=[]), \
         patch("calculator.main_theme.get_leader", return_value=None), \
         patch("calculator.main_theme.get_sub_leader", return_value=None), \
         patch("calculator.main_theme.get_spread_strength", return_value="弱"), \
         patch("config.settings.MARKET_STATE_DIR", str(tmp_path)), \
         patch("config.settings.STATE_CRASH_LIMIT_DOWN_RATIO", 0.30), \
         patch("config.settings.STATE_RETREAT_BIG_DROP_RATIO", 0.50):
        from calculator.market_state import run
        run(date(2026, 3, 19))

    content = (tmp_path / "20260319.md").read_text(encoding="utf-8")
    assert "市场状态" in content
    assert "最大连板高度" in content
    assert "资金扩散强度" in content
