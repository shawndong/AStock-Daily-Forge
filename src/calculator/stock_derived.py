"""
计算层 — 个股衍生指标
数据来源：
  连板数    → calculator/streak.py
  5日涨幅   → calculator/high_level.py
  游资介入  → data/lhb/（比对 config/traders.py 名单）
  市场地位  → calculator/main_theme.py
写入：data/stocks/{code}/derived/YYYYMMDD.md
"""

import logging
import os
from datetime import date

logger = logging.getLogger(__name__)


def _pick_code_field(row: dict) -> str:
    """兼容不同版本龙虎榜表头：代码 / 股票代码。"""
    return (row.get("代码") or row.get("股票代码") or "").strip()


def check_trader_in_lhb(stock_code: str, target_date: date = None,
                         lookback_days: int = 1) -> bool:
    """
    检查近 lookback_days 日龙虎榜中该股是否有已知游资买入席位

    :param lookback_days: 向前查找天数，默认只查当日
    :return: True 表示有游资介入
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import LHB_DIR
    from config.traders import KNOWN_TRADERS
    from storage.reader import parse_md_table, read_recent_mds

    if target_date is None:
        target_date = date.today()

    recent = read_recent_mds(LHB_DIR, n=lookback_days, end_date=target_date)
    for _, content in recent:
        rows = parse_md_table(content)
        for row in rows:
            if _pick_code_field(row) != stock_code:
                continue
            buy_seats = row.get("买入席位", "")
            for trader in KNOWN_TRADERS:
                if trader in buy_seats:
                    return True
    return False


def calc_stock_derived(
    stock_code: str,
    stock_name: str = "",
    target_date: date = None,
) -> dict:
    """
    计算单只股票的衍生指标

    :return: {
        "code": str, "name": str, "date": date,
        "streak": int, "change_5d": float|None,
        "has_trader": bool, "position": str,
        "industry": str, "main_themes": list[str]
    }
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from calculator.high_level import calc_5d_change
    from calculator.main_theme import (
        get_leader,
        get_main_themes,
        get_stock_position,
        get_sub_leader,
    )
    from calculator.streak import get_streak
    from config.settings import LIMIT_UP_DIR
    from storage.reader import parse_md_table, read_md_by_date

    if target_date is None:
        target_date = date.today()

    is_st      = "ST" in stock_name.upper()
    streak     = get_streak(stock_code, target_date, is_st=is_st)
    change_5d  = calc_5d_change(stock_code, target_date)
    has_trader = check_trader_in_lhb(stock_code, target_date)

    # 主线和地位
    main_themes = get_main_themes(target_date)
    leader      = get_leader(main_themes, target_date)
    sub_leader  = get_sub_leader(
        main_themes, leader["code"] if leader else "", target_date
    )
    position = get_stock_position(
        stock_code,
        main_themes,
        leader["code"] if leader else None,
        sub_leader["code"] if sub_leader else None,
        target_date=target_date,
    )

    # 行业
    industry = "N/A"
    content = read_md_by_date(LIMIT_UP_DIR, target_date)
    if content:
        rows = parse_md_table(content)
        for row in rows:
            if row.get("代码", "").strip() == stock_code:
                industry = row.get("所属行业", "N/A").strip()
                break

    return {
        "code":        stock_code,
        "name":        stock_name,
        "date":        target_date,
        "streak":      streak,
        "change_5d":   change_5d,
        "has_trader":  has_trader,
        "position":    position,
        "industry":    industry,
        "main_themes": main_themes,
    }


def save_stock_derived(derived: dict):
    """写入个股衍生指标文件"""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import STOCKS_DIR
    from storage.writer import date_to_filename, rows_to_md_table, write_md

    d    = derived["date"]
    code = derived["code"]

    def fmt_pct(val):
        if val is None:
            return "N/A"
        return f"{val * 100:+.2f}%"

    rows = [
        ["当前连板数",  str(derived["streak"]),    "从涨停池直接读取"],
        ["5日涨幅",    fmt_pct(derived["change_5d"]), "从日K线计算"],
        ["游资介入",   "是" if derived["has_trader"] else "否", "比对龙虎榜席位"],
        ["市场地位",   derived["position"],         "龙头/次龙头/补涨/非主线"],
        ["所属行业",   derived["industry"],          "来自涨停池行业字段"],
        ["主线题材",   "、".join(derived["main_themes"]) or "N/A", "当日主线行业"],
    ]

    derived_dir = os.path.join(STOCKS_DIR, code, "derived")
    content = (
        f"# {code} 衍生指标 {d.strftime('%Y-%m-%d')}\n\n"
        + rows_to_md_table(["指标", "值", "说明"], rows)
    )
    write_md(derived_dir, date_to_filename(d), content)
    logger.info(f"[stock_derived] {code} {d} 已写入")


def run(d: date = None):
    """每日入口：对当日涨停股批量计算衍生指标"""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import LIMIT_UP_DIR
    from storage.reader import parse_md_table, read_md_by_date

    if d is None:
        d = date.today()

    content = read_md_by_date(LIMIT_UP_DIR, d)
    if not content:
        logger.warning(f"[stock_derived] {d} 无涨停数据，跳过")
        return

    rows    = parse_md_table(content)
    success = 0
    for row in rows:
        code = row.get("代码", "").strip()
        name = row.get("名称", "").strip()
        if not code or code == "N/A":
            continue
        try:
            derived = calc_stock_derived(code, name, d)
            save_stock_derived(derived)
            success += 1
        except Exception as e:
            logger.error(f"[stock_derived] {code} 失败: {e}")

    logger.info(f"[stock_derived] {d} 完成，共 {success} 只")
