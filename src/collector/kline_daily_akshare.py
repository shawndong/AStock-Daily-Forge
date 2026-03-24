"""
采集层 — 个股日K线
数据来源：AKShare stock_zh_a_hist（前复权）
写入：data/stocks/{code}/daily_kline/YYYYMMDD.md

设计说明：
  每个交易日写一个文件，文件名为日期（YYYYMMDD.md）
  assembler 读取近30个文件拼成一个月日K数据包
  首次采集时可批量拉取历史数据（一次请求多天）

字段：
  日期、开盘、收盘、最高、最低、成交量(手)、成交额(亿)、
  振幅%、涨跌幅%、涨跌额、换手率%

成交额单位转换：元 → 亿元（÷1e8）
"""

import logging
import os
import time
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

MAX_RETRIES  = 3
RETRY_DELAY  = 5
YUAN_TO_YI   = 1e8

# AKShare 接口返回的列名
REQUIRED_COLUMNS = {"日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"}


def fetch_kline_daily(
    stock_code: str,
    start_date: date,
    end_date: date,
    adjust: str = "qfq",
    retries: int = MAX_RETRIES,
) -> Optional[list[dict]]:
    """
    获取个股日K线数据（支持批量拉取多天）

    :param stock_code: 股票代码，如 "000001"
    :param start_date: 起始日期
    :param end_date:   结束日期
    :param adjust:     复权方式，qfq=前复权（默认），hfq=后复权，""=不复权
    :param retries:    最大重试次数
    :return: 每日K线数据列表（按日期升序），失败返回 None
    """
    import akshare as ak

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            logger.info(f"[kline_daily] {stock_code} 第{attempt}次请求 "
                        f"{start_date}~{end_date}")
            df = ak.stock_zh_a_hist(
                symbol=stock_code,
                period="daily",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                adjust=adjust,
            )
            return _parse_kline_df(df, stock_code)

        except Exception as e:
            last_error = e
            logger.warning(f"[kline_daily] {stock_code} 第{attempt}次失败: {e}")
            if attempt < retries:
                time.sleep(RETRY_DELAY)

    logger.error(f"[kline_daily] {stock_code} 重试{retries}次后仍失败: {last_error}")
    return None


def _parse_kline_df(df, stock_code: str) -> list[dict]:
    """将 AKShare 返回的 DataFrame 转换为字典列表"""

    if df is None or df.empty:
        logger.warning(f"[kline_daily] {stock_code} 返回空数据")
        return []

    _validate_columns(df)

    records = []
    for _, row in df.iterrows():
        trade_date = row["日期"]
        # AKShare 返回的日期可能是 str 或 datetime
        if isinstance(trade_date, str):
            trade_date = date.fromisoformat(trade_date)
        elif hasattr(trade_date, "date"):
            trade_date = trade_date.date()

        amount_yi = None
        raw_amount = _safe_float(row, "成交额")
        if raw_amount is not None:
            amount_yi = round(raw_amount / YUAN_TO_YI, 4)

        records.append({
            "date":        trade_date,
            "code":        stock_code,
            "open":        _safe_float(row, "开盘"),
            "close":       _safe_float(row, "收盘"),
            "high":        _safe_float(row, "最高"),
            "low":         _safe_float(row, "最低"),
            "volume":      _safe_float(row, "成交量"),   # 手
            "amount":      amount_yi,                    # 亿元
            "amplitude":   _safe_float(row, "振幅"),     # %
            "change_pct":  _safe_float(row, "涨跌幅"),   # %
            "change_amt":  _safe_float(row, "涨跌额"),
            "turnover":    _safe_float(row, "换手率"),    # %
        })

    logger.info(f"[kline_daily] {stock_code} 解析完成，共 {len(records)} 条")
    return records


def _validate_columns(df):
    """校验必需字段，接口变更时快速发现"""
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"[kline_daily] AKShare 返回字段缺失: {missing}")


def _safe_float(row, col: str) -> Optional[float]:
    import pandas as pd
    val = row.get(col)
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return round(float(val), 4)
    except (ValueError, TypeError):
        return None


# ── 存储 ──────────────────────────────────────────────────────────────────────

def save_kline_daily(stock_code: str, records: list[dict]):
    """
    将日K线数据写入文件，每个交易日写一个独立文件
    文件路径：data/stocks/{code}/daily_kline/YYYYMMDD.md
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import STOCKS_DIR
    from storage.writer import date_to_filename, rows_to_md_table, write_md

    if not records:
        logger.warning(f"[kline_daily] {stock_code} 无数据，跳过写入")
        return

    kline_dir = os.path.join(STOCKS_DIR, stock_code, "daily_kline")

    for r in records:
        d = r["date"]

        def fmt(val, decimals=3):
            return f"{val:.{decimals}f}" if val is not None else "N/A"

        def fmt_pct(val):
            if val is None:
                return "N/A"
            return f"{val:+.2f}%"

        row = [[
            str(d),
            fmt(r["open"]),
            fmt(r["close"]),
            fmt(r["high"]),
            fmt(r["low"]),
            fmt(r["volume"], 0),
            fmt(r["amount"], 4),
            fmt_pct(r["amplitude"]),
            fmt_pct(r["change_pct"]),
            fmt(r["change_amt"]),
            fmt(r["turnover"], 2) + "%" if r["turnover"] is not None else "N/A",
        ]]

        content = (
            f"# {stock_code} 日K线 {d}\n\n"
            + rows_to_md_table(
                ["日期", "开盘", "收盘", "最高", "最低",
                 "成交量(手)", "成交额(亿)", "振幅", "涨跌幅", "涨跌额", "换手率"],
                row
            )
        )
        write_md(kline_dir, date_to_filename(d), content)

    logger.info(f"[kline_daily] {stock_code} 写入完成，共 {len(records)} 个文件")


# ── 批量采集工具 ──────────────────────────────────────────────────────────────

def fetch_and_save(
    stock_code: str,
    start_date: date,
    end_date: date = None,
    skip_existing: bool = True,
):
    """
    采集指定股票的日K线并写入文件
    :param skip_existing: True 时跳过已存在的日期文件（增量更新）
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import STOCKS_DIR

    if end_date is None:
        end_date = date.today()

    # 找出已有文件，跳过已存在的日期
    kline_dir = os.path.join(STOCKS_DIR, stock_code, "daily_kline")
    existing = set()
    if skip_existing and os.path.exists(kline_dir):
        for fname in os.listdir(kline_dir):
            if fname.endswith(".md"):
                try:
                    existing.add(date(int(fname[:4]), int(fname[4:6]), int(fname[6:8])))
                except (ValueError, IndexError):
                    pass

    records = fetch_kline_daily(stock_code, start_date, end_date)
    if records is None:
        return

    # 过滤掉已存在的日期
    if skip_existing:
        before = len(records)
        records = [r for r in records if r["date"] not in existing]
        if before != len(records):
            logger.info(f"[kline_daily] {stock_code} 跳过 {before - len(records)} 个已存在文件")

    save_kline_daily(stock_code, records)


def run_batch(
    stock_codes: list[str],
    start_date: date = None,
    end_date: date = None,
    batch_delay: float = 0.3,
):
    """
    批量采集多只股票的日K线
    :param start_date: 默认为30天前（初次运行建议设置更早的日期）
    :param batch_delay: 每只股票之间的间隔（秒）
    """
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=30)

    total = len(stock_codes)
    success, failed = 0, []

    for i, code in enumerate(stock_codes, 1):
        try:
            fetch_and_save(code, start_date, end_date)
            success += 1
            if i % 50 == 0:
                logger.info(f"[kline_daily] 进度 {i}/{total}")
        except Exception as e:
            failed.append(code)
            logger.error(f"[kline_daily] {code} 失败: {e}")
        time.sleep(batch_delay)

    logger.info(f"[kline_daily] 批量完成: 成功 {success}，失败 {len(failed)}")
    if failed:
        logger.warning(f"[kline_daily] 失败列表: {failed}")


def run(d: date = None):
    """每日定时任务入口：采集昨日涨停股的当日K线"""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import LIMIT_UP_DIR
    from storage.reader import parse_md_table, read_md_by_date

    if d is None:
        d = date.today()

    # 读取当日涨停股列表，只采集这些股票
    content = read_md_by_date(LIMIT_UP_DIR, d)
    if not content:
        logger.warning(f"[kline_daily] 未找到 {d} 涨停列表，跳过")
        return

    rows = parse_md_table(content)
    codes = [(r.get("代码") or r.get("股票代码") or "").strip() for r in rows if (r.get("代码") or r.get("股票代码"))]

    if not codes:
        logger.info(f"[kline_daily] {d} 无涨停股，跳过")
        return

    logger.info(f"[kline_daily] 采集 {d} 涨停股日K线，共 {len(codes)} 只")
    run_batch(codes, start_date=d - timedelta(days=35), end_date=d)

