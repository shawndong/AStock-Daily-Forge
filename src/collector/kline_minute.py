"""
采集层 — 个股分钟线
数据来源：新浪财经 CN_MarketData.getKLineData（curl + subprocess）
写入：data/stocks/{code}/minute_kline/YYYYMMDD.md

接口说明：
  URL: https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData
  参数：
    symbol  : 市场前缀+代码，如 sz000001 / sh600000
    scale   : 分钟周期，5=5分钟（固定）
    ma      : no（不需要均线）
    datalen : 返回条数，240=近5个交易日（固定）
  返回：JSON 数组，字段：day, open, high, low, close, volume
  成交额：接口不提供，记为 N/A
  成交量单位：股（÷100 = 手）

保留策略：
  每个交易日写一个文件，保留最近 KEEP_DAYS 个文件
  旧文件在写入新文件后自动清理
"""

import json
import logging
import os
import subprocess
import time
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)

SINA_URL     = (
    "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
    "/CN_MarketData.getKLineData"
    "?symbol={symbol}&scale=5&ma=no&datalen=240"
)
REFERER      = "https://finance.sina.com.cn"
KEEP_DAYS    = 5
MAX_RETRIES  = 3
RETRY_DELAY  = 5


# ── 市场前缀 ──────────────────────────────────────────────────────────────────

def to_sina_symbol(code: str) -> str:
    """股票代码转新浪格式，如 000001 → sz000001"""
    if code.startswith(("6",)):
        return f"sh{code}"
    return f"sz{code}"


# ── 采集 ──────────────────────────────────────────────────────────────────────

def fetch_kline_minute(
    stock_code: str,
    retries: int = MAX_RETRIES,
) -> Optional[list[dict]]:
    """
    获取个股近5个交易日的5分钟线数据

    :param stock_code: 股票代码，如 "000001"
    :param retries:    最大重试次数
    :return: 分钟线记录列表（按时间升序），失败返回 None
    每条记录字段：
      datetime : datetime 对象
      open     : float
      high     : float
      low      : float
      close    : float
      volume   : float（手，已÷100）
    """
    symbol = to_sina_symbol(stock_code)
    url    = SINA_URL.format(symbol=symbol)
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            logger.info(f"[kline_minute] {stock_code} 第{attempt}次请求")
            result = subprocess.run(
                ["curl", "-s", "--max-time", "15", url,
                 "-H", f"Referer: {REFERER}"],
                capture_output=True,
                timeout=20,
            )
            if result.returncode != 0:
                raise RuntimeError(f"curl 返回码 {result.returncode}")

            raw = result.stdout.decode("utf-8", errors="replace").strip()
            return _parse_minute_json(raw, stock_code)

        except Exception as e:
            last_error = e
            logger.warning(f"[kline_minute] {stock_code} 第{attempt}次失败: {e}")
            if attempt < retries:
                time.sleep(RETRY_DELAY)

    logger.error(f"[kline_minute] {stock_code} 重试{retries}次后仍失败: {last_error}")
    return None


def _parse_minute_json(raw: str, stock_code: str) -> list[dict]:
    """
    解析新浪接口返回的 JSON 数据
    :return: 按时间升序排列的分钟线记录列表
    """
    if not raw or raw.startswith("/*"):
        logger.warning(f"[kline_minute] {stock_code} 接口返回异常: {raw[:100]}")
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"[kline_minute] {stock_code} JSON 解析失败: {e} | 原始: {raw[:200]}")
        return []

    if not isinstance(data, list):
        logger.warning(f"[kline_minute] {stock_code} 返回格式非列表: {type(data)}")
        return []

    records = []
    for item in data:
        parsed = _parse_one_record(item, stock_code)
        if parsed:
            records.append(parsed)

    logger.info(f"[kline_minute] {stock_code} 解析完成，共 {len(records)} 条")
    return records


def _parse_one_record(item: dict, stock_code: str) -> Optional[dict]:
    """解析单条分钟线记录，字段缺失或格式错误时返回 None"""
    try:
        dt_str = item.get("day", "")
        dt     = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        return {
            "datetime": dt,
            "date":     dt.date(),
            "open":     _safe_float(item.get("open")),
            "high":     _safe_float(item.get("high")),
            "low":      _safe_float(item.get("low")),
            "close":    _safe_float(item.get("close")),
            "volume":   _safe_volume(item.get("volume")),
        }
    except (ValueError, AttributeError) as e:
        logger.debug(f"[kline_minute] 记录解析失败: {e} | {item}")
        return None


def _safe_float(val) -> Optional[float]:
    try:
        return round(float(val), 4) if val is not None else None
    except (ValueError, TypeError):
        return None


def _safe_volume(val) -> Optional[float]:
    """成交量：股 → 手（÷100），保留整数"""
    v = _safe_float(val)
    return round(v / 100, 0) if v is not None else None


# ── 按日期分组 ────────────────────────────────────────────────────────────────

def group_by_date(records: list[dict]) -> dict[date, list[dict]]:
    """将分钟线记录按交易日分组"""
    groups: dict[date, list[dict]] = {}
    for r in records:
        d = r["date"]
        groups.setdefault(d, []).append(r)
    return groups


# ── 存储 ──────────────────────────────────────────────────────────────────────

def save_kline_minute(stock_code: str, records: list[dict]):
    """
    将分钟线数据按日期写入独立文件，并清理超出 KEEP_DAYS 的旧文件
    文件路径：data/stocks/{code}/minute_kline/YYYYMMDD.md
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import STOCKS_DIR
    from storage.writer import date_to_filename, rows_to_md_table, write_md

    if not records:
        logger.warning(f"[kline_minute] {stock_code} 无数据，跳过写入")
        return

    minute_dir = os.path.join(STOCKS_DIR, stock_code, "minute_kline")
    groups     = group_by_date(records)

    for d, day_records in sorted(groups.items()):
        rows = [
            [
                r["datetime"].strftime("%H:%M"),
                f"{r['open']:.3f}"   if r["open"]   is not None else "N/A",
                f"{r['high']:.3f}"   if r["high"]   is not None else "N/A",
                f"{r['low']:.3f}"    if r["low"]    is not None else "N/A",
                f"{r['close']:.3f}"  if r["close"]  is not None else "N/A",
                f"{r['volume']:.0f}" if r["volume"]  is not None else "N/A",
            ]
            for r in day_records
        ]
        content = (
            f"# {stock_code} 5分钟线 {d}\n\n"
            f"> 共 {len(day_records)} 条，成交量单位：手\n\n"
            + rows_to_md_table(
                ["时间", "开盘", "最高", "最低", "收盘", "成交量(手)"],
                rows
            )
        )
        write_md(minute_dir, date_to_filename(d), content)
        logger.info(f"[kline_minute] {stock_code} {d} 写入 {len(day_records)} 条")

    _cleanup_old_files(minute_dir, keep=KEEP_DAYS)


def _cleanup_old_files(minute_dir: str, keep: int = KEEP_DAYS):
    """删除超出保留天数的旧文件，保留最新的 keep 个"""
    if not os.path.exists(minute_dir):
        return
    files = sorted(
        [f for f in os.listdir(minute_dir) if f.endswith(".md")]
    )
    to_delete = files[:-keep] if len(files) > keep else []
    for fname in to_delete:
        fpath = os.path.join(minute_dir, fname)
        os.remove(fpath)
        logger.info(f"[kline_minute] 清理旧文件: {fname}")


# ── 入口 ──────────────────────────────────────────────────────────────────────

def run(stock_codes: list[str], batch_delay: float = 0.3):
    """
    批量采集多只股票的分钟线
    :param stock_codes:  股票代码列表
    :param batch_delay:  每只之间的间隔（秒）
    """
    total   = len(stock_codes)
    success = 0
    failed  = []

    for i, code in enumerate(stock_codes, 1):
        try:
            records = fetch_kline_minute(code)
            if records is None:
                failed.append(code)
            else:
                save_kline_minute(code, records)
                success += 1
            if i % 20 == 0:
                logger.info(f"[kline_minute] 进度 {i}/{total}")
        except Exception as e:
            failed.append(code)
            logger.error(f"[kline_minute] {code} 异常: {e}")
        time.sleep(batch_delay)

    logger.info(f"[kline_minute] 完成: 成功 {success}，失败 {len(failed)}")
    if failed:
        logger.warning(f"[kline_minute] 失败列表: {failed}")
