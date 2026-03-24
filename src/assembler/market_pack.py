"""
汇总层 — 市场分析数据包
读取多个已计算好的数据文件，组装为可直接传给大模型的提示词数据包
写入：data/assembled/market/YYYYMMDD.md

数据来源（按顺序拼接）：
  一、市场状态        ← market/market_state/
  二、涨停股列表      ← market/limit_up/
  三、市场行情核心    ← market/daily_quote/（仅核心指标）
  四、北向资金        ← market/northbound/
  五、当日热点概念    ← concepts/daily_hot/
  六、当日龙虎榜      ← lhb/
  七、近5日状态趋势   ← market/market_state/ 近5个文件
  八、个股明细        ← market/daily_quote/（放最后）
"""

import logging
import os
from datetime import date

logger = logging.getLogger(__name__)


def _split_market_quote(quote: str) -> tuple[str, str]:
    """
    将 market_quote 内容拆分为“核心部分”和“个股明细部分”。

    约定：collector/market_quote.py 生成内容中包含 "## 个股明细" 标题。
    若未命中该标题，全部内容归入核心部分。
    """
    if not quote:
        return "", ""

    marker = "\n## 个股明细\n"
    idx = quote.find(marker)
    if idx == -1:
        return quote, ""

    core = quote[:idx].rstrip() + "\n"
    details = quote[idx + len(marker):].lstrip().rstrip() + "\\n"  # 仅保留明细表格内容
    return core, details


def assemble_market_pack(d: date = None) -> str:
    """
    组装市场分析数据包

    :return: 完整 Markdown 字符串，可直接作为提示词的一部分
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import (
        CONCEPTS_DIR,
        LHB_DIR,
        LIMIT_UP_DIR,
        MARKET_QUOTE_DIR,
        MARKET_STATE_DIR,
        NORTHBOUND_DIR,
    )
    from storage.reader import read_md_by_date, read_recent_mds

    if d is None:
        d = date.today()

    sections = [
        f"# 市场分析数据包 {d.strftime('%Y-%m-%d')}\n",
        "> 以下数据供大模型分析当日市场整体动向\n",
    ]

    # 一、市场状态（最重要，放最前）
    sections.append("\n## 一、市场状态\n")
    state = read_md_by_date(MARKET_STATE_DIR, d)
    sections.append(state if state else "_数据缺失 (N/A)_\n")

    # 二、涨停股列表
    sections.append("\n## 二、当日涨停股\n")
    limit_up = read_md_by_date(LIMIT_UP_DIR, d)
    sections.append(limit_up if limit_up else "_数据缺失 (N/A)_\n")

    # 三、市场行情汇总（核心，不含个股明细）
    sections.append("\n## 三、市场行情汇总（核心）\n")
    quote = read_md_by_date(MARKET_QUOTE_DIR, d)
    quote_core, quote_details = _split_market_quote(quote or "")
    sections.append(quote_core if quote_core else "_数据缺失 (N/A)_\n")

    # 四、北向资金
    sections.append("\n## 四、北向资金\n")
    nb = read_md_by_date(NORTHBOUND_DIR, d)
    sections.append(nb if nb else "_数据缺失 (N/A)_\n")

    # 五、当日热点概念
    sections.append("\n## 五、当日热点概念\n")
    concepts_daily_dir = os.path.join(CONCEPTS_DIR, "daily_hot")
    concepts_daily = read_md_by_date(concepts_daily_dir, d)
    sections.append(concepts_daily if concepts_daily else "_数据缺失 (N/A)_\n")

    # 六、当日龙虎榜
    sections.append("\n## 六、当日龙虎榜\n")
    lhb = read_md_by_date(LHB_DIR, d)
    sections.append(lhb if lhb else "_数据缺失 (N/A)_\n")

    # 七、近5日市场状态趋势
    sections.append("\n## 七、近5日市场状态趋势\n")
    recent = read_recent_mds(MARKET_STATE_DIR, n=5, end_date=d)
    if recent:
        for rd, rc in recent:
            sections.append(f"**{rd.strftime('%Y-%m-%d')}**\n{rc}\n")
    else:
        sections.append("_暂无历史数据_\n")

    # 八、个股明细（放最后）
    sections.append("\n## 八、个股明细\n")
    if quote_details:
        sections.append(quote_details)
    elif quote:
        sections.append("_未检测到个股明细分段，已保留在‘市场行情汇总（核心）’部分_\n")
    else:
        sections.append("_数据缺失 (N/A)_\n")

    return "\n".join(sections)


def run(d: date = None):
    """写入市场分析数据包"""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import ASSEMBLED_DIR
    from storage.writer import date_to_filename, write_md

    if d is None:
        d = date.today()

    content = assemble_market_pack(d)
    assembled_market_dir = os.path.join(ASSEMBLED_DIR, "market")
    write_md(assembled_market_dir, date_to_filename(d), content)
    logger.info(f"[market_pack] 市场数据包已生成：{d}")

