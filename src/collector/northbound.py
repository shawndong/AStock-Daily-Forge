"""
采集层 — 北向资金
数据来源：AKShare stock_hsgt_fund_flow_summary_em
写入：data/market/northbound/YYYYMMDD.md

字段说明（来自 AKShare 源码）：
  板块        : 沪股通 / 深股通
  成交净买额  : 当日实际净买入（亿元）
  资金净流入  : 当日额度使用净流入（亿元，与成交净买额略有差异）
  当日资金余额: 剩余额度（亿元）
"""

import logging
import os
import time
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

# 最大重试次数和间隔（秒）
MAX_RETRIES = 3
RETRY_DELAY = 10

# 板块名称常量（与 AKShare 返回值一致）
BOARD_SHANGHAI = "沪股通"
BOARD_SHENZHEN = "深股通"


def fetch_northbound(target_date: date = None, retries: int = MAX_RETRIES) -> Optional[dict]:
    """
    双源获取北向资金：
      1) 主源：Tushare moneyflow_hsgt（需要 TUSHARE_TOKEN）
      2) 备源：AKShare stock_hsgt_fund_flow_summary_em

    :param target_date: 目标日期，默认今天
    :param retries:     最大重试次数
    :return: {
        "date":           date,
        "sh_net_buy":     float | None,  # 沪股通成交净买额（亿），None 表示数据缺失
        "sz_net_buy":     float | None,  # 深股通成交净买额（亿）
        "total_net_buy":  float | None,  # 北向合计
        "sh_quota_left":  float | None,  # 沪股通当日资金余额（亿）
        "sz_quota_left":  float | None,  # 深股通当日资金余额（亿）
        "data_available": bool           # False 表示数据源无数据（非交易日或接口异常）
    }
    失败时返回 None（网络异常且重试耗尽）
    """
    if target_date is None:
        target_date = date.today()

    tushare_data = _fetch_from_tushare(target_date)
    if tushare_data and tushare_data.get("data_available"):
        return tushare_data

    if tushare_data:
        logger.warning("[northbound] Tushare 无可用数据，回退 AKShare")
    else:
        logger.info("[northbound] Tushare 不可用或未配置，回退 AKShare")

    ak_data = _fetch_from_akshare(target_date, retries=retries)
    if ak_data is None:
        return None

    # 避免“接口异常全 0”误导下游模型
    if _looks_like_all_zero_anomaly(ak_data):
        ak_data["data_available"] = False
        ak_data["warning"] = "AKShare 返回核心资金字段全 0，疑似数据源异常，已标记不可用"
        logger.warning(f"[northbound] {target_date} 疑似异常全0，按不可用处理")
    return ak_data


def _base_result(target_date: date, source: str) -> dict:
    return {
        "date": target_date,
        "source": source,
        "sh_net_buy": None,
        "sz_net_buy": None,
        "total_net_buy": None,
        "sh_quota_left": None,
        "sz_quota_left": None,
        "data_available": False,
        "warning": None,
    }


def _fetch_from_tushare(target_date: date) -> Optional[dict]:
    """
    主源：Tushare moneyflow_hsgt
    文档单位通常为百万元，这里统一转换为“亿元”
    """
    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if not token:
        return None

    try:
        import pandas as pd
        import tushare as ts

        pro = ts.pro_api(token)
        trade_date = target_date.strftime("%Y%m%d")
        df = pro.moneyflow_hsgt(trade_date=trade_date)
        result = _base_result(target_date, source="tushare")

        if df is None or df.empty:
            result["warning"] = "Tushare 未返回当日北向资金数据"
            return result

        row = df.iloc[0]

        def get_num(key: str) -> Optional[float]:
            if key not in row.index:
                return None
            val = row[key]
            if pd.isna(val):
                return None
            # 百万元 -> 亿元
            return round(float(val) / 100.0, 2)

        result["sh_net_buy"] = get_num("hgt")
        result["sz_net_buy"] = get_num("sgt")

        north = get_num("north_money")
        if north is not None:
            result["total_net_buy"] = north
        elif result["sh_net_buy"] is not None and result["sz_net_buy"] is not None:
            result["total_net_buy"] = round(result["sh_net_buy"] + result["sz_net_buy"], 2)

        result["data_available"] = any(
            v is not None for v in [
                result["sh_net_buy"],
                result["sz_net_buy"],
                result["total_net_buy"],
            ]
        )
        if not result["data_available"]:
            result["warning"] = "Tushare 返回记录存在，但关键字段为空"
        return result
    except Exception as e:
        logger.warning(f"[northbound] Tushare 请求失败: {e}")
        return None


def _fetch_from_akshare(target_date: date, retries: int = MAX_RETRIES) -> Optional[dict]:
    """备源：AKShare stock_hsgt_fund_flow_summary_em"""
    import akshare as ak

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            logger.info(f"[northbound] AKShare 第 {attempt} 次请求...")
            df = ak.stock_hsgt_fund_flow_summary_em()
            result = _parse_northbound(df, target_date)
            result["source"] = "akshare"
            return result
        except Exception as e:
            last_error = e
            logger.warning(f"[northbound] AKShare 第 {attempt} 次请求失败: {e}")
            if attempt < retries:
                logger.info(f"[northbound] {RETRY_DELAY}s 后重试...")
                time.sleep(RETRY_DELAY)

    logger.error(f"[northbound] AKShare 重试 {retries} 次后仍失败: {last_error}")
    return None


def _parse_northbound(df, target_date: date) -> dict:
    """
    从 AKShare 返回的 DataFrame 中提取目标日期的数据

    AKShare 返回结构：
      每行代表某一天某个板块（沪股通/深股通）的资金情况
      数据已按日期降序排列，金额单位已转换为亿元
    """

    result = _base_result(target_date, source="akshare")

    if df is None or df.empty:
        logger.warning("[northbound] 接口返回空数据")
        return result

    _validate_columns(df)

    # 过滤目标日期（交易日 字段是 date 对象）
    day_df = df[df["交易日"] == target_date]

    if day_df.empty:
        logger.warning(f"[northbound] {target_date} 无数据（可能为非交易日或数据延迟）")
        return result

    result["data_available"] = True

    sh_row = day_df[day_df["板块"] == BOARD_SHANGHAI]
    sz_row = day_df[day_df["板块"] == BOARD_SHENZHEN]

    result["sh_net_buy"]    = _safe_float(sh_row, "成交净买额")
    result["sz_net_buy"]    = _safe_float(sz_row, "成交净买额")
    result["sh_quota_left"] = _safe_float(sh_row, "当日资金余额")
    result["sz_quota_left"] = _safe_float(sz_row, "当日资金余额")

    # 只有两个分项都有数据才合计，避免掩盖缺失
    if result["sh_net_buy"] is not None and result["sz_net_buy"] is not None:
        result["total_net_buy"] = round(result["sh_net_buy"] + result["sz_net_buy"], 2)

    return result


def _validate_columns(df):
    """校验 DataFrame 包含必需字段，字段变动时快速发现"""
    required = {"交易日", "板块", "成交净买额", "当日资金余额"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"[northbound] AKShare 返回字段缺失: {missing}，请检查接口是否变更")


def _looks_like_all_zero_anomaly(data: dict) -> bool:
    """
    识别疑似“数据源异常全0”。
    仅在 AKShare 路径生效，防止把 0.00 当成真实净流入。
    """
    nums = [
        data.get("sh_net_buy"),
        data.get("sz_net_buy"),
        data.get("total_net_buy"),
        data.get("sh_quota_left"),
        data.get("sz_quota_left"),
    ]
    vals = [v for v in nums if v is not None]
    return bool(vals) and all(v == 0 for v in vals)


def _safe_float(row_df, col: str) -> Optional[float]:
    """安全提取单行 DataFrame 中的浮点数，空行或 NaN 返回 None"""
    import pandas as pd
    if row_df.empty:
        return None
    val = row_df.iloc[0][col]
    if pd.isna(val):
        return None
    return round(float(val), 2)


# ── 存储 ──────────────────────────────────────────────────────────────────────

def save_northbound(data: dict):
    """
    将北向资金数据写入 md 文件
    data 为 fetch_northbound() 的返回值
    """
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import NORTHBOUND_DIR
    from storage.writer import date_to_filename, rows_to_md_table, write_md

    d = data["date"]

    if not data["data_available"]:
        warning = data.get("warning")
        source = data.get("source", "unknown")
        content = (
            f"# 北向资金 {d.strftime('%Y-%m-%d')}\n\n"
            f"> ⚠️ 当日无数据（非交易日或接口暂未更新）\n"
            + (f"> 数据源: {source}\n" if source else "")
            + (f"> 说明: {warning}\n" if warning else "")
        )
        write_md(NORTHBOUND_DIR, date_to_filename(d), content)
        logger.warning(f"[northbound] {d} 写入缺失标记")
        return

    def fmt(val):
        if val is None:
            return "N/A"
        prefix = "+" if val > 0 else ""
        return f"{prefix}{val:.2f}"

    rows = [
        ["沪股通成交净买额(亿)", fmt(data["sh_net_buy"])],
        ["深股通成交净买额(亿)", fmt(data["sz_net_buy"])],
        ["北向资金合计(亿)",     fmt(data["total_net_buy"])],
        ["沪股通当日余额(亿)",   fmt(data["sh_quota_left"])],
        ["深股通当日余额(亿)",   fmt(data["sz_quota_left"])],
    ]
    content = (
        f"# 北向资金 {d.strftime('%Y-%m-%d')}\n\n"
        + (f"> 数据源: {data.get('source', 'unknown')}\n\n")
        + rows_to_md_table(["指标", "数值"], rows)
    )
    write_md(NORTHBOUND_DIR, date_to_filename(d), content)
    logger.info(f"[northbound] {d} 已写入，合计: {fmt(data['total_net_buy'])} 亿")


# ── 入口 ──────────────────────────────────────────────────────────────────────

def run(d: date = None):
    if d is None:
        d = date.today()
    data = fetch_northbound(target_date=d)
    if data is None:
        logger.error(f"[northbound] {d} 采集失败，文件未写入")
        return
    save_northbound(data)
