# Project Review (2026-03-24)

## Overall assessment

当前项目主流程清晰，四层分工明确（采集/计算/装配/调度），且数据字典与落地文件基本一致，适合作为 LLM 分析前的数据基座。

## Key findings and fixes applied

1. Historical date consistency bug
- Problem: `calculator/main_theme.py` 的 `get_stock_position()` 内部使用 `date.today()` 读取涨停池，会在补历史数据时串日。
- Fix: 改为显式使用 `target_date`。

2. LHB schema compatibility risk
- Problem: `calculator/stock_derived.py` 和 `assembler/stock_pack.py` 部分逻辑仅识别 `股票代码` 字段，但当前 `lhb/*.md` 实际表头是 `代码`。
- Fix: 增加兼容读取（`代码` / `股票代码` 双兼容）。

3. limit_up overwrite risk
- Problem: `collector/market_quote.py` 会写入 `market/limit_up/` 简版文件，可能覆盖 `collector/limit_up.py` 的完整版（在非标准执行路径下风险更高）。
- Fix: 将该简版输出改写到 `market/limit_up_snapshot/`。

4. Assembler output file explosion
- Problem: `assembled/stocks/` 每日按股票逐个落地，长期文件数膨胀。
- Fix: 新增配置 `STOCK_PACK_OUTPUT_MODE`：
  - `per_stock`（默认）
  - `single_file`（输出 `all_YYYYMMDD.md`）

## Directory organization suggestions

- Code-only repo + runtime data split（推荐）
  - 把 `src/` 作为主仓库内容。
  - `assembled/market/stocks/lhb/logs` 作为运行产物，不入库。
- 长期归档策略
  - 日频文件按月归档压缩。
  - 汇总型文件（如 `all_YYYYMMDD.md`）优先保留，明细按需回溯。

## Assembler enhancement suggestions

- 增加 token-budget 视图
  - 输出“精简版”（摘要）与“全量版”（明细），便于不同模型上下文窗口。
- 增加 provenance 元信息
  - 每个章节头加数据日期、来源文件、缺失标记，提升可追溯性。
- 增加失败隔离
  - 对某一股票装配失败时写局部错误块，不影响当日总体单文件产出。

## Next recommendations

- 增加轻量 schema contract tests（列名、单位、日期格式）。
- 增加 `src/logs/` 与根 `logs/` 的单一路径规范，避免运维混淆。
- 为 `README` 增加“如何做次日预测输入拼接”的实例 prompt 模板。
