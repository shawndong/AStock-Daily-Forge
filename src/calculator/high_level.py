"""
计算层 — 高位股筛选
数据来源：
  连板数  → calculator/streak.py（优先从 limit_up 读）
  5日涨幅 → data/stocks/{code}/daily_kline/（从已存文件计算）

高位股定义（满足任一）：
  - 连板数 >= HIGH_LEVEL_MIN_STREAK（默认3）
  - 5日涨幅 >= HIGH_LEVEL_MIN_CHANGE_5D（默认25%）
"""

import logging
import os
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


def calc_5d_change(stock_code: str, as_of: date = None) -> Optional[float]:
    """
    从 daily_kline 文件计算5日涨幅
    取最近6个有效交易日文件，计算 (最新收盘 - 5日前收盘) / 5日前收盘

    :return: 5日涨幅（小数，如 0.25 表示 25%），数据不足时返回 None
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import STOCKS_DIR
    from storage.reader import parse_md_table, read_recent_mds

    if as_of is None:
        as_of = date.today()

    kline_dir = os.path.join(STOCKS_DIR, stock_code, "daily_kline")
    recent    = read_recent_mds(kline_dir, n=6, end_date=as_of)

    if len(recent) < 2:
        return None

    def get_close(content: str) -> Optional[float]:
        rows = parse_md_table(content)
        if not rows:
            return None
        close_str = rows[-1].get("收盘", "N/A").strip()
        try:
            return float(close_str)
        except ValueError:
            return None

    close_latest = get_close(recent[-1][1])
    close_base   = get_close(recent[0][1])

    if close_latest is None or close_base is None or close_base == 0:
        return None

    return round((close_latest - close_base) / close_base, 4)


def is_high_level(stock_code: str, streak: int, change_5d: Optional[float]) -> bool:
    """
    判断是否为高位股
    :param streak:    连板数
    :param change_5d: 5日涨幅（小数），None 时只用连板数判断
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import HIGH_LEVEL_MIN_CHANGE_5D, HIGH_LEVEL_MIN_STREAK

    if streak >= HIGH_LEVEL_MIN_STREAK:
        return True
    if change_5d is not None and change_5d >= HIGH_LEVEL_MIN_CHANGE_5D:
        return True
    return False


def filter_high_level(as_of: date = None) -> list[dict]:
    """
    筛选当日高位股列表

    策略：
      1. 从涨停池获取所有涨停股及其连板数
      2. 对每只涨停股，补充计算5日涨幅
      3. 满足高位股条件的加入结果

    :return: [{"code": str, "name": str, "streak": int,
               "change_5d": float|None, "industry": str}, ...]
             按连板数降序排列
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from calculator.streak import get_all_streaks
    from config.settings import LIMIT_UP_DIR
    from storage.reader import parse_md_table, read_md_by_date

    if as_of is None:
        as_of = date.today()

    # 从涨停池获取基础数据
    content = read_md_by_date(LIMIT_UP_DIR, as_of)
    if not content:
        logger.warning(f"[high_level] {as_of} 涨停池无数据")
        return []

    rows        = parse_md_table(content)
    all_streaks = get_all_streaks(as_of)
    result      = []

    for row in rows:
        code     = row.get("代码", "").strip()
        name     = row.get("名称", "").strip()
        industry = row.get("所属行业", "N/A").strip()

        if not code or code == "N/A":
            continue

        streak   = all_streaks.get(code, 0)
        change5d = calc_5d_change(code, as_of)

        if is_high_level(code, streak, change5d):
            result.append({
                "code":      code,
                "name":      name,
                "streak":    streak,
                "change_5d": change5d,
                "industry":  industry,
            })

    result.sort(key=lambda x: x["streak"], reverse=True)
    logger.info(f"[high_level] {as_of} 筛选出高位股 {len(result)} 只")
    return result


def get_high_level_state(stocks: list[dict]) -> dict:
    """
    统计高位股的状态分布，为市场状态评分提供输入

    从 daily_kline 文件读取当日涨跌幅来判断高位股状态。
    返回各分类数量，供 market_state.py 使用。

    :param stocks: filter_high_level() 的返回值
    :return: {
        "total": int,
        "limit_up_count": int,
        "limit_down_count": int,
        "big_drop_count": int,   # 跌幅 > 5%
    }
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from calculator.streak import LIMIT_UP_PCT_NORMAL, LIMIT_UP_PCT_ST
    from config.settings import BIG_DROP_THRESHOLD, STOCKS_DIR
    from storage.reader import parse_md_table, read_recent_mds

    total          = len(stocks)
    limit_up_count = 0
    limit_down_count = 0
    big_drop_count   = 0

    for stock in stocks:
        code   = stock["code"]
        is_st  = "ST" in stock.get("name", "").upper()
        kline_dir = os.path.join(STOCKS_DIR, code, "daily_kline")
        recent = read_recent_mds(kline_dir, n=1)
        if not recent:
            continue

        rows = parse_md_table(recent[0][1])
        if not rows:
            continue

        pct_str = rows[-1].get("涨跌幅", "N/A").replace("%", "").replace("+", "").strip()
        try:
            pct = float(pct_str)
        except ValueError:
            continue

        lu_threshold = (LIMIT_UP_PCT_NORMAL
                        if not is_st else LIMIT_UP_PCT_ST)
        ld_threshold = -lu_threshold

        if pct >= lu_threshold:
            limit_up_count += 1
        elif pct <= ld_threshold:
            limit_down_count += 1
        elif pct < -(BIG_DROP_THRESHOLD * 100):
            big_drop_count += 1

    return {
        "total":            total,
        "limit_up_count":   limit_up_count,
        "limit_down_count": limit_down_count,
        "big_drop_count":   big_drop_count,
    }
