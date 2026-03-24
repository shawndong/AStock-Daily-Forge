# AStock-Daily-Forge — 完整技术文档

> Technical Design · Data Dictionary · Operations Manual · API Reference  
> v1.1 | 2026-03-24

---

## 目录

- [第一部分 技术架构与设计文档](#第一部分-技术架构与设计文档)
  - [1. 系统架构概述](#1-系统架构概述)
  - [2. 模块功能说明](#2-模块功能说明)
  - [3. 本版更新摘要（v1.1）](#3-本版更新摘要v11)
- [第二部分 数据字典与模型文档](#第二部分-数据字典与模型文档)
  - [4. 数据源清单](#4-数据源清单)
  - [5. 数据文件结构（Schema）](#5-数据文件结构schema)
  - [6. 加工逻辑（Lineage）](#6-加工逻辑lineage)
- [第三部分 运维与部署手册](#第三部分-运维与部署手册)
  - [7. 环境搭建指南](#7-环境搭建指南)
  - [8. 任务调度说明](#8-任务调度说明)
  - [9. 监控与日志](#9-监控与日志)
- [第四部分 接口与使用文档](#第四部分-接口与使用文档)
  - [10. 命令行接口（CLI）](#10-命令行接口cli)
  - [11. 配置参数完整说明](#11-配置参数完整说明)
  - [12. 输出示例与下游LLM对接建议](#12-输出示例与下游llm对接建议)

---

# 第一部分 技术架构与设计文档

## 1. 系统架构概述

AStock-Daily-Forge 采用四层流水线架构，将 A 股市场数据从采集到提示词数据包组装的过程标准化、自动化。系统在交易日按 cron 定时运行，通常在 21:00 启动，并在约 30 分钟窗口内完成全流程（含慢接口缓冲），供次日分析模型使用。

### 1.1 整体数据流向

| 层级 | 名称 | 说明 | 写入位置 |
| --- | --- | --- | --- |
| 第一层 | 数据源层 | AKShare / 新浪财经 / 腾讯行情等外部数据源 | 外部接口 |
| 第二层 | 采集层（Collector） | 拉取并清洗数据，写入 Markdown 文件 | `market/`、`stocks/`、`lhb/`、`concepts/` |
| 第三层 | 计算层（Calculator） | 计算连板、高位股、主线、市场状态与个股衍生指标 | `market/market_state/`、`stocks/*/derived/` |
| 第四层 | 汇总层（Assembler） | 组装市场与个股分析数据包供 LLM 直接消费 | `assembled/` |

### 1.2 数据流向详图

```text
外部数据源                     采集层                    存储层
─────────────────────────────────────────────────────────────────────
AKShare                        northbound.py    →   market/northbound/
  └─ stock_hsgt_fund_flow      limit_up.py      →   market/limit_up/  ⭐
  └─ stock_zt_pool_em          lhb.py           →   lhb/
  └─ stock_lhb_detail_em       kline_daily.py   →   stocks/*/daily_kline/

新浪财经                        kline_minute.py  →   stocks/*/minute_kline/
  └─ CN_MarketData (scale=240) concepts.py      →   concepts/
  └─ CN_MarketData (scale=5)

腾讯行情                        market_quote.py  →   market/daily_quote/
  └─ qt.gtimg.cn（curl批量）    market_quote.py  →   market/limit_up_snapshot/

         ↓ 采集完成

      计算层                         汇总层
─────────────────────────────────────────────────────────────────────
streak.py       （连板数查询）        market_pack.py → assembled/market/
high_level.py   （高位股筛选）        stock_pack.py  → assembled/stocks/
main_theme.py   （主线识别）
market_state.py → market/market_state/
stock_derived.py→ stocks/*/derived/
```

## 2. 模块功能说明

### 2.1 采集层（collector/）

| 模块文件 | 功能定义 | 数据来源 | 输出目录 |
| --- | --- | --- | --- |
| `northbound.py` | 采集沪深股通净买入和余额 | AKShare | `market/northbound/` |
| `market_quote.py` | 采集全市场行情、统计涨跌停与市场摘要 | 腾讯行情 | `market/daily_quote/` + `market/limit_up_snapshot/` |
| `limit_up.py` | 采集当日涨停股完整信息（连板、行业等） | AKShare | `market/limit_up/` |
| `lhb.py` | 采集龙虎榜完整数据 | AKShare | `lhb/` |
| `kline_daily.py` | 涨停股日K线采集（主方案） | 新浪 | `stocks/{code}/daily_kline/` |
| `kline_daily_akshare.py` | 日K线备用采集（备方案） | AKShare | `stocks/{code}/daily_kline/` |
| `kline_minute.py` | 涨停股5分钟线采集，保留近5交易日 | 新浪 | `stocks/{code}/minute_kline/` |
| `concepts.py` | 基于涨停池派生热点行业与映射 | 本地文件 | `concepts/daily_hot/` + `concepts/stock_concept_map.md` |

### 2.2 计算层（calculator/）

| 模块文件 | 功能定义 | 输入依赖 | 输出 |
| --- | --- | --- | --- |
| `streak.py` | 连板数查询（主：涨停池；备：K线推算） | `limit_up/`, `daily_kline/` | 连板数 |
| `high_level.py` | 高位股筛选（连板>=3 或 5日涨幅>=25%） | `streak`, `daily_kline` | 高位股列表与状态分布 |
| `main_theme.py` | 主线/龙头/次龙头/扩散强度识别 | `limit_up`, `concepts` | 主线与地位信息 |
| `market_state.py` | 市场状态评分（强势/分歧/回撤/崩溃） | `high_level`, `main_theme`, `streak` | `market/market_state/YYYYMMDD.md` |
| `stock_derived.py` | 个股衍生指标计算（含游资识别） | `streak`, `main_theme`, `lhb`, `kline` | `stocks/{code}/derived/YYYYMMDD.md` |

### 2.3 汇总层（assembler/）

| 模块文件 | 功能定义 | 输出 |
| --- | --- | --- |
| `market_pack.py` | 组装市场分析数据包（市场状态、涨停池、核心行情、北向、热点概念、龙虎榜、近5日趋势、个股明细） | `assembled/market/YYYYMMDD.md` |
| `stock_pack.py` | 组装个股分析数据包，支持按股票文件或单日单文件汇总 | `assembled/stocks/{code}_YYYYMMDD.md` 或 `assembled/stocks/all_YYYYMMDD.md` |

## 3. 本版更新摘要（v1.1）

### 3.1 项目与仓库

- 项目名从 `Hunter 数据工程` 更新为 `AStock-Daily-Forge`。
- 已补齐 GitHub 工程化文件：`README.md`、`.gitignore`、`.editorconfig`、`.gitattributes`、`LICENSE`、`CONTRIBUTING.md`、`pyproject.toml`。

### 3.2 关键逻辑修复

- 修复历史补跑串日风险：`main_theme.get_stock_position()` 改为使用 `target_date`，避免误读 `date.today()`。
- 修复龙虎榜列名兼容问题：`代码` / `股票代码` 双兼容，避免游资识别漏匹配。

### 3.3 输出与装配增强

- `market_quote.py` 的简版涨停列表改写到 `market/limit_up_snapshot/`，避免覆盖 `market/limit_up/` 完整版。
- `stock_pack.py` 增加 `single_file` 模式，可将当日全部个股包合并为一个文件，显著减少文件数。
- `market_pack.py` 新增当日热点概念与龙虎榜章节，并将个股明细移动到报告最后。

---

# 第二部分 数据字典与模型文档

## 4. 数据源清单

| 数据源 | 访问方式 | 频率 | 用途 |
| --- | --- | --- | --- |
| AKShare 北向资金 | Python库调用 | 每日1次 | 北向资金章节 |
| AKShare 涨停池 | Python库调用 | 每日1次 | 连板、行业、主线核心输入 |
| AKShare 龙虎榜 | Python库调用 | 每日1次 | 游资识别与市场汇总章节 |
| 新浪日K线 | curl + subprocess | 按需批量 | 个股趋势与衍生指标 |
| 新浪5分钟线 | curl + subprocess | 按需批量 | 短周期结构 |
| 腾讯全市场行情 | curl + subprocess | 每日1次 | 市场核心指标与个股明细 |

## 5. 数据文件结构（Schema）

### 5.1 市场目录

- `market/daily_quote/YYYYMMDD.md`：市场核心指标 + 个股明细。
- `market/limit_up/YYYYMMDD.md`：涨停股完整版（连板、行业、封板时间等）。
- `market/limit_up_snapshot/YYYYMMDD.md`：行情任务生成的简版涨停快照。
- `market/market_state/YYYYMMDD.md`：市场状态评分结果。
- `market/northbound/YYYYMMDD.md`：北向资金数据。

### 5.2 个股目录

- `stocks/{code}/daily_kline/YYYYMMDD.md`：日K线（单日一文件）。
- `stocks/{code}/minute_kline/YYYYMMDD.md`：5分钟线（近5交易日滚动）。
- `stocks/{code}/derived/YYYYMMDD.md`：个股衍生指标。

### 5.3 汇总目录

- `assembled/market/YYYYMMDD.md`：市场分析总包。
- `assembled/stocks/{code}_YYYYMMDD.md`：按股票输出。
- `assembled/stocks/all_YYYYMMDD.md`：单日汇总输出（single_file 模式）。

## 6. 加工逻辑（Lineage）

### 6.1 高位股规则

满足以下任一：
- 连板数 >= 3
- 5日涨幅 >= 25%

### 6.2 市场状态分类优先级

1. 跌停比例 >= 30% → 崩溃  
2. 大跌比例 >= 50% → 大回撤  
3. 同时存在涨停与大跌 → 分歧  
4. 其余 → 强势  
5. 若无高位股 → 无高位股

### 6.3 主线与地位

- 主线由当日热点概念计数判定（阈值见配置）。
- 龙头：主线行业内连板优先、成交额次优。
- 次龙头：排除龙头后同规则选出。
- 个股地位：龙头 / 次龙头 / 补涨 / 非主线。

### 6.4 游资识别

- 从 `lhb/YYYYMMDD.md` 读取买入席位。
- 与 `config/traders.py` 名单进行子串匹配。
- 兼容 `代码` / `股票代码` 两种表头。

---

# 第三部分 运维与部署手册

## 7. 环境搭建指南

```bash
cd ~/AStock-Daily-Forge/src
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install -r requirements.txt
pytest tests/ -q
```

## 8. 任务调度说明

### 8.1 调度工具

- Linux `cron`
- 任务入口：`src/scheduler/runner.py --job <job_name>`
- 每个任务先进行交易日检查，非交易日直接退出。

### 8.2 时序（交易日）

- 21:00 并行：`market_quote` / `northbound` / `limit_up` / `lhb`
- 21:08 并行：`concepts` / `kline_daily`
- 21:14：`kline_minute`
- 21:20 并行：`market_state` / `stock_derived`
- 21:25：`market_pack`
- 21:27：`stock_packs`
- 周一 21:30：`concept_map_weekly`

## 9. 监控与日志

- 运行日志位于 `logs/`。
- 建议按任务关键阶段打印：启动、输入量、输出量、失败重试、最终状态。
- 建议每天检查：
  - 是否生成 `assembled/market/YYYYMMDD.md`
  - `assembled/stocks/` 文件数或 `all_YYYYMMDD.md` 是否存在

---

# 第四部分 接口与使用文档

## 10. 命令行接口（CLI）

### 10.1 手动全量补跑

```bash
cd src
python main.py --full --date 20260323
```

### 10.2 生成单只个股包

```bash
cd src
python main.py --stock 600396 --date 20260323
```

### 10.3 调度器任务运行

```bash
cd src/scheduler
python runner.py --list
python runner.py --job market_pack
python runner.py --job stock_packs
```

## 11. 配置参数完整说明

配置文件：`src/config/settings.py`

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `HIGH_LEVEL_MIN_STREAK` | 高位股最小连板阈值 | `3` |
| `HIGH_LEVEL_MIN_CHANGE_5D` | 高位股5日涨幅阈值 | `0.25` |
| `MAIN_THEME_MIN_COUNT` | 主线行业最小涨停数 | `5` |
| `SPREAD_STRONG_COUNT` | 扩散强（强）阈值 | `6` |
| `SPREAD_MID_COUNT` | 扩散中（中）阈值 | `3` |
| `STOCK_PACK_OUTPUT_MODE` | 个股包输出模式（`per_stock` / `single_file`） | `per_stock` |

## 12. 输出示例与下游LLM对接建议

### 12.1 市场总包推荐输入

- 直接使用：`assembled/market/YYYYMMDD.md`
- 建议让模型优先读：
  - 市场状态
  - 当日涨停股
  - 当日热点概念
  - 当日龙虎榜
  - 近5日趋势

### 12.2 个股包推荐输入

- 默认：`assembled/stocks/{code}_YYYYMMDD.md`
- 大规模批处理：`assembled/stocks/all_YYYYMMDD.md`

### 12.3 提示词建议

- 指令中明确：
  - 只基于给定数据分析，不引入外部猜测
  - 输出风险等级与主要证据字段
  - 区分“数据缺失”与“看空结论”

---

## 附录 A：版本历史

- `v1.0`（2026-03-23）：初版完整技术文档
- `v1.1`（2026-03-24）：
  - 项目更名为 AStock-Daily-Forge
  - 调度窗口调整为 21:00 起并行执行（30分钟节奏）
  - 增加 `limit_up_snapshot` 路径说明
  - 增加 stock pack 单文件模式说明
  - 增加 market pack 新章节（热点概念、龙虎榜、个股明细置底）
  - 增加兼容与补跑一致性修复说明


