"""
汇总层 — 个股分析数据包
读取多个已计算好的数据文件，组装为可直接传给大模型的提示词数据包

默认输出：data/assembled/stocks/{code}_YYYYMMDD.md
可选输出：单文件模式 data/assembled/stocks/all_YYYYMMDD.md（减少文件数）

数据来源（按顺序拼接）：
  一、最新衍生指标  ← stocks/{code}/derived/
  二、近1个月日K线  ← stocks/{code}/daily_kline/ 近30个文件
  三、近5日分钟线   ← stocks/{code}/minute_kline/ 近5个文件
  四、近5日龙虎榜   ← lhb/ 近5个文件，过滤该股
"""

import logging
import os
from datetime import date

logger = logging.getLogger(__name__)

# 日K线读取条数（约1个月）
KLINE_DAILY_COUNT = 30
# 分钟线读取天数
KLINE_MINUTE_DAYS = 5
# 龙虎榜回溯天数
LHB_LOOKBACK_DAYS = 5


def _pick_code_field(row: dict) -> str:
    """兼容不同版本龙虎榜表头：代码 / 股票代码。"""
    return (row.get("代码") or row.get("股票代码") or "").strip()


def assemble_stock_pack(stock_code: str, d: date = None) -> str:
    """
    组装个股分析数据包

    :param stock_code: 股票代码，如 "000001"
    :return: 完整 Markdown 字符串
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import LHB_DIR, STOCKS_DIR
    from storage.reader import parse_md_table, read_md_by_date, read_recent_mds
    from storage.writer import rows_to_md_table

    if d is None:
        d = date.today()

    sections = [
        f"# {stock_code} 个股分析数据包 {d.strftime('%Y-%m-%d')}\n",
        "> 以下数据供大模型分析该股走势\n",
    ]

    # 一、最新衍生指标
    sections.append("\n## 一、最新衍生指标\n")
    derived_dir = os.path.join(STOCKS_DIR, stock_code, "derived")
    derived = read_md_by_date(derived_dir, d)
    sections.append(derived if derived else "_数据缺失 (N/A)_\n")

    # 二、近1个月日K线（合并近30个文件为一张表）
    sections.append("\n## 二、近1个月日K线\n")
    kline_dir = os.path.join(STOCKS_DIR, stock_code, "daily_kline")
    recent_klines = read_recent_mds(kline_dir, n=KLINE_DAILY_COUNT, end_date=d)

    if recent_klines:
        all_rows = []
        headers = None
        for _, content in recent_klines:
            rows = parse_md_table(content)
            if rows:
                if headers is None:
                    headers = list(rows[0].keys())
                all_rows.extend(rows)

        if all_rows and headers:
            data = [[row.get(h, "N/A") for h in headers] for row in all_rows]
            sections.append(rows_to_md_table(headers, data) + "\n")
        else:
            sections.append("_数据缺失 (N/A)_\n")
    else:
        sections.append("_数据缺失 (N/A)_\n")

    # 三、近5日分钟线
    sections.append("\n## 三、近5日5分钟线\n")
    minute_dir = os.path.join(STOCKS_DIR, stock_code, "minute_kline")
    recent_minutes = read_recent_mds(minute_dir, n=KLINE_MINUTE_DAYS, end_date=d)

    if recent_minutes:
        for md, mc in recent_minutes:
            sections.append(f"**{md.strftime('%Y-%m-%d')}**\n{mc}\n")
    else:
        sections.append("_数据缺失 (N/A)_\n")

    # 四、近5日龙虎榜
    sections.append("\n## 四、近5日龙虎榜\n")
    recent_lhb = read_recent_mds(LHB_DIR, n=LHB_LOOKBACK_DAYS, end_date=d)
    found_any = False

    for ld, lc in recent_lhb:
        rows = parse_md_table(lc)
        stock_rows = [r for r in rows if _pick_code_field(r) == stock_code]
        if stock_rows:
            found_any = True
            headers = list(stock_rows[0].keys())
            data = [[r.get(h, "N/A") for h in headers] for r in stock_rows]
            sections.append(f"**{ld.strftime('%Y-%m-%d')}**\n")
            sections.append(rows_to_md_table(headers, data) + "\n")

    if not found_any:
        sections.append("_近5日无龙虎榜记录_\n")

    return "\n".join(sections)


def run(stock_code: str, d: date = None):
    """写入单个个股分析数据包"""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import ASSEMBLED_DIR
    from storage.writer import write_md

    if d is None:
        d = date.today()

    content  = assemble_stock_pack(stock_code, d)
    out_dir  = os.path.join(ASSEMBLED_DIR, "stocks")
    filename = f"{stock_code}_{d.strftime('%Y%m%d')}.md"
    write_md(out_dir, filename, content)
    logger.info(f"[stock_pack] {stock_code} 数据包已生成：{d}")


def run_batch(stock_codes: list[str], d: date = None, mode: str = "per_stock"):
    """
    批量写入个股分析数据包

    :param mode:
      - per_stock: 每股一个文件
      - single_file: 全部股票合并一个文件（减少文件数量）
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import ASSEMBLED_DIR
    from storage.writer import write_md

    if d is None:
        d = date.today()

    mode = (mode or "per_stock").strip().lower()
    if mode == "single_file":
        chunks = [f"# 当日个股分析数据包汇总 {d.strftime('%Y-%m-%d')}\n"]
        for idx, code in enumerate(stock_codes, 1):
            try:
                chunks.append(f"\n\n---\n\n## {idx}. {code}\n")
                chunks.append(assemble_stock_pack(code, d))
            except Exception as e:
                logger.error(f"[stock_pack] {code} 汇总失败: {e}")
                chunks.append(f"\n> {code} 生成失败: {e}\n")

        out_dir = os.path.join(ASSEMBLED_DIR, "stocks")
        filename = f"all_{d.strftime('%Y%m%d')}.md"
        write_md(out_dir, filename, "\n".join(chunks))
        logger.info(f"[stock_pack] 单文件模式已生成：{filename}，共 {len(stock_codes)} 只")
        return

    # 默认保持原行为
    for code in stock_codes:
        try:
            run(code, d)
        except Exception as e:
            logger.error(f"[stock_pack] {code} 失败: {e}")
