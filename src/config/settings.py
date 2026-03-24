# Hunter 全局配置
# ⚠️  所有阈值固定在此处，不允许在业务代码中硬编码或随意修改

import os

# ── 路径 ──
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = BASE_DIR  # 数据目录即项目根目录

MARKET_QUOTE_DIR   = os.path.join(DATA_DIR, "market", "daily_quote")
LIMIT_UP_DIR       = os.path.join(DATA_DIR, "market", "limit_up")
# market_quote 的简版涨停快照目录，避免覆盖 limit_up.py 的完整版文件
MARKET_QUOTE_LIMIT_UP_SNAPSHOT_DIR = os.path.join(DATA_DIR, "market", "limit_up_snapshot")
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

# ── Assembler 输出模式 ──
# per_stock: 每只股票输出一个文件（现有默认）
# single_file: 当日所有个股打包到一个文件，显著减少文件数
STOCK_PACK_OUTPUT_MODE = "per_stock"

# ── 日志 ──
LOG_DIR = os.path.join(BASE_DIR, "logs")
