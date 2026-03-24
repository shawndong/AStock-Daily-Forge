#!/bin/bash
# AStock-Daily-Forge — cron 定时任务配置脚本
# 运行方式：bash setup_cron.sh
# 功能：将所有定时任务写入当前用户的 crontab

PYTHON="/home/shawn/AStock-Daily-Forge/src/.venv/bin/python"
RUNNER="/home/shawn/AStock-Daily-Forge/src/scheduler/runner.py"
LOG_DIR="/home/shawn/AStock-Daily-Forge/src/logs"

# 确保日志目录存在
mkdir -p "$LOG_DIR"

echo "正在配置 cron 定时任务..."
echo "Python 路径: $PYTHON"
echo "Runner 路径: $RUNNER"
echo ""

# 生成 crontab 内容
# 格式：分 时 日 月 周 命令
CRON_CONTENT="
# AStock-Daily-Forge 定时任务（由 setup_cron.sh 生成）
# 每个任务内部已有交易日判断，非交易日自动跳过

# 21:00 并行启动：全市场行情 / 北向资金 / 涨停股池 / 龙虎榜
0 21 * * 1-5 $PYTHON $RUNNER --job market_quote >> $LOG_DIR/cron.log 2>&1
0 21 * * 1-5 $PYTHON $RUNNER --job northbound >> $LOG_DIR/cron.log 2>&1
0 21 * * 1-5 $PYTHON $RUNNER --job limit_up >> $LOG_DIR/cron.log 2>&1
0 21 * * 1-5 $PYTHON $RUNNER --job lhb >> $LOG_DIR/cron.log 2>&1

# 21:08 并行启动：题材概念统计 / 涨停股日K线
8 21 * * 1-5 $PYTHON $RUNNER --job concepts >> $LOG_DIR/cron.log 2>&1
8 21 * * 1-5 $PYTHON $RUNNER --job kline_daily >> $LOG_DIR/cron.log 2>&1

# 21:14 涨停股5分钟线
14 21 * * 1-5 $PYTHON $RUNNER --job kline_minute >> $LOG_DIR/cron.log 2>&1

# 21:20 并行启动：市场状态 / 个股衍生指标
20 21 * * 1-5 $PYTHON $RUNNER --job market_state >> $LOG_DIR/cron.log 2>&1
20 21 * * 1-5 $PYTHON $RUNNER --job stock_derived >> $LOG_DIR/cron.log 2>&1

# 21:25 市场分析数据包
25 21 * * 1-5 $PYTHON $RUNNER --job market_pack >> $LOG_DIR/cron.log 2>&1

# 21:27 个股分析数据包
27 21 * * 1-5 $PYTHON $RUNNER --job stock_packs >> $LOG_DIR/cron.log 2>&1

# 21:30 概念映射表更新（仅周一）
30 21 * * 1 $PYTHON $RUNNER --job concept_map_weekly >> $LOG_DIR/cron.log 2>&1
"

# 读取现有 crontab，去掉旧的 Hunter 相关行，追加新配置
(crontab -l 2>/dev/null | grep -v "AStock-Daily-Forge\|$RUNNER"; echo "$CRON_CONTENT") | crontab -

echo "✅ cron 定时任务已配置完成！"
echo ""
echo "当前 crontab 内容："
echo "────────────────────────────────────────"
crontab -l
echo "────────────────────────────────────────"
echo ""
echo "常用命令："
echo "  查看日志：  tail -f $LOG_DIR/cron.log"
echo "  手动测试：  $PYTHON $RUNNER --job limit_up"
echo "  查看任务：  $PYTHON $RUNNER --list"
echo "  清除任务：  crontab -r"
