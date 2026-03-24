"""
任务执行入口
配合系统 cron 使用，每个任务对应一条 crontab 记录

用法：
  # 执行单个任务（由 cron 调用）
  python runner.py --job market_quote
  python runner.py --job northbound
  python runner.py --job limit_up
  ...

  # 查看所有可用任务
  python runner.py --list

  # 手动触发全流水线（调试用）
  python runner.py --all
"""

import argparse
import logging
import os
import sys
from datetime import datetime

# 确保 src/ 在路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 日志配置 ──────────────────────────────────────────────────────────────────

def setup_logging():
    from config.settings import LOG_DIR
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, f"runner_{datetime.today().strftime('%Y%m%d')}.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ]
    )


# ── 任务映射 ──────────────────────────────────────────────────────────────────

def get_job_map():
    """返回 {任务名: (函数, 描述)} 的映射"""
    from scheduler.daily_jobs import (
        job_concept_map_weekly,
        job_concepts,
        job_kline_daily,
        job_kline_minute,
        job_lhb,
        job_limit_up,
        job_market_pack,
        job_market_quote,
        job_market_state,
        job_northbound,
        job_stock_derived,
        job_stock_packs,
    )
    return {
        "market_quote":       (job_market_quote,       "全市场行情采集"),
        "northbound":         (job_northbound,          "北向资金采集"),
        "limit_up":           (job_limit_up,            "涨停股池采集"),
        "kline_daily":        (job_kline_daily,         "涨停股日K线采集"),
        "kline_minute":       (job_kline_minute,        "涨停股5分钟线采集"),
        "lhb":                (job_lhb,                 "龙虎榜采集"),
        "concepts":           (job_concepts,            "题材概念统计"),
        "market_state":       (job_market_state,        "市场状态计算"),
        "stock_derived":      (job_stock_derived,       "个股衍生指标计算"),
        "market_pack":        (job_market_pack,         "市场分析数据包生成"),
        "stock_packs":        (job_stock_packs,         "个股分析数据包生成"),
        "concept_map_weekly": (job_concept_map_weekly,  "概念映射表更新（仅周一）"),
    }


def run_job(job_name: str):
    """执行单个任务，捕获异常并记录日志"""
    logger = logging.getLogger(__name__)
    job_map = get_job_map()

    if job_name not in job_map:
        logger.error(f"未知任务: {job_name}，可用任务: {list(job_map.keys())}")
        sys.exit(1)

    fn, desc = job_map[job_name]
    logger.info(f"开始执行: [{job_name}] {desc}")
    try:
        fn()
        logger.info(f"完成: [{job_name}]")
    except NotImplementedError:
        logger.warning(f"跳过（未实现）: [{job_name}]")
    except Exception as e:
        logger.error(f"失败: [{job_name}] — {e}", exc_info=True)
        sys.exit(1)


def run_all():
    """按顺序执行全部任务（调试用）"""
    logger = logging.getLogger(__name__)
    logger.info("=== 开始全流水线 ===")
    for job_name in get_job_map():
        run_job(job_name)
    logger.info("=== 全流水线完成 ===")


def list_jobs():
    """打印所有可用任务"""
    print("\n可用任务：")
    print(f"{'任务名':<22} {'描述'}")
    print("-" * 50)
    for name, (_, desc) in get_job_map().items():
        print(f"{name:<22} {desc}")
    print()


# ── 主入口 ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    setup_logging()

    parser = argparse.ArgumentParser(
        description="Hunter 数据流水线任务执行器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python runner.py --job market_quote    # 执行行情采集
  python runner.py --job lhb             # 执行龙虎榜采集
  python runner.py --list                # 查看所有任务
  python runner.py --all                 # 执行全流水线（调试用）
        """
    )
    parser.add_argument("--job",  "-j", help="执行指定任务")
    parser.add_argument("--all",  "-a", action="store_true", help="执行全部任务")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有任务")
    args = parser.parse_args()

    if args.list:
        list_jobs()
    elif args.all:
        run_all()
    elif args.job:
        run_job(args.job)
    else:
        parser.print_help()
