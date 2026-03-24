"""
题材概念模块测试

覆盖场景：
  每日热门概念统计
  1.  正常涨停数据中正确统计各行业数量
  2.  同一行业多只涨停股时计数正确
  3.  行业为 N/A 的记录不参与统计
  4.  代码为空的记录不参与统计
  5.  无涨停数据时返回空列表
  6.  结果按涨停数量降序排列
  7.  每个行业的涨停股票代码列表完整

  存储
  8.  正常数据写入文件包含行业、数量、股票列表
  9.  主线行业（>=3只）在文件头部摘要中标注
  10. 涨停数量不足3只时不显示主线
  11. 无数据时写入缺失标记

  概念映射更新
  12. 从多日数据聚合出正确的股票→行业映射
  13. 同一股票取最新日期的行业记录（不覆盖更旧的）
  14. 代码为 N/A 的行不写入映射
  15. 无历史数据时跳过更新不崩溃

  查询接口
  16. get_stock_industry 在映射表中找到时返回正确行业
  17. get_stock_industry 找不到时返回 "N/A"
  18. get_main_themes 返回涨停数 >= min_count 的行业
  19. get_main_themes 按涨停数降序排列
"""

import os
import sys
from datetime import date, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from collector.concepts import (
    calc_daily_hot,
    get_main_themes,
    get_stock_industry,
    save_daily_hot,
    update_concept_map,
)

# ── 测试数据工厂 ──────────────────────────────────────────────────────────────

def make_limit_up_content(rows: list[dict]) -> str:
    """构造 limit_up md 文件内容"""
    headers = ["代码", "名称", "涨跌幅", "最新价", "成交额(亿)",
               "流通市值(亿)", "总市值(亿)", "换手率", "封板资金(亿)",
               "首次封板", "最后封板", "炸板次数", "涨停统计", "连板数", "所属行业"]
    lines = [
        "# 涨停股池 2026-03-19\n",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        cells = [row.get(h, "N/A") for h in headers]
        lines.append("| " + " | ".join(str(c) for c in cells) + " |")
    return "\n".join(lines)


def make_concept_map_content(rows: list[dict]) -> str:
    """构造 stock_concept_map.md 内容"""
    headers = ["股票代码", "股票名称", "所属行业", "最近涨停日"]
    lines = [
        "# 股票概念映射表\n",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        cells = [row.get(h, "N/A") for h in headers]
        lines.append("| " + " | ".join(str(c) for c in cells) + " |")
    return "\n".join(lines)


# ── 1. 正常数据统计各行业数量 ────────────────────────────────────────────────

def test_calc_daily_hot_counts():
    d = date(2026, 3, 19)
    content = make_limit_up_content([
        {"代码": "000020", "名称": "深华发A",  "所属行业": "光学光电"},
        {"代码": "000677", "名称": "恒天海龙", "所属行业": "化学纤维"},
        {"代码": "603687", "名称": "大胜达",   "所属行业": "包装印刷"},
        {"代码": "300001", "名称": "特锐德",   "所属行业": "光学光电"},
    ])
    with patch("storage.reader.read_md_by_date", return_value=content):
        result = calc_daily_hot(d)

    counts = {r["industry"]: r["count"] for r in result}
    assert counts["光学光电"] == 2
    assert counts["化学纤维"] == 1
    assert counts["包装印刷"] == 1


# ── 2. 同一行业多只涨停股计数正确 ───────────────────────────────────────────

def test_calc_daily_hot_same_industry():
    d = date(2026, 3, 19)
    content = make_limit_up_content([
        {"代码": f"{i:06d}", "名称": f"股票{i}", "所属行业": "AI算力"}
        for i in range(1, 6)
    ])
    with patch("storage.reader.read_md_by_date", return_value=content):
        result = calc_daily_hot(d)

    assert len(result) == 1
    assert result[0]["industry"] == "AI算力"
    assert result[0]["count"]    == 5


# ── 3. N/A 行业不参与统计 ────────────────────────────────────────────────────

def test_calc_excludes_na_industry():
    d = date(2026, 3, 19)
    content = make_limit_up_content([
        {"代码": "000001", "名称": "A股", "所属行业": "N/A"},
        {"代码": "000002", "名称": "B股", "所属行业": "光学光电"},
    ])
    with patch("storage.reader.read_md_by_date", return_value=content):
        result = calc_daily_hot(d)

    industries = [r["industry"] for r in result]
    assert "N/A" not in industries
    assert "光学光电" in industries


# ── 4. 代码为空的记录不参与统计 ─────────────────────────────────────────────

def test_calc_excludes_empty_code():
    d = date(2026, 3, 19)
    content = make_limit_up_content([
        {"代码": "",       "名称": "空代码", "所属行业": "光学光电"},
        {"代码": "000001", "名称": "正常股", "所属行业": "光学光电"},
    ])
    with patch("storage.reader.read_md_by_date", return_value=content):
        result = calc_daily_hot(d)

    assert result[0]["count"] == 1
    assert result[0]["stocks"] == ["000001"]


# ── 5. 无涨停数据时返回空列表 ────────────────────────────────────────────────

def test_calc_no_data_returns_empty():
    with patch("storage.reader.read_md_by_date", return_value=None):
        result = calc_daily_hot(date(2026, 3, 21))
    assert result == []


# ── 6. 结果按涨停数量降序排列 ────────────────────────────────────────────────

def test_calc_sorted_by_count_desc():
    d = date(2026, 3, 19)
    content = make_limit_up_content([
        {"代码": "000001", "所属行业": "单板行业"},
        {"代码": "000002", "所属行业": "热门行业"},
        {"代码": "000003", "所属行业": "热门行业"},
        {"代码": "000004", "所属行业": "热门行业"},
    ])
    with patch("storage.reader.read_md_by_date", return_value=content):
        result = calc_daily_hot(d)

    assert result[0]["industry"] == "热门行业"
    assert result[0]["count"]    == 3
    assert result[1]["industry"] == "单板行业"


# ── 7. 股票代码列表完整 ──────────────────────────────────────────────────────

def test_calc_stocks_list_complete():
    d = date(2026, 3, 19)
    content = make_limit_up_content([
        {"代码": "000020", "所属行业": "光学光电"},
        {"代码": "300001", "所属行业": "光学光电"},
    ])
    with patch("storage.reader.read_md_by_date", return_value=content):
        result = calc_daily_hot(d)

    stocks = set(result[0]["stocks"])
    assert stocks == {"000020", "300001"}


# ── 8. 写入文件包含行业、数量、股票 ─────────────────────────────────────────

def test_save_daily_hot_content(tmp_path):
    d = date(2026, 3, 19)
    records = [
        {"industry": "AI算力",  "count": 5, "stocks": ["A", "B", "C", "D", "E"]},
        {"industry": "光学光电", "count": 2, "stocks": ["F", "G"]},
    ]
    with patch("config.settings.CONCEPTS_DIR", str(tmp_path)):
        save_daily_hot(records, d)

    content = (tmp_path / "daily_hot" / "20260319.md").read_text(encoding="utf-8")
    assert "AI算力"  in content
    assert "5"       in content
    assert "光学光电" in content


# ── 9. 主线行业在摘要中标注 ──────────────────────────────────────────────────

def test_save_main_theme_in_summary(tmp_path):
    d = date(2026, 3, 19)
    records = [
        {"industry": "主线行业", "count": 5, "stocks": ["A", "B", "C", "D", "E"]},
        {"industry": "小众行业", "count": 1, "stocks": ["F"]},
    ]
    with patch("config.settings.CONCEPTS_DIR", str(tmp_path)):
        save_daily_hot(records, d)

    content = (tmp_path / "daily_hot" / "20260319.md").read_text(encoding="utf-8")
    assert "主线：主线行业" in content
    assert "小众行业" not in content.split("\n")[2]  # 小众行业不在摘要行


# ── 10. 不足3只时不显示主线 ─────────────────────────────────────────────────

def test_save_no_main_theme_when_count_low(tmp_path):
    d = date(2026, 3, 19)
    records = [
        {"industry": "小行业A", "count": 2, "stocks": ["A", "B"]},
        {"industry": "小行业B", "count": 1, "stocks": ["C"]},
    ]
    with patch("config.settings.CONCEPTS_DIR", str(tmp_path)):
        save_daily_hot(records, d)

    content = (tmp_path / "daily_hot" / "20260319.md").read_text(encoding="utf-8")
    assert "主线：" not in content


# ── 11. 无数据时写入缺失标记 ────────────────────────────────────────────────

def test_save_empty_writes_marker(tmp_path):
    d = date(2026, 3, 21)
    with patch("config.settings.CONCEPTS_DIR", str(tmp_path)):
        save_daily_hot([], d)

    content = (tmp_path / "daily_hot" / "20260321.md").read_text(encoding="utf-8")
    assert "无涨停数据" in content
    assert "|" not in content


# ── 12. 从多日数据聚合概念映射 ──────────────────────────────────────────────

def test_update_concept_map_aggregates(tmp_path):
    today   = date(2026, 3, 19)
    content = make_limit_up_content([
        {"代码": "000020", "名称": "深华发A",  "所属行业": "光学光电"},
        {"代码": "603687", "名称": "大胜达",   "所属行业": "包装印刷"},
    ])

    def mock_read(dir_path, d):
        if d == today:
            return content
        return None

    with patch("storage.reader.read_md_by_date", side_effect=mock_read), \
         patch("config.settings.LIMIT_UP_DIR", str(tmp_path / "limit_up")), \
         patch("config.settings.CONCEPTS_DIR", str(tmp_path)), \
         patch("collector.concepts.date") as mock_date:
        mock_date.today.return_value = today
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        update_concept_map(lookback_days=5)

    map_file = tmp_path / "stock_concept_map.md"
    assert map_file.exists()
    content_out = map_file.read_text(encoding="utf-8")
    assert "000020" in content_out
    assert "光学光电" in content_out
    assert "603687" in content_out


# ── 13. 同一股票取最新日期记录 ──────────────────────────────────────────────

def test_update_concept_map_uses_latest(tmp_path):
    today   = date(2026, 3, 19)
    yesterday = today - timedelta(days=1)

    content_today = make_limit_up_content([
        {"代码": "000020", "名称": "深华发A", "所属行业": "新行业"},
    ])
    content_yesterday = make_limit_up_content([
        {"代码": "000020", "名称": "深华发A", "所属行业": "旧行业"},
    ])

    def mock_read(dir_path, d):
        if d == today:
            return content_today
        if d == yesterday:
            return content_yesterday
        return None

    with patch("storage.reader.read_md_by_date", side_effect=mock_read), \
         patch("config.settings.LIMIT_UP_DIR", str(tmp_path / "lu")), \
         patch("config.settings.CONCEPTS_DIR", str(tmp_path)), \
         patch("collector.concepts.date") as mock_date:
        mock_date.today.return_value = today
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        update_concept_map(lookback_days=5)

    content_out = (tmp_path / "stock_concept_map.md").read_text(encoding="utf-8")
    assert "新行业" in content_out
    assert "旧行业" not in content_out


# ── 14. 代码 N/A 的行不写入映射 ─────────────────────────────────────────────

def test_update_concept_map_excludes_na_code(tmp_path):
    today   = date(2026, 3, 19)
    content = make_limit_up_content([
        {"代码": "N/A",    "名称": "无效股", "所属行业": "行业A"},
        {"代码": "000020", "名称": "深华发A", "所属行业": "行业B"},
    ])

    with patch("storage.reader.read_md_by_date",
               side_effect=lambda d_path, d: content if d == today else None), \
         patch("config.settings.LIMIT_UP_DIR", str(tmp_path / "lu")), \
         patch("config.settings.CONCEPTS_DIR", str(tmp_path)), \
         patch("collector.concepts.date") as mock_date:
        mock_date.today.return_value = today
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        update_concept_map(lookback_days=3)

    content_out = (tmp_path / "stock_concept_map.md").read_text(encoding="utf-8")
    assert "000020" in content_out
    assert "无效股" not in content_out


# ── 15. 无历史数据时不崩溃 ──────────────────────────────────────────────────

def test_update_concept_map_no_data_no_crash(tmp_path):
    with patch("storage.reader.read_md_by_date", return_value=None), \
         patch("config.settings.LIMIT_UP_DIR", str(tmp_path / "lu")), \
         patch("config.settings.CONCEPTS_DIR", str(tmp_path)):
        update_concept_map(lookback_days=5)  # 不应抛出异常


# ── 16. get_stock_industry 找到时返回行业 ────────────────────────────────────

def test_get_stock_industry_found(tmp_path):
    map_content = make_concept_map_content([
        {"股票代码": "000020", "股票名称": "深华发A",
         "所属行业": "光学光电", "最近涨停日": "2026-03-19"},
    ])
    with patch("storage.reader.read_md", return_value=map_content), \
         patch("config.settings.CONCEPTS_DIR", str(tmp_path)):
        result = get_stock_industry("000020")
    assert result == "光学光电"


# ── 17. get_stock_industry 找不到时返回 N/A ──────────────────────────────────

def test_get_stock_industry_not_found(tmp_path):
    map_content = make_concept_map_content([
        {"股票代码": "000020", "股票名称": "深华发A",
         "所属行业": "光学光电", "最近涨停日": "2026-03-19"},
    ])
    with patch("storage.reader.read_md", return_value=map_content), \
         patch("config.settings.CONCEPTS_DIR", str(tmp_path)):
        result = get_stock_industry("999999")
    assert result == "N/A"


# ── 18. get_main_themes 返回达标行业 ─────────────────────────────────────────

def test_get_main_themes_threshold():
    d = date(2026, 3, 19)
    content = make_limit_up_content([
        {"代码": f"{i:06d}", "所属行业": "主线行业"} for i in range(1, 4)
    ] + [
        {"代码": "999999", "所属行业": "小众行业"},
    ])
    with patch("storage.reader.read_md_by_date", return_value=content):
        result = get_main_themes(d, min_count=3)

    assert "主线行业" in result
    assert "小众行业" not in result


# ── 19. get_main_themes 按涨停数降序 ─────────────────────────────────────────

def test_get_main_themes_sorted():
    d = date(2026, 3, 19)
    content = make_limit_up_content(
        [{"代码": f"{i:06d}", "所属行业": "大行业"} for i in range(1, 6)] +
        [{"代码": f"{i:06d}", "所属行业": "中行业"} for i in range(10, 13)]
    )
    with patch("storage.reader.read_md_by_date", return_value=content):
        result = get_main_themes(d, min_count=3)

    assert result[0] == "大行业"
    assert result[1] == "中行业"
