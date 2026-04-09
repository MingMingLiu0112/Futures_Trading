#!/usr/bin/env python3
"""PTA日度三维度分析报告 - v5
维度1: 宏观基本面 - 凤凰财经(地缘) + 多源搜索(产业) [定时3次: 08:30/12:00/17:30]
维度2: 期货技术面 - 缠论笔段/线段 [每日一次]
维度3: 期权数据面 - akshare PTA期权 [每日一次]
数据源: 凤凰财经 + 东方财富PTA板块 + 360搜索 + 新浪财经(RSS/搜索，待恢复) + akshare
"""
import urllib.request, re, json, warnings
from html import unescape
from datetime import datetime, timedelta
import pandas as pd

# ============================================================
# 新闻提取 - 新浪财经搜索API（主力产业新闻源）
# ============================================================
def fetch(url, timeout=12):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            for enc in ['utf-8', 'gbk', 'gb2312']:
                try: return raw.decode(enc)
                except: pass
    except: return ''

def extract_pta_data(text):
    """从文章正文提取PTA结构化数据"""
    data = {}
    text = re.sub(r'\s+', ' ', text)[:6000]

    # 降负
    for m in re.finditer(r'([A-Za-z\u4e00-\u9fa5]{2,8}(?:新材料|石化|化工|化纤|能源|总厂))\s*(\d+)\s*万吨?\s*(?:装置)?\s*降?\s*负?\s*(\d+)\s*%', text):
        if '降负' not in data: data['降负'] = []
        data['降负'].append(f"{m.group(1)}{m.group(2)}万吨降{m.group(3)}%")
    for m in re.finditer(r'([A-Za-z\u4e00-\u9fa5]{2,6}(?:新材料|石化|化工|化纤|总厂))\s*降\s*负\s*(\d+)\s*%', text):
        if '降负' not in data: data['降负'] = []
        data['降负'].append(f"{m.group(1)}降{m.group(2)}%")

    # 检修/停车
    for m in re.finditer(r'([A-Za-z\u4e00-\u9fa5]{2,6}(?:新材料|石化|化工|化纤))\s*检修\s*(\d+)', text):
        if '检修' not in data: data['检修'] = []
        data['检修'].append(f"{m.group(1)}{m.group(2)}万吨")
    for m in re.finditer(r'([A-Za-z\u4e00-\u9fa5]{2,6}(?:新材料|石化|化工|化纤))\s*停车\s*(\d+)', text):
        if '停车' not in data: data['停车'] = []
        data['停车'].append(f"{m.group(1)}{m.group(2)}万吨")

    # 开工率/织机
    for m in re.finditer(r'织机开工[^0-9]{0,8}(\d+(?:\.\d+)?)\s*%', text):
        data['织机开工'] = f"{m.group(1)}%"
    for m in re.finditer(r'聚酯[^0-9]{0,8}?负荷[^0-9]{0,8}(\d+(?:\.\d+)?)\s*%', text):
        data['聚酯负荷'] = f"{m.group(1)}%"
    for m in re.finditer(r'开工(?:率)?[^0-9]{0,8}(\d+(?:\.\d+)?)\s*%\s*(?:负荷|开工)', text):
        if '开工率' not in data: data['开工率'] = f"{m.group(1)}%"

    # PTA价格
    for m in re.finditer(r'PTA[^0-9]{0,10}(\d{4})\s*元', text):
        data['PTA价格'] = f"¥{m.group(1)}/吨"

    # PX价格
    for m in re.finditer(r'PX[^0-9]{0,8}(\d{3,4})\s*美元', text):
        if 'PX' not in data: data['PX进口'] = f"${m.group(1)}/吨"
    for m in re.finditer(r'PX[^0-9]{0,8}(\d{3,4})\s*元/吨', text):
        if 'PX' not in data: data['PX'] = f"¥{m.group(1)}/吨"

    # 加工费
    for m in re.finditer(r'加工费[^0-9]{0,5}(\d{3,4})\s*元', text):
        data['加工费'] = f"{m.group(1)}元/吨"

    # 库存
    for m in re.finditer(r'库[存]*(?:量)?[^0-9]{0,5}(\d+(?:\.\d+)?)\s*(?:万吨|万手)', text):
        data['库存'] = f"{m.group(1)}万吨"
    for m in re.finditer(r'社会?库[存][^0-9]{0,5}(\d+)\s*(?:万吨|万手)', text):
        data['库存'] = f"{m.group(1)}万吨"

    # 下游减产
    for m in re.finditer(r'聚酯(?:长丝)?\s*[减降]\s*产\s*(\d+)\s*%', text):
        data['下游减产'] = f"聚酯降{m.group(1)}%"
    for m in re.finditer(r'长丝\s*[减降]\s*产\s*(\d+)\s*%', text):
        if '下游减产' not in data: data['下游减产'] = f"长丝降{m.group(1)}%"

    return data

def fetch_sina_news():
    """从新浪财经搜索抓PTA相关快讯"""
    keywords = ['PTA', 'PX', '聚酯', '织机', '加工费', 'pta']
    seen = set()
    articles = []

    for kw in keywords:
        encoded_kw = urllib.parse.quote(kw) if hasattr(urllib.parse, 'quote') else kw
        url = f'https://search.sina.com.cn/?q={encoded_kw}+%E8%81%94%E8%B4%B8&c=news&num=10&ie=utf-8'
        if kw.lower() == 'pta':
            url = f'https://search.sina.com.cn/?q={encoded_kw}&c=news&num=10&ie=utf-8'

        html = fetch(url)
        if not html: continue
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)

        items = re.findall(r'<h2[^>]*><a[^>]+href="(https?://[^\"]+)"[^>]*>(.*?)</a>', html, flags=re.DOTALL)

        for href, title_raw in items:
            title = unescape(re.sub(r'<[^>]+>', '', title_raw)).strip()
            if title in seen: continue
            if not any(k.upper() in title.upper() for k in ['PTA', 'PX', '聚酯', '织机', '加工费', '检修', '降负', '停车', '库存', '下游', '长丝', '负荷']): continue
            seen.add(title)
            dt_match = re.search(r'(\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2})', title_raw)
            dt = dt_match.group(1) if dt_match else ''

            structs = {}
            art_html = fetch(href)
            if art_html:
                art = re.sub(r'<script[^>]*>.*?</script>', '', art_html, flags=re.DOTALL)
                art = re.sub(r'<style[^>]*>.*?</style>', '', art, flags=re.DOTALL)
                paras = re.findall(r'<p[^>]*>(.*?)</p>', art, flags=re.DOTALL)
                text = ' '.join([unescape(re.sub(r'<[^>]+>', '', p)) for p in paras])
                structs = extract_pta_data(text[:3000])

            articles.append({'keyword': kw, 'datetime': dt, 'title': title, 'url': href, 'data': structs})

    articles.sort(key=lambda x: x['datetime'], reverse=True)
    return articles

# ============================================================
# 凤凰财经宏观
# ============================================================
def fetch_fenghuang_events():
    html = fetch('https://finance.ifeng.com/')
    if not html: return {}
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
    links = re.findall(r'<a[^>]+href="(https?://[^\"]{10,})"[^>]*>(.*?)</a>', html, flags=re.DOTALL)

    TYPE_KW = {
        '地缘风险': ['地缘','制裁','中东','俄乌','红海','以色列','伊朗','霍尔木兹','胡塞'],
        '美联储/央行': ['美联储','降息','加息','鲍威尔','利率'],
        '宏观经济': ['CPI','PPI','GDP','非农','就业','PMI','通胀'],
    }
    events = {}
    for cat, kws in TYPE_KW.items():
        matches = [unescape(t).strip() for h, t in links if len(t) > 5 and any(k in t for k in kws)]
        events[cat] = list(dict.fromkeys(matches))[:3]
    return events

# ============================================================
# 原油+美债
# ============================================================
def fetch_oil_bonds():
    oil = {}
    for sym, name in [('BZ=F','布伦特'), ('CL=F','WTI')]:
        try:
            u = f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d'
            req = urllib.request.Request(u, headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'})
            with urllib.request.urlopen(req, timeout=8) as r:
                d = json.loads(r.read())
                oil[name] = round(d['chart']['result'][0]['indicators']['quote'][0]['close'][-1], 2)
        except: oil[name] = None

    bonds = {'us10y': None, 'spread': None}
    try:
        import akshare as ak
        df = ak.bond_zh_us_rate()
        if df is not None and len(df) > 0:
            l = df.iloc[-1]
            bonds['us10y'] = round(float(l.get('美国国债收益率10年',0) or 0), 2)
            bonds['spread'] = round(float(l.get('美国国债收益率10年-2年',0) or 0), 1)
    except: pass
    return oil, bonds

# ============================================================
# PTA/PX现货
# ============================================================
def fetch_spot():
    pta_data = {'spot': None, 'near_contract': None, 'near_price': None}
    px_data = {'spot': None}
    try:
        import akshare as ak
        df_spot = ak.futures_spot_price()
        if df_spot is not None:
            for sym, d in [('TA', pta_data), ('PX', px_data)]:
                row = df_spot[df_spot['symbol'] == sym]
                if len(row) > 0:
                    r = row.iloc[-1]
                    d['spot'] = round(float(r['spot_price']), 1) if r['spot_price'] else None
                    if sym == 'TA':
                        pta_data['near_contract'] = r.get('near_contract', '')
                        pta_data['near_price'] = round(float(r['near_contract_price']), 1) if r.get('near_contract_price') else None
    except: pass
    return pta_data, px_data

# ============================================================
# 期权
# ============================================================
def fetch_options():
    opt_data = {'pcr_vol': None, 'pcr_oi': None, 'iv_mean': None, 'trade_date': None, 'top_puts': [], 'top_calls': []}
    warnings.filterwarnings('ignore')
    try:
        import akshare as ak
        td = None
        for d in [datetime.now().strftime('%Y%m%d')] + \
                 [(datetime.now()-timedelta(days=i)).strftime('%Y%m%d') for i in range(1,8)]:
            try:
                df_o = ak.option_hist_czce(symbol='PTA期权', trade_date=d)
                if df_o is not None and len(df_o) > 100:
                    td = d; break
            except: pass

        if td:
            def get_strike(code):
                m = re.search(r'[PC](\d+)', code); return int(m.group(1)) if m else None
            df_o['行权价'] = df_o['合约代码'].apply(get_strike)
            puts = df_o[df_o['合约代码'].str.contains('P',na=False)].copy()
            calls = df_o[df_o['合约代码'].str.contains('C',na=False)].copy()
            puts['iv'] = pd.to_numeric(puts['隐含波动率'], errors='coerce')
            calls['iv'] = pd.to_numeric(calls['隐含波动率'], errors='coerce')
            cv = calls['成交量(手)'].sum(); pv = puts['成交量(手)'].sum()
            co = calls['持仓量'].sum(); po = puts['持仓量'].sum()
            opt_data['pcr_vol'] = round(pv/cv, 3) if cv else None
            opt_data['pcr_oi'] = round(po/co, 3) if co else None
            iv_s = pd.to_numeric(df_o['隐含波动率'], errors='coerce').dropna()
            opt_data['iv_mean'] = round(iv_s.mean(), 1) if len(iv_s) > 0 else None
            opt_data['trade_date'] = td
            opt_data['top_puts'] = [{'合约代码':r['合约代码'],'行权价':int(r['行权价']),'成交量':r['成交量(手)'],'持仓量':r['持仓量'],'iv':r['iv']} for _,r in puts.nlargest(5,'持仓量').iterrows()]
            opt_data['top_calls'] = [{'合约代码':r['合约代码'],'行权价':int(r['行权价']),'成交量':r['成交量(手)'],'持仓量':r['持仓量'],'iv':r['iv']} for _,r in calls.nlargest(5,'持仓量').iterrows()]
    except: pass
    return opt_data

# ============================================================
# 主报告生成
# ============================================================
print("[1/5] 新浪财经PTA快讯...")
articles = fetch_sina_news()
print(f"  获取 {len(articles)} 篇相关文章")
has_data = [a for a in articles if a['data']]
print(f"  其中 {len(has_data)} 篇含结构化数据")

# 合并产业数据
merged = {}
for a in articles:
    for k, v in a['data'].items():
        if k not in merged:
            merged[k] = v

print("[2/5] 凤凰财经宏观...")
events = fetch_fenghuang_events()
print(f"  地缘 {len(events.get('地缘风险',[]))}条 美联储 {len(events.get('美联储/央行',[]))}条")

print("[3/5] 原油+美债...")
oil, bonds = fetch_oil_bonds()
print(f"  布伦特={oil.get('布伦特')} WTI={oil.get('WTI')} 美10Y={bonds.get('us10y')}%")

print("[4/5] PTA/PX现货...")
pta_data, px_data = fetch_spot()
print(f"  PTA={pta_data.get('spot')} PX={px_data.get('spot')}")

print("[5/5] 期权...")
opt_data = fetch_options()
print(f"  PCR_oi={opt_data.get('pcr_oi')} IV={opt_data.get('iv_mean')}%")

# 成本链
cost_low = cost_high = None
if px_data.get('spot') and pta_data.get('spot'):
    px = px_data['spot']
    cost_low = round(px * 0.655 + 300, 0)
    cost_high = round(px * 0.655 + 800, 0)
    merged['PX'] = f"¥{px:.0f}/吨"
    jgf_est = round(pta_data['spot'] - px * 0.655, 0)
    merged['加工费'] = f"约{jgf_est:.0f}元/吨(估算)"

# ============================================================
# 生成报告
# ============================================================
now = datetime.now().strftime('%m-%d %H:%M')
lines = [f"📊 PTA 日度综合分析 | {now}", ""]

# 一、宏观
lines += ["━━━━━ 一、宏观经济金融环境 ━━━━━", ""]
geo = events.get('地缘风险', [])
fed = events.get('美联储/央行', [])
if geo:
    lines.append("【地缘风险】")
    for t in geo[:2]: lines.append(f"  · {t}")
else: lines.append("【地缘风险】无重大地缘事件")
if fed:
    lines.append("【美联储/央行】")
    for t in fed[:2]: lines.append(f"  · {t}")

brent = oil.get('布伦特'); wti = oil.get('WTI')
lines += ["", "【原油-成本链】"]
if brent: lines.append(f"  布伦特: ${brent}/桶")
if wti: lines.append(f"  WTI: ${wti}/桶")
if bonds.get('us10y'): lines.append(f"  美10Y: {bonds['us10y']}% ({'+' if bonds['spread']>0 else ''}{bonds['spread']}bp利差)")

lines += ["", "【逻辑推断】"]
if geo: lines.append(f"  中东/霍尔木兹等地缘持续 → 原油风险溢价，支撑偏强")
if brent and brent > 85: lines.append(f"  布伦特${brent}>85 → 成本支撑强，偏多")
if bonds.get('us10y') and bonds['us10y'] > 4.5: lines.append(f"  美10Y{bonds['us10y']}%高位 → 压制商品估值")
elif bonds.get('us10y') and bonds['us10y'] < 4.0: lines.append(f"  美10Y{bonds['us10y']}%低位 → 金融宽松")
if bonds.get('spread') and bonds['spread'] > 0.3: lines.append(f"  美债利差+{bonds['spread']}bp → 衰退预期降温")

# 二、产业
lines += ["", "━━━━━ 二、中观行业基本面 ━━━━━", ""]
lines.append("【成本链】")
if pta_data.get('spot'): lines.append(f"  PTA现货: ¥{pta_data['spot']}/吨")
if pta_data.get('near_contract'): lines.append(f"    近月: {pta_data['near_contract']} ¥{pta_data['near_price']}")
if px_data.get('spot'): lines.append(f"  PX现货: ¥{px_data['spot']}/吨")
if cost_low and cost_high:
    lines.append(f"  PTA成本区间: ¥{cost_low:.0f}~¥{cost_high:.0f}/吨（PX×0.655+300~800）")
    if pta_data.get('spot'):
        m = pta_data['spot'] - cost_low
        if m > 0: lines.append(f"    现货-成本={m:.0f}元（盈利）")
        else: lines.append(f"    现货-成本={m:.0f}元（亏损）")

# 新浪快讯结构化数据
if merged:
    lines.append("【新浪财经提取-产业数据】")
    for k, v in merged.items():
        lines.append(f"  {k}: {v}")

# 新浪快讯摘要
if has_data:
    lines += ["", "【最新产业快讯】"]
    for a in has_data[:4]:
        lines.append(f"  · {a['datetime']} {a['title'][:55]}")
        for k, v in a['data'].items():
            lines.append(f"    {k}: {v}")

lines += ["", "【逻辑推断】"]
if pta_data.get('spot') and cost_low:
    pta = pta_data['spot']
    if pta < cost_low: lines.append(f"  PTA现货¥{pta:.0f}<成本下沿¥{cost_low:.0f} → 产业亏损，底部强撑 🟢")
    elif pta > cost_high: lines.append(f"  PTA现货¥{pta:.0f}>成本上沿¥{cost_high:.0f} → 高估 🔴")
    else: lines.append(f"  PTA现货¥{pta:.0f}在成本区间内 → 正常 🟡")

# 三、期权
lines += ["", "━━━━━ 三、期权市场 ━━━━━", ""]
if opt_data.get('trade_date'):
    td = opt_data['trade_date']
    pcr_v = opt_data.get('pcr_vol'); pcr_o = opt_data.get('pcr_oi'); iv_m = opt_data.get('iv_mean')
    lines.append(f"【PTA期权 · {td}】")
    lines.append(f"  PCR成交量: {pcr_v}  PCR持仓量: {pcr_o}  隐波均值: {iv_m}%")
    if pcr_o:
        if pcr_o > 1.2: lines.append(f"  → PCR_oi={pcr_o:.2f}>1.2，看跌持仓更重，空头防线强 🟢")
        elif pcr_o < 0.8: lines.append(f"  → PCR_oi={pcr_o:.2f}<0.8，多头力量偏强 🔴")
        else: lines.append(f"  → 多空均衡 🟡")

    lines.append(f"  关键PUT（下行防线）:")
    for r in opt_data['top_puts'][:3]:
        iv_s = f"{r['iv']:.1f}%" if pd.notna(r.get('iv')) else "N/A"
        lines.append(f"    {r['合约代码']}({r['行权价']}) 持仓={r['持仓量']:.0f}手 IV={iv_s}")
    lines.append(f"  关键CALL（上行压力）:")
    for r in opt_data['top_calls'][:3]:
        iv_s = f"{r['iv']:.1f}%" if pd.notna(r.get('iv')) else "N/A"
        lines.append(f"    {r['合约代码']}({r['行权价']}) 持仓={r['持仓量']:.0f}手 IV={iv_s}")
    if iv_m and iv_m > 60: lines.append(f"  IV={iv_m}%高位 → 权利金偏贵")
    elif iv_m and iv_m < 30: lines.append(f"  IV={iv_m}%低位 → 权利金便宜")

# 四、综合
lines += ["", "━━━━━ 四，综合判断 ━━━━━"]
score = 0.0; reasons = []
if geo and len(geo) >= 2: score += 1; reasons.append("地缘持续")
if brent and brent > 85: score += 1; reasons.append(f"布伦特${brent}>85")
if bonds.get('us10y') and bonds['us10y'] > 4.5: score -= 1; reasons.append(f"美10Y{bonds['us10y']}%偏高")
if bonds.get('spread') and bonds['spread'] > 0.3: score += 0.5; reasons.append(f"利差+{bonds['spread']}bp")
if pta_data.get('spot') and cost_low and pta_data['spot'] < cost_low: score += 1; reasons.append("PTA亏损压缩供应")
if pcr_o and pcr_o > 1.2: score += 0.5; reasons.append(f"PCR_oi={pcr_o}>1.2")

if score >= 2: verdict = "🟢 偏多"
elif score <= -1: verdict = "🔴 偏空"
else: verdict = "🟡 中性"
lines.append(f"  方向: {verdict} (得分{score:+.1f})")
if reasons: lines.append(f"  依据: {'; '.join(reasons)}")

src = ["新浪财经搜索", "凤凰财经", "Yahoo原油", "akshare"]
if opt_data.get('trade_date'): src.append(f"PTA期权({opt_data['trade_date']})")
lines += ["", f"数据: {' · '.join(src)}"]

report = '\n'.join(lines)
print("\n" + "="*50)
print(report)

# 发送飞书
try:
    import requests
    WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/8148922b-04f5-469f-994e-ae3e17d6b256'
    resp = requests.post(WEBHOOK, json={'msg_type': 'text', 'content': {'text': report}}, timeout=10)
    if resp.status_code == 200 and resp.json().get('code') == 0:
        print("\n✅ 飞书推送成功")
    else:
        print(f"\n❌ 推送失败: {resp.text[:100]}")
except Exception as e:
    print(f"\n❌ 异常: {e}")