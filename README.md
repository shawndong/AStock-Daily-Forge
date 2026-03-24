# AStock-Daily-Forge

AStock-Daily-Forge 是一个面向 A 股收盘后分析场景的数据工程项目。它在交易日晚间自动采集、清洗、计算并组装结构化 Markdown 数据包，供大模型在次日盘前进行预测与研判。

## 项目目标

- 每个交易日稳定产出完整数据链路（采集 → 计算 → 组装）。
- 输出格式对人类可读、对 LLM 可直接消费。
- 通过定时任务自动运行，支持补跑与手动调试。

## 架构概览

- `collector/`：采集层（腾讯/新浪/AKShare）。
- `calculator/`：计算层（连板、高位股、主线、市场状态、个股衍生）。
- `assembler/`：装配层（市场数据包、个股数据包）。
- `scheduler/`：调度层（交易日检查、任务编排、runner 入口）。
- `storage/`：统一 md 读写、表格解析。
- `config/`：路径、阈值、交易日历、游资名单。

## 目录结构

```text
AStock-Daily-Forge/
├─ assembled/               # 装配输出
├─ concepts/                # 概念与映射
├─ lhb/                     # 龙虎榜数据
├─ market/                  # 市场级数据（行情、涨停池、状态、北向）
├─ stocks/                  # 个股级数据（K线、衍生）
├─ logs/                    # 运行日志
├─ src/
│  ├─ assembler/
│  ├─ calculator/
│  ├─ collector/
│  ├─ config/
│  ├─ scheduler/
│  ├─ storage/
│  ├─ tests/
│  └─ main.py
└─ README.md
```

## 快速开始

```bash
cd src
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install -r requirements.txt
pytest tests/ -q
```

## 运行方式

### 1) 手动补跑

```bash
cd src
python main.py --full --date 20260323
```

### 2) 仅生成单只个股数据包

```bash
cd src
python main.py --stock 600396 --date 20260323
```

### 3) 按任务执行（与 cron 一致）

```bash
cd src/scheduler
python runner.py --list
python runner.py --job market_quote
python runner.py --job stock_packs
```

## 调度时序（交易日，21:00 启动）

- 21:00 并行：`market_quote` / `northbound` / `limit_up` / `lhb`
- 21:08 并行：`concepts` / `kline_daily`
- 21:14：`kline_minute`
- 21:20 并行：`market_state` / `stock_derived`
- 21:25：`market_pack`
- 21:27：`stock_packs`
- 周一 21:30：`concept_map_weekly`

## 文件数量优化

为减少 `assembled/stocks/` 文件数量，新增配置项：

- `src/config/settings.py` → `STOCK_PACK_OUTPUT_MODE`
  - `per_stock`（默认）：每只股票一个文件
  - `single_file`：当日所有股票输出为 `all_YYYYMMDD.md`

## 重要设计原则

- 所有阈值统一维护在 `src/config/settings.py`。
- 数据缺失统一写 `N/A`，不做“猜测补值”。
- 业务层不直接写文件，统一走 `storage/writer.py`。
- 默认以“交易日”作为运行前置检查。

## 开发与贡献

- 贡献流程见 `CONTRIBUTING.md`
- 代码审查与优化建议见 `docs/PROJECT_REVIEW.md`

## 许可

MIT License
