"""
计算层 — 连板数查询
主要数据来源：data/market/limit_up/（直接读取，无需计算）
备用来源：data/stocks/{code}/daily_kline/（接口限制时从K线推算）

设计说明：
  limit_up 接口（stock_zt_pool_em）直接提供连板数字段，这是最可靠的来源。
  当股票不在当日涨停池中时，连板数为 0（当日未涨停）。
  备用方法：从 daily_kline 文件向前遍历连续涨停天数，
  判断标准：close >= prev_close × 1.09（普通股涨停约为 +9.9%）
"""

import logging
import os
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

# 涨停判断阈值（与 kline 数据配合使用，新浪接口无涨停价字段）
LIMIT_UP_PCT_NORMAL = 9.5   # 普通股涨幅 >= 9.5% 视为涨停
LIMIT_UP_PCT_ST     = 4.5   # ST股涨幅 >= 4.5% 视为涨停
MAX_LOOKBACK_DAYS   = 60    # 向前最多查找60个日历天


def get_streak_from_limit_up(stock_code: str, target_date: date = None) -> Optional[int]:
    """
    从涨停股池文件直接读取连板数（首选方案）

    :param stock_code:  股票代码
    :param target_date: 目标日期，默认今天
    :return: 连板数（整数），股票不在涨停池中返回 0，文件不存在返回 None
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import LIMIT_UP_DIR
    from storage.reader import parse_md_table, read_md_by_date

    if target_date is None:
        target_date = date.today()

    content = read_md_by_date(LIMIT_UP_DIR, target_date)
    if not content:
        logger.debug(f"[streak] {target_date} 涨停池文件不存在")
        return None

    rows = parse_md_table(content)
    for row in rows:
        if row.get("代码", "").strip() == stock_code:
            try:
                return int(row.get("连板数", 0))
            except (ValueError, TypeError):
                return 0

    # 不在涨停池中，连板数为 0
    return 0


def get_streak_from_kline(stock_code: str, target_date: date = None,
                          is_st: bool = False) -> int:
    """
    从 daily_kline 文件推算连板数（备用方案）
    向前遍历，计算连续涨停天数

    :param stock_code:  股票代码
    :param target_date: 目标日期，默认今天
    :param is_st:       是否为 ST 股
    :return: 连板数（整数），数据不足时返回 0
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import STOCKS_DIR
    from storage.reader import parse_md_table, read_recent_mds

    if target_date is None:
        target_date = date.today()

    kline_dir  = os.path.join(STOCKS_DIR, stock_code, "daily_kline")
    threshold  = LIMIT_UP_PCT_ST if is_st else LIMIT_UP_PCT_NORMAL
    recent     = read_recent_mds(kline_dir, n=30, end_date=target_date)

    if not recent:
        return 0

    streak = 0
    for _, content in reversed(recent):
        rows = parse_md_table(content)
        if not rows:
            break
        row = rows[-1]
        pct_str = row.get("涨跌幅", "N/A").replace("%", "").replace("+", "").strip()
        try:
            pct = float(pct_str)
        except ValueError:
            break
        if pct >= threshold:
            streak += 1
        else:
            break

    return streak


def get_streak(stock_code: str, target_date: date = None,
               is_st: bool = False) -> int:
    """
    获取连板数（自动选择最优来源）
    优先从涨停池读取，失败时从 kline 推算

    :return: 连板数（整数），无法获取时返回 0
    """
    streak = get_streak_from_limit_up(stock_code, target_date)

    if streak is None:
        logger.debug(f"[streak] {stock_code} 涨停池无数据，改从K线推算")
        streak = get_streak_from_kline(stock_code, target_date, is_st)

    return streak


def get_all_streaks(target_date: date = None) -> dict[str, int]:
    """
    获取当日所有涨停股的连板数
    直接从涨停池文件批量读取，效率最高

    :return: {"股票代码": 连板数, ...}，只包含当日涨停股
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import LIMIT_UP_DIR
    from storage.reader import parse_md_table, read_md_by_date

    if target_date is None:
        target_date = date.today()

    content = read_md_by_date(LIMIT_UP_DIR, target_date)
    if not content:
        logger.warning(f"[streak] {target_date} 涨停池文件不存在")
        return {}

    rows   = parse_md_table(content)
    result = {}
    for row in rows:
        code = row.get("代码", "").strip()
        if not code or code == "N/A":
            continue
        try:
            result[code] = int(row.get("连板数", 0))
        except (ValueError, TypeError):
            result[code] = 0

    logger.info(f"[streak] {target_date} 批量读取连板数，共 {len(result)} 只")
    return result


def get_max_streak(target_date: date = None) -> int:
    """获取当日最高连板数"""
    streaks = get_all_streaks(target_date)
    return max(streaks.values(), default=0)
