"""
采集层 — 龙虎榜
数据来源：AKShare stock_lhb_detail_em（东方财富）
写入：data/lhb/YYYYMMDD.md

保存字段（全量）：
  代码、名称、上榜日、解读、收盘价、涨跌幅
  龙虎榜净买额、买入额、卖出额、成交额、市场总成交额
  净买额占总成交比、成交额占总成交比、换手率、流通市值
  上榜原因、上榜后1/2/5/10日涨跌幅

金额单位说明：
  AKShare 原始单位为元，存储时转换为万元（÷10000），保留2位小数
  流通市值单位为亿元（÷1e8），保留2位小数
"""

import logging
import time
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

MAX_RETRIES  = 3
RETRY_DELAY  = 10

# 金额转换
YUAN_TO_WAN  = 10_000       # 元 → 万元
YUAN_TO_YI   = 1e8          # 元 → 亿元


def fetch_lhb(target_date: date = None, retries: int = MAX_RETRIES) -> Optional[list[dict]]:
    """
    获取指定日期的龙虎榜数据

    :param target_date: 目标日期，默认今天
    :param retries:     最大重试次数
    :return: 龙虎榜记录列表，每条记录为字典；失败返回 None
    每条记录字段：
      code, name, date, explain, close, change_pct,
      net_buy_wan, buy_wan, sell_wan, lhb_amount_wan, total_amount_wan,
      net_buy_ratio, amount_ratio, turnover_rate, float_cap_yi,
      reason, d1_chg, d2_chg, d5_chg, d10_chg
    """
    import akshare as ak

    if target_date is None:
        target_date = date.today()

    date_str = target_date.strftime("%Y%m%d")
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            logger.info(f"[lhb] 第 {attempt} 次请求，日期: {target_date}")
            df = ak.stock_lhb_detail_em(start_date=date_str, end_date=date_str)
            return _parse_lhb_df(df, target_date)

        except Exception as e:
            last_error = e
            logger.warning(f"[lhb] 第 {attempt} 次请求失败: {e}")
            if attempt < retries:
                logger.info(f"[lhb] {RETRY_DELAY}s 后重试...")
                time.sleep(RETRY_DELAY)

    logger.error(f"[lhb] 重试 {retries} 次后仍失败: {last_error}")
    return None


def _parse_lhb_df(df, target_date: date) -> list[dict]:
    """
    将 AKShare 返回的 DataFrame 转换为字典列表
    只保留目标日期的记录（接口可能返回多日数据）
    金额从元转换为万元，流通市值转换为亿元
    """

    if df is None or df.empty:
        logger.warning(f"[lhb] {target_date} 无数据（非交易日或当日无上榜）")
        return []

    _validate_columns(df)

    # 过滤目标日期（上榜日 字段是 date 对象）
    day_df = df[df["上榜日"] == target_date].copy()

    if day_df.empty:
        logger.warning(f"[lhb] {target_date} 过滤后无数据")
        return []

    records = []
    for _, row in day_df.iterrows():
        records.append({
            "code":            _safe_str(row, "代码"),
            "name":            _safe_str(row, "名称"),
            "date":            target_date,
            "explain":         _safe_str(row, "解读"),
            "close":           _safe_float(row, "收盘价"),
            "change_pct":      _safe_float(row, "涨跌幅"),
            "net_buy_wan":     _to_wan(row, "龙虎榜净买额"),
            "buy_wan":         _to_wan(row, "龙虎榜买入额"),
            "sell_wan":        _to_wan(row, "龙虎榜卖出额"),
            "lhb_amount_wan":  _to_wan(row, "龙虎榜成交额"),
            "total_amount_wan":_to_wan(row, "市场总成交额"),
            "net_buy_ratio":   _safe_float(row, "净买额占总成交比"),
            "amount_ratio":    _safe_float(row, "成交额占总成交比"),
            "turnover_rate":   _safe_float(row, "换手率"),
            "float_cap_yi":    _to_yi(row, "流通市值"),
            "reason":          _safe_str(row, "上榜原因"),
            "d1_chg":          _safe_float(row, "上榜后1日"),
            "d2_chg":          _safe_float(row, "上榜后2日"),
            "d5_chg":          _safe_float(row, "上榜后5日"),
            "d10_chg":         _safe_float(row, "上榜后10日"),
        })

    logger.info(f"[lhb] {target_date} 解析完成，共 {len(records)} 条")
    return records


def _validate_columns(df):
    """校验必需字段，接口变更时快速发现"""
    required = {"代码", "名称", "上榜日", "龙虎榜净买额", "上榜原因"}
    missing  = required - set(df.columns)
    if missing:
        raise ValueError(f"[lhb] AKShare 返回字段缺失: {missing}，请检查接口是否变更")


def _safe_str(row, col: str) -> str:
    val = row.get(col)
    if val is None:
        return "N/A"
    import pandas as pd
    return str(val).strip() if not pd.isna(val) else "N/A"


def _safe_float(row, col: str) -> Optional[float]:
    import pandas as pd
    val = row.get(col)
    if val is None or pd.isna(val):
        return None
    try:
        return round(float(val), 4)
    except (ValueError, TypeError):
        return None


def _to_wan(row, col: str) -> Optional[float]:
    """元 → 万元"""
    val = _safe_float(row, col)
    return round(val / YUAN_TO_WAN, 2) if val is not None else None


def _to_yi(row, col: str) -> Optional[float]:
    """元 → 亿元"""
    val = _safe_float(row, col)
    return round(val / YUAN_TO_YI, 2) if val is not None else None


# ── 存储 ──────────────────────────────────────────────────────────────────────

def save_lhb(records: list[dict], d: date = None):
    """
    将龙虎榜数据写入 md 文件
    全量保存所有字段，按净买额降序排列
    """
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import LHB_DIR
    from storage.writer import date_to_filename, rows_to_md_table, write_md

    if d is None:
        d = date.today()

    if not records:
        content = (
            f"# 龙虎榜 {d.strftime('%Y-%m-%d')}\n\n"
            f"> ⚠️ 当日无数据（非交易日或无上榜股票）\n"
        )
        write_md(LHB_DIR, date_to_filename(d), content)
        logger.warning(f"[lhb] {d} 写入空标记")
        return

    # 按净买额降序排列（净买最多的在前）
    sorted_records = sorted(
        records,
        key=lambda x: x.get("net_buy_wan") or 0,
        reverse=True
    )

    def fmt_float(val, decimals=2):
        if val is None:
            return "N/A"
        return f"{val:.{decimals}f}"

    def fmt_chg(val):
        if val is None:
            return "N/A"
        return f"{val:+.2f}%"

    rows = [
        [
            r["code"],
            r["name"],
            r["explain"],
            fmt_float(r["close"]),
            fmt_chg(r["change_pct"]),
            fmt_float(r["net_buy_wan"]),
            fmt_float(r["buy_wan"]),
            fmt_float(r["sell_wan"]),
            fmt_float(r["lhb_amount_wan"]),
            fmt_float(r["total_amount_wan"]),
            fmt_float(r["net_buy_ratio"]),
            fmt_float(r["amount_ratio"]),
            fmt_float(r["turnover_rate"]),
            fmt_float(r["float_cap_yi"]),
            r["reason"],
            fmt_chg(r["d1_chg"]),
            fmt_chg(r["d2_chg"]),
            fmt_chg(r["d5_chg"]),
            fmt_chg(r["d10_chg"]),
        ]
        for r in sorted_records
    ]

    headers = [
        "代码", "名称", "解读",
        "收盘价", "涨跌幅",
        "净买额(万)", "买入额(万)", "卖出额(万)", "龙虎榜成交(万)", "市场总成交(万)",
        "净买/总成交%", "龙虎榜/总成交%", "换手率%", "流通市值(亿)",
        "上榜原因",
        "上榜后1日", "上榜后2日", "上榜后5日", "上榜后10日",
    ]

    content = (
        f"# 龙虎榜 {d.strftime('%Y-%m-%d')}\n\n"
        f"> 共 {len(records)} 条，按净买额降序排列，金额单位：万元\n\n"
        + rows_to_md_table(headers, rows)
    )

    write_md(LHB_DIR, date_to_filename(d), content)
    logger.info(f"[lhb] {d} 已写入，共 {len(records)} 条")


# ── 入口 ──────────────────────────────────────────────────────────────────────

def run(d: date = None):
    if d is None:
        d = date.today()
    records = fetch_lhb(target_date=d)
    if records is None:
        logger.error(f"[lhb] {d} 采集失败，文件未写入")
        return
    save_lhb(records, d)
