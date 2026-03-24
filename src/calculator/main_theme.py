"""
计算层 — 主线识别 & 龙头判断
数据来源：
  主线识别 → collector/concepts.py（基于 limit_up 行业字段）
  龙头判断 → data/market/limit_up/（连板最高 + 成交额最大）
  扩散强度 → data/market/limit_up/（主线行业涨停股数量）
"""

import logging
import os
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


def get_main_themes(target_date: date = None, min_count: int = None) -> list[str]:
    """
    获取当日主线题材列表
    直接调用 concepts 模块，从 limit_up 行业字段统计

    :return: 主线行业列表，按涨停数降序
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from collector.concepts import get_main_themes as _get
    from config.settings import MAIN_THEME_MIN_COUNT

    if target_date is None:
        target_date = date.today()
    if min_count is None:
        min_count = MAIN_THEME_MIN_COUNT

    return _get(target_date, min_count=min_count)


def get_leader(main_themes: list[str], target_date: date = None) -> Optional[dict]:
    """
    识别龙头股：主线行业中连板数最高、成交额最大的股票

    :return: {"code": str, "name": str, "streak": int,
              "amount": float, "industry": str} 或 None
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import LIMIT_UP_DIR
    from storage.reader import parse_md_table, read_md_by_date

    if target_date is None:
        target_date = date.today()
    if not main_themes:
        return None

    content = read_md_by_date(LIMIT_UP_DIR, target_date)
    if not content:
        return None

    rows = parse_md_table(content)
    candidates = []
    for row in rows:
        industry = row.get("所属行业", "").strip()
        if industry not in main_themes:
            continue
        code = row.get("代码", "").strip()
        name = row.get("名称", "").strip()
        if not code or code == "N/A":
            continue
        try:
            streak = int(row.get("连板数", 0))
            amount = float(row.get("成交额(亿)", 0) or 0)
        except (ValueError, TypeError):
            streak, amount = 0, 0.0
        candidates.append({
            "code": code, "name": name,
            "streak": streak, "amount": amount,
            "industry": industry,
        })

    if not candidates:
        return None

    leader = max(candidates, key=lambda x: (x["streak"], x["amount"]))
    logger.info(f"[main_theme] {target_date} 龙头: {leader['name']}({leader['code']}) "
                f"{leader['streak']}板")
    return leader


def get_sub_leader(main_themes: list[str], leader_code: str,
                   target_date: date = None) -> Optional[dict]:
    """
    识别次龙头：主线行业中连板数第二高的股票（排除龙头）
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import LIMIT_UP_DIR
    from storage.reader import parse_md_table, read_md_by_date

    if target_date is None:
        target_date = date.today()
    if not main_themes:
        return None

    content = read_md_by_date(LIMIT_UP_DIR, target_date)
    if not content:
        return None

    rows = parse_md_table(content)
    candidates = []
    for row in rows:
        code     = row.get("代码", "").strip()
        industry = row.get("所属行业", "").strip()
        if code == leader_code or industry not in main_themes:
            continue
        try:
            streak = int(row.get("连板数", 0))
            amount = float(row.get("成交额(亿)", 0) or 0)
        except (ValueError, TypeError):
            streak, amount = 0, 0.0
        candidates.append({
            "code": code, "name": row.get("名称", "").strip(),
            "streak": streak, "amount": amount, "industry": industry,
        })

    if not candidates:
        return None

    return max(candidates, key=lambda x: (x["streak"], x["amount"]))


def get_spread_strength(main_themes: list[str], target_date: date = None) -> str:
    """
    计算主线资金扩散强度
    统计主线行业涨停股数量：>= 6 → 强，>= 3 → 中，其余 → 弱
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import LIMIT_UP_DIR, SPREAD_MID_COUNT, SPREAD_STRONG_COUNT
    from storage.reader import parse_md_table, read_md_by_date

    if target_date is None:
        target_date = date.today()
    if not main_themes:
        return "弱"

    content = read_md_by_date(LIMIT_UP_DIR, target_date)
    if not content:
        return "弱"

    rows  = parse_md_table(content)
    count = sum(
        1 for row in rows
        if row.get("所属行业", "").strip() in main_themes
    )

    if count >= SPREAD_STRONG_COUNT:
        return "强"
    if count >= SPREAD_MID_COUNT:
        return "中"
    return "弱"


def get_stock_position(
    stock_code: str,
    main_themes: list[str],
    leader_code: Optional[str],
    sub_leader_code: Optional[str],
    target_date: date = None,
) -> str:
    """
    判断个股在主线板块中的地位
    :return: "龙头" | "次龙头" | "补涨" | "非主线"

    注意：这里必须使用 target_date，避免补历史数据时混用“今天”的涨停池。
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import LIMIT_UP_DIR
    from storage.reader import parse_md_table, read_md_by_date

    if target_date is None:
        target_date = date.today()

    if not main_themes:
        return "非主线"
    if stock_code == leader_code:
        return "龙头"
    if stock_code == sub_leader_code:
        return "次龙头"

    # 检查是否属于主线行业
    content = read_md_by_date(LIMIT_UP_DIR, target_date)
    if not content:
        return "非主线"

    rows = parse_md_table(content)
    for row in rows:
        if row.get("代码", "").strip() == stock_code:
            if row.get("所属行业", "").strip() in main_themes:
                return "补涨"
            return "非主线"
    return "非主线"
