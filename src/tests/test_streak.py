"""
连板数计算层测试

覆盖场景：
  从涨停池读取（首选）
  1.  股票在涨停池中，返回正确连板数
  2.  股票不在涨停池中，返回 0
  3.  涨停池文件不存在，返回 None
  4.  连板数字段非数字时返回 0，不崩溃
  5.  涨停池为空表格时返回 0

  从K线推算（备用）
  6.  连续涨停时正确计算连板数
  7.  中间有一天未涨停，只计算连续部分
  8.  第一天就未涨停，返回 0
  9.  ST 股使用更低的涨停阈值（4.5%）
  10. K线文件不存在时返回 0，不崩溃
  11. 涨跌幅为 N/A 时中断计算

  自动选择来源（get_streak）
  12. 涨停池有数据时优先用涨停池
  13. 涨停池文件不存在时回退到K线
  14. 涨停池返回 0（未涨停）时不回退K线

  批量读取
  15. get_all_streaks 正确返回所有涨停股的连板数
  16. 涨停池为空时返回空字典
  17. get_max_streak 返回最大连板数
  18. get_max_streak 空数据时返回 0
"""

import os
import sys
from datetime import date
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from calculator.streak import (
    get_all_streaks,
    get_max_streak,
    get_streak,
    get_streak_from_kline,
    get_streak_from_limit_up,
)

# ── 测试数据工厂 ──────────────────────────────────────────────────────────────

def make_limit_up_content(rows: list[dict]) -> str:
    headers = ["代码", "名称", "涨跌幅", "最新价", "成交额(亿)", "流通市值(亿)",
               "总市值(亿)", "换手率", "封板资金(亿)", "首次封板", "最后封板",
               "炸板次数", "涨停统计", "连板数", "所属行业"]
    lines = ["# 涨停股池 2026-03-19\n",
             "| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        cells = [str(row.get(h, "N/A")) for h in headers]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def make_kline_content(code: str, rows: list[dict]) -> str:
    headers = ["日期", "开盘", "收盘", "最高", "最低", "成交量(手)", "成交额(亿)", "涨跌幅"]
    lines = [f"# {code} 日K线\n",
             "| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        cells = [str(row.get(h, "N/A")) for h in headers]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


# ── 1. 股票在涨停池中返回正确连板数 ──────────────────────────────────────────

def test_get_streak_from_limit_up_found():
    content = make_limit_up_content([
        {"代码": "000020", "连板数": "5"},
        {"代码": "000677", "连板数": "1"},
    ])
    with patch("storage.reader.read_md_by_date", return_value=content):
        assert get_streak_from_limit_up("000020", date(2026, 3, 19)) == 5
        assert get_streak_from_limit_up("000677", date(2026, 3, 19)) == 1


# ── 2. 股票不在涨停池中返回 0 ────────────────────────────────────────────────

def test_get_streak_from_limit_up_not_found():
    content = make_limit_up_content([{"代码": "000020", "连板数": "5"}])
    with patch("storage.reader.read_md_by_date", return_value=content):
        assert get_streak_from_limit_up("999999", date(2026, 3, 19)) == 0


# ── 3. 涨停池文件不存在返回 None ─────────────────────────────────────────────

def test_get_streak_from_limit_up_no_file():
    with patch("storage.reader.read_md_by_date", return_value=None):
        assert get_streak_from_limit_up("000020", date(2026, 3, 19)) is None


# ── 4. 连板数字段非数字返回 0 ────────────────────────────────────────────────

def test_get_streak_from_limit_up_invalid_value():
    content = make_limit_up_content([{"代码": "000020", "连板数": "N/A"}])
    with patch("storage.reader.read_md_by_date", return_value=content):
        assert get_streak_from_limit_up("000020", date(2026, 3, 19)) == 0


# ── 5. 涨停池为空表格返回 0 ──────────────────────────────────────────────────

def test_get_streak_from_limit_up_empty_table():
    content = make_limit_up_content([])
    with patch("storage.reader.read_md_by_date", return_value=content):
        assert get_streak_from_limit_up("000020", date(2026, 3, 19)) == 0


# ── 6. 连续涨停时正确计算连板数 ──────────────────────────────────────────────

def test_get_streak_from_kline_consecutive():
    kline_rows = [
        {"日期": "2026-03-17", "涨跌幅": "+10.01%"},
        {"日期": "2026-03-18", "涨跌幅": "+10.00%"},
        {"日期": "2026-03-19", "涨跌幅": "+9.99%"},
    ]
    content = make_kline_content("000020", kline_rows)

    def mock_recent(dir_path, n, end_date):
        return [(date(2026, 3, 17), content),
                (date(2026, 3, 18), content),
                (date(2026, 3, 19), content)]

    with patch("storage.reader.read_recent_mds", side_effect=mock_recent):
        result = get_streak_from_kline("000020", date(2026, 3, 19))
    assert result == 3


# ── 7. 中间有一天未涨停，只计算连续部分 ──────────────────────────────────────

def test_get_streak_from_kline_interrupted():
    day1 = make_kline_content("000020", [{"涨跌幅": "+3.00%"}])   # 未涨停
    day2 = make_kline_content("000020", [{"涨跌幅": "+10.01%"}])  # 涨停
    day3 = make_kline_content("000020", [{"涨跌幅": "+9.99%"}])   # 涨停

    def mock_recent(dir_path, n, end_date):
        return [(date(2026, 3, 17), day1),
                (date(2026, 3, 18), day2),
                (date(2026, 3, 19), day3)]

    with patch("storage.reader.read_recent_mds", side_effect=mock_recent):
        result = get_streak_from_kline("000020", date(2026, 3, 19))
    assert result == 2


# ── 8. 第一天就未涨停，返回 0 ────────────────────────────────────────────────

def test_get_streak_from_kline_no_streak():
    day = make_kline_content("000020", [{"涨跌幅": "+3.00%"}])

    with patch("storage.reader.read_recent_mds", return_value=[(date(2026, 3, 19), day)]):
        result = get_streak_from_kline("000020", date(2026, 3, 19))
    assert result == 0


# ── 9. ST 股使用更低阈值 ─────────────────────────────────────────────────────

def test_get_streak_from_kline_st_threshold():
    # ST 股涨 4.8% 应判定为涨停（>= 4.5%），普通股则不是（< 9.5%）
    day = make_kline_content("000020", [{"涨跌幅": "+4.80%"}])

    with patch("storage.reader.read_recent_mds", return_value=[(date(2026, 3, 19), day)]):
        result_normal = get_streak_from_kline("000020", date(2026, 3, 19), is_st=False)
        result_st     = get_streak_from_kline("000020", date(2026, 3, 19), is_st=True)

    assert result_normal == 0
    assert result_st     == 1


# ── 10. K线文件不存在时返回 0 ────────────────────────────────────────────────

def test_get_streak_from_kline_no_file():
    with patch("storage.reader.read_recent_mds", return_value=[]):
        assert get_streak_from_kline("000020", date(2026, 3, 19)) == 0


# ── 11. 涨跌幅为 N/A 时中断计算 ─────────────────────────────────────────────

def test_get_streak_from_kline_na_interrupts():
    day1 = make_kline_content("000020", [{"涨跌幅": "N/A"}])
    day2 = make_kline_content("000020", [{"涨跌幅": "+10.01%"}])

    with patch("storage.reader.read_recent_mds",
               return_value=[(date(2026, 3, 18), day1), (date(2026, 3, 19), day2)]):
        result = get_streak_from_kline("000020", date(2026, 3, 19))
    assert result == 1  # day2 涨停，day1 N/A 中断


# ── 12. 涨停池有数据时优先使用 ──────────────────────────────────────────────

def test_get_streak_prefers_limit_up():
    content = make_limit_up_content([{"代码": "000020", "连板数": "5"}])
    with patch("storage.reader.read_md_by_date", return_value=content), \
         patch("calculator.streak.get_streak_from_kline") as mock_kline:
        result = get_streak("000020", date(2026, 3, 19))
    assert result == 5
    mock_kline.assert_not_called()


# ── 13. 涨停池文件不存在时回退到K线 ────────────────────────────────────────

def test_get_streak_falls_back_to_kline():
    day = make_kline_content("000020", [{"涨跌幅": "+10.01%"}])
    with patch("storage.reader.read_md_by_date", return_value=None), \
         patch("storage.reader.read_recent_mds",
               return_value=[(date(2026, 3, 19), day)]):
        result = get_streak("000020", date(2026, 3, 19))
    assert result == 1


# ── 14. 涨停池返回 0（未涨停）时不回退K线 ────────────────────────────────────

def test_get_streak_zero_not_fallback():
    content = make_limit_up_content([{"代码": "other_stock", "连板数": "3"}])
    with patch("storage.reader.read_md_by_date", return_value=content), \
         patch("calculator.streak.get_streak_from_kline") as mock_kline:
        result = get_streak("000020", date(2026, 3, 19))
    assert result == 0
    mock_kline.assert_not_called()


# ── 15. 批量读取所有涨停股连板数 ────────────────────────────────────────────

def test_get_all_streaks():
    content = make_limit_up_content([
        {"代码": "000020", "连板数": "5"},
        {"代码": "000677", "连板数": "1"},
        {"代码": "603687", "连板数": "3"},
    ])
    with patch("storage.reader.read_md_by_date", return_value=content):
        result = get_all_streaks(date(2026, 3, 19))
    assert result == {"000020": 5, "000677": 1, "603687": 3}


# ── 16. 涨停池为空时返回空字典 ──────────────────────────────────────────────

def test_get_all_streaks_empty():
    with patch("storage.reader.read_md_by_date", return_value=None):
        assert get_all_streaks(date(2026, 3, 19)) == {}


# ── 17. get_max_streak 返回最大连板数 ────────────────────────────────────────

def test_get_max_streak():
    content = make_limit_up_content([
        {"代码": "A", "连板数": "5"},
        {"代码": "B", "连板数": "3"},
        {"代码": "C", "连板数": "1"},
    ])
    with patch("storage.reader.read_md_by_date", return_value=content):
        assert get_max_streak(date(2026, 3, 19)) == 5


# ── 18. get_max_streak 空数据时返回 0 ────────────────────────────────────────

def test_get_max_streak_empty():
    with patch("storage.reader.read_md_by_date", return_value=None):
        assert get_max_streak(date(2026, 3, 19)) == 0
