"""
调度工具 — 交易日判断
供 scheduler/runner.py 和 main.py 调用

判断逻辑（优先级从高到低）：
  1. 周六 / 周日 → 非交易日
  2. 在 config/trading_calendar.py 的节假日区间内 → 非交易日
  3. 其余 → 交易日
"""

import logging
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


def is_trading_day(d: date = None) -> bool:
    """
    判断指定日期是否为交易日

    :param d: 日期，默认今天
    :return: True 表示交易日，False 表示非交易日
    """
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.trading_calendar import HOLIDAYS

    if d is None:
        d = date.today()

    # 1. 周末判断
    if d.weekday() >= 5:   # 5=周六, 6=周日
        logger.debug(f"[trading_day] {d} 是周末，非交易日")
        return False

    # 2. 节假日判断
    holiday = _find_holiday(d, HOLIDAYS)
    if holiday:
        logger.debug(f"[trading_day] {d} 是节假日（{holiday['name']}），非交易日")
        return False

    return True


def _find_holiday(d: date, holidays: list[dict]) -> Optional[dict]:
    """在节假日列表中查找包含日期 d 的记录，找不到返回 None"""
    for h in holidays:
        try:
            start = date.fromisoformat(h["start"])
            end   = date.fromisoformat(h["end"])
            if start <= d <= end:
                return h
        except (KeyError, ValueError) as e:
            logger.warning(f"[trading_day] 节假日配置格式错误: {h} — {e}")
    return None


def get_last_trading_day(d: date = None, max_lookback: int = 10) -> Optional[date]:
    """
    获取指定日期之前（含当天）最近的交易日

    :param d:            基准日期，默认今天
    :param max_lookback: 最大向前查找天数
    :return: 最近交易日，超出范围返回 None
    """
    if d is None:
        d = date.today()

    for i in range(max_lookback):
        candidate = d - timedelta(days=i)
        if is_trading_day(candidate):
            return candidate

    logger.warning(f"[trading_day] 向前 {max_lookback} 天内未找到交易日")
    return None


def get_next_trading_day(d: date = None, max_lookahead: int = 10) -> Optional[date]:
    """
    获取指定日期之后（不含当天）最近的交易日
    """
    if d is None:
        d = date.today()

    for i in range(1, max_lookahead + 1):
        candidate = d + timedelta(days=i)
        if is_trading_day(candidate):
            return candidate

    logger.warning(f"[trading_day] 向后 {max_lookahead} 天内未找到交易日")
    return None


def assert_trading_day(d: date = None) -> bool:
    """
    断言今天是交易日，非交易日时打印日志并返回 False
    供 cron 脚本入口调用：
        if not assert_trading_day(): sys.exit(0)
    """
    if d is None:
        d = date.today()

    if is_trading_day(d):
        logger.info(f"[trading_day] {d} 是交易日，继续执行")
        return True
    else:
        logger.info(f"[trading_day] {d} 非交易日，跳过执行")
        return False
