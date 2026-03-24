"""
个股衍生指标计算层测试

覆盖场景：
  游资识别
  1.  龙虎榜有已知游资买入席位 → True
  2.  龙虎榜无已知游资 → False
  3.  龙虎榜无该股记录 → False
  4.  无龙虎榜数据时 → False，不崩溃

  衍生指标计算
  5.  calc_stock_derived 包含所有必要字段
  6.  连板数、5日涨幅、游资、地位、行业字段均正确

  存储
  7.  正常数据写入文件包含必要内容
  8.  5日涨幅为 None 时写入 N/A
"""

import os
import sys
from datetime import date
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from calculator.stock_derived import (
    calc_stock_derived,
    check_trader_in_lhb,
    save_stock_derived,
)


def make_lhb_content(rows: list[dict]) -> str:
    headers = ["股票代码", "股票名称", "买入席位", "卖出席位", "净买入(万)"]
    lines = ["# 龙虎榜\n",
             "| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        cells = [str(row.get(h, "N/A")) for h in headers]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


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


# ── 1. 有已知游资买入席位 → True ─────────────────────────────────────────────

def test_check_trader_found():
    content = make_lhb_content([
        {"股票代码": "000020", "买入席位": "章盟主、方新侠"}
    ])
    with patch("storage.reader.read_recent_mds",
               return_value=[(date(2026, 3, 19), content)]), \
         patch("config.traders.KNOWN_TRADERS", ["章盟主", "方新侠"]):
        assert check_trader_in_lhb("000020", date(2026, 3, 19)) is True


# ── 2. 无已知游资 → False ────────────────────────────────────────────────────

def test_check_trader_not_found():
    content = make_lhb_content([
        {"股票代码": "000020", "买入席位": "机构专用席位"}
    ])
    with patch("storage.reader.read_recent_mds",
               return_value=[(date(2026, 3, 19), content)]), \
         patch("config.traders.KNOWN_TRADERS", ["章盟主"]):
        assert check_trader_in_lhb("000020", date(2026, 3, 19)) is False


# ── 3. 龙虎榜无该股记录 → False ──────────────────────────────────────────────

def test_check_trader_stock_not_in_lhb():
    content = make_lhb_content([
        {"股票代码": "000001", "买入席位": "章盟主"}
    ])
    with patch("storage.reader.read_recent_mds",
               return_value=[(date(2026, 3, 19), content)]), \
         patch("config.traders.KNOWN_TRADERS", ["章盟主"]):
        assert check_trader_in_lhb("000020", date(2026, 3, 19)) is False


# ── 4. 无龙虎榜数据 → False，不崩溃 ─────────────────────────────────────────

def test_check_trader_no_lhb():
    with patch("storage.reader.read_recent_mds", return_value=[]):
        assert check_trader_in_lhb("000020", date(2026, 3, 19)) is False


# ── 5 & 6. calc_stock_derived 字段完整且正确 ─────────────────────────────────

def test_calc_stock_derived_has_all_fields():
    limit_up_content = make_limit_up_content([
        {"代码": "000020", "名称": "深华发A",
         "连板数": "5", "所属行业": "光学光电"},
    ])
    with patch("calculator.streak.get_streak", return_value=5), \
         patch("calculator.high_level.calc_5d_change", return_value=0.30), \
         patch("calculator.main_theme.get_main_themes", return_value=["光学光电"]), \
         patch("calculator.main_theme.get_leader",
               return_value={"code": "000020", "name": "深华发A"}), \
         patch("calculator.main_theme.get_sub_leader", return_value=None), \
         patch("calculator.main_theme.get_stock_position", return_value="龙头"), \
         patch("storage.reader.read_md_by_date", return_value=limit_up_content), \
         patch("storage.reader.read_recent_mds", return_value=[]):
        result = calc_stock_derived("000020", "深华发A", date(2026, 3, 19))

    assert result["streak"]      == 5
    assert result["change_5d"]   == pytest.approx(0.30)
    assert result["position"]    == "龙头"
    assert result["industry"]    == "光学光电"
    assert result["main_themes"] == ["光学光电"]


# ── 7. 写入文件包含必要内容 ───────────────────────────────────────────────────

def test_save_stock_derived_content(tmp_path):
    derived = {
        "code": "000020", "name": "深华发A",
        "date": date(2026, 3, 19),
        "streak": 5, "change_5d": 0.30,
        "has_trader": True, "position": "龙头",
        "industry": "光学光电", "main_themes": ["光学光电"],
    }
    with patch("config.settings.STOCKS_DIR", str(tmp_path)):
        save_stock_derived(derived)

    content = (tmp_path / "000020" / "derived" / "20260319.md").read_text(encoding="utf-8")
    assert "当前连板数" in content
    assert "5" in content
    assert "游资介入" in content
    assert "是" in content
    assert "龙头" in content
    assert "+30.00%" in content


# ── 8. 5日涨幅 None 时写入 N/A ───────────────────────────────────────────────

def test_save_stock_derived_none_change(tmp_path):
    derived = {
        "code": "000020", "name": "深华发A",
        "date": date(2026, 3, 19),
        "streak": 1, "change_5d": None,
        "has_trader": False, "position": "非主线",
        "industry": "N/A", "main_themes": [],
    }
    with patch("config.settings.STOCKS_DIR", str(tmp_path)):
        save_stock_derived(derived)

    content = (tmp_path / "000020" / "derived" / "20260319.md").read_text(encoding="utf-8")
    assert "N/A" in content
