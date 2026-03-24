#!/bin/bash

# Hunter 数据工程 — 目录初始化脚本
# 运行方式：bash setup_hunter_data.sh [目标路径]
# 示例：bash setup_hunter_data.sh ~/hunter_data
# 不传参数时，默认在当前目录下创建 hunter_data/

ROOT="${1:-./hunter_data}"

echo "正在初始化 Hunter 数据目录..."
echo "目标路径：$(realpath $ROOT 2>/dev/null || echo $ROOT)"
echo ""

# ── 市场整体数据 ──
mkdir -p "$ROOT/market/daily_quote"
mkdir -p "$ROOT/market/limit_up"
mkdir -p "$ROOT/market/northbound"
mkdir -p "$ROOT/market/market_state"

# ── 个股数据（模板占位目录） ──
mkdir -p "$ROOT/stocks/.template/daily_kline"
mkdir -p "$ROOT/stocks/.template/minute_kline"
mkdir -p "$ROOT/stocks/.template/derived"

# ── 龙虎榜 ──
mkdir -p "$ROOT/lhb"

# ── 题材概念 ──
mkdir -p "$ROOT/concepts/daily_hot"

# ── 汇总数据包 ──
mkdir -p "$ROOT/assembled/market"
mkdir -p "$ROOT/assembled/stocks"

# ── 写入各目录的 README 说明 ──

cat > "$ROOT/README.md" << 'EOF'
# Hunter 数据工程 — 数据目录

## 目录说明

| 目录 | 内容 |
|------|------|
| market/daily_quote/ | 每日全市场行情汇总，文件名格式：YYYYMMDD.md |
| market/limit_up/ | 每日涨停股列表，文件名格式：YYYYMMDD.md |
| market/northbound/ | 每日北向资金，文件名格式：YYYYMMDD.md |
| market/market_state/ | 每日计算后的市场状态指标，文件名格式：YYYYMMDD.md |
| stocks/{code}/ | 个股数据，按股票代码分目录 |
| stocks/{code}/daily_kline/ | 日K线，每日追加，文件名格式：YYYYMMDD.md |
| stocks/{code}/minute_kline/ | 分钟线，只保留近5交易日，文件名格式：YYYYMMDD.md |
| stocks/{code}/derived/ | 衍生指标（连板数、5日涨幅等），文件名格式：YYYYMMDD.md |
| lhb/ | 每日全市场龙虎榜，文件名格式：YYYYMMDD.md |
| concepts/stock_concept_map.md | 股票→概念映射表，周更 |
| concepts/daily_hot/ | 每日热门概念统计，文件名格式：YYYYMMDD.md |
| assembled/market/ | 市场分析提示词数据包，文件名格式：YYYYMMDD.md |
| assembled/stocks/ | 个股分析提示词数据包，文件名格式：{code}_YYYYMMDD.md |

## 文件命名规则

- 日期格式统一为 `YYYYMMDD`，例如 `20250110.md`
- 个股目录名为股票代码，例如 `stocks/300001/`
- 个股汇总包文件名格式：`{股票代码}_{日期}.md`，例如 `300001_20250110.md`

## 注意事项

- 分钟线数据只保留近5个交易日，旧文件定期清理
- 数据缺失字段统一标记为 N/A，严禁伪造
- assembled/ 目录为只读产物，不要手动修改
EOF

cat > "$ROOT/concepts/stock_concept_map.md" << 'EOF'
# 股票概念映射表

> 更新频率：每周一次
> 最后更新：（待填写）

| 股票代码 | 股票名称 | 所属概念 |
|----------|----------|----------|
| 示例：300001 | 特锐德 | 新能源,充电桩 |
EOF

cat > "$ROOT/stocks/.template/daily_kline/.gitkeep" << 'EOF'
EOF
cat > "$ROOT/stocks/.template/minute_kline/.gitkeep" << 'EOF'
EOF
cat > "$ROOT/stocks/.template/derived/.gitkeep" << 'EOF'
EOF

# ── 写入各数据目录的格式说明 ──

cat > "$ROOT/market/daily_quote/.format.md" << 'EOF'
# 格式说明：市场行情汇总

文件名：YYYYMMDD.md

```markdown
# 市场行情汇总 YYYY-MM-DD

## 核心指标
| 指标 | 数值 |
|------|------|
| 涨停数量 | - |
| 跌停数量 | - |
| 上涨家数 | - |
| 下跌家数 | - |
| 全市场成交额(亿) | - |
| 北向净买入(亿) | - |

## 涨停股列表
| 股票代码 | 股票名称 | 连板数 | 所属概念 | 成交额(亿) |
|----------|----------|--------|----------|-----------|
```
EOF

cat > "$ROOT/market/market_state/.format.md" << 'EOF'
# 格式说明：市场状态

文件名：YYYYMMDD.md

```markdown
# 市场状态 YYYY-MM-DD

| 指标 | 值 |
|------|----|
| 最大连板高度 | - |
| 高位股总数 | - |
| 高位股跌停数 | - |
| 高位股大跌(>5%)数 | - |
| 市场状态 | 强势 / 分歧 / 大回撤 / 崩溃 |
| 资金扩散强度 | 强 / 中 / 弱 |
| 主线概念 | - |
| 龙头股票 | - |
```
EOF

cat > "$ROOT/lhb/.format.md" << 'EOF'
# 格式说明：龙虎榜

文件名：YYYYMMDD.md

```markdown
# 龙虎榜 YYYY-MM-DD

| 股票代码 | 股票名称 | 买入席位 | 卖出席位 | 净买入(万) | 游资介入 |
|----------|----------|----------|----------|-----------|---------|
```
EOF

cat > "$ROOT/assembled/.format.md" << 'EOF'
# 格式说明：assembled 汇总数据包

## 市场分析包 assembled/market/YYYYMMDD.md
依次包含：
1. 市场整体行情（涨跌停数、成交额）
2. 涨停股列表（含连板数、所属概念）
3. 主线题材统计
4. 北向资金净流入
5. 高位股状态分类
6. 近5日市场情绪对比

## 个股分析包 assembled/stocks/{code}_YYYYMMDD.md
依次包含：
1. 近1个月日K线
2. 近5日分钟线摘要
3. 近5日龙虎榜记录
4. 最新衍生指标
5. 所属概念及板块地位
EOF

# ── 完成提示 ──
echo "目录结构创建完成！"
echo ""
echo "目录预览："
find "$ROOT" -not -name '.gitkeep' | sort | sed "s|$ROOT||" | sed 's|^/||' | awk '{
  n = split($0, a, "/")
  indent = ""
  for (i = 1; i < n; i++) indent = indent "  "
  if (n > 0) print indent (n==1 ? a[n] : "└── " a[n])
}'
echo ""
echo "下一步建议："
echo "  1. 编辑 $ROOT/concepts/stock_concept_map.md，填入股票概念映射"
echo "  2. 参考各目录下的 .format.md 了解文件格式"
echo "  3. 开始配置定时采集任务"
