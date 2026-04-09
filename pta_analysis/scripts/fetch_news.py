#!/usr/bin/env python3
"""PTA新闻抓取测试 - 新浪财经RSS扩展"""
import urllib.request, re, json
from html import unescape
from datetime import datetime

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def fetch_json(url):
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())
    except: return {}

def fetch_html(url):
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as r:
            raw = r.read()
            for enc in ['utf-8', 'gbk', 'gb2312']:
                try: return raw.decode(enc)
                except: pass
    except: return ''

def extract(text):
    data = {}
    text = re.sub(r'\s+', ' ', text)[:5000]
    
    # 降负
    for m in re.finditer(r'([\u4e00-\u9fa5A-Za-z]{2,8}(?:新材料|石化|化工|化纤|能源|总厂))\s*(\d+)\s*万吨?\s*(?:装置)?\s*降?\s*负?\s*(\d+)\s*%', text):
        if '降负' not in data: data['降负'] = []
        data['降负'].append(f"{m.group(1)}{m.group(2)}万吨降{m.group(3)}%")
    for m in re.finditer(r'([\u4e00-\u9fa5]{2,6}(?:新材料|石化|化工|化纤|总厂))\s*降\s*负\s*(\d+)\s*%', text):
        if '降负' not in data: data['降负'] = []
        data['降负'].append(f"{m.group(1)}降{m.group(2)}%")
    
    # 检修
    for m in re.finditer(r'([\u4e00-\u9fa5]{2,6}(?:新材料|石化|化工|化纤))\s*检修\s*(\d+)', text):
        if '检修' not in data: data['检修'] = []
        data['检修'].append(f"{m.group(1)}{m.group(2)}万吨")
    
    # 开工率
    for m in re.finditer(r'织机开工(?:率)?[^0-9]{0,8}(\d+(?:\.\d+)?)\s*%', text):
        data['织机开工'] = f"{m.group(1)}%"
    for m in re.finditer(r'开工(?:率)?[^0-9]{0,8}(\d+(?:\.\d+)?)\s*%\s*(?:负荷|开工)', text):
        if '开工率' not in data: data['开工率'] = f"{m.group(1)}%"
    
    # 价格
    for m in re.finditer(r'PTA[^0-9]{0,8}(\d{4})\s*元', text):
        data['PTA价格'] = f"¥{m.group(1)}/吨"
    for m in re.finditer(r'PX[^0-9]{0,8}(\d{3,4})\s*(?:元|美元)', text):
        if 'PX' not in data: data['PX价格'] = f"¥{m.group(1)}" + ('元/吨' if '元' in m.group(0) else '美元/吨')
    
    # 加工费
    for m in re.finditer(r'加工费[^0-9]{0,5}(\d{3,4})\s*元', text):
        data['加工费'] = f"{m.group(1)}元/吨"
    
    # 库存
    for m in re.finditer(r'库[存]*(?:量)?[^0-9]{0,5}(\d+(?:\.\d+)?)\s*(?:万吨|万手)', text):
        data['库存'] = f"{m.group(1)}万吨"
    for m in re.finditer(r'社会?库[存][^0-9]{0,5}(\d+)\s*(?:万吨|万手)', text):
        data['库存'] = f"{m.group(1)}万吨"
    
    # 下游
    for m in re.finditer(r'聚酯(?:长丝)?\s*[降减]\s*产\s*(\d+)\s*%', text):
        data['下游'] = f"聚酯降{m.group(1)}%"
    for m in re.finditer(r'长丝(?:大厂)?\s*[降减]\s*产\s*(\d+)\s*%', text):
        if '下游' not in data: data['下游'] = f"长丝降{m.group(1)}%"
    
    return data

queries = [
    ('PTA', 'PTA'), ('PX', 'PX'), ('聚酯', '聚酯'), ('织机', '织机'),
    ('加工费', '加工费'), ('检修', '检修'), ('PTA装置', 'PTA装置'), ('聚酯负荷', '聚酯负荷'),
]

seen = set()
articles = []
for label, kw in queries:
    url = f'https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&k={kw}&num=15'
    data = fetch_json(url)
    items = data.get('result', {}).get('data', [])
    for item in items[:12]:
        title = item.get('title', '')
        if title in seen: continue
        if not any(k in title for k in ['PTA', 'PX', '聚酯', '织机', '加工费', '检修', '降负', '停车', '库存', '下游', '长丝', '负荷']): continue
        seen.add(title)
        url_link = item.get('url', '')
        ct = item.get('ctime', '')
        dt = datetime.fromtimestamp(int(ct)).strftime('%m-%d %H:%M') if ct else ''
        
        structs = {}
        if url_link:
            html = fetch_html(url_link)
            if html:
                h = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
                h = re.sub(r'<style[^>]*>.*?</style>', '', h, flags=re.DOTALL)
                paras = re.findall(r'<p[^>]*>(.*?)</p>', h, flags=re.DOTALL)
                text = ' '.join([unescape(re.sub(r'<[^>]+>', '', p)) for p in paras])
                structs = extract(text[:3000])
        
        articles.append({'keyword': label, 'datetime': dt, 'title': title, 'url': url_link, 'data': structs})

articles.sort(key=lambda x: x['datetime'], reverse=True)
print(f"=== 新浪财经PTA快讯 {datetime.now().strftime('%m-%d %H:%M')} ===\n")
print(f"共 {len(articles)} 篇相关文章\n")

has_data = [a for a in articles if a['data']]
print(f"有结构化数据: {len(has_data)}篇\n")

for a in articles[:15]:
    print(f"[{a['keyword']}] {a['datetime']} {a['title'][:60]}")
    if a['data']:
        for k, v in a['data'].items():
            print(f"    {k}: {v}")
    print()

# 保存到文件
with open('/tmp/news_result.txt', 'w') as f:
    f.write(f"=== 新浪财经PTA快讯 {datetime.now().strftime('%m-%d %H:%M')} ===\n")
    f.write(f"共 {len(articles)} 篇相关文章，有数据: {len(has_data)}篇\n\n")
    for a in articles[:20]:
        f.write(f"[{a['datetime']}] {a['title'][:60]}\n")
        if a['data']:
            for k, v in a['data'].items():
                f.write(f"    {k}: {v}\n")
        f.write('\n')
print("结果已保存到 /tmp/news_result.txt")