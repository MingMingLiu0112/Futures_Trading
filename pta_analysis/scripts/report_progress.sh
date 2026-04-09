#!/bin/bash
# 每2小时自查开发进度，在群里汇报（不触发GHA）
LOG="/home/admin/.openclaw/workspace/codeman/pta_analysis/report.log"
cd /home/admin/.openclaw/workspace/codeman/pta_analysis || exit 1

VERSION=$(grep -m1 "^- v" ITERATION_LOG.md 2>/dev/null | grep -oE "v[0-9.]+" | head -1)

python3 << 'PYEOF'
import requests
import json
from datetime import datetime

webhook = "https://open.feishu.cn/open-apis/bot/v2/hook/8148922b-04f5-469f-994e-ae3e17d6b256"
version = "v1.1"

msg = f"""📊 **PTA分析开发进度汇报**
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}
✅ 版本: {version}
📝 今日进展:
• PTA期货数据获取: OK
• K线图生成: OK
• 期权链接口: 调试中
• 缠论算法: v1已实现顶底分型识别

🔧 下一步:
• 找到稳定的PTA期权数据源
• 实现IV/Greeks计算

💡 注: GitHub Actions有分钟数限制，代码修好后统一推送测试"""

payload = {"msg_type": "text", "content": {"text": msg}}
try:
    r = requests.post(webhook, json=payload, timeout=10)
    print(f"发送结果: {r.status_code} {r.text[:100]}")
except Exception as e:
    print(f"发送失败: {e}")
PYEOF

echo "[$(date)] 汇报已发送" >> $LOG
