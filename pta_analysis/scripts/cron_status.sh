#!/bin/bash
# 每2小时报告PTA分析进度
WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/8148922b-04f5-469f-994e-ae3e17d6b256"
LOG="/home/admin/.openclaw/workspace/codeman/pta_analysis/cron_run.log"

VERSION=$(cat /home/admin/.openclaw/workspace/codeman/pta_analysis/ITERATION_LOG.md 2>/dev/null | grep -m1 "^- v" | grep -oE "v[0-9.]+" | head -1)

MSG="📊 **PTA分析系统定时报告**
⏰ $(date '+%Y-%m-%d %H:%M')
✅ 当前版本: ${VERSION:-未知}
🔧 迭代中...
📋 https://github.com/MingMingLiu0112/pta-analysis"

curl -s -X POST "$WEBHOOK" -H "Content-Type: application/json" -d "{\"msg_type\": \"text\", \"content\": {\"text\": \"$MSG\"}}" >> $LOG 2>&1
echo "[$(date)] 报告已发送" >> $LOG
