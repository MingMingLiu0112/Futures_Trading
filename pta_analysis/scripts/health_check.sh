#!/bin/bash
# PTA数据源健康检查脚本
# 每小时运行一次，监控所有可用数据源连通性

PYTHON="/home/admin/.pyenv/shims/python3.11"
WORKSPACE="/home/admin/.openclaw/workspace/codeman/pta_analysis"
LOGFILE="$WORKSPACE/health_check.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M')] $1" | tee -a "$LOGFILE"; }

log "=== PTA数据源健康检查 ==="

# 1. 郑商所PTA期货实时行情
RESULT=$($PYTHON -c "
import akshare as ak
try:
    df = ak.futures_zh_realtime()
    ta = df[df['exchange'] == 'czce']
    ta = ta[ta['symbol'].str.match(r'^TA\d{4}$')]
    print(f'OK:{len(ta)}合约,主力:{ta.nlargest(1,\"volume\").iloc[0][\"symbol\"]}:{ta.nlargest(1,\"volume\").iloc[0][\"trade\"]}')
except Exception as e:
    print(f'FAIL:{type(e).__name__}:{str(e)[:80]}')
" 2>&1)
log "futures_zh_realtime(PTA): $RESULT"

# 2. 郑商所PTA期权日线
RESULT2=$($PYTHON -c "
import akshare as ak
from datetime import datetime, timedelta
for i in range(1,5):
    d = (datetime.now()-timedelta(days=i)).strftime('%Y%m%d')
    try:
        df = ak.option_hist_czce(symbol='PTA期权', trade_date=d)
        if not df.empty:
            print(f'OK:{len(df)}行:{d}')
            break
        else:
            print(f'EMPTY:{d}')
    except Exception as e:
        print(f'FAIL:{type(e).__name__}:{str(e)[:60]}')
        break
" 2>&1)
log "option_hist_czce(PTA): $RESULT2"

# 3. TA/PX现货价
RESULT3=$($PYTHON -c "
import akshare as ak
from datetime import datetime, timedelta
for i in range(1,5):
    d = (datetime.now()-timedelta(days=i)).strftime('%Y%m%d')
    try:
        df = ak.futures_spot_price(date=d, vars_list=['TA','PX'])
        if not df.empty:
            ta = df[df['symbol']=='TA'].iloc[0]
            px = df[df['symbol']=='PX'].iloc[0]
            print(f'OK:TA={ta[\"spot_price\"]} PX={px[\"spot_price\"]} ({d})')
            break
    except Exception as e:
        print(f'FAIL:{type(e).__name__}:{str(e)[:60]}')
        break
" 2>&1)
log "futures_spot_price(TA/PX): $RESULT3"

# 4. 布伦特原油
RESULT4=$($PYTHON -c "
import akshare as ak
try:
    df = ak.futures_global_spot_em()
    b = df[df['名称'].str.contains('布伦特| Brent', na=False)]
    price = b['最新价'].dropna().iloc[0]
    print(f'OK:\${price}')
except Exception as e:
    print(f'FAIL:{type(e).__name__}:{str(e)[:60]}')
" 2>&1)
log "futures_global_spot_em(Brent): $RESULT4"

# 5. 东方财富实时期权API（已知挂了，仅记录）
RESULT5=$($PYTHON -c "
import akshare as ak
try:
    df = ak.option_current_em()
    print(f'OK:{len(df)}')
except Exception as e:
    print(f'FAIL:{type(e).__name__}:{str(e)[:60]}')
" 2>&1)
log "option_current_em(东财): $RESULT5  ← 已知故障"

log "=== 检查完成 ==="
echo "" >> "$LOGFILE"
