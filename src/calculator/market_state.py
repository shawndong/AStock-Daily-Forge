"""
计算层 — 市场状态评分
依赖：
  high_level.py  → 高位股列表及状态分布
  main_theme.py  → 主线识别、龙头、扩散强度
  streak.py      → 最高连板数
写入：data/market/market_state/YYYYMMDD.md
"""

import logging
import os
from datetime import date

logger = logging.getLogger(__name__)


def classify_market_state(high_level_state: dict) -> str:
    """
    根据高位股状态分类市场状态
    规则（按优先级）：
      跌停比例 >= 30%         → 崩溃
      大跌(>5%)比例 >= 50%    → 大回撤
      存在涨停 且 存在大跌     → 分歧
      其余                    → 强势
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import STATE_CRASH_LIMIT_DOWN_RATIO, STATE_RETREAT_BIG_DROP_RATIO

    total = high_level_state.get("total", 0)
    if total == 0:
        return "无高位股"

    limit_down = high_level_state.get("limit_down_count", 0)
    big_drop   = high_level_state.get("big_drop_count", 0)
    limit_up   = high_level_state.get("limit_up_count", 0)

    if limit_down / total >= STATE_CRASH_LIMIT_DOWN_RATIO:
        return "崩溃"
    if big_drop / total >= STATE_RETREAT_BIG_DROP_RATIO:
        return "大回撤"
    if limit_up > 0 and big_drop > 0:
        return "分歧"
    return "强势"


def run(d: date = None):
    """
    计算并写入当日市场状态
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from calculator.high_level import filter_high_level, get_high_level_state
    from calculator.main_theme import (
        get_leader,
        get_main_themes,
        get_spread_strength,
        get_sub_leader,
    )
    from calculator.streak import get_max_streak
    from config.settings import MARKET_STATE_DIR
    from storage.writer import date_to_filename, rows_to_md_table, write_md

    if d is None:
        d = date.today()

    high_level    = filter_high_level(d)
    hl_state      = get_high_level_state(high_level)
    state         = classify_market_state(hl_state)
    max_streak    = get_max_streak(d)
    main_themes   = get_main_themes(d)
    leader        = get_leader(main_themes, d)
    sub_leader    = get_sub_leader(main_themes,
                                   leader["code"] if leader else "", d)
    spread        = get_spread_strength(main_themes, d)

    rows = [
        ["最大连板高度",      max_streak],
        ["高位股总数",        hl_state["total"]],
        ["高位股涨停数",      hl_state["limit_up_count"]],
        ["高位股跌停数",      hl_state["limit_down_count"]],
        ["高位股大跌(>5%)数", hl_state["big_drop_count"]],
        ["市场状态",          state],
        ["主线概念",          "、".join(main_themes) if main_themes else "N/A"],
        ["龙头股票",          f"{leader['name']}({leader['code']})" if leader else "N/A"],
        ["次龙头",            f"{sub_leader['name']}({sub_leader['code']})" if sub_leader else "N/A"],
        ["资金扩散强度",      spread],
    ]

    content = (
        f"# 市场状态 {d.strftime('%Y-%m-%d')}\n\n"
        + rows_to_md_table(["指标", "值"], rows)
    )
    write_md(MARKET_STATE_DIR, date_to_filename(d), content)
    logger.info(f"[market_state] {d} 状态: {state} 主线: {main_themes} 扩散: {spread}")
    return state
