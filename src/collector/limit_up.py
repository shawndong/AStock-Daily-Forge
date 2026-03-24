"""
采集层 — 涨停股池
数据来源：AKShare stock_zt_pool_em（东方财富 push2ex 接口）
写入：data/market/limit_up/YYYYMMDD.md

字段说明（AKShare 已处理单位）：
  成交额      : 元 → 亿元（÷1e8）
  流通市值    : 元 → 亿元（÷1e8）
  总市值      : 元 → 亿元（÷1e8）
  封板资金    : 元 → 亿元（÷1e8）
  涨跌幅      : 已为百分比小数（如 9.995285），存储时保留2位
  首次/最后封板时间 : 6位字符串如 "092500" → 格式化为 "09:25:00"
  涨停统计    : 已为 "5/5" 格式（近N日涨停/统计天数）
  连板数      : 整数，直接使用

重要：此接口直接提供连板数和所属行业，无需额外计算。
"""

import logging
import time
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 10
YUAN_TO_YI  = 1e8

REQUIRED_COLUMNS = {"代码", "名称", "连板数", "成交额", "所属行业"}


def fetch_limit_up(
    target_date: date = None,
    retries: int = MAX_RETRIES,
) -> Optional[list[dict]]:
    """
    获取指定日期涨停股池数据

    :param target_date: 目标日期，默认今天
    :param retries:     最大重试次数
    :return: 涨停股记录列表，非交易日返回空列表，失败返回 None
    每条记录字段：
      code, name, change_pct, close, amount_yi, float_cap_yi,
      total_cap_yi, turnover, seal_amount_yi, first_seal_time,
      last_seal_time, blast_count, zt_stat, streak, industry
    """
    import akshare as ak

    if target_date is None:
        target_date = date.today()

    date_str   = target_date.strftime("%Y%m%d")
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            logger.info(f"[limit_up] 第{attempt}次请求，日期: {target_date}")
            df = ak.stock_zt_pool_em(date=date_str)
            return _parse_zt_df(df, target_date)

        except Exception as e:
            last_error = e
            logger.warning(f"[limit_up] 第{attempt}次失败: {e}")
            if attempt < retries:
                logger.info(f"[limit_up] {RETRY_DELAY}s 后重试...")
                time.sleep(RETRY_DELAY)

    logger.error(f"[limit_up] 重试{retries}次后仍失败: {last_error}")
    return None


def _parse_zt_df(df, target_date: date) -> list[dict]:
    """将 AKShare 返回的 DataFrame 转换为字典列表"""

    if df is None or df.empty:
        logger.warning(f"[limit_up] {target_date} 无数据（非交易日或无涨停股）")
        return []

    _validate_columns(df)

    records = []
    for _, row in df.iterrows():
        records.append({
            "code":           _safe_str(row, "代码"),
            "name":           _safe_str(row, "名称"),
            "change_pct":     _safe_float(row, "涨跌幅"),
            "close":          _safe_float(row, "最新价"),
            "amount_yi":      _to_yi(row, "成交额"),
            "float_cap_yi":   _to_yi(row, "流通市值"),
            "total_cap_yi":   _to_yi(row, "总市值"),
            "turnover":       _safe_float(row, "换手率"),
            "seal_amount_yi": _to_yi(row, "封板资金"),
            "first_seal":     _fmt_time(row, "首次封板时间"),
            "last_seal":      _fmt_time(row, "最后封板时间"),
            "blast_count":    _safe_int(row, "炸板次数"),
            "zt_stat":        _safe_str(row, "涨停统计"),
            "streak":         _safe_int(row, "连板数"),
            "industry":       _safe_str(row, "所属行业"),
        })

    logger.info(f"[limit_up] {target_date} 解析完成，共 {len(records)} 只")
    return records


def _validate_columns(df):
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"[limit_up] AKShare 返回字段缺失: {missing}")


def _safe_str(row, col: str) -> str:
    import pandas as pd
    val = row.get(col)
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "N/A"
    return str(val).strip()


def _safe_float(row, col: str) -> Optional[float]:
    import pandas as pd
    val = row.get(col)
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return round(float(val), 4)
    except (ValueError, TypeError):
        return None


def _safe_int(row, col: str) -> Optional[int]:
    import pandas as pd
    val = row.get(col)
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _to_yi(row, col: str) -> Optional[float]:
    """元 → 亿元"""
    val = _safe_float(row, col)
    return round(val / YUAN_TO_YI, 2) if val is not None else None


def _fmt_time(row, col: str) -> str:
    """
    封板时间格式化：6位字符串 "092500" → "09:25:00"
    AKShare 已做 zfill(6) 处理
    """
    val = _safe_str(row, col)
    if val == "N/A" or len(val) < 6:
        return "N/A"
    try:
        return f"{val[:2]}:{val[2:4]}:{val[4:6]}"
    except Exception:
        return val


# ── 存储 ──────────────────────────────────────────────────────────────────────

def save_limit_up(records: list[dict], d: date = None):
    """
    写入涨停股池完整数据
    按连板数降序，连板数相同按成交额降序排列
    """
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import LIMIT_UP_DIR
    from storage.writer import date_to_filename, rows_to_md_table, write_md

    if d is None:
        d = date.today()

    if not records:
        content = (
            f"# 涨停股池 {d.strftime('%Y-%m-%d')}\n\n"
            f"> ⚠️ 当日无数据（非交易日或无涨停股）\n"
        )
        write_md(LIMIT_UP_DIR, date_to_filename(d), content)
        logger.warning(f"[limit_up] {d} 写入空标记")
        return

    # 排序：连板数降序，成交额降序
    sorted_records = sorted(
        records,
        key=lambda x: (x.get("streak") or 0, x.get("amount_yi") or 0),
        reverse=True,
    )

    def fmt_float(val, decimals=2):
        return f"{val:.{decimals}f}" if val is not None else "N/A"

    def fmt_pct(val):
        if val is None:
            return "N/A"
        return f"{val:.2f}%"

    def fmt_int(val):
        return str(val) if val is not None else "N/A"

    rows = [
        [
            r["code"],
            r["name"],
            fmt_pct(r["change_pct"]),
            fmt_float(r["close"]),
            fmt_float(r["amount_yi"]),
            fmt_float(r["float_cap_yi"]),
            fmt_float(r["total_cap_yi"]),
            fmt_pct(r["turnover"]),
            fmt_float(r["seal_amount_yi"]),
            r["first_seal"],
            r["last_seal"],
            fmt_int(r["blast_count"]),
            r["zt_stat"],
            fmt_int(r["streak"]),
            r["industry"],
        ]
        for r in sorted_records
    ]

    headers = [
        "代码", "名称", "涨跌幅", "最新价",
        "成交额(亿)", "流通市值(亿)", "总市值(亿)", "换手率",
        "封板资金(亿)", "首次封板", "最后封板", "炸板次数",
        "涨停统计", "连板数", "所属行业",
    ]

    # 统计摘要
    max_streak    = max((r.get("streak") or 0) for r in records)
    streak_counts = {}
    for r in records:
        s = r.get("streak") or 0
        streak_counts[s] = streak_counts.get(s, 0) + 1
    streak_summary = "  ".join(
        f"{s}板×{cnt}" for s, cnt in sorted(streak_counts.items(), reverse=True)
    )

    content = (
        f"# 涨停股池 {d.strftime('%Y-%m-%d')}\n\n"
        f"> 共 {len(records)} 只  |  最高连板 {max_streak} 板  |  {streak_summary}\n\n"
        + rows_to_md_table(headers, rows)
    )

    write_md(LIMIT_UP_DIR, date_to_filename(d), content)
    logger.info(f"[limit_up] {d} 已写入，共 {len(records)} 只，最高连板 {max_streak}")


# ── 入口 ──────────────────────────────────────────────────────────────────────

def run(d: date = None):
    if d is None:
        d = date.today()
    records = fetch_limit_up(target_date=d)
    if records is None:
        logger.error(f"[limit_up] {d} 采集失败，文件未写入")
        return
    save_limit_up(records, d)
