#!/usr/bin/env python3
"""PTA新闻多源抓取 v2
数据源:
1. 东方财富PTA专属板块 (futures.eastmoney.com/news/apta.html) - 20篇/天
2. 东方财富快讯首页 (finance.eastmoney.com/a/) - 宏观地缘
3. 东方财富期货早餐 (finance.eastmoney.com/a/日期) - 日度总结
4. 新浪财经搜索 (search.sina.com.cn) - 被封时跳过
5. 360搜索 (so.com) - 备选搜索源
"""
import urllib.request, re, urllib.parse, json
from html import unescape
from datetime import datetime, timedelta

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def fetch(url, enc='utf-8', timeout=10):
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode(enc, errors='replace')
    except: return ''

def extract(text):
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

    # 开工率
    for m in re.finditer(r'织机开工[^0-9]{0,8}(\d+(?:\.\d+)?)\s*%', text):
        data['织机开工'] = f"{m.group(1)}%"
    for m in re.finditer(r'聚酯[^0-9]{0,8}?负荷[^0-9]{0,8}(\d+(?:\.\d+)?)\s*%', text):
        data['聚酯负荷'] = f"{m.group(1)}%"
    for m in re.finditer(r'开工(?:率)?[^0-9]{0,8}(\d+(?:\.\d+)?)\s*%\s*(?:负荷|开工)', text):
        if '开工率' not in data: data['开工率'] = f"{m.group(1)}%"

    # PTA价格
    for m in re.finditer(r'PTA[^0-9]{0,10}(\d{4})\s*元', text):
        data['PTA价格'] = f"¥{m.group(1)}/吨"
    for m in re.finditer(r'PTA[^0-9]{0,10}(\d{4})', text):
        if 'PTA价格' not in data and 4500 <= int(m.group(1)) <= 8000:
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

def fetch_article_text(url):
    html = fetch(url)
    if not html: return ''
    h = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    h = re.sub(r'<style[^>]*>.*?</style>', '', h, flags=re.DOTALL)
    paras = re.findall(r'<p[^>]*>(.*?)</p>', h, flags=re.DOTALL)
    return ' '.join([unescape(re.sub(r'<[^>]+>', '', p)) for p in paras])

def get_article_links(url, min_len=15):
    """从列表页获取文章链接"""
    html = fetch(url)
    if not html: return []
    links = re.findall(r'<a[^>]+href="(https?://[^\"]{10,})"[^>]*>(.*?)</a>', html, flags=re.DOTALL)
    arts = []
    for href, title_raw in links:
        title = unescape(re.sub(r'<[^>]+>', '', title_raw)).strip()
        if len(title) > min_len and ('a/20' in href or '/a/20' in href):
            arts.append((href, title))
    # 去重
    seen = set()
    result = []
    for href, title in arts:
        if href not in seen:
            seen.add(href)
            result.append((href, title))
    return result

def search_360(kw):
    """360搜索"""
    encoded = urllib.parse.quote(kw)
    url = f'https://www.so.com/s?q={encoded}&pn=1&rn=10'
    html = fetch(url)
    if not html: return []
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
    items = re.findall(r'<h3[^>]*><a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a></h3>', html, flags=re.DOTALL)
    results = []
    for href, title_raw in items:
        title = unescape(re.sub(r'<[^>]+>', '', title_raw)).strip()
        if len(title) > 5:
            results.append((href, title))
    return results

# ============================================================
# 主流程
# ============================================================
print(f"=== 多源PTA新闻抓取 {datetime.now().strftime('%m-%d %H:%M')} ===\n")

all_articles = []
seen_urls = set()

# 源1: 东方财富PTA资讯板块
print("[1/4] 东方财富PTA资讯...")
links = get_article_links('http://futures.eastmoney.com/news/apta.html')
print(f"  获取 {len(links)} 篇")
for href, title in links[:15]:
    if href not in seen_urls:
        seen_urls.add(href)
        all_articles.append({'source': '东方财富PTA资讯', 'title': title, 'url': href})

# 源2: 东方财富PTA评论板块
print("[2/4] 东方财富PTA评论...")
links2 = get_article_links('http://futures.eastmoney.com/news/aptapl.html')
print(f"  获取 {len(links2)} 篇")
for href, title in links2[:15]:
    if href not in seen_urls:
        seen_urls.add(href)
        all_articles.append({'source': '东方财富PTA评论', 'title': title, 'url': href})

# 源3: 东方财富期货早餐(今日)
print("[3/4] 东方财富期货早餐...")
today = datetime.now().strftime('%Y%m%d')
for date in [today, (datetime.now()-timedelta(days=1)).strftime('%Y%m%d')]:
    url = f'https://finance.eastmoney.com/a/2026{date[4:]}.html'
    html = fetch(url)
    if html and len(html) > 1000:
        links3 = get_article_links(url)
        print(f"  {date}: {len(links3)} 篇")
        for href, title in links3[:5]:
            if href not in seen_urls and any(k in title for k in ['PTA', 'PTA', '聚酯', '织机', 'PX', '原油']):
                seen_urls.add(href)
                all_articles.append({'source': '东方财富期货早餐', 'title': title, 'url': href})
        break

# 源4: 360搜索备选
print("[4/4] 360搜索...")
kw_map = {'PTA': 'PTA 聚酯', 'PX': 'PX对二甲苯', '织机': '织机开工率'}
for kw_label, kw in kw_map.items():
    try:
        results = search_360(kw)
        count = 0
        for href, title in results:
            if href not in seen_urls and ('PTA' in title or '聚酯' in title or 'PX' in title):
                seen_urls.add(href)
                all_articles.append({'source': f'360搜索({kw_label})', 'title': title, 'url': href})
                count += 1
        print(f"  {kw_label}: {count} 条新增")
    except Exception as e:
        print(f"  {kw_label}失败: {e}")

print(f"\n共获取 {len(all_articles)} 篇文章，开始抓取正文...\n")

# 抓取正文
articles_with_data = []
for item in all_articles:
    text = fetch_article_text(item['url'])
    data = extract(text)
    item['data'] = data
    item['text_preview'] = text[:150].strip() if text else ''
    if data:
        articles_with_data.append(item)

# 按数据丰富程度排序
all_articles.sort(key=lambda x: len(x['data']), reverse=True)

print(f"=== 结果: {len(all_articles)}篇 total, {len(articles_with_data)}篇含数据 ===\n")

for a in all_articles[:15]:
    print(f"[{a['source']}] {a['title'][:55]}")
    if a['data']:
        for k, v in a['data'].items():
            print(f"    {k}: {v}")
    elif a['text_preview']:
        print(f"    (无提取数据,摘要:) " + a['text_preview'][:80])
    print()

# 保存结果
with open('/tmp/multi_news_result.txt', 'w') as f:
    f.write(f"=== 多源PTA新闻 {datetime.now().strftime('%m-%d %H:%M')} ===\n")
    f.write(f"共 {len(all_articles)} 篇, 含数据 {len(articles_with_data)} 篇\n\n")
    for a in all_articles:
        f.write(f"[{a['source']}] {a['title']}\n")
        if a['data']:
            for k, v in a['data'].items():
                f.write(f"  {k}: {v}\n")
        f.write('\n')

print(f"\n结果已保存. 含数据文章: {len(articles_with_data)}篇")
if articles_with_data:
    print("数据摘要:")
    merged = {}
    for a in articles_with_data:
        for k, v in a['data'].items():
            if k not in merged:
                merged[k] = v
    for k, v in merged.items():
        print(f"  {k}: {v}")