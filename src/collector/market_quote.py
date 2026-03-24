"""
采集层 — 全市场行情
数据来源：
  - 股票代码列表：AKShare stock_info_a_code_name()
  - 实时行情：腾讯接口 qt.gtimg.cn（curl + subprocess，绕过代理）

腾讯接口字段索引（~分隔）：
  f[1]  股票名称    f[2]  股票代码    f[3]  现价
  f[4]  昨收        f[5]  今开        f[31] 涨跌额
  f[32] 涨跌幅%     f[33] 最高        f[34] 最低
  f[36] 成交量(手)  f[37] 成交额(万)  f[38] 换手率%

写入：
  data/market/daily_quote/YYYYMMDD.md
  data/market/limit_up/YYYYMMDD.md
  data/market/limit_down/YYYYMMDD.md
"""

import logging
import subprocess
import time
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────────

TENCENT_URL   = "https://qt.gtimg.cn/q={symbols}"
BATCH_SIZE    = 50      # 每次请求股票数量
BATCH_DELAY   = 0.5     # 批次间隔（秒），避免被封
MAX_RETRIES   = 3
RETRY_DELAY   = 5

# 涨跌停幅度
NORMAL_LIMIT  = 0.10    # 普通股 ±10%
ST_LIMIT      = 0.05    # ST股   ±5%

# 涨跌停判断容差（处理浮点和撮合误差）
LIMIT_TOLERANCE = 0.0005


# ── 市场前缀 ──────────────────────────────────────────────────────────────────

def to_tencent_symbol(code: str) -> str:
    """股票代码转腾讯格式，如 000001 → sz000001"""
    if code.startswith(("000", "002", "003", "300", "301")):
        return f"sz{code}"
    elif code.startswith(("600", "601", "603", "605", "688", "689")):
        return f"sh{code}"
    elif code.startswith(("430", "830", "831", "832", "833", "834", "835",
                          "836", "837", "838", "839", "870", "871", "872",
                          "873", "874", "875", "876", "877", "878", "879")):
        return f"bj{code}"
    else:
        return f"sz{code}"  # 默认深市


# ── 代码列表 ──────────────────────────────────────────────────────────────────

def fetch_stock_list() -> list[dict]:
    """
    从 AKShare 获取全量 A 股代码列表
    :return: [{"code": "000001", "name": "平安银行"}, ...]
    """
    import akshare as ak
    df = ak.stock_info_a_code_name()
    return [{"code": row["code"], "name": row["name"]} for _, row in df.iterrows()]


# ── 腾讯行情解析 ──────────────────────────────────────────────────────────────

def _fetch_tencent_batch(symbols: list[str], retries: int = MAX_RETRIES) -> str:
    """
    用 curl + subprocess 查询一批腾讯行情数据
    :param symbols: 腾讯格式代码列表，如 ["sz000001", "sh600000"]
    :return: 原始响应文本（gbk 解码后）
    """
    url = TENCENT_URL.format(symbols=",".join(symbols))
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            result = subprocess.run(
                ["curl", "-s", "--max-time", "10", url],
                capture_output=True
            )
            if result.returncode != 0:
                raise RuntimeError(f"curl 返回码 {result.returncode}: {result.stderr.decode()}")
            return result.stdout.decode("gbk", errors="replace")
        except Exception as e:
            last_error = e
            logger.warning(f"[market_quote] 批次请求失败（第{attempt}次）: {e}")
            if attempt < retries:
                time.sleep(RETRY_DELAY)

    raise RuntimeError(f"批次请求重试 {retries} 次后仍失败: {last_error}")


def _parse_tencent_line(line: str, name_hint: str = "") -> Optional[dict]:
    """
    解析腾讯接口单行数据
    :return: 股票数据字典，数据不完整时返回 None
    """
    if "~" not in line:
        return None

    try:
        raw = line.split("=", 1)[1].strip().strip('"').strip("'").rstrip(";")
        f = raw.split("~")

        if len(f) < 45:
            return None

        name      = f[1].strip() or name_hint
        code      = f[2].strip()
        close     = _to_float(f[3])
        pre_close = _to_float(f[4])
        open_     = _to_float(f[5])
        high      = _to_float(f[33])
        low       = _to_float(f[34])
        volume    = _to_float(f[36])       # 手
        amount_wan = _to_float(f[37])      # 万元
        change_pct = _to_float(f[32])      # 涨跌幅 %

        if close is None or pre_close is None or pre_close == 0:
            return None

        amount_yi = round(amount_wan / 10000, 4) if amount_wan is not None else None

        # 判断是否 ST
        is_st = "ST" in name.upper()
        limit_rate = ST_LIMIT if is_st else NORMAL_LIMIT

        # 计算涨跌停价（精确到分）
        limit_up_price   = _calc_limit_price(pre_close, 1 + limit_rate)
        limit_down_price = _calc_limit_price(pre_close, 1 - limit_rate)

        # 涨跌停判断
        is_limit_up   = (close is not None and
                         limit_up_price is not None and
                         close >= limit_up_price * (1 - LIMIT_TOLERANCE))
        is_limit_down = (close is not None and
                         limit_down_price is not None and
                         close <= limit_down_price * (1 + LIMIT_TOLERANCE))

        return {
            "code":             code,
            "name":             name,
            "open":             open_,
            "high":             high,
            "low":              low,
            "close":            close,
            "pre_close":        pre_close,
            "change_pct":       change_pct,
            "volume":           volume,
            "amount":           amount_yi,
            "limit_up_price":   limit_up_price,
            "limit_down_price": limit_down_price,
            "is_limit_up":      is_limit_up,
            "is_limit_down":    is_limit_down,
            "is_st":            is_st,
        }
    except Exception as e:
        logger.debug(f"[market_quote] 解析行失败: {e} | 原始: {line[:80]}")
        return None


def _to_float(val: str) -> Optional[float]:
    """安全转换字符串为浮点数"""
    try:
        v = float(val.strip())
        return v if v != 0.0 else None
    except (ValueError, AttributeError):
        return None


def _calc_limit_price(pre_close: float, rate: float) -> float:
    """
    计算涨跌停价
    A 股规则：(昨收 × 倍率) 四舍五入到分
    """
    return round(pre_close * rate, 2)


# ── 全市场采集主逻辑 ──────────────────────────────────────────────────────────

def fetch_market_quote(stock_list: list[dict] = None) -> list[dict]:
    """
    采集全市场行情
    :param stock_list: 股票列表，为 None 时自动从 AKShare 获取
    :return: 所有股票的行情字典列表
    """
    if stock_list is None:
        logger.info("[market_quote] 获取股票代码列表...")
        stock_list = fetch_stock_list()
        logger.info(f"[market_quote] 共 {len(stock_list)} 只股票")

    name_map = {s["code"]: s["name"] for s in stock_list}
    symbols  = [to_tencent_symbol(s["code"]) for s in stock_list]

    # 分批查询
    batches = [symbols[i:i + BATCH_SIZE] for i in range(0, len(symbols), BATCH_SIZE)]
    all_stocks = []
    failed_batches = 0

    for idx, batch in enumerate(batches, 1):
        try:
            raw = _fetch_tencent_batch(batch)
            for line in raw.strip().splitlines():
                line = line.strip()
                if not line or "~" not in line:
                    continue
                # 从行首提取代码，用于查 name_map
                code_raw = line.split("~")[2].strip() if "~" in line else ""
                stock = _parse_tencent_line(line, name_hint=name_map.get(code_raw, ""))
                if stock:
                    all_stocks.append(stock)

            if idx % 20 == 0:
                logger.info(f"[market_quote] 进度 {idx}/{len(batches)} 批，已解析 {len(all_stocks)} 只")

        except Exception as e:
            failed_batches += 1
            logger.error(f"[market_quote] 第 {idx} 批失败，跳过: {e}")

        time.sleep(BATCH_DELAY)

    logger.info(f"[market_quote] 采集完成，共 {len(all_stocks)} 只，失败批次 {failed_batches}")
    return all_stocks


# ── 统计汇总 ──────────────────────────────────────────────────────────────────

def summarize(stocks: list[dict]) -> dict:
    """计算全市场统计汇总"""
    valid = [s for s in stocks if s.get("close") and s.get("pre_close")]

    up_count      = sum(1 for s in valid if (s.get("change_pct") or 0) > 0)
    down_count    = sum(1 for s in valid if (s.get("change_pct") or 0) < 0)
    flat_count    = sum(1 for s in valid if (s.get("change_pct") or 0) == 0)
    limit_up_cnt  = sum(1 for s in valid if s.get("is_limit_up"))
    limit_down_cnt= sum(1 for s in valid if s.get("is_limit_down"))
    total_amount  = sum(s["amount"] for s in valid if s.get("amount"))

    return {
        "total":        len(valid),
        "up_count":     up_count,
        "down_count":   down_count,
        "flat_count":   flat_count,
        "limit_up":     limit_up_cnt,
        "limit_down":   limit_down_cnt,
        "total_amount": round(total_amount, 2),
    }


# ── 存储 ──────────────────────────────────────────────────────────────────────

def save_market_quote(stocks: list[dict], d: date = None):
    """写入全市场行情汇总和涨跌停列表"""
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import MARKET_QUOTE_DIR, MARKET_QUOTE_LIMIT_UP_SNAPSHOT_DIR
    from storage.writer import date_to_filename, rows_to_md_table, write_md

    if d is None:
        d = date.today()

    summary = summarize(stocks)

    # ── 1. 市场行情汇总 ──
    summary_rows = [
        ["涨停数量",       summary["limit_up"]],
        ["跌停数量",       summary["limit_down"]],
        ["上涨家数",       summary["up_count"]],
        ["下跌家数",       summary["down_count"]],
        ["平盘家数",       summary["flat_count"]],
        ["全市场成交额(亿)", f"{summary['total_amount']:.2f}"],
    ]

    # 所有股票明细（按涨跌幅降序）
    sorted_stocks = sorted(stocks, key=lambda x: x.get("change_pct") or 0, reverse=True)
    stock_rows = [
        [s["code"], s["name"],
         f"{s['close']:.3f}" if s.get("close") else "N/A",
         f"{s['change_pct']:+.2f}%" if s.get("change_pct") is not None else "N/A",
         f"{s['amount']:.2f}" if s.get("amount") else "N/A",
         "✓" if s.get("is_limit_up") else "",
         "✓" if s.get("is_limit_down") else ""]
        for s in sorted_stocks
    ]

    content = (
        f"# 市场行情汇总 {d.strftime('%Y-%m-%d')}\n\n"
        "## 核心指标\n"
        + rows_to_md_table(["指标", "数值"], summary_rows)
        + "\n## 个股明细\n"
        + rows_to_md_table(
            ["股票代码", "股票名称", "收盘价", "涨跌幅", "成交额(亿)", "涨停", "跌停"],
            stock_rows
        )
    )
    write_md(MARKET_QUOTE_DIR, date_to_filename(d), content)
    logger.info(f"[market_quote] 行情汇总已写入 {d}")

    # ── 2. 涨停股列表 ──
    limit_up_stocks = [s for s in stocks if s.get("is_limit_up")]
    lu_rows = [
        [s["code"], s["name"],
         f"{s['close']:.3f}" if s.get("close") else "N/A",
         f"{s['amount']:.2f}" if s.get("amount") else "N/A"]
        for s in sorted(limit_up_stocks, key=lambda x: x.get("amount") or 0, reverse=True)
    ]
    lu_content = (
        f"# 涨停股列表 {d.strftime('%Y-%m-%d')}\n\n"
        f"> 共 {len(limit_up_stocks)} 只\n\n"
        + rows_to_md_table(["股票代码", "股票名称", "收盘价", "成交额(亿)"], lu_rows)
    )
    write_md(MARKET_QUOTE_LIMIT_UP_SNAPSHOT_DIR, date_to_filename(d), lu_content)
    logger.info(f"[market_quote] 涨停快照已写入，共 {len(limit_up_stocks)} 只")


# ── 入口 ──────────────────────────────────────────────────────────────────────

def run(d: date = None):
    if d is None:
        d = date.today()
    stocks = fetch_market_quote()
    if not stocks:
        logger.error("[market_quote] 未采集到任何数据")
        return
    save_market_quote(stocks, d)

