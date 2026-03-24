"""
主线识别计算层测试

覆盖场景：
  1.  龙头：连板数最高的股票优先
  2.  龙头：连板数相同时成交额大的优先
  3.  主线为空时龙头返回 None
  4.  次龙头不包含龙头自身
  5.  扩散强度：主线涨停数 >= 6 → 强
  6.  扩散强度：主线涨停数 >= 3 → 中
  7.  扩散强度：主线涨停数 < 3 → 弱
  8.  主线为空时扩散强度为弱
  9.  个股地位：龙头
  10. 个股地位：次龙头
  11. 个股地位：补涨（在主线但非龙头/次龙头）
  12. 个股地位：非主线
"""

import os
import sys
from datetime import date
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from calculator.main_theme import (
    get_leader,
    get_spread_strength,
    get_stock_position,
    get_sub_leader,
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


# ── 1. 龙头：连板数最高优先 ──────────────────────────────────────────────────

def test_get_leader_by_streak_then_amount():
    content = make_limit_up_content([
        {"代码": "A", "名称": "高成交3板", "连板数": "3",
         "成交额(亿)": "20.0", "所属行业": "AI算力"},
        {"代码": "B", "名称": "低成交5板", "连板数": "5",
         "成交额(亿)": "5.0",  "所属行业": "AI算力"},
        {"代码": "C", "名称": "1板股",    "连板数": "1",
         "成交额(亿)": "50.0", "所属行业": "AI算力"},
    ])
    with patch("storage.reader.read_md_by_date", return_value=content):
        leader = get_leader(["AI算力"], date(2026, 3, 19))
    assert leader["code"] == "B"


# ── 2. 龙头：同连板时成交额大的优先 ─────────────────────────────────────────

def test_get_leader_same_streak_uses_amount():
    content = make_limit_up_content([
        {"代码": "A", "名称": "低量3板", "连板数": "3",
         "成交额(亿)": "5.0",  "所属行业": "光学光电"},
        {"代码": "B", "名称": "高量3板", "连板数": "3",
         "成交额(亿)": "20.0", "所属行业": "光学光电"},
    ])
    with patch("storage.reader.read_md_by_date", return_value=content):
        leader = get_leader(["光学光电"], date(2026, 3, 19))
    assert leader["code"] == "B"


# ── 3. 主线为空时龙头为 None ─────────────────────────────────────────────────

def test_get_leader_no_themes_returns_none():
    with patch("storage.reader.read_md_by_date", return_value=None):
        assert get_leader([], date(2026, 3, 19)) is None


# ── 4. 次龙头不包含龙头自身 ──────────────────────────────────────────────────

def test_get_sub_leader_excludes_leader():
    content = make_limit_up_content([
        {"代码": "A", "名称": "5板龙头", "连板数": "5",
         "成交额(亿)": "20.0", "所属行业": "AI算力"},
        {"代码": "B", "名称": "3板次龙", "连板数": "3",
         "成交额(亿)": "10.0", "所属行业": "AI算力"},
        {"代码": "C", "名称": "1板补涨", "连板数": "1",
         "成交额(亿)": "50.0", "所属行业": "AI算力"},
    ])
    with patch("storage.reader.read_md_by_date", return_value=content):
        sub = get_sub_leader(["AI算力"], "A", date(2026, 3, 19))
    assert sub["code"] == "B"


# ── 5. 扩散强度：>= 6 → 强 ──────────────────────────────────────────────────

def test_get_spread_strength_strong():
    rows    = [{"代码": f"{i:06d}", "所属行业": "AI算力"} for i in range(6)]
    content = make_limit_up_content(rows)
    with patch("storage.reader.read_md_by_date", return_value=content), \
         patch("config.settings.SPREAD_STRONG_COUNT", 6), \
         patch("config.settings.SPREAD_MID_COUNT", 3):
        assert get_spread_strength(["AI算力"], date(2026, 3, 19)) == "强"


# ── 6. 扩散强度：>= 3 → 中 ──────────────────────────────────────────────────

def test_get_spread_strength_mid():
    rows    = [{"代码": f"{i:06d}", "所属行业": "AI算力"} for i in range(4)]
    content = make_limit_up_content(rows)
    with patch("storage.reader.read_md_by_date", return_value=content), \
         patch("config.settings.SPREAD_STRONG_COUNT", 6), \
         patch("config.settings.SPREAD_MID_COUNT", 3):
        assert get_spread_strength(["AI算力"], date(2026, 3, 19)) == "中"


# ── 7. 扩散强度：< 3 → 弱 ───────────────────────────────────────────────────

def test_get_spread_strength_weak():
    content = make_limit_up_content([{"代码": "000001", "所属行业": "AI算力"}])
    with patch("storage.reader.read_md_by_date", return_value=content), \
         patch("config.settings.SPREAD_STRONG_COUNT", 6), \
         patch("config.settings.SPREAD_MID_COUNT", 3):
        assert get_spread_strength(["AI算力"], date(2026, 3, 19)) == "弱"


# ── 8. 主线为空时扩散强度为弱 ───────────────────────────────────────────────

def test_get_spread_strength_no_themes():
    assert get_spread_strength([], date(2026, 3, 19)) == "弱"


# ── 9. 个股地位：龙头 ────────────────────────────────────────────────────────

def test_get_stock_position_leader():
    with patch("storage.reader.read_md_by_date", return_value=None):
        assert get_stock_position("A", ["AI算力"], "A", "B") == "龙头"


# ── 10. 个股地位：次龙头 ─────────────────────────────────────────────────────

def test_get_stock_position_sub_leader():
    with patch("storage.reader.read_md_by_date", return_value=None):
        assert get_stock_position("B", ["AI算力"], "A", "B") == "次龙头"


# ── 11. 个股地位：补涨 ───────────────────────────────────────────────────────

def test_get_stock_position_follow():
    content = make_limit_up_content([{"代码": "C", "所属行业": "AI算力"}])
    with patch("storage.reader.read_md_by_date", return_value=content):
        assert get_stock_position("C", ["AI算力"], "A", "B") == "补涨"


# ── 12. 个股地位：非主线 ─────────────────────────────────────────────────────

def test_get_stock_position_not_main():
    content = make_limit_up_content([{"代码": "D", "所属行业": "其他行业"}])
    with patch("storage.reader.read_md_by_date", return_value=content):
        assert get_stock_position("D", ["AI算力"], "A", "B") == "非主线"
