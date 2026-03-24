"""
定时任务定义
各任务的执行时间、顺序和调用入口

设计原则：
  - 每个任务函数首先检查今天是否交易日，非交易日直接返回
  - 21:00 后统一启动，减少白天网络波动影响
  - 在依赖允许的前提下并行，缩短总耗时
"""

import logging
from datetime import date

logger = logging.getLogger(__name__)


def _check_trading_day() -> bool:
    """交易日检查，非交易日时记录日志并返回 False"""
    from scheduler.trading_day import assert_trading_day
    return assert_trading_day()


# ── 采集任务 ──────────────────────────────────────────────────────────────────

def job_market_quote():
    """21:00  全市场行情（腾讯批量）"""
    if not _check_trading_day():
        return
    from collector.market_quote import run
    run()


def job_northbound():
    """21:00  北向资金"""
    if not _check_trading_day():
        return
    from collector.northbound import run
    run()


def job_limit_up():
    """21:00  涨停股池（含连板数、行业）"""
    if not _check_trading_day():
        return
    from collector.limit_up import run
    run()


def job_kline_daily():
    """21:08  当日涨停股日K线"""
    if not _check_trading_day():
        return
    from collector.kline_daily import run
    run()


def job_kline_minute():
    """21:14  当日涨停股5分钟线"""
    if not _check_trading_day():
        return
    from collector.kline_minute import run
    from config.settings import LIMIT_UP_DIR
    from storage.reader import parse_md_table, read_md_by_date

    today   = date.today()
    content = read_md_by_date(LIMIT_UP_DIR, today)
    if not content:
        logger.warning("[job_kline_minute] 未找到涨停列表，跳过分钟线采集")
        return
    rows  = parse_md_table(content)
    codes = [r.get("代码", "").strip() for r in rows
             if r.get("代码", "").strip() and r.get("代码") != "N/A"]
    if codes:
        run(codes)


def job_lhb():
    """21:00  龙虎榜（晚间稳定窗口）"""
    if not _check_trading_day():
        return
    from collector.lhb import run
    run()


def job_concepts():
    """21:08  题材概念统计（从 limit_up 派生）"""
    if not _check_trading_day():
        return
    from collector.concepts import run
    run()


# ── 计算任务 ──────────────────────────────────────────────────────────────────

def job_market_state():
    """21:20  市场状态计算"""
    if not _check_trading_day():
        return
    from calculator.market_state import run
    run()


def job_stock_derived():
    """21:20  个股衍生指标"""
    if not _check_trading_day():
        return
    from calculator.stock_derived import run
    run()


# ── 汇总任务 ──────────────────────────────────────────────────────────────────

def job_market_pack():
    """21:25  市场分析数据包"""
    if not _check_trading_day():
        return
    from assembler.market_pack import run
    run()


def job_stock_packs():
    """21:27  当日涨停股个股分析数据包"""
    if not _check_trading_day():
        return
    from assembler.stock_pack import run_batch
    from config.settings import LIMIT_UP_DIR, STOCK_PACK_OUTPUT_MODE
    from storage.reader import parse_md_table, read_md_by_date

    today   = date.today()
    content = read_md_by_date(LIMIT_UP_DIR, today)
    if not content:
        logger.warning("[job_stock_packs] 未找到涨停列表，跳过个股数据包生成")
        return

    rows  = parse_md_table(content)
    codes = [r.get("代码", "").strip() for r in rows
             if r.get("代码", "").strip() and r.get("代码") != "N/A"]
    if not codes:
        logger.warning("[job_stock_packs] 当日涨停列表为空")
        return

    run_batch(codes, d=today, mode=STOCK_PACK_OUTPUT_MODE)


# ── 每周任务 ──────────────────────────────────────────────────────────────────

def job_concept_map_weekly():
    """每周一 21:30  概念映射表更新"""
    if not _check_trading_day():
        return
    from collector.concepts import run
    run(update_map=True)


# ── 时序配置（供 runner.py 和 cron 使用）─────────────────────────────────────
#
# 格式：(cron时间, 任务函数, 描述)
# cron时间 格式：(分, 时)  —— 与 crontab 的 分 时 保持一致
#
SCHEDULE = [
    # 21:00 并行启动（互不依赖）
    ("00 21", job_market_quote,       "全市场行情采集"),
    ("00 21", job_northbound,         "北向资金采集"),
    ("00 21", job_limit_up,           "涨停股池采集"),
    ("00 21", job_lhb,                "龙虎榜采集"),
    # 21:08 并行启动（依赖 limit_up）
    ("08 21", job_concepts,           "题材概念统计"),
    ("08 21", job_kline_daily,        "涨停股日K线采集"),
    # 21:14（依赖 limit_up）
    ("14 21", job_kline_minute,       "涨停股5分钟线采集"),
    # 21:20 并行启动（依赖 limit_up/kline/lhb）
    ("20 21", job_market_state,       "市场状态计算"),
    ("20 21", job_stock_derived,      "个股衍生指标计算"),
    # 汇总阶段
    ("25 21", job_market_pack,        "市场分析数据包生成"),
    ("27 21", job_stock_packs,        "个股分析数据包生成"),
    ("30 21", job_concept_map_weekly, "概念映射表更新（仅周一）"),
]
