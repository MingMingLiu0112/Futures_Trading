#!/bin/bash
# 东财T链连通性检测脚本
# 每小时自动运行一次，记录结果到日志文件

PYTHON="/home/admin/.pyenv/shims/python3.11"
LOGFILE="/home/admin/.openclaw/workspace/codeman/pta_analysis/eastmoney_check.log"
DATE=$(date '+%Y-%m-%d %H:%M')

echo "[$DATE] 开始检测..." >> $LOGFILE

# 测试 option_current_em (无参数)
RESULT=$($PYTHON -c "
import akshare as ak
try:
    df = ak.option_current_em()
    print(f'SUCCESS:{len(df)}')
except Exception as e:
    print(f'FAIL:{type(e).__name__}:{str(e)[:100]}')
" 2>&1)

echo "[$DATE] option_current_em(): $RESULT" >> $LOGFILE

# 测试 option_risk_analysis_em (无参数)
RESULT2=$($PYTHON -c "
import akshare as ak
try:
    df = ak.option_risk_analysis_em()
    print(f'SUCCESS:{len(df)}')
except Exception as e:
    print(f'FAIL:{type(e).__name__}:{str(e)[:100]}')
" 2>&1)

echo "[$DATE] option_risk_analysis_em(): $RESULT2" >> $LOGFILE

# 测试 option_value_analysis_em
RESULT3=$($PYTHON -c "
import akshare as ak
try:
    df = ak.option_value_analysis_em()
    print(f'SUCCESS:{len(df)}')
except Exception as e:
    print(f'FAIL:{type(e).__name__}:{str(e)[:100]}')
" 2>&1)

echo "[$DATE] option_value_analysis_em(): $RESULT3" >> $LOGFILE

# 统计成功率
TOTAL=$(grep -c "FAIL\|SUCCESS" $LOGFILE 2>/dev/null || echo 0)
SUCCESS=$(grep -c "SUCCESS" $LOGFILE 2>/dev/null || echo 0)
echo "[$DATE] 历史统计: 成功率 $SUCCESS/$TOTAL" >> $LOGFILE
echo "" >> $LOGFILE
