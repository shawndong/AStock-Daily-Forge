"""
采集层 — 个股日K线
数据来源：新浪财经 CN_MarketData.getKLineData（curl + subprocess，scale=240）
写入：data/stocks/{code}/daily_kline/YYYYMMDD.md

与分钟线使用同一接口，scale=240 表示日线。

字段说明：
  接口原始字段：day, open, high, low, close, volume（股）
  派生字段：
    amount_est  : volume × close ÷ 1e6，单位亿元（估算，标注"（估）"）
    change_pct  : (close - prev_close) / prev_close × 100，第一条无前日数据为 None
  缺失字段（接口不提供）：振幅、换手率，存储为 N/A

设计说明：
  每个交易日写一个文件（YYYYMMDD.md）
  skip_existing=True 保护已有文件（增量更新）
  datalen=35 约覆盖1.5个月，assembler 取近30条
"""

import json
import logging
import os
import subprocess
import time
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

SINA_URL = (
    "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
    "/CN_MarketData.getKLineData"
    "?symbol={symbol}&scale=240&ma=no&datalen={datalen}"
)
REFERER         = "https://finance.sina.com.cn"
DEFAULT_DATALEN = 35
MAX_RETRIES     = 3
RETRY_DELAY     = 5


def to_sina_symbol(code: str) -> str:
    return f"sh{code}" if code.startswith("6") else f"sz{code}"


# ── 采集 ──────────────────────────────────────────────────────────────────────

def fetch_kline_daily(
    stock_code: str,
    datalen: int = DEFAULT_DATALEN,
    retries: int = MAX_RETRIES,
) -> Optional[list[dict]]:
    """
    获取个股日K线数据

    :param stock_code: 股票代码，如 "000001"
    :param datalen:    获取条数，默认35（约1.5个月）
    :param retries:    最大重试次数
    :return: 日K线记录列表（按日期升序），失败返回 None
    """
    symbol     = to_sina_symbol(stock_code)
    url        = SINA_URL.format(symbol=symbol, datalen=datalen)
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            logger.info(f"[kline_daily] {stock_code} 第{attempt}次请求 datalen={datalen}")
            result = subprocess.run(
                ["curl", "-s", "--max-time", "15", url,
                 "-H", f"Referer: {REFERER}"],
                capture_output=True, timeout=20,
            )
            if result.returncode != 0:
                raise RuntimeError(f"curl 返回码 {result.returncode}")
            raw = result.stdout.decode("utf-8", errors="replace").strip()
            return _parse_kline_json(raw, stock_code)
        except Exception as e:
            last_error = e
            logger.warning(f"[kline_daily] {stock_code} 第{attempt}次失败: {e}")
            if attempt < retries:
                time.sleep(RETRY_DELAY)

    logger.error(f"[kline_daily] {stock_code} 重试{retries}次后仍失败: {last_error}")
    return None


def _parse_kline_json(raw: str, stock_code: str) -> list[dict]:
    """解析新浪日K线 JSON，并派生计算涨跌幅"""
    if not raw or raw.startswith("/*"):
        logger.warning(f"[kline_daily] {stock_code} 接口返回异常: {raw[:100]}")
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"[kline_daily] {stock_code} JSON 解析失败: {e}")
        return []
    if not isinstance(data, list):
        return []

    records = [r for item in data for r in [_parse_one_record(item)] if r]

    # 派生涨跌幅（需要前一日收盘价）
    for i, r in enumerate(records):
        if i == 0:
            r["change_pct"] = None
        else:
            prev = records[i - 1]["close"]
            r["change_pct"] = round((r["close"] - prev) / prev * 100, 4) if prev else None

    logger.info(f"[kline_daily] {stock_code} 解析完成，共 {len(records)} 条")
    return records


def _parse_one_record(item: dict) -> Optional[dict]:
    try:
        close  = _sf(item.get("close"))
        open_  = _sf(item.get("open"))
        if close is None or open_ is None:
            return None
        vol_raw = _sf(item.get("volume"))
        volume  = round(vol_raw / 100, 0) if vol_raw is not None else None
        # 成交额估算：手数 × 100股/手 × 收盘价 ÷ 1e8 = 手数 × 收盘价 ÷ 1e6
        amount_est = round(volume * close / 1e6, 4) if (volume and close) else None
        return {
            "date":       date.fromisoformat(item["day"]),
            "open":       open_,
            "high":       _sf(item.get("high")),
            "low":        _sf(item.get("low")),
            "close":      close,
            "volume":     volume,
            "amount_est": amount_est,
            "change_pct": None,  # 由 _parse_kline_json 填充
        }
    except (KeyError, ValueError, TypeError) as e:
        logger.debug(f"[kline_daily] 记录解析失败: {e} | {item}")
        return None


def _sf(val) -> Optional[float]:
    try:
        v = float(val)
        return round(v, 4) if v != 0 else None
    except (TypeError, ValueError):
        return None


# ── 存储 ──────────────────────────────────────────────────────────────────────

def save_kline_daily(stock_code: str, records: list[dict]):
    """每个交易日写一个独立文件"""
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
        amt = f"{r['amount_est']:.4f}（估）" if r["amount_est"] is not None else "N/A"
        row = [[
            str(d),
            f"{r['open']:.3f}"   if r["open"]   is not None else "N/A",
            f"{r['close']:.3f}"  if r["close"]  is not None else "N/A",
            f"{r['high']:.3f}"   if r["high"]   is not None else "N/A",
            f"{r['low']:.3f}"    if r["low"]    is not None else "N/A",
            f"{r['volume']:.0f}" if r["volume"] is not None else "N/A",
            amt,
            f"{r['change_pct']:+.2f}%" if r["change_pct"] is not None else "N/A",
        ]]
        content = (
            f"# {stock_code} 日K线 {d}\n\n"
            + rows_to_md_table(
                ["日期", "开盘", "收盘", "最高", "最低",
                 "成交量(手)", "成交额(亿)", "涨跌幅"],
                row
            )
        )
        write_md(kline_dir, date_to_filename(d), content)

    logger.info(f"[kline_daily] {stock_code} 写入完成，共 {len(records)} 个文件")


# ── 增量采集 ──────────────────────────────────────────────────────────────────

def fetch_and_save(
    stock_code: str,
    datalen: int = DEFAULT_DATALEN,
    skip_existing: bool = True,
):
    """采集并写入，skip_existing=True 时跳过已有日期（增量更新）"""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import STOCKS_DIR

    kline_dir = os.path.join(STOCKS_DIR, stock_code, "daily_kline")
    existing  = set()
    if skip_existing and os.path.exists(kline_dir):
        for fname in os.listdir(kline_dir):
            if fname.endswith(".md"):
                try:
                    existing.add(date(int(fname[:4]), int(fname[4:6]), int(fname[6:8])))
                except (ValueError, IndexError):
                    pass

    records = fetch_kline_daily(stock_code, datalen=datalen)
    if records is None:
        return

    if skip_existing:
        before  = len(records)
        records = [r for r in records if r["date"] not in existing]
        if before != len(records):
            logger.info(f"[kline_daily] {stock_code} 跳过 {before-len(records)} 个已存在文件")

    save_kline_daily(stock_code, records)


def run_batch(stock_codes: list[str], datalen: int = DEFAULT_DATALEN,
              batch_delay: float = 0.3):
    """批量采集多只股票的日K线"""
    success, failed = 0, []
    for i, code in enumerate(stock_codes, 1):
        try:
            fetch_and_save(code, datalen=datalen)
            success += 1
            if i % 50 == 0:
                logger.info(f"[kline_daily] 进度 {i}/{len(stock_codes)}")
        except Exception as e:
            failed.append(code)
            logger.error(f"[kline_daily] {code} 失败: {e}")
        time.sleep(batch_delay)
    logger.info(f"[kline_daily] 完成: 成功{success} 失败{len(failed)}")
    if failed:
        logger.warning(f"[kline_daily] 失败列表: {failed}")


def run(d: date = None):
    """每日入口：采集当日涨停股的日K线"""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import LIMIT_UP_DIR
    from storage.reader import parse_md_table, read_md_by_date

    if d is None:
        d = date.today()
    content = read_md_by_date(LIMIT_UP_DIR, d)
    if not content:
        logger.warning(f"[kline_daily] 未找到 {d} 涨停列表，跳过")
        return
    rows  = parse_md_table(content)
    codes = [r.get("代码") for r in rows if r.get("代码") and r.get("代码") != "N/A"]
    if not codes:
        return
    logger.info(f"[kline_daily] {d} 涨停股 {len(codes)} 只，开始采集")
    run_batch(codes, datalen=DEFAULT_DATALEN)
