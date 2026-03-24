#!/bin/bash

# Hunter 数据工程 — 项目初始化脚本
# 运行方式：bash setup_hunter_project.sh [目标路径]
# 示例：bash setup_hunter_project.sh ~/stock_data
# 数据目录（market/ stocks/ 等）必须已存在于目标路径下

ROOT="${1:-./stock_data}"

echo "正在初始化 Hunter 项目..."
echo "目标路径：$(realpath $ROOT 2>/dev/null || echo $ROOT)"
echo ""

# ── 创建程序目录（数据目录已存在，不重建）──
mkdir -p "$ROOT/collector"
mkdir -p "$ROOT/calculator"
mkdir -p "$ROOT/assembler"
mkdir -p "$ROOT/scheduler"
mkdir -p "$ROOT/storage"
mkdir -p "$ROOT/config"
mkdir -p "$ROOT/tests"
mkdir -p "$ROOT/logs"

# ════════════════════════════════════════
# config/
# ════════════════════════════════════════

cat > "$ROOT/config/__init__.py" << 'PYEOF'
PYEOF

cat > "$ROOT/config/settings.py" << 'PYEOF'
# Hunter 全局配置
# ⚠️  所有阈值固定在此处，不允许在业务代码中硬编码或随意修改

import os

# ── 路径 ──
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = BASE_DIR  # 数据目录即项目根目录

MARKET_QUOTE_DIR   = os.path.join(DATA_DIR, "market", "daily_quote")
LIMIT_UP_DIR       = os.path.join(DATA_DIR, "market", "limit_up")
NORTHBOUND_DIR     = os.path.join(DATA_DIR, "market", "northbound")
MARKET_STATE_DIR   = os.path.join(DATA_DIR, "market", "market_state")
LHB_DIR            = os.path.join(DATA_DIR, "lhb")
STOCKS_DIR         = os.path.join(DATA_DIR, "stocks")
CONCEPTS_DIR       = os.path.join(DATA_DIR, "concepts")
ASSEMBLED_DIR      = os.path.join(DATA_DIR, "assembled")

# ── 涨停 / 跌停判断阈值 ──
LIMIT_UP_RATIO   = 0.999   # close >= limit_up_price * LIMIT_UP_RATIO
LIMIT_DOWN_RATIO = 1.001   # close <= limit_down_price * LIMIT_DOWN_RATIO

# ── 高位股筛选条件 ──
HIGH_LEVEL_MIN_STREAK    = 3     # 连板数 >= 3
HIGH_LEVEL_MIN_CHANGE_5D = 0.25  # 5日涨幅 >= 25%

# ── 市场状态分类阈值 ──
STATE_CRASH_LIMIT_DOWN_RATIO  = 0.30  # 高位股跌停比例 >= 30% → 崩溃
STATE_RETREAT_BIG_DROP_RATIO  = 0.50  # 高位股大跌比例 >= 50% → 大回撤
BIG_DROP_THRESHOLD            = 0.05  # 跌幅 > 5% 视为大跌

# ── 主线识别阈值 ──
MAIN_THEME_MIN_COUNT = 5   # 概念出现涨停股数 >= 5 才视为主线

# ── 资金扩散强度 ──
SPREAD_STRONG_COUNT = 6    # 主线涨停数 >= 6 → 强
SPREAD_MID_COUNT    = 3    # 主线涨停数 >= 3 → 中

# ── 候选股池过滤 ──
MIN_AMOUNT = 3e8            # 成交额 >= 3亿

# ── 数据保留天数 ──
MINUTE_KLINE_KEEP_DAYS = 5  # 分钟线只保留最近5个交易日

# ── 日志 ──
LOG_DIR = os.path.join(BASE_DIR, "logs")
PYEOF

cat > "$ROOT/config/traders.py" << 'PYEOF'
# 已知游资席位名单
# 如需更新，在此处手动维护，不由采集层自动修改

KNOWN_TRADERS = [
    "章盟主",
    "方新侠",
    "作手新一",
    "赵老哥",
    "炒股养家",
    "宁波涨停板",
    "深股通",
    "沪股通",
]
PYEOF

# ════════════════════════════════════════
# storage/
# ════════════════════════════════════════

cat > "$ROOT/storage/__init__.py" << 'PYEOF'
PYEOF

cat > "$ROOT/storage/writer.py" << 'PYEOF'
"""
存储写入工具
所有 md 文件的写入操作统一在此处，业务层不直接操作文件
"""

import os
from datetime import date


def ensure_dir(path: str):
    """确保目录存在"""
    os.makedirs(path, exist_ok=True)


def date_to_filename(d: date) -> str:
    """date 对象 → 文件名，例如 20250110.md"""
    return d.strftime("%Y%m%d") + ".md"


def write_md(dir_path: str, filename: str, content: str, mode: str = "w"):
    """
    写入 md 文件
    :param dir_path: 目标目录
    :param filename: 文件名（含 .md）
    :param content:  文件内容
    :param mode:     'w' 覆盖写入，'a' 追加写入
    """
    ensure_dir(dir_path)
    file_path = os.path.join(dir_path, filename)
    with open(file_path, mode, encoding="utf-8") as f:
        f.write(content)
    return file_path


def rows_to_md_table(headers: list[str], rows: list[list]) -> str:
    """
    将列表数据转换为 Markdown 表格字符串
    :param headers: 表头列表
    :param rows:    数据行列表（每行是一个列表）
    :return: Markdown 表格字符串
    """
    header_row = "| " + " | ".join(headers) + " |"
    separator  = "| " + " | ".join(["---"] * len(headers)) + " |"
    data_rows  = [
        "| " + " | ".join(str(cell) if cell is not None else "N/A" for cell in row) + " |"
        for row in rows
    ]
    return "\n".join([header_row, separator] + data_rows) + "\n"
PYEOF

cat > "$ROOT/storage/reader.py" << 'PYEOF'
"""
存储读取工具
所有 md 文件的读取操作统一在此处
"""

import os
import re
from datetime import date, timedelta


def date_to_filename(d: date) -> str:
    return d.strftime("%Y%m%d") + ".md"


def read_md(dir_path: str, filename: str) -> str | None:
    """
    读取 md 文件，文件不存在时返回 None
    """
    file_path = os.path.join(dir_path, filename)
    if not os.path.exists(file_path):
        return None
    with open(file_path, encoding="utf-8") as f:
        return f.read()


def read_md_by_date(dir_path: str, d: date) -> str | None:
    """按日期读取 md 文件"""
    return read_md(dir_path, date_to_filename(d))


def read_recent_mds(dir_path: str, n: int, end_date: date = None) -> list[tuple[date, str]]:
    """
    读取最近 n 个交易日的 md 文件（从目录中已存在的文件推断）
    :return: [(date, content), ...] 按日期升序排列，跳过不存在的文件
    """
    if end_date is None:
        end_date = date.today()

    results = []
    d = end_date
    while len(results) < n and d >= end_date - timedelta(days=60):
        content = read_md_by_date(dir_path, d)
        if content is not None:
            results.append((d, content))
        d -= timedelta(days=1)

    return list(reversed(results))


def parse_md_table(content: str, section: str = None) -> list[dict]:
    """
    解析 md 文件中的表格为字典列表
    :param content: md 文件内容
    :param section: 如果指定，只解析该 ## 标题下的第一个表格
    :return: [{"列名": "值", ...}, ...]
    """
    if section:
        pattern = rf"##\s+{re.escape(section)}\n(.*?)(?=\n##|\Z)"
        match = re.search(pattern, content, re.DOTALL)
        content = match.group(1) if match else ""

    lines = [l.strip() for l in content.strip().splitlines()]
    table_lines = [l for l in lines if l.startswith("|")]

    if len(table_lines) < 2:
        return []

    headers = [h.strip() for h in table_lines[0].strip("|").split("|")]
    rows = []
    for line in table_lines[2:]:  # 跳过分隔行
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))

    return rows


def list_stock_dirs(stocks_dir: str) -> list[str]:
    """列出 stocks/ 下所有有效的股票代码目录"""
    if not os.path.exists(stocks_dir):
        return []
    return [
        d for d in os.listdir(stocks_dir)
        if os.path.isdir(os.path.join(stocks_dir, d))
        and not d.startswith(".")
    ]
PYEOF

# ════════════════════════════════════════
# collector/
# ════════════════════════════════════════

cat > "$ROOT/collector/__init__.py" << 'PYEOF'
PYEOF

cat > "$ROOT/collector/market_quote.py" << 'PYEOF'
"""
采集层 — 全市场行情汇总
数据来源：sina-realtime / tencent-realtime（通过 OpenClaw）
写入：data/market/daily_quote/YYYYMMDD.md
"""

from datetime import date
from config.settings import MARKET_QUOTE_DIR
from storage.writer import write_md, date_to_filename, rows_to_md_table


def fetch_market_quote() -> dict:
    """
    从行情接口获取全市场汇总数据
    TODO: 接入 OpenClaw tencent-realtime / sina-realtime
    :return: {
        "limit_up": int,
        "limit_down": int,
        "up_count": int,
        "down_count": int,
        "total_amount": float,  # 单位：亿
        "northbound_net": float,
        "stocks": [{"code": str, "name": str, "open": float, "high": float,
                    "low": float, "close": float, "pre_close": float,
                    "volume": float, "amount": float,
                    "limit_up_price": float, "limit_down_price": float}, ...]
    }
    """
    raise NotImplementedError("TODO: 接入行情接口")


def save_market_quote(data: dict, d: date = None):
    """将市场行情数据写入 md 文件"""
    if d is None:
        d = date.today()

    summary_rows = [
        ["涨停数量",       data.get("limit_up",       "N/A")],
        ["跌停数量",       data.get("limit_down",      "N/A")],
        ["上涨家数",       data.get("up_count",        "N/A")],
        ["下跌家数",       data.get("down_count",      "N/A")],
        ["全市场成交额(亿)", data.get("total_amount",   "N/A")],
        ["北向净买入(亿)",  data.get("northbound_net", "N/A")],
    ]
    summary_table = rows_to_md_table(["指标", "数值"], summary_rows)

    stock_rows = [
        [s["code"], s["name"], s.get("close", "N/A"),
         s.get("amount", "N/A"), s.get("change_pct", "N/A")]
        for s in data.get("stocks", [])
    ]
    stock_table = rows_to_md_table(
        ["股票代码", "股票名称", "收盘价", "成交额(亿)", "涨跌幅%"],
        stock_rows
    )

    content = f"# 市场行情汇总 {d.strftime('%Y-%m-%d')}\n\n"
    content += "## 核心指标\n" + summary_table + "\n"
    content += "## 个股行情\n" + stock_table

    write_md(MARKET_QUOTE_DIR, date_to_filename(d), content)
    print(f"[market_quote] 已写入 {d}")


def run(d: date = None):
    data = fetch_market_quote()
    save_market_quote(data, d)
PYEOF

cat > "$ROOT/collector/limit_up.py" << 'PYEOF'
"""
采集层 — 涨停股列表
数据来源：全市场行情过滤（stock_zt_pool_em 补充后优先使用）
写入：data/market/limit_up/YYYYMMDD.md
"""

from datetime import date
from config.settings import LIMIT_UP_DIR, MARKET_QUOTE_DIR, LIMIT_UP_RATIO
from storage.writer import write_md, date_to_filename, rows_to_md_table
from storage.reader import read_md_by_date, parse_md_table


def extract_limit_up_from_quote(d: date = None) -> list[dict]:
    """
    从已存储的当日行情文件中过滤出涨停股
    TODO: 优先接入 stock_zt_pool_em 专题接口以获得更准确的数据
    """
    if d is None:
        d = date.today()

    content = read_md_by_date(MARKET_QUOTE_DIR, d)
    if not content:
        print(f"[limit_up] 未找到 {d} 的行情数据，请先运行 market_quote.py")
        return []

    stocks = parse_md_table(content, section="个股行情")
    # TODO: 需要行情数据包含 limit_up_price 字段才能精确判断
    # 当前仅作占位，接入专题接口后替换
    raise NotImplementedError("TODO: 接入 stock_zt_pool_em 涨停专题接口")


def save_limit_up(stocks: list[dict], d: date = None):
    """将涨停股列表写入 md 文件"""
    if d is None:
        d = date.today()

    rows = [
        [s.get("code", "N/A"), s.get("name", "N/A"),
         s.get("streak", "N/A"), s.get("concepts", "N/A"),
         s.get("amount", "N/A")]
        for s in stocks
    ]
    table = rows_to_md_table(
        ["股票代码", "股票名称", "连板数", "所属概念", "成交额(亿)"],
        rows
    )
    content = f"# 涨停股列表 {d.strftime('%Y-%m-%d')}\n\n" + table
    write_md(LIMIT_UP_DIR, date_to_filename(d), content)
    print(f"[limit_up] 已写入 {d}，共 {len(stocks)} 只")


def run(d: date = None):
    stocks = extract_limit_up_from_quote(d)
    save_limit_up(stocks, d)
PYEOF

cat > "$ROOT/collector/northbound.py" << 'PYEOF'
"""
采集层 — 北向资金
数据来源：eastmoney-northbound（AKShare）
写入：data/market/northbound/YYYYMMDD.md
"""

from datetime import date
from config.settings import NORTHBOUND_DIR
from storage.writer import write_md, date_to_filename, rows_to_md_table


def fetch_northbound() -> dict:
    """
    从接口获取北向资金数据
    TODO: 接入 OpenClaw eastmoney-northbound
    :return: {
        "shanghai_net": float,  # 沪股通净买入（亿）
        "shenzhen_net": float,  # 深股通净买入（亿）
        "total_net": float      # 合计
    }
    """
    raise NotImplementedError("TODO: 接入 eastmoney-northbound")


def save_northbound(data: dict, d: date = None):
    if d is None:
        d = date.today()

    total = data.get("total_net") or (
        (data.get("shanghai_net") or 0) + (data.get("shenzhen_net") or 0)
    )
    rows = [
        ["沪股通净买入(亿)", data.get("shanghai_net", "N/A")],
        ["深股通净买入(亿)", data.get("shenzhen_net", "N/A")],
        ["北向资金合计(亿)", round(total, 2) if isinstance(total, float) else "N/A"],
    ]
    content = f"# 北向资金 {d.strftime('%Y-%m-%d')}\n\n"
    content += rows_to_md_table(["指标", "数值"], rows)
    write_md(NORTHBOUND_DIR, date_to_filename(d), content)
    print(f"[northbound] 已写入 {d}")


def run(d: date = None):
    data = fetch_northbound()
    save_northbound(data, d)
PYEOF

cat > "$ROOT/collector/lhb.py" << 'PYEOF'
"""
采集层 — 龙虎榜
数据来源：eastmoney-lhb（AKShare）
写入：data/lhb/YYYYMMDD.md
"""

from datetime import date
from config.settings import LHB_DIR
from storage.writer import write_md, date_to_filename, rows_to_md_table


def fetch_lhb(d: date = None) -> list[dict]:
    """
    获取龙虎榜数据
    TODO: 接入 OpenClaw eastmoney-lhb
    :return: [{
        "code": str,
        "name": str,
        "buy_seats": list[str],   # 买入席位（前5）
        "sell_seats": list[str],  # 卖出席位（前5）
        "net_buy": float          # 净买入（万元）
    }, ...]
    """
    raise NotImplementedError("TODO: 接入 eastmoney-lhb")


def save_lhb(records: list[dict], d: date = None):
    if d is None:
        d = date.today()

    rows = [
        [r.get("code", "N/A"),
         r.get("name", "N/A"),
         "、".join(r.get("buy_seats", [])) or "N/A",
         "、".join(r.get("sell_seats", [])) or "N/A",
         r.get("net_buy", "N/A")]
        for r in records
    ]
    table = rows_to_md_table(
        ["股票代码", "股票名称", "买入席位", "卖出席位", "净买入(万)"],
        rows
    )
    content = f"# 龙虎榜 {d.strftime('%Y-%m-%d')}\n\n" + table
    write_md(LHB_DIR, date_to_filename(d), content)
    print(f"[lhb] 已写入 {d}，共 {len(records)} 条")


def run(d: date = None):
    records = fetch_lhb(d)
    save_lhb(records, d)
PYEOF

cat > "$ROOT/collector/kline_daily.py" << 'PYEOF'
"""
采集层 — 个股日K线
数据来源：AKShare stock_zh_a_hist（需补充接入）
写入：data/stocks/{code}/daily_kline/YYYYMMDD.md（追加模式）
"""

import os
from datetime import date
from config.settings import STOCKS_DIR
from storage.writer import write_md, date_to_filename, rows_to_md_table


def fetch_kline_daily(stock_code: str, d: date = None) -> dict:
    """
    获取个股当日日K数据
    TODO: 接入 AKShare stock_zh_a_hist
    :return: {
        "code": str, "date": str,
        "open": float, "high": float, "low": float, "close": float,
        "pre_close": float, "volume": float, "amount": float,
        "change_pct": float,
        "limit_up_price": float, "limit_down_price": float
    }
    """
    raise NotImplementedError("TODO: 接入 AKShare stock_zh_a_hist")


def save_kline_daily(stock_code: str, data: dict, d: date = None):
    """追加写入当日日K数据到该股的 daily_kline 文件"""
    if d is None:
        d = date.today()

    kline_dir = os.path.join(STOCKS_DIR, stock_code, "daily_kline")
    filename = date_to_filename(d)
    file_path = os.path.join(kline_dir, filename)

    row = [[
        data.get("date", d.strftime("%Y-%m-%d")),
        data.get("open", "N/A"), data.get("high", "N/A"),
        data.get("low", "N/A"),  data.get("close", "N/A"),
        data.get("volume", "N/A"), data.get("amount", "N/A"),
        data.get("change_pct", "N/A"),
        data.get("limit_up_price", "N/A"), data.get("limit_down_price", "N/A"),
    ]]

    # 文件不存在时写入表头，否则追加数据行
    if not os.path.exists(file_path):
        content = f"# {stock_code} 日K线数据\n\n"
        content += rows_to_md_table(
            ["日期", "开盘", "最高", "最低", "收盘", "成交量(万)", "成交额(亿)", "涨跌幅%", "涨停价", "跌停价"],
            row
        )
        write_md(kline_dir, filename, content, mode="w")
    else:
        data_line = "| " + " | ".join(str(v) for v in row[0]) + " |\n"
        write_md(kline_dir, filename, data_line, mode="a")

    print(f"[kline_daily] {stock_code} {d} 已写入")


def run(stock_codes: list[str], d: date = None):
    for code in stock_codes:
        try:
            data = fetch_kline_daily(code, d)
            save_kline_daily(code, data, d)
        except Exception as e:
            print(f"[kline_daily] {code} 失败: {e}")
PYEOF

cat > "$ROOT/collector/kline_minute.py" << 'PYEOF'
"""
采集层 — 个股分钟线
数据来源：AKShare stock_zh_a_hist_min_em（需补充接入）
写入：data/stocks/{code}/minute_kline/YYYYMMDD.md
只保留最近 MINUTE_KLINE_KEEP_DAYS 个交易日，旧文件自动清理
"""

import os
from datetime import date
from config.settings import STOCKS_DIR, MINUTE_KLINE_KEEP_DAYS
from storage.writer import write_md, date_to_filename, rows_to_md_table


def fetch_kline_minute(stock_code: str, d: date = None) -> list[dict]:
    """
    获取个股当日分钟线数据
    TODO: 接入 AKShare stock_zh_a_hist_min_em
    :return: [{"time": str, "open": float, "high": float,
               "low": float, "close": float, "volume": float}, ...]
    """
    raise NotImplementedError("TODO: 接入 AKShare stock_zh_a_hist_min_em")


def cleanup_old_minute_klines(stock_code: str, keep_days: int = MINUTE_KLINE_KEEP_DAYS):
    """删除超出保留天数的分钟线文件"""
    minute_dir = os.path.join(STOCKS_DIR, stock_code, "minute_kline")
    if not os.path.exists(minute_dir):
        return
    files = sorted([f for f in os.listdir(minute_dir) if f.endswith(".md")])
    for old_file in files[:-keep_days]:
        os.remove(os.path.join(minute_dir, old_file))
        print(f"[kline_minute] 清理旧文件: {old_file}")


def save_kline_minute(stock_code: str, records: list[dict], d: date = None):
    if d is None:
        d = date.today()

    minute_dir = os.path.join(STOCKS_DIR, stock_code, "minute_kline")
    rows = [
        [r.get("time", "N/A"), r.get("open", "N/A"), r.get("high", "N/A"),
         r.get("low", "N/A"), r.get("close", "N/A"), r.get("volume", "N/A")]
        for r in records
    ]
    content = f"# {stock_code} 分钟线 {d.strftime('%Y-%m-%d')}\n\n"
    content += rows_to_md_table(["时间", "开盘", "最高", "最低", "收盘", "成交量"], rows)
    write_md(minute_dir, date_to_filename(d), content)
    cleanup_old_minute_klines(stock_code)
    print(f"[kline_minute] {stock_code} {d} 已写入，共 {len(records)} 条")


def run(stock_codes: list[str], d: date = None):
    for code in stock_codes:
        try:
            records = fetch_kline_minute(code, d)
            save_kline_minute(code, records, d)
        except Exception as e:
            print(f"[kline_minute] {code} 失败: {e}")
PYEOF

cat > "$ROOT/collector/concepts.py" << 'PYEOF'
"""
采集层 — 题材概念映射
数据来源：AKShare stock_board_concept_name_em（需补充接入）
写入：data/concepts/stock_concept_map.md（全量覆盖，周更）
"""

from config.settings import CONCEPTS_DIR
from storage.writer import write_md, rows_to_md_table
import os


def fetch_concept_map() -> list[dict]:
    """
    获取全市场股票→概念映射
    TODO: 接入 AKShare stock_board_concept_name_em
    :return: [{"code": str, "name": str, "concepts": ["概念A", "概念B"]}, ...]
    """
    raise NotImplementedError("TODO: 接入 AKShare stock_board_concept_name_em")


def save_concept_map(records: list[dict]):
    rows = [
        [r["code"], r["name"], "、".join(r.get("concepts", []))]
        for r in records
    ]
    table = rows_to_md_table(["股票代码", "股票名称", "所属概念"], rows)
    content = "# 股票概念映射表\n\n"
    content += "> 由采集脚本自动生成，每周更新\n\n"
    content += table
    write_md(CONCEPTS_DIR, "stock_concept_map.md", content)
    print(f"[concepts] 概念映射已写入，共 {len(records)} 只股票")


def run():
    records = fetch_concept_map()
    save_concept_map(records)
PYEOF

# ════════════════════════════════════════
# calculator/
# ════════════════════════════════════════

cat > "$ROOT/calculator/__init__.py" << 'PYEOF'
PYEOF

cat > "$ROOT/calculator/streak.py" << 'PYEOF'
"""
计算层 — 连板数计算
依赖：data/stocks/{code}/daily_kline/
输出：int（连板天数）
"""

from datetime import date
from config.settings import STOCKS_DIR, LIMIT_UP_RATIO
from storage.reader import read_recent_mds, parse_md_table
import os


def calc_streak(stock_code: str, as_of: date = None) -> int:
    """
    计算指定股票截至 as_of 日期的当前连板数
    从最新一天向前遍历，直到非涨停日为止
    """
    if as_of is None:
        as_of = date.today()

    kline_dir = os.path.join(STOCKS_DIR, stock_code, "daily_kline")
    recent = read_recent_mds(kline_dir, n=15, end_date=as_of)

    streak = 0
    for d, content in reversed(recent):
        rows = parse_md_table(content)
        if not rows:
            break
        # 取最后一行（当日数据）
        row = rows[-1]
        try:
            close = float(row.get("收盘", 0))
            limit_up_price = float(row.get("涨停价", 0))
        except (ValueError, TypeError):
            break

        if limit_up_price > 0 and close >= limit_up_price * LIMIT_UP_RATIO:
            streak += 1
        else:
            break

    return streak


def calc_all_streaks(as_of: date = None) -> dict[str, int]:
    """
    计算所有股票的连板数
    :return: {"股票代码": 连板数, ...}
    """
    from storage.reader import list_stock_dirs
    from config.settings import STOCKS_DIR

    result = {}
    for code in list_stock_dirs(STOCKS_DIR):
        result[code] = calc_streak(code, as_of)
    return result
PYEOF

cat > "$ROOT/calculator/high_level.py" << 'PYEOF'
"""
计算层 — 高位股筛选
依赖：data/stocks/*/derived/ 中的连板数和5日涨幅
输出：高位股列表
"""

from datetime import date
from config.settings import (
    STOCKS_DIR, HIGH_LEVEL_MIN_STREAK, HIGH_LEVEL_MIN_CHANGE_5D
)
from storage.reader import read_md_by_date, parse_md_table, list_stock_dirs
import os


def get_5d_change(stock_code: str, as_of: date = None) -> float | None:
    """从日K线文件中计算5日涨幅"""
    from config.settings import STOCKS_DIR
    from storage.reader import read_recent_mds

    kline_dir = os.path.join(STOCKS_DIR, stock_code, "daily_kline")
    recent = read_recent_mds(kline_dir, n=6, end_date=as_of)

    if len(recent) < 6:
        return None
    try:
        rows_start = parse_md_table(recent[0][1])
        rows_end   = parse_md_table(recent[-1][1])
        close_start = float(rows_start[-1]["收盘"])
        close_end   = float(rows_end[-1]["收盘"])
        return (close_end - close_start) / close_start
    except Exception:
        return None


def filter_high_level(as_of: date = None) -> list[dict]:
    """
    筛选高位股：连板数 >= HIGH_LEVEL_MIN_STREAK 或 5日涨幅 >= HIGH_LEVEL_MIN_CHANGE_5D
    :return: [{"code": str, "streak": int, "change_5d": float}, ...]
    """
    if as_of is None:
        as_of = date.today()

    from calculator.streak import calc_streak
    result = []

    for code in list_stock_dirs(STOCKS_DIR):
        streak   = calc_streak(code, as_of)
        change5d = get_5d_change(code, as_of)

        is_high = (
            streak >= HIGH_LEVEL_MIN_STREAK or
            (change5d is not None and change5d >= HIGH_LEVEL_MIN_CHANGE_5D)
        )
        if is_high:
            result.append({
                "code":      code,
                "streak":    streak,
                "change_5d": round(change5d, 4) if change5d else None,
            })

    return result
PYEOF

cat > "$ROOT/calculator/main_theme.py" << 'PYEOF'
"""
计算层 — 主线识别 & 龙头识别
依赖：data/market/limit_up/、data/concepts/stock_concept_map.md
"""

from datetime import date
from collections import defaultdict
from config.settings import (
    LIMIT_UP_DIR, CONCEPTS_DIR, MAIN_THEME_MIN_COUNT,
    SPREAD_STRONG_COUNT, SPREAD_MID_COUNT
)
from storage.reader import read_md_by_date, parse_md_table, read_md


def load_concept_map() -> dict[str, list[str]]:
    """加载股票→概念映射，返回 {code: [概念, ...]}"""
    import os
    content = read_md(CONCEPTS_DIR, "stock_concept_map.md")
    if not content:
        return {}
    rows = parse_md_table(content)
    return {
        r["股票代码"]: r.get("所属概念", "").split("、")
        for r in rows if "股票代码" in r
    }


def identify_main_themes(d: date = None) -> list[str]:
    """
    识别当日主线题材
    :return: 涨停股数量 >= MAIN_THEME_MIN_COUNT 的概念列表
    """
    if d is None:
        d = date.today()

    content = read_md_by_date(LIMIT_UP_DIR, d)
    if not content:
        return []

    limit_up_stocks = parse_md_table(content)
    concept_map = load_concept_map()

    concept_count = defaultdict(int)
    for stock in limit_up_stocks:
        code = stock.get("股票代码", "")
        for concept in concept_map.get(code, []):
            if concept.strip():
                concept_count[concept.strip()] += 1

    return [c for c, cnt in concept_count.items() if cnt >= MAIN_THEME_MIN_COUNT]


def identify_leader(main_themes: list[str], d: date = None) -> str | None:
    """
    识别龙头：主线概念中连板数最高、成交额最大的股票
    """
    if d is None:
        d = date.today()

    content = read_md_by_date(LIMIT_UP_DIR, d)
    if not content or not main_themes:
        return None

    concept_map = load_concept_map()
    limit_up_stocks = parse_md_table(content)

    candidates = []
    for stock in limit_up_stocks:
        code = stock.get("股票代码", "")
        concepts = concept_map.get(code, [])
        if any(t in concepts for t in main_themes):
            try:
                streak = int(stock.get("连板数", 0))
                amount = float(stock.get("成交额(亿)", 0))
            except ValueError:
                streak, amount = 0, 0
            candidates.append((code, streak, amount))

    if not candidates:
        return None

    leader = max(candidates, key=lambda x: (x[1], x[2]))
    return leader[0]


def calc_spread_strength(main_themes: list[str], d: date = None) -> str:
    """计算主线资金扩散强度：强 / 中 / 弱"""
    if d is None:
        d = date.today()

    content = read_md_by_date(LIMIT_UP_DIR, d)
    if not content or not main_themes:
        return "弱"

    concept_map = load_concept_map()
    limit_up_stocks = parse_md_table(content)

    count = sum(
        1 for s in limit_up_stocks
        if any(t in concept_map.get(s.get("股票代码", ""), []) for t in main_themes)
    )

    if count >= SPREAD_STRONG_COUNT:
        return "强"
    elif count >= SPREAD_MID_COUNT:
        return "中"
    return "弱"
PYEOF

cat > "$ROOT/calculator/market_state.py" << 'PYEOF'
"""
计算层 — 市场状态评分
依赖：data/market/limit_up/、calculator/high_level.py
写入：data/market/market_state/YYYYMMDD.md
"""

from datetime import date
from config.settings import (
    MARKET_STATE_DIR, BIG_DROP_THRESHOLD,
    STATE_CRASH_LIMIT_DOWN_RATIO, STATE_RETREAT_BIG_DROP_RATIO
)
from storage.writer import write_md, date_to_filename, rows_to_md_table
from calculator.high_level import filter_high_level
from calculator.main_theme import identify_main_themes, identify_leader, calc_spread_strength
from calculator.streak import calc_all_streaks


def classify_market_state(high_level_stocks: list[dict]) -> str:
    """
    根据高位股状态分类市场状态
    规则（按优先级）：
      跌停比例 >= 30%         → 崩溃
      大跌(>5%)比例 >= 50%    → 大回撤
      存在涨停 且 存在大跌     → 分歧
      其余                    → 强势
    """
    total = len(high_level_stocks)
    if total == 0:
        return "无高位股"

    limit_down_count = sum(1 for s in high_level_stocks if s.get("is_limit_down"))
    big_drop_count   = sum(1 for s in high_level_stocks if s.get("change_pct", 0) < -BIG_DROP_THRESHOLD)
    limit_up_count   = sum(1 for s in high_level_stocks if s.get("is_limit_up"))

    if limit_down_count / total >= STATE_CRASH_LIMIT_DOWN_RATIO:
        return "崩溃"
    if big_drop_count / total >= STATE_RETREAT_BIG_DROP_RATIO:
        return "大回撤"
    if limit_up_count > 0 and big_drop_count > 0:
        return "分歧"
    return "强势"


def run(d: date = None):
    if d is None:
        d = date.today()

    high_level   = filter_high_level(d)
    all_streaks  = calc_all_streaks(d)
    max_streak   = max(all_streaks.values(), default=0)
    state        = classify_market_state(high_level)
    main_themes  = identify_main_themes(d)
    leader       = identify_leader(main_themes, d)
    spread       = calc_spread_strength(main_themes, d)

    rows = [
        ["最大连板高度",      max_streak],
        ["高位股总数",        len(high_level)],
        ["市场状态",          state],
        ["主线概念",          "、".join(main_themes) if main_themes else "N/A"],
        ["龙头股票",          leader or "N/A"],
        ["资金扩散强度",      spread],
    ]
    content = f"# 市场状态 {d.strftime('%Y-%m-%d')}\n\n"
    content += rows_to_md_table(["指标", "值"], rows)
    write_md(MARKET_STATE_DIR, date_to_filename(d), content)
    print(f"[market_state] {d} 市场状态：{state}，主线：{main_themes}")
PYEOF

cat > "$ROOT/calculator/stock_derived.py" << 'PYEOF'
"""
计算层 — 个股衍生指标
依赖：daily_kline、lhb、concepts
写入：data/stocks/{code}/derived/YYYYMMDD.md
"""

import os
from datetime import date
from config.settings import STOCKS_DIR, LHB_DIR
from storage.reader import read_md_by_date, parse_md_table, list_stock_dirs
from storage.writer import write_md, date_to_filename, rows_to_md_table
from calculator.streak import calc_streak
from calculator.high_level import get_5d_change
from calculator.main_theme import identify_main_themes, load_concept_map
from config.traders import KNOWN_TRADERS


def check_trader_in_lhb(stock_code: str, d: date) -> bool:
    """检查该股当日龙虎榜是否有已知游资席位"""
    content = read_md_by_date(LHB_DIR, d)
    if not content:
        return False
    rows = parse_md_table(content)
    for row in rows:
        if row.get("股票代码") == stock_code:
            buy_seats = row.get("买入席位", "")
            for trader in KNOWN_TRADERS:
                if trader in buy_seats:
                    return True
    return False


def get_market_position(stock_code: str, main_themes: list[str], d: date) -> str:
    """判断个股在主线板块中的地位：龙头 / 次龙头 / 补涨 / 非主线"""
    from calculator.main_theme import identify_leader

    concept_map = load_concept_map()
    stock_concepts = concept_map.get(stock_code, [])

    if not any(t in stock_concepts for t in main_themes):
        return "非主线"

    leader = identify_leader(main_themes, d)
    if leader == stock_code:
        return "龙头"

    streak = calc_streak(stock_code, d)
    if streak >= 2:
        return "次龙头"
    return "补涨"


def calc_stock_derived(stock_code: str, d: date = None):
    """计算并写入单只股票的衍生指标"""
    if d is None:
        d = date.today()

    streak      = calc_streak(stock_code, d)
    change_5d   = get_5d_change(stock_code, d)
    main_themes = identify_main_themes(d)
    has_trader  = check_trader_in_lhb(stock_code, d)
    position    = get_market_position(stock_code, main_themes, d)

    concept_map     = load_concept_map()
    stock_concepts  = concept_map.get(stock_code, [])

    rows = [
        ["当前连板数",   streak],
        ["5日涨幅%",    f"{change_5d * 100:.2f}" if change_5d else "N/A"],
        ["所属主线",    "、".join([c for c in stock_concepts if c in main_themes]) or "N/A"],
        ["游资介入",    "是" if has_trader else "否"],
        ["市场地位",    position],
    ]
    derived_dir = os.path.join(STOCKS_DIR, stock_code, "derived")
    content = f"# {stock_code} 衍生指标 {d.strftime('%Y-%m-%d')}\n\n"
    content += rows_to_md_table(["指标", "值", "说明"], [r + [""] for r in rows])
    write_md(derived_dir, date_to_filename(d), content)
    print(f"[stock_derived] {stock_code} {d} 已写入")


def run(d: date = None):
    for code in list_stock_dirs(STOCKS_DIR):
        try:
            calc_stock_derived(code, d)
        except Exception as e:
            print(f"[stock_derived] {code} 失败: {e}")
PYEOF

# ════════════════════════════════════════
# assembler/
# ════════════════════════════════════════

cat > "$ROOT/assembler/__init__.py" << 'PYEOF'
PYEOF

cat > "$ROOT/assembler/market_pack.py" << 'PYEOF'
"""
汇总层 — 市场分析数据包
读取多个数据文件，组装为可直接传给大模型的提示词数据包
写入：data/assembled/market/YYYYMMDD.md
"""

from datetime import date, timedelta
from config.settings import (
    MARKET_QUOTE_DIR, LIMIT_UP_DIR, NORTHBOUND_DIR,
    MARKET_STATE_DIR, ASSEMBLED_DIR
)
from storage.reader import read_md_by_date, read_recent_mds
from storage.writer import write_md, date_to_filename
import os


def assemble_market_pack(d: date = None) -> str:
    """
    组装市场分析数据包
    :return: 完整的 markdown 字符串（可直接作为提示词的一部分）
    """
    if d is None:
        d = date.today()

    sections = [f"# 市场分析数据包 {d.strftime('%Y-%m-%d')}\n"]
    sections.append("> 以下数据供大模型分析当日市场整体动向\n")

    # 1. 市场状态
    state_content = read_md_by_date(MARKET_STATE_DIR, d)
    sections.append("\n## 一、市场状态\n")
    sections.append(state_content if state_content else "_数据缺失 (N/A)_\n")

    # 2. 涨停股列表
    limit_up_content = read_md_by_date(LIMIT_UP_DIR, d)
    sections.append("\n## 二、当日涨停股\n")
    sections.append(limit_up_content if limit_up_content else "_数据缺失 (N/A)_\n")

    # 3. 市场行情汇总
    quote_content = read_md_by_date(MARKET_QUOTE_DIR, d)
    sections.append("\n## 三、市场行情汇总\n")
    sections.append(quote_content if quote_content else "_数据缺失 (N/A)_\n")

    # 4. 北向资金
    nb_content = read_md_by_date(NORTHBOUND_DIR, d)
    sections.append("\n## 四、北向资金\n")
    sections.append(nb_content if nb_content else "_数据缺失 (N/A)_\n")

    # 5. 近5日市场状态对比
    sections.append("\n## 五、近5日市场状态趋势\n")
    recent = read_recent_mds(MARKET_STATE_DIR, n=5, end_date=d)
    for rd, rc in recent:
        sections.append(f"**{rd.strftime('%Y-%m-%d')}**\n{rc}\n")

    return "\n".join(sections)


def run(d: date = None):
    if d is None:
        d = date.today()

    content = assemble_market_pack(d)
    assembled_market_dir = os.path.join(ASSEMBLED_DIR, "market")
    write_md(assembled_market_dir, date_to_filename(d), content)
    print(f"[market_pack] 市场数据包已生成：{d}")
PYEOF

cat > "$ROOT/assembler/stock_pack.py" << 'PYEOF'
"""
汇总层 — 个股分析数据包
读取多个数据文件，组装为可直接传给大模型的提示词数据包
写入：data/assembled/stocks/{code}_YYYYMMDD.md
"""

import os
from datetime import date
from config.settings import STOCKS_DIR, LHB_DIR, ASSEMBLED_DIR
from storage.reader import read_recent_mds, read_md_by_date, parse_md_table
from storage.writer import write_md


def assemble_stock_pack(stock_code: str, d: date = None) -> str:
    """
    组装个股分析数据包
    :return: 完整的 markdown 字符串
    """
    if d is None:
        d = date.today()

    sections = [f"# {stock_code} 个股分析数据包 {d.strftime('%Y-%m-%d')}\n"]
    sections.append("> 以下数据供大模型分析该股走势\n")

    # 1. 最新衍生指标
    derived_dir = os.path.join(STOCKS_DIR, stock_code, "derived")
    derived = read_md_by_date(derived_dir, d)
    sections.append("\n## 一、最新衍生指标\n")
    sections.append(derived if derived else "_数据缺失 (N/A)_\n")

    # 2. 近1个月日K线（取最近30条）
    kline_dir = os.path.join(STOCKS_DIR, stock_code, "daily_kline")
    recent_klines = read_recent_mds(kline_dir, n=30, end_date=d)
    sections.append("\n## 二、近1个月日K线\n")
    if recent_klines:
        # 合并所有日K行（跳过每个文件的标题和表头，只取数据行）
        all_rows = []
        for _, content in recent_klines:
            rows = parse_md_table(content)
            all_rows.extend(rows)
        # 重新组装为一张表
        if all_rows:
            headers = list(all_rows[0].keys())
            from storage.writer import rows_to_md_table
            data = [[row.get(h, "N/A") for h in headers] for row in all_rows]
            sections.append(rows_to_md_table(headers, data))
    else:
        sections.append("_数据缺失 (N/A)_\n")

    # 3. 近5日分钟线
    minute_dir = os.path.join(STOCKS_DIR, stock_code, "minute_kline")
    recent_minutes = read_recent_mds(minute_dir, n=5, end_date=d)
    sections.append("\n## 三、近5日分钟线\n")
    for md, mc in recent_minutes:
        sections.append(f"**{md.strftime('%Y-%m-%d')}**\n{mc}\n")
    if not recent_minutes:
        sections.append("_数据缺失 (N/A)_\n")

    # 4. 近5日龙虎榜
    sections.append("\n## 四、近5日龙虎榜\n")
    recent_lhb = read_recent_mds(LHB_DIR, n=5, end_date=d)
    found_lhb = False
    for ld, lc in recent_lhb:
        rows = parse_md_table(lc)
        stock_rows = [r for r in rows if r.get("股票代码") == stock_code]
        if stock_rows:
            found_lhb = True
            from storage.writer import rows_to_md_table
            headers = list(stock_rows[0].keys())
            data = [[r.get(h, "N/A") for h in headers] for r in stock_rows]
            sections.append(f"**{ld.strftime('%Y-%m-%d')}**\n")
            sections.append(rows_to_md_table(headers, data) + "\n")
    if not found_lhb:
        sections.append("_近5日无龙虎榜记录_\n")

    return "\n".join(sections)


def run(stock_code: str, d: date = None):
    if d is None:
        d = date.today()

    content = assemble_stock_pack(stock_code, d)
    assembled_stocks_dir = os.path.join(ASSEMBLED_DIR, "stocks")
    filename = f"{stock_code}_{d.strftime('%Y%m%d')}.md"
    write_md(assembled_stocks_dir, filename, content)
    print(f"[stock_pack] {stock_code} 数据包已生成：{d}")
PYEOF

# ════════════════════════════════════════
# scheduler/
# ════════════════════════════════════════

cat > "$ROOT/scheduler/__init__.py" << 'PYEOF'
PYEOF

cat > "$ROOT/scheduler/daily_jobs.py" << 'PYEOF'
"""
定时任务定义
各任务的执行时间和调用入口
"""

from datetime import date

# 任务按执行顺序排列
# 每个任务：(时间字符串, 描述, 可调用函数)

def job_concepts():
    from collector.concepts import run
    run()

def job_market_quote():
    from collector.market_quote import run
    run()

def job_northbound():
    from collector.northbound import run
    run()

def job_limit_up():
    from collector.limit_up import run
    run()

def job_market_state():
    from calculator.market_state import run
    run()

def job_kline_minute(stock_codes: list[str]):
    from collector.kline_minute import run
    run(stock_codes)

def job_lhb():
    from collector.lhb import run
    run()

def job_stock_derived():
    from calculator.stock_derived import run
    run()

def job_assemble_market():
    from assembler.market_pack import run
    run()


# 时序配置（供 runner.py 使用）
SCHEDULE = [
    ("09:00", "题材概念更新（周一执行）", job_concepts),
    ("15:05", "全市场行情采集",           job_market_quote),
    ("15:06", "北向资金采集",             job_northbound),
    ("15:10", "涨停列表 + 市场状态计算",  lambda: (job_limit_up(), job_market_state())),
    ("15:30", "分钟线采集",               lambda: job_kline_minute([])),  # TODO: 传入监控股票列表
    ("16:00", "龙虎榜采集",               job_lhb),
    ("16:30", "个股衍生指标计算",         job_stock_derived),
    ("17:00", "市场数据包组装",           job_assemble_market),
]
PYEOF

cat > "$ROOT/scheduler/runner.py" << 'PYEOF'
"""
任务调度入口
使用 schedule 库实现定时执行
安装：pip install schedule
"""

import schedule
import time
import logging
import os
from datetime import datetime
from config.settings import LOG_DIR
from scheduler.daily_jobs import SCHEDULE

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "runner.log"), encoding="utf-8"),
        logging.StreamHandler()
    ]
)


def wrap_job(name: str, fn):
    """包装任务，捕获异常并记录日志"""
    def wrapped():
        logging.info(f"开始执行：{name}")
        try:
            fn()
            logging.info(f"完成：{name}")
        except NotImplementedError:
            logging.warning(f"跳过（未实现）：{name}")
        except Exception as e:
            logging.error(f"失败：{name} — {e}", exc_info=True)
    return wrapped


def register_jobs():
    for time_str, name, fn in SCHEDULE:
        schedule.every().day.at(time_str).do(wrap_job(name, fn))
        logging.info(f"已注册任务 [{time_str}] {name}")


if __name__ == "__main__":
    logging.info("Hunter 调度器启动")
    register_jobs()
    while True:
        schedule.run_pending()
        time.sleep(30)
PYEOF

# ════════════════════════════════════════
# tests/
# ════════════════════════════════════════

cat > "$ROOT/tests/__init__.py" << 'PYEOF'
PYEOF

cat > "$ROOT/tests/test_calculator.py" << 'PYEOF'
"""
计算层单元测试
重点覆盖纯函数逻辑（不依赖外部接口）
"""

import pytest
from calculator.market_state import classify_market_state


def test_classify_market_state_crash():
    stocks = [{"is_limit_down": True}] * 4 + [{"is_limit_down": False}] * 6
    assert classify_market_state(stocks) == "崩溃"


def test_classify_market_state_retreat():
    stocks = [{"change_pct": -0.06}] * 6 + [{"change_pct": 0.02}] * 4
    assert classify_market_state(stocks) == "大回撤"


def test_classify_market_state_diverge():
    stocks = [
        {"is_limit_up": True,  "change_pct": 0.10},
        {"is_limit_down": False, "change_pct": -0.06},
    ]
    assert classify_market_state(stocks) == "分歧"


def test_classify_market_state_strong():
    stocks = [{"is_limit_up": True, "change_pct": 0.10}] * 5
    assert classify_market_state(stocks) == "强势"


def test_classify_market_state_empty():
    assert classify_market_state([]) == "无高位股"
PYEOF

cat > "$ROOT/tests/test_assembler.py" << 'PYEOF'
"""
汇总层测试（基于 mock 数据）
"""

import pytest
from unittest.mock import patch
from datetime import date


def test_market_pack_missing_data():
    """当数据文件不存在时，汇总包应包含缺失标记而非崩溃"""
    with patch("assembler.market_pack.read_md_by_date", return_value=None), \
         patch("assembler.market_pack.read_recent_mds", return_value=[]):
        from assembler.market_pack import assemble_market_pack
        result = assemble_market_pack(date(2025, 1, 10))
        assert "N/A" in result or "数据缺失" in result


def test_stock_pack_no_lhb():
    """无龙虎榜记录时应有明确说明"""
    with patch("assembler.stock_pack.read_recent_mds", return_value=[]), \
         patch("assembler.stock_pack.read_md_by_date", return_value=None):
        from assembler.stock_pack import assemble_stock_pack
        result = assemble_stock_pack("300001", date(2025, 1, 10))
        assert "无龙虎榜记录" in result
PYEOF

# ════════════════════════════════════════
# 根目录文件
# ════════════════════════════════════════

cat > "$ROOT/main.py" << 'PYEOF'
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
            print(f"  ⚠️  未实现，跳过")
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
PYEOF

cat > "$ROOT/requirements.txt" << 'EOF'
schedule>=1.2.0
pytest>=7.0.0
EOF

cat > "$ROOT/README.md" << 'EOF'
# Hunter 数据工程

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 初始化数据目录
bash setup_hunter_data.sh ./data

# 手动运行完整流水线（补数据用）
python main.py --full --date 20250110

# 生成指定个股数据包
python main.py --stock 300001

# 启动定时调度器
python scheduler/runner.py
```

## 目录说明

| 目录 | 职责 |
|------|------|
| collector/ | 采集层，对接 OpenClaw 接口 |
| calculator/ | 计算层，衍生指标计算 |
| assembler/ | 汇总层，组装提示词数据包 |
| scheduler/ | 定时任务调度 |
| storage/ | 文件读写工具 |
| config/ | 全局配置和阈值 |
| tests/ | 单元测试 |
| data/ | 数据存储目录 |
| logs/ | 运行日志 |

## 接入新数据源

1. 在对应的 `collector/` 文件中找到 `raise NotImplementedError` 的函数
2. 实现 `fetch_*` 方法，调用 OpenClaw 相应 Skill
3. 运行 `pytest tests/` 确保计算层测试通过

## 重要规则

- 所有阈值在 `config/settings.py` 中统一维护，不得在业务代码中硬编码
- 数据缺失时写入 `N/A`，严禁伪造
- 游资席位名单在 `config/traders.py` 中人工维护
EOF

# ── 完成提示 ──
echo ""
echo "项目骨架创建完成！"
echo ""
echo "目录结构："
find "$ROOT" -name "*.py" -o -name "*.txt" -o -name "*.md" | grep -v __pycache__ | sort | sed "s|$ROOT/||" | awk -F'/' '{
  indent=""
  for(i=1;i<NF;i++) indent=indent"  "
  print indent"└── "$NF
}'
echo ""
echo "下一步："
echo "  1. cd $ROOT"
echo "  2. pip install -r requirements.txt"
echo "  3. 在 collector/ 各文件中实现 fetch_* 方法，接入 OpenClaw"
echo "  4. python main.py --full  （测试流水线）"
echo "  5. python scheduler/runner.py  （启动定时调度）"
