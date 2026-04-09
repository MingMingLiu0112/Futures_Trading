#!/usr/bin/env python3
"""
PTA 宏观分析数据抓取 - v2
来源：Yahoo Finance（原油）、akshare（债券）、18qh（产业）
"""

import re, urllib.request, json, time
from html import unescape
from datetime import datetime

FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/8148922b-04f5-469f-994e-ae3e17d6b256'
APP_ID = 'cli_a93a74737d7a5cc0'
APP_SECRET = 'ITgEfB7XN07z69JfadO06dfcPfZ5ylw6'

def fetch(url, headers=None, timeout=12):
    h = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', 'Accept': 'text/html,application/xhtml+xml'}
    if headers: h.update(headers)
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            for enc in ['utf-8', 'gbk', 'gb2312', 'gb18030']:
                try: return raw.decode(enc)
                except: pass
            return raw.decode('utf-8', errors='replace')
    except Exception as e:
        return f"ERROR: {e}"

def get_text(url):
    text = fetch(url)
    if text.startswith('ERROR'): return ''
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
    paras = re.findall(r'<p[^>]*>(.*?)</p>', text, flags=re.DOTALL)
    if not paras: return ''
    text = ' '.join([unescape(re.sub(r'<[^>]+>', ' ', p)) for p in paras])
    return re.sub(r'\s+', ' ', text).strip()

# ===== 1. 原油价格 =====
def get_oil_prices():
    result = {}
    # WTI
    try:
        url = 'https://query1.finance.yahoo.com/v8/finance/chart/CL%3DF?interval=1d&range=5d'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            result['wti'] = data['chart']['result'][0]['indicators']['quote'][0]['close'][-1]
    except: pass
    # Brent
    try:
        url = 'https://query1.finance.yahoo.com/v8/finance/chart/BZ%3DF?interval=1d&range=5d'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            result['brent'] = data['chart']['result'][0]['indicators']['quote'][0]['close'][-1]
    except: pass
    return result

# ===== 2. 美债收益率 =====
def get_bond_yields():
    result = {}
    try:
        import akshare as ak
        df = ak.bond_zh_us_rate()
        if df is not None and len(df) > 0:
            latest = df.iloc[-1]
            result['us10y'] = float(latest.get('最新价', latest.get('收益率', 0)))
            result['cn10y'] = float(latest.get('最新价_0', 0))
    except: pass
    return result

# ===== 3. 美元指数 =====
def get_dxy():
    try:
        url = 'https://query1.finance.yahoo.com/v8/finance/chart/DXY?interval=1d&range=5d'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            return data['chart']['result'][0]['indicators']['quote'][0]['close'][-1]
    except: return None

# ===== 4. 18qh产业数据 =====
def get_18qh_data():
    result = {'articles': []}
    text = get_text('https://www.18qh.com/zixun/')
    if not text:
        return result
    # 提取关键句子
    key_kws = ['PTA', '开工', '库存', '检修', '下游', '订单', '成本', '加工费', '仓单', '原油', 'PX', '织造', '聚酯']
    sents = [s.strip() for s in re.split(r'[。；]', text) if len(s.strip()) > 15 and any(k in s for k in key_kws)]
    result['articles'] = sents[:20]
    # 提取数值
    nums = re.findall(r'PTA[^0-9]{0,5}?(\d{3,5})', text)
    return result

# ===== 5. 18qh PTA期货行情 =====
def get_18qh_pta():
    result = {}
    text = get_text('https://www.18qh.com/zixun/')
    if not text:
        return result
    # 找价格相关
    prices = re.findall(r'(?:PTA|pta)[^0-9]{0,5}?(\d{3,5}(?:\.\d+)?)', text)
    return result

# ===== 6. 抓18qh文章找开工率库存 =====
def scrape_18qh_pta_articles():
    """从18qh抓PTA相关文章提取关键数据"""
    articles_text = get_text('https://www.18qh.com/zixun/')
    if not articles_text:
        return {}
    html = fetch('https://www.18qh.com/zixun/')
    articles = re.findall(r'<a[^>]+href="(https://www\.18qh\.com/zixun/c-\d{4}-\d{2}-\d{2}-\d+\.html)"[^>]*>([^<]+)</a>', html)
    key_data = {}
    key_kws = ['开工', '库存', '加工费', '仓单', '检修', '停车', '下游', '订单']
    for url, title in articles[:30]:
        t = title.strip()
        if any(k in t for k in ['PTA', 'PX', '聚酯']):
            art_text = get_text(url)
            if not art_text: continue
            for kw in key_kws:
                if kw in art_text:
                    # 提取数值
                    if kw == '开工':
                        m = re.search(r'(\d+(?:\.\d+)?)\s*%\s*(?:开工|负荷)', art_text)
                        if m: key_data['开工率'] = f"{m.group(1)}%"
                    elif kw == '库存':
                        m = re.search(r'库[存率]*[^：:：]*?[:：\s]+(\d+(?:\.\d+)?)\s*%?', art_text)
                        if m: key_data['库存'] = m.group(1)
                    elif kw == '加工费':
                        m = re.search(r'加工[费]*[^0-9]{0,3}(\d+)', art_text)
                        if m: key_data['加工费'] = f"{m.group(1)}元/吨"
    return key_data

# ===== 发送飞书消息 =====
def send_feishu(msg):
    try:
        import requests
        requests.post(FEISHU_WEBHOOK, json=msg, timeout=10)
    except: pass

def send_text(text):
    send_feishu({'msg_type': 'text', 'text': {'content': text}})

def send_image(img_key):
    send_feishu({'msg_type': 'image', 'image': {'image_key': img_key}})

def upload_image(path):
    try:
        import requests
        r = requests.post('https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
            json={'app_id': APP_ID, 'app_secret': APP_SECRET}, timeout=10)
        token = r.json().get('tenant_access_token', '')
        with open(path, 'rb') as f:
            files = {'image': (path.split('/')[-1], f, 'image/png')}
            data = {'image_type': 'message'}
            r2 = requests.post('https://open.feishu.cn/open-apis/im/v1/images',
                headers={'Authorization': f'Bearer {token}'}, data=data, files=files, timeout=30)
        return r2.json().get('data', {}).get('image_key', '')
    except: return ''

# ===== 主程序 =====
def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始抓取宏观数据...")
    
    # 1. 原油
    oil = get_oil_prices()
    brent = oil.get('brent', 'N/A')
    wti = oil.get('wti', 'N/A')
    print(f"  原油: WTI=${wti} Brent=${brent}")
    
    # 2. 美债
    bonds = get_bond_yields()
    us10y = bonds.get('us10y', 'N/A')
    cn10y = bonds.get('cn10y', 'N/A')
    print(f"  美债: US10Y={us10y}% CN10Y={cn10y}%")
    
    # 3. 美元指数
    dxy = get_dxy()
    print(f"  美元指数: {dxy}")
    
    # 4. 18qh产业数据
    industry = scrape_18qh_pta_articles()
    print(f"  产业数据: {industry}")
    
    # 组装报告
    lines = [
        f"📊 PTA 宏观速报 | {datetime.now().strftime('%m-%d %H:%M')}",
        "",
        "🌍 宏观金融",
        f"  布伦特原油: ${brent}/桶" if isinstance(brent, float) else f"  布伦特原油: {brent}",
        f"  WTI原油: ${wti}/桶" if isinstance(wti, float) else f"  WTI原油: {wti}",
        f"  美元指数: {dxy:.2f}" if isinstance(dxy, float) else f"  美元指数: {dxy}",
        f"  美10Y: {us10y}%" if isinstance(us10y, float) else f"  美10Y: {us10y}%",
        "",
        "🏭 PTA产业",
    ]
    for k, v in industry.items():
        lines.append(f"  {k}: {v}")
    
    report = '\n'.join(lines)
    print(report)
    send_text(report)

if __name__ == '__main__':
    main()
