#!/usr/bin/env python3
"""PTA宏观分析报告 - 三维框架完整版（宏观+产业+期权）"""
import urllib.request, re, json, warnings
from html import unescape
from datetime import datetime, timedelta
import pandas as pd

def fetch(url, timeout=12):
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html',
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode('utf-8', errors='replace')
    except Exception as e:
        return f'ERROR:{e}'

# === 维度一：宏观经济金融 ===
html = fetch('https://finance.ifeng.com/')
if not html.startswith('ERROR'):
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
    links = re.findall(r'<a[^>]+href="(https?://[^\"]{10,})"[^>]*>(.*?)</a>', html, flags=re.DOTALL)
else:
    links = []

TYPE_KW = {
    '地缘风险': ['地缘','制裁','中东','俄乌','红海','以色列','伊朗','霍尔木兹','胡塞',' OPEC','欧佩克'],
    '美联储/央行': ['美联储','降息','加息','缩表','扩表','央行','鲍威尔','利率','美债'],
    '宏观经济': ['CPI','PPI','GDP','非农','就业','制造业','PMI','通胀','衰退','经济'],
    '市场情绪': ['黑天鹅','恐慌','避险','美股','大跌','大涨','资金流','抛售'],
}

events = {}
for cat, kws in TYPE_KW.items():
    matches = []
    for href, title in links:
        t = unescape(title).strip()
        if t and len(t) > 5 and any(k in t for k in kws):
            matches.append(t[:60])
    events[cat] = list(dict.fromkeys(matches))[:3]

# 原油
oil = {}
for sym, name in [('BZ=F','布伦特'), ('CL=F','WTI')]:
    try:
        u = f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d'
        req = urllib.request.Request(u, headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'})
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read())
            c = d['chart']['result'][0]['indicators']['quote'][0]['close']
            oil[name] = round(c[-1], 2)
    except:
        oil[name] = None

# 美债
bonds = {'us10y': None, 'spread': None}
try:
    import akshare as ak
    df_bond = ak.bond_zh_us_rate()
    if df_bond is not None and len(df_bond) > 0:
        latest = df_bond.iloc[-1]
        bonds['us10y'] = round(float(latest.get('美国国债收益率10年', 0) or 0), 2)
        bonds['spread'] = round(float(latest.get('美国国债收益率10年-2年', 0) or 0), 1)
except:
    pass

# === 维度二：中观行业基本面 ===
pta_data = {'spot': None, 'near_contract': None, 'near_price': None}
px_data = {'spot': None}
try:
    import akshare as ak
    df_spot = ak.futures_spot_price()
    if df_spot is not None:
        for sym, data in [('TA', pta_data), ('PX', px_data)]:
            row = df_spot[df_spot['symbol'] == sym]
            if len(row) > 0:
                r = row.iloc[-1]
                data['spot'] = round(float(r['spot_price']), 1) if r['spot_price'] else None
                if sym == 'TA':
                    pta_data['near_contract'] = r.get('near_contract', '')
                    pta_data['near_price'] = round(float(r['near_contract_price']), 1) if r.get('near_contract_price') else None
except:
    pass

cost_low = cost_high = jgf_est = None
if px_data.get('spot') and pta_data.get('spot'):
    px = px_data['spot']
    cost_low = round(px * 0.655 + 300, 0)
    cost_high = round(px * 0.655 + 800, 0)
    jgf_est = round(pta_data['spot'] - px * 0.655, 0)

# === 维度三：期权市场 ===
opt_data = {'pcr_vol': None, 'pcr_oi': None, 'iv_mean': None, 'trade_date': None,
            'top_puts': [], 'top_calls': []}
warnings.filterwarnings('ignore')

try:
    import akshare as ak
    trade_date = None
    for d in [datetime.now().strftime('%Y%m%d')] + \
               [(datetime.now() - timedelta(days=i)).strftime('%Y%m%d') for i in range(1, 8)]:
        try:
            df_opt = ak.option_hist_czce(symbol='PTA期权', trade_date=d)
            if df_opt is not None and len(df_opt) > 100:
                trade_date = d
                break
        except:
            pass

    if trade_date:
        opt_df = df_opt
        def get_strike(code):
            m = re.search(r'[PC](\d+)', code)
            return int(m.group(1)) if m else None
        opt_df['行权价'] = opt_df['合约代码'].apply(get_strike)
        puts = opt_df[opt_df['合约代码'].str.contains('P', na=False)].copy()
        calls = opt_df[opt_df['合约代码'].str.contains('C', na=False)].copy()
        puts['iv'] = pd.to_numeric(puts['隐含波动率'], errors='coerce')
        calls['iv'] = pd.to_numeric(calls['隐含波动率'], errors='coerce')

        call_vol = calls['成交量(手)'].sum()
        put_vol = puts['成交量(手)'].sum()
        call_oi = calls['持仓量'].sum()
        put_oi = puts['持仓量'].sum()
        opt_data['pcr_vol'] = round(put_vol/call_vol, 3) if call_vol > 0 else None
        opt_data['pcr_oi'] = round(put_oi/call_oi, 3) if call_oi > 0 else None
        iv_series = pd.to_numeric(opt_df['隐含波动率'], errors='coerce').dropna()
        opt_data['iv_mean'] = round(iv_series.mean(), 1) if len(iv_series) > 0 else None
        opt_data['trade_date'] = trade_date

        top5p = puts.nlargest(5, '持仓量')
        top5c = calls.nlargest(5, '持仓量')
        opt_data['top_puts'] = [
            {'合约代码': r['合约代码'], '行权价': int(r['行权价']),
             '成交量(手)': r['成交量(手)'], '持仓量': r['持仓量'], 'iv': r['iv']}
            for _, r in top5p.iterrows()
        ]
        opt_data['top_calls'] = [
            {'合约代码': r['合约代码'], '行权价': int(r['行权价']),
             '成交量(手)': r['成交量(手)'], '持仓量': r['持仓量'], 'iv': r['iv']}
            for _, r in top5c.iterrows()
        ]
except Exception as e:
    opt_data['error'] = str(e)[:60]

# === 生成报告 ===
now = datetime.now().strftime('%m-%d %H:%M')
lines = [
    f"📊 PTA 日度综合分析 | {now}",
    "",
    "━━━━━━━━━━━━━━━━━━━━",
    "一、宏观经济金融环境",
    "━━━━━━━━━━━━━━━━━━━━",
]

geo = events.get('地缘风险', [])
fed = events.get('美联储/央行', [])

if geo:
    lines.append("【地缘风险】")
    for t in geo[:2]:
        lines.append(f"  · {t}")
else:
    lines.append("【地缘风险】无重大地缘事件")

if fed:
    lines.append("【美联储/央行】")
    for t in fed[:2]:
        lines.append(f"  · {t}")

brent = oil.get('布伦特')
wti = oil.get('WTI')
lines += ["", "【原油-成本链】"]
if brent: lines.append(f"  布伦特: ${brent}/桶")
if wti: lines.append(f"  WTI: ${wti}/桶")
if bonds.get('us10y'): lines.append(f"  美10Y: {bonds['us10y']}% ({'+' if bonds['spread']>0 else ''}{bonds['spread']}bp利差)")

lines += ["", "【逻辑推断】"]
if geo:
    lines.append(f"  中东/霍尔木兹等地缘持续紧张 → 原油风险溢价支撑偏强")
if brent and brent > 85:
    lines.append(f"  布伦特${brent}高位 → PTA成本支撑上移，偏多")
if bonds.get('us10y') and bonds['us10y'] > 4.5:
    lines.append(f"  美10Y{bonds['us10y']}%高位 → 压制商品估值，偏空")
elif bonds.get('us10y') and bonds['us10y'] < 4.0:
    lines.append(f"  美10Y{bonds['us10y']}%低位 → 金融宽松，商品友好")
if bonds.get('spread') and bonds['spread'] > 0.3:
    lines.append(f"  美债利差+{bonds['spread']}bp → 衰退预期降温")

lines += ["", "━━━━━━━━━━━━━━━━━━━━", "二、中观行业基本面", "━━━━━━━━━━━━━━━━━━━━"]
lines.append("【成本链】")
if pta_data.get('spot'): lines.append(f"  PTA现货: ¥{pta_data['spot']}/吨")
if pta_data.get('near_contract'): lines.append(f"    近月: {pta_data['near_contract']} ¥{pta_data['near_price']}")
if px_data.get('spot'): lines.append(f"  PX现货: ¥{px_data['spot']}/吨")
if cost_low and cost_high:
    lines.append(f"  PTA成本区间: ¥{cost_low:.0f}~¥{cost_high:.0f}/吨（PX×0.655+300~800）")
    if pta_data.get('spot'):
        margin = pta_data['spot'] - cost_low
        if margin > 0:
            lines.append(f"    现货-成本下沿 = ¥{margin:.0f}（盈利区间）")
        else:
            lines.append(f"    现货-成本下沿 = ¥{margin:.0f}（亏损区间）")
if jgf_est:
    lines.append(f"  估算加工费: ≈{jgf_est:.0f}元/吨")
    if jgf_est < 400:
        lines.append(f"  → 持续亏损，供应压缩，底部支撑强 🟢")
    elif jgf_est > 800:
        lines.append(f"  → 高加工费刺激开工，供应压力 🔴")

lines += ["", "【逻辑推断】"]
if pta_data.get('spot') and cost_low:
    pta = pta_data['spot']
    if pta < cost_low:
        lines.append(f"  PTA现货¥{pta:.0f} < 成本下沿¥{cost_low:.0f} → 产业亏损，底部支撑强 🟢")
    elif pta > cost_high:
        lines.append(f"  PTA现货¥{pta:.0f} > 成本上沿¥{cost_high:.0f} → 高估，压力区 🔴")
    else:
        lines.append(f"  PTA现货¥{pta:.0f}在成本区间内 → 正常波动 🟡")

lines += ["", "━━━━━━━━━━━━━━━━━━━━", "三、期权市场", "━━━━━━━━━━━━━━━━━━━━"]
if opt_data.get('trade_date'):
    td = opt_data['trade_date']
    lines.append(f"【PTA期权 · {td}】")
    pcr_v = opt_data.get('pcr_vol')
    pcr_o = opt_data.get('pcr_oi')
    iv_m = opt_data.get('iv_mean')
    lines.append(f"  PCR成交量: {pcr_v}  PCR持仓量: {pcr_o}")
    if iv_m: lines.append(f"  隐含波动率均值: {iv_m}%")
    if pcr_o:
        if pcr_o > 1.2:
            lines.append(f"  → PCR_oi={pcr_o:.2f}>1.2，看跌持仓更重，空头力量偏强 🟢")
        elif pcr_o < 0.8:
            lines.append(f"  → PCR_oi={pcr_o:.2f}<0.8，看涨持仓更重，多头力量偏强 🔴")
        else:
            lines.append(f"  → PCR_oi={pcr_o:.2f}中性，多空力量均衡 🟡")

    lines.append(f"  关键PUT持仓（下行防线）:")
    for row in opt_data.get('top_puts', [])[:4]:
        iv_str = f"{row['iv']:.1f}%" if pd.notna(row.get('iv')) else "N/A"
        lines.append(f"    {row['合约代码']}(行权价{row['行权价']}) 持仓={row['持仓量']:.0f}手 IV={iv_str}")

    lines.append(f"  关键CALL持仓（上行压力）:")
    for row in opt_data.get('top_calls', [])[:4]:
        iv_str = f"{row['iv']:.1f}%" if pd.notna(row.get('iv')) else "N/A"
        lines.append(f"    {row['合约代码']}(行权价{row['行权价']}) 持仓={row['持仓量']:.0f}手 IV={iv_str}")

    lines += ["", "【期权逻辑推断】"]
    top_puts = opt_data.get('top_puts', [])
    top_calls = opt_data.get('top_calls', [])
    p6000 = next((r for r in top_puts if r.get('行权价', 0) == 6000), None)
    c7000 = next((r for r in top_calls if r.get('行权价', 0) == 7000), None)
    if p6000:
        iv_s = f"{p6000['iv']:.1f}%" if pd.notna(p6000.get('iv')) else "N/A"
        lines.append(f"  6000P防线: {p6000['持仓量']:.0f}手持仓，IV={iv_s} — 多头防线，若跌破则下行加速")
    if c7000:
        iv_s = f"{c7000['iv']:.1f}%" if pd.notna(c7000.get('iv')) else "N/A"
        lines.append(f"  7000C压力: {c7000['持仓量']:.0f}手持仓，IV={iv_s} — 产业空头在7000重仓，上行压制强")
    if iv_m and iv_m > 60:
        lines.append(f"  IV={iv_m}%高位 → 期权定价偏贵，权利金成本高")
    elif iv_m and iv_m < 30:
        lines.append(f"  IV={iv_m}%低位 → 期权定价便宜，权利金成本低")
else:
    lines.append("  (期权数据获取中，可能非交易日)")

lines += ["", "━━━━━━━━━━━━━━━━━━━━", "四，综合判断", "━━━━━━━━━━━━━━━━━━━━"]

score = 0.0
reasons = []
if geo and len(geo) >= 2: score += 1; reasons.append("地缘持续紧张")
if brent and brent > 85: score += 1; reasons.append(f"布伦特${brent}高位")
if bonds.get('us10y') and bonds['us10y'] > 4.5: score -= 1; reasons.append(f"美10Y{bonds['us10y']}%偏高")
if bonds.get('spread') and bonds['spread'] > 0.3: score += 0.5; reasons.append(f"利差+{bonds['spread']}bp")
if pta_data.get('spot') and cost_low and pta_data['spot'] < cost_low: score += 1; reasons.append("PTA亏损压缩供应")
if jgf_est and jgf_est < 400: score += 1; reasons.append(f"加工费≈{jgf_est}元/吨偏低")
if pcr_o and pcr_o > 1.2: score += 0.5; reasons.append(f"PCR_oi={pcr_o}偏高(看跌持仓重)")

if score >= 2:
    verdict = "🟢 偏多"
elif score <= -1:
    verdict = "🔴 偏空"
else:
    verdict = "🟡 中性"

lines.append(f"  方向: {verdict} (得分{score:+.1f})")
if reasons:
    lines.append(f"  依据: {'; '.join(reasons)}")

src_parts = ["凤凰财经", "Yahoo原油", "akshare美债/现货"]
if opt_data.get('trade_date'):
    src_parts.append(f"PTA期权({opt_data['trade_date']})")
lines += ["", f"数据: {' · '.join(src_parts)}"]

report = '\n'.join(lines)
print(report)

try:
    import requests
    WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/8148922b-04f5-469f-994e-ae3e17d6b256'
    resp = requests.post(WEBHOOK, json={'msg_type': 'text', 'content': {'text': report}}, timeout=10)
    if resp.status_code == 200 and resp.json().get('code') == 0:
        print("\n✅ 飞书推送成功")
    else:
        print(f"\n❌ 推送失败: {resp.text[:100]}")
except Exception as e:
    print(f"\n❌ 推送异常: {e}")