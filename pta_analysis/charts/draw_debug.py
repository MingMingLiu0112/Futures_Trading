"""调试：用原始K线画图，验证基础渲染"""
import akshare as ak, pandas as pd, warnings, matplotlib
warnings.filterwarnings('ignore')
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

df = ak.futures_zh_minute_sina(symbol='TA0', period='1')
df['datetime'] = pd.to_datetime(df['datetime'])
df = df.sort_values('datetime').tail(200).reset_index(drop=True)
df = df.reset_index(drop=True)

print(f"数据: {df['datetime'].iloc[0].strftime('%H:%M')} ~ {df['datetime'].iloc[-1].strftime('%H:%M')}  共{len(df)}根")

plt.style.use('dark_background')
fig, ax = plt.subplots(figsize=(18, 8))

# 画所有原始K线
for i, row in df.iterrows():
    dt = row['datetime']
    o, h, l, c = row['open'], row['high'], row['low'], row['close']
    color = '#e54d4d' if c >= o else '#4da64d'
    ax.plot([i, i], [l, h], color=color, linewidth=0.8)
    body_bottom = min(o, c)
    body_top = max(o, c)
    ax.add_patch(mpatches.Rectangle((i-0.4, body_bottom), 0.8, body_top-body_bottom,
                                    facecolor=color, edgecolor=color, linewidth=0.5))

ax.set_title(f"原始K线 {df['datetime'].iloc[0].strftime('%H:%M')}~{df['datetime'].iloc[-1].strftime('%H:%M')}  共{len(df)}根", color='white')
ax.set_xlabel('K线索引(0起)')
ax.set_ylabel('价格')
ax.grid(True, alpha=0.2)
plt.tight_layout()
plt.savefig('/home/admin/.openclaw/workspace/codeman/pta_analysis/raw_kline.png', dpi=120)
print("原始K线图已保存")
