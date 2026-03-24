"""
个股分析数据包汇总层测试

覆盖场景：
  1.  所有数据齐全时，输出包含四个章节
  2.  衍生指标缺失时显示缺失标记
  3.  日K线缺失时显示缺失标记
  4.  分钟线缺失时显示缺失标记
  5.  龙虎榜5日内有记录时正确筛选该股
  6.  龙虎榜5日内无该股记录时显示提示
  7.  日K线多个文件正确合并为一张表
  8.  分钟线多天数据按日期分别显示
  9.  run() 写入文件名格式为 {code}_YYYYMMDD.md
  10. 龙虎榜只过滤目标股票（不包含其他股票数据）
"""

import os
import sys
from datetime import date
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from assembler.stock_pack import assemble_stock_pack, run

# ── 测试数据 ──────────────────────────────────────────────────────────────────

DERIVED_CONTENT = (
    "# 000020 衍生指标 2026-03-19\n\n"
    "| 指标 | 值 | 说明 |\n| --- | --- | --- |\n"
    "| 当前连板数 | 5 | 从涨停池直接读取 |\n"
    "| 市场地位 | 龙头 | 龙头/次龙头/补涨/非主线 |\n"
)

KLINE_CONTENT = (
    "# 000020 日K线 2026-03-19\n\n"
    "| 日期 | 开盘 | 收盘 | 最高 | 最低 | 成交量(手) | 成交额(亿) | 涨跌幅 |\n"
    "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
    "| 2026-03-19 | 21.21 | 21.21 | 21.21 | 21.21 | 32521 | 0.6900（估） | N/A |\n"
)

MINUTE_CONTENT = (
    "# 000020 5分钟线 2026-03-19\n\n"
    "| 时间 | 开盘 | 最高 | 最低 | 收盘 | 成交量(手) |\n"
    "| --- | --- | --- | --- | --- | --- |\n"
    "| 09:35 | 21.21 | 21.30 | 21.10 | 21.25 | 1234 |\n"
)

LHB_CONTENT_WITH_STOCK = (
    "# 龙虎榜 2026-03-19\n\n"
    "| 代码 | 名称 | 解读 | 收盘价 | 涨跌幅 | 净买额(万) | 买入额(万) | 卖出额(万) |"
    " 龙虎榜成交(万) | 市场总成交(万) | 净买/总成交% | 龙虎榜/总成交% | 换手率% |"
    " 流通市值(亿) | 上榜原因 | 上榜后1日 | 上榜后2日 | 上榜后5日 | 上榜后10日 |\n"
    "| --- | --- | --- | --- | --- | --- | --- | --- |"
    " --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
    "| 000020 | 深华发A | 普通席位 | 21.21 | +10.01% | 3471.62 | 5181.65 | 1710.04 |"
    " 6891.69 | 12473.60 | 27.83 | 55.25 | 1.80 | 41.69 | 涨幅偏离 | N/A | N/A | N/A | N/A |\n"
    "| 000001 | 平安银行 | 机构买入 | 10.88 | -0.73% | -200.00 | 100.00 | 300.00 |"
    " 400.00 | 2000.00 | -10.00 | 20.00 | 0.32 | 211.13 | 跌幅异常 | N/A | N/A | N/A | N/A |\n"
)


# ── 1. 所有数据齐全时包含四个章节 ───────────────────────────────────────────

def test_all_data_present_has_four_sections():
    with patch("storage.reader.read_md_by_date", return_value=DERIVED_CONTENT), \
         patch("storage.reader.read_recent_mds",
               return_value=[(date(2026, 3, 19), KLINE_CONTENT)]):
        result = assemble_stock_pack("000020", date(2026, 3, 19))

    assert "## 一、最新衍生指标" in result
    assert "## 二、近1个月日K线" in result
    assert "## 三、近5日5分钟线" in result
    assert "## 四、近5日龙虎榜" in result


# ── 2. 衍生指标缺失时显示标记 ───────────────────────────────────────────────

def test_derived_missing_shows_marker():
    with patch("storage.reader.read_md_by_date", return_value=None), \
         patch("storage.reader.read_recent_mds", return_value=[]):
        result = assemble_stock_pack("000020", date(2026, 3, 19))

    assert "## 一、最新衍生指标" in result
    assert "数据缺失" in result


# ── 3. 日K线缺失时显示标记 ──────────────────────────────────────────────────

def test_kline_missing_shows_marker():
    with patch("storage.reader.read_md_by_date", return_value=None), \
         patch("storage.reader.read_recent_mds", return_value=[]):
        result = assemble_stock_pack("000020", date(2026, 3, 19))

    assert "## 二、近1个月日K线" in result
    assert "数据缺失" in result


# ── 4. 分钟线缺失时显示标记 ─────────────────────────────────────────────────

def test_minute_missing_shows_marker():
    with patch("storage.reader.read_md_by_date", return_value=None), \
         patch("storage.reader.read_recent_mds", return_value=[]):
        result = assemble_stock_pack("000020", date(2026, 3, 19))

    assert "## 三、近5日5分钟线" in result
    assert "数据缺失" in result


# ── 5. 龙虎榜有该股记录时正确显示 ──────────────────────────────────────────

def test_lhb_stock_found():
    def mock_recent(dir_path, n, end_date=None):
        if "lhb" in dir_path:
            return [(date(2026, 3, 19), LHB_CONTENT_WITH_STOCK)]
        return [(date(2026, 3, 19), KLINE_CONTENT)]

    with patch("storage.reader.read_md_by_date", return_value=DERIVED_CONTENT), \
         patch("storage.reader.read_recent_mds", side_effect=mock_recent):
        result = assemble_stock_pack("000020", date(2026, 3, 19))

    assert "深华发A" in result
    assert "近5日无龙虎榜记录" not in result


# ── 6. 龙虎榜无该股记录时显示提示 ──────────────────────────────────────────

def test_lhb_stock_not_found():
    lhb_other = (
        "# 龙虎榜\n\n| 代码 | 名称 |\n| --- | --- |\n"
        "| 000001 | 平安银行 |\n"
    )

    def mock_recent(dir_path, n, end_date=None):
        if "lhb" in dir_path:
            return [(date(2026, 3, 19), lhb_other)]
        return []

    with patch("storage.reader.read_md_by_date", return_value=None), \
         patch("storage.reader.read_recent_mds", side_effect=mock_recent):
        result = assemble_stock_pack("000020", date(2026, 3, 19))

    assert "近5日无龙虎榜记录" in result


# ── 7. 日K线多个文件合并为一张表 ────────────────────────────────────────────

def test_kline_multiple_files_merged():
    kline1 = (
        "# 000020 日K线\n\n"
        "| 日期 | 开盘 | 收盘 | 最高 | 最低 | 成交量(手) | 成交额(亿) | 涨跌幅 |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| 2026-03-18 | 19.28 | 19.28 | 19.50 | 19.10 | 28921 | 0.557（估） | N/A |\n"
    )
    kline2 = (
        "# 000020 日K线\n\n"
        "| 日期 | 开盘 | 收盘 | 最高 | 最低 | 成交量(手) | 成交额(亿) | 涨跌幅 |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| 2026-03-19 | 21.21 | 21.21 | 21.21 | 21.21 | 32521 | 0.690（估） | +10.01% |\n"
    )

    def mock_recent(dir_path, n, end_date=None):
        if "daily_kline" in dir_path:
            return [(date(2026, 3, 18), kline1), (date(2026, 3, 19), kline2)]
        return []

    with patch("storage.reader.read_md_by_date", return_value=None), \
         patch("storage.reader.read_recent_mds", side_effect=mock_recent):
        result = assemble_stock_pack("000020", date(2026, 3, 19))

    assert "2026-03-18" in result
    assert "2026-03-19" in result
    # 表头只出现一次（合并后）
    assert result.count("| 日期 |") == 1


# ── 8. 分钟线多天数据按日期显示 ─────────────────────────────────────────────

def test_minute_multiple_days_shown():
    minute1 = "# 000020 5分钟线 2026-03-18\n\n| 时间 | 收盘 |\n| --- | --- |\n| 09:35 | 19.28 |\n"
    minute2 = "# 000020 5分钟线 2026-03-19\n\n| 时间 | 收盘 |\n| --- | --- |\n| 09:35 | 21.21 |\n"

    def mock_recent(dir_path, n, end_date=None):
        if "minute_kline" in dir_path:
            return [(date(2026, 3, 18), minute1), (date(2026, 3, 19), minute2)]
        return []

    with patch("storage.reader.read_md_by_date", return_value=None), \
         patch("storage.reader.read_recent_mds", side_effect=mock_recent):
        result = assemble_stock_pack("000020", date(2026, 3, 19))

    assert "**2026-03-18**" in result
    assert "**2026-03-19**" in result


# ── 9. run() 文件名格式正确 ──────────────────────────────────────────────────

def test_run_filename_format(tmp_path):
    with patch("storage.reader.read_md_by_date", return_value=None), \
         patch("storage.reader.read_recent_mds", return_value=[]), \
         patch("config.settings.ASSEMBLED_DIR", str(tmp_path)):
        run("000020", date(2026, 3, 19))

    assert (tmp_path / "stocks" / "000020_20260319.md").exists()


# ── 10. 龙虎榜只过滤目标股票 ────────────────────────────────────────────────

def test_lhb_filters_only_target_stock():
    def mock_recent(dir_path, n, end_date=None):
        if "lhb" in dir_path:
            return [(date(2026, 3, 19), LHB_CONTENT_WITH_STOCK)]
        return []

    with patch("storage.reader.read_md_by_date", return_value=None), \
         patch("storage.reader.read_recent_mds", side_effect=mock_recent):
        result = assemble_stock_pack("000020", date(2026, 3, 19))

    # 深华发A（000020）应出现
    assert "深华发A" in result
    # 平安银行（000001）不应出现
    assert "平安银行" not in result
