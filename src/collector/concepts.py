"""
采集层 — 题材概念统计
数据来源：从已采集的 limit_up 数据派生，无需外部网络请求

功能：
  1. 每日热门概念统计：统计当日涨停股中各行业出现次数
     写入：data/concepts/daily_hot/YYYYMMDD.md

  2. 概念映射更新：从近期 limit_up 数据聚合股票→行业映射
     写入：data/concepts/stock_concept_map.md

设计原则：
  - 纯计算模块，不发起任何网络请求
  - 依赖 limit_up/ 目录下的已有数据
  - 可以单独运行，也会在 market_state 计算后自动调用
"""

import logging
import os
from datetime import date, timedelta

logger = logging.getLogger(__name__)


# ── 每日热门概念统计 ──────────────────────────────────────────────────────────

def calc_daily_hot(target_date: date = None) -> list[dict]:
    """
    统计当日涨停股中各行业/概念出现次数

    :param target_date: 目标日期，默认今天
    :return: [{"industry": str, "count": int, "stocks": [code, ...]}, ...]
             按出现次数降序排列
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import LIMIT_UP_DIR
    from storage.reader import parse_md_table, read_md_by_date

    if target_date is None:
        target_date = date.today()

    content = read_md_by_date(LIMIT_UP_DIR, target_date)
    if not content:
        logger.warning(f"[concepts] {target_date} 无涨停数据，跳过概念统计")
        return []

    rows = parse_md_table(content)
    if not rows:
        logger.warning(f"[concepts] {target_date} 涨停数据解析为空")
        return []

    # 按行业统计
    industry_stocks: dict[str, list[str]] = {}
    for row in rows:
        industry = row.get("所属行业", "").strip()
        code     = row.get("代码", "").strip()
        if not industry or industry == "N/A" or not code:
            continue
        industry_stocks.setdefault(industry, []).append(code)

    result = [
        {"industry": ind, "count": len(codes), "stocks": codes}
        for ind, codes in industry_stocks.items()
    ]
    result.sort(key=lambda x: x["count"], reverse=True)

    logger.info(f"[concepts] {target_date} 统计完成，共 {len(result)} 个行业")
    return result


def save_daily_hot(records: list[dict], d: date = None):
    """写入每日热门概念统计"""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import CONCEPTS_DIR
    from storage.writer import date_to_filename, rows_to_md_table, write_md

    if d is None:
        d = date.today()

    hot_dir = os.path.join(CONCEPTS_DIR, "daily_hot")

    if not records:
        content = (
            f"# 热门概念 {d.strftime('%Y-%m-%d')}\n\n"
            f"> ⚠️ 当日无涨停数据\n"
        )
        write_md(hot_dir, date_to_filename(d), content)
        return

    rows = [
        [r["industry"], str(r["count"]), "、".join(r["stocks"])]
        for r in records
    ]

    # 主线判断：涨停股 >= 3 只的行业视为主线
    main_themes = [r["industry"] for r in records if r["count"] >= 3]

    content = (
        f"# 热门概念 {d.strftime('%Y-%m-%d')}\n\n"
        f"> 共 {len(records)} 个行业有涨停股"
        + (f"  |  主线：{' / '.join(main_themes)}" if main_themes else "")
        + "\n\n"
        + rows_to_md_table(["行业", "涨停数", "涨停股票"], rows)
    )
    write_md(hot_dir, date_to_filename(d), content)
    logger.info(f"[concepts] {d} 热门概念已写入，主线: {main_themes}")


# ── 概念映射更新 ──────────────────────────────────────────────────────────────

def update_concept_map(lookback_days: int = 30):
    """
    从近期 limit_up 数据聚合股票→行业映射
    每只股票取最近一次出现时的行业标签

    :param lookback_days: 向前查找的天数，默认30天
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import CONCEPTS_DIR, LIMIT_UP_DIR
    from storage.reader import parse_md_table, read_md_by_date
    from storage.writer import rows_to_md_table, write_md

    today    = date.today()
    stock_map: dict[str, dict] = {}   # code → {name, industry, last_seen}

    for i in range(lookback_days):
        d       = today - timedelta(days=i)
        content = read_md_by_date(LIMIT_UP_DIR, d)
        if not content:
            continue

        rows = parse_md_table(content)
        for row in rows:
            code     = row.get("代码", "").strip()
            name     = row.get("名称", "").strip()
            industry = row.get("所属行业", "").strip()

            if not code or code == "N/A":
                continue

            # 取最新出现的记录（i=0 是今天，最先遍历到的即最新）
            if code not in stock_map:
                stock_map[code] = {
                    "name":      name,
                    "industry":  industry if industry != "N/A" else "",
                    "last_seen": str(d),
                }

    if not stock_map:
        logger.warning("[concepts] 近期无涨停数据，概念映射未更新")
        return

    rows_data = [
        [code, info["name"], info["industry"], info["last_seen"]]
        for code, info in sorted(stock_map.items())
    ]

    content = (
        "# 股票概念映射表\n\n"
        f"> 从近 {lookback_days} 日涨停数据聚合，最后更新：{today}\n\n"
        + rows_to_md_table(
            ["股票代码", "股票名称", "所属行业", "最近涨停日"],
            rows_data
        )
    )
    write_md(CONCEPTS_DIR, "stock_concept_map.md", content)
    logger.info(f"[concepts] 概念映射已更新，共 {len(stock_map)} 只股票")


# ── 查询接口（供其他模块使用）────────────────────────────────────────────────

def get_stock_industry(stock_code: str) -> str:
    """
    查询单只股票的行业归属
    从 stock_concept_map.md 中查找，找不到返回 "N/A"
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import CONCEPTS_DIR
    from storage.reader import parse_md_table, read_md

    content = read_md(CONCEPTS_DIR, "stock_concept_map.md")
    if not content:
        return "N/A"

    rows = parse_md_table(content)
    for row in rows:
        if row.get("股票代码", "").strip() == stock_code:
            return row.get("所属行业", "N/A").strip()
    return "N/A"


def get_main_themes(target_date: date = None, min_count: int = 3) -> list[str]:
    """
    获取当日主线题材列表
    :param min_count: 涨停股数量门槛，默认3只
    :return: 主线行业名称列表，按涨停数降序
    """
    records = calc_daily_hot(target_date)
    return [r["industry"] for r in records if r["count"] >= min_count]


# ── 入口 ──────────────────────────────────────────────────────────────────────

def run(d: date = None, update_map: bool = False):
    """
    每日执行入口：
      1. 计算当日热门概念统计
      2. 可选：更新概念映射表（建议每周一执行）

    :param update_map: 是否同时更新 stock_concept_map.md
    """
    if d is None:
        d = date.today()

    records = calc_daily_hot(d)
    save_daily_hot(records, d)

    if update_map:
        update_concept_map()
