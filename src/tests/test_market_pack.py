"""
市场分析数据包汇总层测试

覆盖场景：
  1.  所有数据齐全时，输出包含新版章节结构
  2.  market_state 数据缺失时显示缺失标记，不崩溃
  3.  limit_up 数据缺失时显示缺失标记
  4.  northbound 数据缺失时显示缺失标记
  5.  所有数据均缺失时仍生成完整结构
  6.  近5日趋势：有历史数据时正确拼接
  7.  近5日趋势：无历史数据时显示提示
  8.  run() 写入文件到正确路径
  9.  输出文件名格式为 YYYYMMDD.md
"""

import os
import sys
from datetime import date
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from assembler.market_pack import assemble_market_pack, run

MARKET_STATE_CONTENT = (
    "# 市场状态 2026-03-19\n\n"
    "| 指标 | 值 |\n| --- | --- |\n"
    "| 市场状态 | 强势 |\n| 最大连板高度 | 5 |\n"
)
LIMIT_UP_CONTENT = (
    "# 涨停股池 2026-03-19\n\n"
    "> 共 28 只\n\n"
    "| 代码 | 名称 | 连板数 |\n| --- | --- | --- |\n"
    "| 000020 | 深华发A | 5 |\n"
)
QUOTE_CONTENT = (
    "# 市场行情汇总 2026-03-19\n\n"
    "| 指标 | 数值 |\n| --- | --- |\n"
    "| 涨停数量 | 28 |\n"
)
NORTHBOUND_CONTENT = (
    "# 北向资金 2026-03-19\n\n"
    "| 指标 | 数值 |\n| --- | --- |\n"
    "| 北向资金合计(亿) | +32.40 |\n"
)


def mock_read_by_date(content_map: dict):
    """根据文件目录返回对应内容"""
    def _read(dir_path, d):
        for key, content in content_map.items():
            if key in dir_path:
                return content
        return None
    return _read


# ── 1. 所有数据齐全时包含新版章节 ───────────────────────────────────────────

def test_all_data_present_has_new_sections():
    content_map = {
        "market_state":  MARKET_STATE_CONTENT,
        "limit_up":      LIMIT_UP_CONTENT,
        "daily_quote":   QUOTE_CONTENT,
        "northbound":    NORTHBOUND_CONTENT,
    }
    with patch("storage.reader.read_md_by_date",
               side_effect=mock_read_by_date(content_map)), \
         patch("storage.reader.read_recent_mds", return_value=[]):
        result = assemble_market_pack(date(2026, 3, 19))

    assert "## 一、市场状态" in result
    assert "## 二、当日涨停股" in result
    assert "## 三、市场行情汇总（核心）" in result
    assert "## 四、北向资金" in result
    assert "## 五、当日热点概念" in result
    assert "## 六、当日龙虎榜" in result
    assert "## 七、近5日市场状态趋势" in result
    assert "## 八、个股明细" in result


# ── 2. market_state 缺失时显示标记 ──────────────────────────────────────────

def test_market_state_missing_shows_marker():
    content_map = {"limit_up": LIMIT_UP_CONTENT}
    with patch("storage.reader.read_md_by_date",
               side_effect=mock_read_by_date(content_map)), \
         patch("storage.reader.read_recent_mds", return_value=[]):
        result = assemble_market_pack(date(2026, 3, 19))

    assert "## 一、市场状态" in result
    assert "数据缺失" in result


# ── 3. limit_up 缺失时显示标记 ──────────────────────────────────────────────

def test_limit_up_missing_shows_marker():
    content_map = {"market_state": MARKET_STATE_CONTENT}
    with patch("storage.reader.read_md_by_date",
               side_effect=mock_read_by_date(content_map)), \
         patch("storage.reader.read_recent_mds", return_value=[]):
        result = assemble_market_pack(date(2026, 3, 19))

    assert "## 二、当日涨停股" in result
    assert "数据缺失" in result


# ── 4. northbound 缺失时显示标记 ────────────────────────────────────────────

def test_northbound_missing_shows_marker():
    content_map = {"market_state": MARKET_STATE_CONTENT}
    with patch("storage.reader.read_md_by_date",
               side_effect=mock_read_by_date(content_map)), \
         patch("storage.reader.read_recent_mds", return_value=[]):
        result = assemble_market_pack(date(2026, 3, 19))

    assert "## 四、北向资金" in result
    assert "数据缺失" in result


# ── 5. 所有数据缺失时仍生成完整结构 ─────────────────────────────────────────

def test_all_missing_still_generates_structure():
    with patch("storage.reader.read_md_by_date", return_value=None), \
         patch("storage.reader.read_recent_mds", return_value=[]):
        result = assemble_market_pack(date(2026, 3, 19))

    for section in ["一", "二", "三", "四", "五", "六", "七", "八"]:
        assert f"## {section}、" in result


# ── 6. 近5日趋势有数据时正确拼接 ────────────────────────────────────────────

def test_recent_trend_with_data():
    recent = [
        (date(2026, 3, 17), "# 市场状态 2026-03-17\n| 市场状态 | 分歧 |"),
        (date(2026, 3, 18), "# 市场状态 2026-03-18\n| 市场状态 | 强势 |"),
        (date(2026, 3, 19), MARKET_STATE_CONTENT),
    ]
    with patch("storage.reader.read_md_by_date", return_value=None), \
         patch("storage.reader.read_recent_mds", return_value=recent):
        result = assemble_market_pack(date(2026, 3, 19))

    assert "2026-03-17" in result
    assert "2026-03-18" in result
    assert "2026-03-19" in result


# ── 7. 近5日趋势无数据时显示提示 ────────────────────────────────────────────

def test_recent_trend_no_data():
    with patch("storage.reader.read_md_by_date", return_value=None), \
         patch("storage.reader.read_recent_mds", return_value=[]):
        result = assemble_market_pack(date(2026, 3, 19))

    assert "暂无历史数据" in result


# ── 8. run() 写入文件到正确路径 ──────────────────────────────────────────────

def test_run_writes_to_correct_path(tmp_path):
    with patch("storage.reader.read_md_by_date", return_value=None), \
         patch("storage.reader.read_recent_mds", return_value=[]), \
         patch("config.settings.ASSEMBLED_DIR", str(tmp_path)):
        run(date(2026, 3, 19))

    assert (tmp_path / "market" / "20260319.md").exists()


# ── 9. 输出文件内容包含日期标题 ─────────────────────────────────────────────

def test_run_file_contains_date(tmp_path):
    with patch("storage.reader.read_md_by_date", return_value=None), \
         patch("storage.reader.read_recent_mds", return_value=[]), \
         patch("config.settings.ASSEMBLED_DIR", str(tmp_path)):
        run(date(2026, 3, 19))

    content = (tmp_path / "market" / "20260319.md").read_text(encoding="utf-8")
    assert "2026-03-19" in content
