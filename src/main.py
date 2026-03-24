"""
手动触发入口
用于调试或补跑某一天的数据，不依赖定时调度
"""

import argparse
from datetime import date, datetime


def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y%m%d").date()


def run_full_pipeline(d: date):
    """运行完整流水线（按顺序执行所有采集和计算）"""
    print(f"\n=== 开始运行 {d} 完整流水线 ===\n")
    steps = [
        ("行情采集",       "collector.market_quote",  "run", []),
        ("北向资金",       "collector.northbound",    "run", []),
        ("涨停列表",       "collector.limit_up",      "run", []),
        ("龙虎榜",         "collector.lhb",           "run", []),
        ("市场状态计算",   "calculator.market_state", "run", []),
        ("个股衍生指标",   "calculator.stock_derived","run", []),
        ("市场数据包组装", "assembler.market_pack",   "run", []),
    ]
    for name, module, fn, args in steps:
        print(f"[{name}]")
        try:
            import importlib
            mod = importlib.import_module(module)
            getattr(mod, fn)(d, *args)
        except NotImplementedError:
            print("  ⚠️  未实现，跳过")
        except Exception as e:
            print(f"  ❌ 失败: {e}")
    print("\n=== 流水线完成 ===")


def run_stock(stock_code: str, d: date):
    """生成指定个股的分析数据包"""
    from assembler.stock_pack import run
    run(stock_code, d)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hunter 手动触发")
    parser.add_argument("--date",  "-d", default=date.today().strftime("%Y%m%d"),
                        help="日期，格式 YYYYMMDD，默认今天")
    parser.add_argument("--stock", "-s", default=None,
                        help="仅生成指定股票的个股数据包，例如 --stock 300001")
    parser.add_argument("--full",  "-f", action="store_true",
                        help="运行完整流水线")
    args = parser.parse_args()

    d = parse_date(args.date)

    if args.stock:
        run_stock(args.stock, d)
    elif args.full:
        run_full_pipeline(d)
    else:
        parser.print_help()
