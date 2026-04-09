#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA宏观面新闻采集模块 v2
========================
从18期货网抓取PTA相关资讯，提取关键宏观驱动因素：
  - 地缘风险（中东/红海/俄乌）
  - 原油/布伦特走势
  - PX供应与PTA加工费
  - 下游需求（聚酯/纺织）
  - 期货持仓/仓单数据

流程：列表页 → 过滤PTA文章 → 抓正文 → 提取关键数据 → 生成宏观摘要
"""

import os
import re
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from html import unescape

WORKSPACE = "/home/admin/.openclaw/workspace/codeman/pta_analysis"

# PTA相关关键词（标题/正文匹配）
PTA_KEYWORDS = ["PTA", "精对苯二甲酸", "原油", "布伦特", "PX", "PXN", "聚酯", "纺织", "中东", "红海", "俄乌", " OPEC", "地缘", "加工费", "仓单", "持仓", "检修", "减产", "升水", "贴水"]
GEO_KEYWORDS = ["中东", "红海", "俄乌", "以色列", "沙特", "俄罗斯", " OPEC", "地缘", "冲突", "制裁"]


def fetch_html(url, timeout=12):
    """抓取HTML，处理编码"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            for enc in ["utf-8", "gbk", "gb2312", "gb18030"]:
                try:
                    return raw.decode(enc)
                except Exception:
                    continue
            return raw.decode("utf-8", errors="replace")
    except Exception as e:
        return f"[ERROR] {type(e).__name__}: {str(e)[:80]}"


def parse_article_list(html):
    """从列表页提取文章标题+链接"""
    if not html or html.startswith("[ERROR]"):
        return []
    # 匹配文章列表项: href + 标题
    pattern = r'<a[^>]+href="(https://www\.18qh\.com/zixun/c-\d{4}-\d{2}-\d{2}-\d+\.html)"[^>]*>([^<]+)</a>'
    matches = re.findall(pattern, html)
    articles = []
    for url, title in matches:
        title = unescape(title).strip()
        if title:
            articles.append({"url": url, "title": title})
    return articles


def is_pta_related(article):
    """判断文章是否与PTA相关"""
    title = article["title"].upper()
    # 检查标题关键词
    title_keywords = ["PTA", "原油", "布伦特", "PX", "聚酯", "化工", "能源"]
    return any(kw.upper() in title for kw in title_keywords)


def fetch_article_text(url):
    """抓取文章正文，提取纯文本"""
    html = fetch_html(url)
    if not html or html.startswith("[ERROR]"):
        return ""
    # 移除干扰内容
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
    html = re.sub(r'<iframe[^>]*>.*?</iframe>', '', html, flags=re.DOTALL)
    # 提取正文段落
    paras = re.findall(r'<p[^>]*>(.*?)</p>', html, flags=re.DOTALL)
    if not paras:
        # 尝试直接提取文本
        body = re.search(r'<div[^>]+class="content"[^>]*>(.*?)</div>', html, flags=re.DOTALL)
        if body:
            text = re.sub(r'<[^>]+>', ' ', body.group(1))
        else:
            text = re.sub(r'<[^>]+>', ' ', html)
    else:
        text = ' '.join(paras)
    text = unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_key_data(text):
    """
    从文章正文提取关键数据点
    返回结构化dict
    """
    data = {
        "price": None,       # PTA价格
        "change_pct": None,  # 涨跌幅
        "position": None,    # 持仓量
        "position_change": None,  # 持仓变化
        "warehouse_receipts": None,  # 仓单
        "wr_change": None,   # 仓单变化
        "net_position": None,  # 净持仓
        "long_change": None,   # 多单变化
        "short_change": None,  # 空单变化
        "geo_risks": [],      # 地缘风险
        "supply_factors": [], # 供应因素
        "demand_factors": [], # 需求因素
        "signal": None,       # 综合信号
    }

    # PTA价格
    m = re.search(r'PTA[^0-9]*?(\d{3,5})\.?\d*元', text)
    if not m:
        m = re.search(r'主力[^0-9]*?(\d{3,5})\.?\d*元', text)
    if m:
        data["price"] = float(m.group(1))

    # 涨跌幅
    m = re.search(r'涨[幅跌]*?\s*(\d+\.?\d*)%', text)
    if m:
        data["change_pct"] = float(m.group(1))

    # 持仓量
    m = re.search(r'持仓量[^\d]*?(\d{3,7})手', text)
    if m:
        data["position"] = int(m.group(1))

    # 持仓变化
    m = re.search(r'(增持|减持)(\d{3,7})手', text)
    if m:
        direction = 1 if m.group(1) == "增持" else -1
        data["position_change"] = direction * int(m.group(2))

    # 仓单
    m = re.search(r'仓单[^\d]*?(\d{3,7})张', text)
    if m:
        data["warehouse_receipts"] = int(m.group(1))
    m = re.search(r'(增加|减少|增持|减持)(\d+)张', text)
    if m:
        direction = 1 if m.group(1) in ["增加", "增持"] else -1
        data["wr_change"] = direction * int(m.group(2))

    # 净持仓
    m = re.search(r'净持仓[^\d]*?-?(\d+)手', text)
    if m:
        val = int(m.group(1))
        data["net_position"] = -val if text.find('净空头') > text.find('净持仓') else val
    m = re.search(r'(净多头|净空头)', text)
    if m:
        data["net_position_type"] = m.group(1)

    # 多单/空单变化
    m = re.search(r'多单[^\d]*?(增持|减持)[^\d]*?(\d{3,7})手', text)
    if m:
        data["long_change"] = (1 if m.group(1) == "增持" else -1) * int(m.group(2))
    m = re.search(r'空单[^\d]*?(增持|减持)[^\d]*?(\d{3,7})手', text)
    if m:
        data["short_change"] = (1 if m.group(1) == "增持" else -1) * int(m.group(2))

    # 地缘风险
    geo_map = {
        "中东": "中东地缘风险",
        "红海": "红海危机",
        "俄乌": "俄乌局势",
        "以色列": "中东以色列",
        "OPEC": "OPEC供应政策",
        "沙特": "沙特供应",
        "制裁": "制裁影响",
    }
    for kw, label in geo_map.items():
        if kw in text:
            data["geo_risks"].append(label)

    # 供应因素
    supply_map = {
        "检修": "装置检修",
        "降负": "降负减产",
        "停车": "装置停车",
        "重启": "装置重启",
        "减产": "减产计划",
        "增产": "增产",
        "累库": "库存累积",
        "去库": "库存去化",
    }
    for kw, label in supply_map.items():
        if kw in text:
            data["supply_factors"].append(label)

    # 需求因素
    demand_map = {
        "需求": "需求变化",
        "订单": "订单情况",
        "纺织": "纺织需求",
        "聚酯": "聚酯开工",
        "开工率": "开工率",
        "负反馈": "需求负反馈",
        "疲软": "需求疲软",
        "羸弱": "需求羸弱",
    }
    for kw, label in demand_map.items():
        if kw in text:
            data["demand_factors"].append(label)

    # 综合信号判断
    signals = []
    if data["change_pct"] and data["change_pct"] > 2:
        signals.append("上涨")
    elif data["change_pct"] and data["change_pct"] < -2:
        signals.append("下跌")

    if data["net_position"]:
        if data["net_position"] < -10000:
            signals.append("机构净空")
        elif data["net_position"] > 10000:
            signals.append("机构净多")

    if data["wr_change"] and data["wr_change"] < 0:
        signals.append("仓单减少(支撑)")
    elif data["wr_change"] and data["wr_change"] > 0:
        signals.append("仓单增加(压力)")

    if data["geo_risks"]:
        signals.append("地缘风险")

    data["signals"] = signals
    return data


def fetch_pta_news(days=3):
    """
    抓取最近N天的PTA相关文章
    返回: list of {url, title, text, data}
    """
    results = []

    # 抓列表页
    list_url = "https://www.18qh.com/zixun/"
    html = fetch_html(list_url)
    if html.startswith("[ERROR]"):
        print(f"列表页抓取失败: {html}")
        return results

    articles = parse_article_list(html)
    print(f"列表页获取 {len(articles)} 篇文章")

    # 过滤PTA相关文章（优先PTA，次选原油/化工）
    pta_articles = []
    other_articles = []
    for a in articles:
        if "PTA" in a["title"].upper():
            pta_articles.append(a)
        elif any(kw in a["title"] for kw in ["原油", "化工", "能源", "PX"]):
            other_articles.append(a)

    # 优先抓PTA文章（最多3篇），不够则补充其他
    target = pta_articles[:3] + other_articles[:2]

    for article in target:
        url = article["url"]
        title = article["title"]
        print(f"  抓取: {title[:30]}...")
        text = fetch_article_text(url)
        if not text or len(text) < 100:
            print(f"    内容过少，跳过")
            continue
        data = extract_key_data(text)
        results.append({
            "url": url,
            "title": title,
            "text": text[:800],  # 保留前800字
            "data": data,
        })
        print(f"    OK | 价格:{data['price']} 涨跌:{data['change_pct']}% 仓单:{data['warehouse_receipts']} 信号:{data['signals']}")

    return results


def generate_macro_summary(news_list):
    """
    基于新闻数据生成宏观判断
    """
    if not news_list:
        return None

    # 汇总所有数据
    all_prices = [n["data"]["price"] for n in news_list if n["data"]["price"]]
    all_changes = [n["data"]["change_pct"] for n in news_list if n["data"]["change_pct"]]
    all_net_pos = [n["data"]["net_position"] for n in news_list if n["data"]["net_position"]]
    all_geo = []
    all_supply = []
    all_demand = []
    all_signals = []

    for n in news_list:
        all_geo.extend(n["data"]["geo_risks"])
        all_supply.extend(n["data"]["supply_factors"])
        all_demand.extend(n["data"]["demand_factors"])
        all_signals.extend(n["data"]["signals"])

    # 去重
    all_geo = list(dict.fromkeys(all_geo))
    all_supply = list(dict.fromkeys(all_supply))
    all_demand = list(dict.fromkeys(all_demand))

    # 综合评分
    score = 0
    reasons = []

    if all_changes:
        avg_change = sum(all_changes) / len(all_changes)
        if avg_change > 2:
            score += 2
            reasons.append(f"近期均涨{avg_change:.1f}%")
        elif avg_change < -2:
            score -= 2
            reasons.append(f"近期均跌{avg_change:.1f}%")
        else:
            score += 0
            reasons.append(f"近期震荡({avg_change:+.1f}%)")

    if all_net_pos:
        avg_net = sum(all_net_pos) / len(all_net_pos)
        if avg_net < -20000:
            score -= 1
            reasons.append("机构净空头")
        elif avg_net > 20000:
            score += 1
            reasons.append("机构净多头")

    if all_geo:
        score += 1
        reasons.append(f"地缘:{', '.join(all_geo[:2])}")

    if all_supply:
        reasons.append(f"供应:{', '.join(all_supply[:2])}")
    if all_demand:
        reasons.append(f"需求:{', '.join(all_demand[:2])}")

    # 信号标签
    if score >= 2:
        label = "宏观偏多"
    elif score <= -2:
        label = "宏观偏空"
    else:
        label = "宏观中性"

    summary = {
        "label": label,
        "score": score,
        "reasons": reasons,
        "geo_risks": all_geo,
        "supply_factors": all_supply,
        "demand_factors": all_demand,
        "latest_price": max(all_prices) if all_prices else None,
        "latest_change": all_changes[0] if all_changes else None,
        "net_position": all_net_pos[0] if all_net_pos else None,
    }

    return summary


def main():
    print("=" * 60)
    print(f"PTA宏观新闻采集  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60 + "\n")

    news = fetch_pta_news(days=3)

    if not news:
        print("未找到PTA相关文章")
        return

    print(f"\n共采集 {len(news)} 篇PTA相关文章\n")

    # 打印摘要
    for n in news:
        d = n["data"]
        pos_chg = f"{d['position_change']:+d}" if d['position_change'] is not None else "N/A"
        wr_chg = f"{d['wr_change']:+d}" if d['wr_change'] is not None else "N/A"
        pct_str = f"{d['change_pct']:+.2f}%" if d['change_pct'] is not None else "N/A"
        print(f"【{n['title']}】")
        print(f"  价格: {d['price'] or 'N/A'} | 涨跌: {pct_str} | 持仓: {d['position'] or 'N/A'}手({pos_chg})")
        print(f"  仓单: {d['warehouse_receipts'] or 'N/A'}张({wr_chg})")
        print(f"  前20席净持仓: {d['net_position'] or 'N/A'}手 ({d.get('net_position_type','')})")
        print(f"  信号: {d['signals']}")
        if d['geo_risks']:
            print(f"  地缘: {d['geo_risks']}")
        if d['supply_factors']:
            print(f"  供应: {d['supply_factors']}")
        if d['demand_factors']:
            print(f"  需求: {d['demand_factors']}")
        print()

    # 综合判断
    summary = generate_macro_summary(news)
    if summary:
        print("=" * 60)
        print(f"【宏观综合判断】 {summary['label']}({summary['score']:+d})")
        print(f"  理由: {'; '.join(summary['reasons'])}")
        print(f"  地缘风险: {', '.join(summary['geo_risks']) or '无'}")
        print(f"  供应动态: {', '.join(summary['supply_factors']) or '无'}")
        print(f"  需求动态: {', '.join(summary['demand_factors']) or '无'}")
        print(f"  最新价格: {summary['latest_price']} | 涨跌幅: {summary['latest_change']}%")
        print(f"  前20席净持仓: {summary['net_position']}手")

    return news, summary


# ===== 以下是新增的补充数据（不影响原有新闻采集逻辑）=====

def get_oil_prices():
    """布伦特 + WTI原油"""
    import json, urllib.request, urllib.parse
    result = {}
    for symbol, name in [('BZ=F', 'brent'), ('CL=F', 'wti')]:
        try:
            url = f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?interval=1d&range=5d'
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
                closes = data['chart']['result'][0]['indicators']['quote'][0]['close']
                result[name] = closes[-1]
        except:
            result[name] = None
    return result

def get_us_bond_yields():
    """美债收益率（akshare）"""
    try:
        import akshare as ak
        df = ak.bond_zh_us_rate()
        if df is not None and len(df) > 0:
            latest = df.iloc[-1]
            us10 = float(latest.get('美国国债收益率10年', 0) or 0)
            spread = float(latest.get('美国国债收益率10年-2年', 0) or 0)
            return {'us10y': us10, 'spread': spread}
    except:
        pass
    return {'us10y': None, 'spread': None}

def send_macro_report(news, summary, oil, bonds):
    """发送完整报告到飞书"""
    try:
        import requests
        FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/8148922b-04f5-469f-994e-ae3e17d6b256'
        
        brent = oil.get('brent')
        wti = oil.get('wti')
        us10y = bonds.get('us10y')
        spread = bonds.get('spread')
        
        # 组装消息
        lines = [
            f"📊 PTA 宏观分析报告 | {datetime.now().strftime('%m-%d %H:%M')}",
            "",
            "🌍 宏观金融",
        ]
        if brent: lines.append(f"  布伦特原油: ${brent:.2f}/桶")
        if wti: lines.append(f"  WTI原油: ${wti:.2f}/桶")
        if us10y: lines.append(f"  美10Y国债: {us10y:.2f}%")
        if spread is not None: lines.append(f"  美10-2Y利差: {spread:.1f}bp")
        
        lines += ["", "📰 产业新闻摘要"]
        for n in (news or [])[:5]:
            d = n.get('data', {})
            price_str = f"{d.get('price', 'N/A')}"
            geo = ', '.join(d.get('geo_risks', [])[:1]) or '无'
            supply = ', '.join(d.get('supply_factors', [])[:1]) or '无'
            demand = ', '.join(d.get('demand_factors', [])[:1]) or '无'
            lines.append(f"  · {n.get('title', 'N/A')[:30]}")
            if d.get('price'): lines.append(f"    价格:{price_str} 地缘:{geo}")
        
        if summary:
            lines += [
                "",
                f"【综合判断】{summary.get('label', 'N/A')}",
                f"  理由: {'; '.join(summary.get('reasons', [])[:3])}",
            ]
            if summary.get('net_position'):
                lines.append(f"  前20席净持仓: {summary['net_position']}手")
        
        text = '\n'.join(lines)
        requests.post(FEISHU_WEBHOOK, json={'msg_type': 'text', 'content': {'text': text}}, timeout=10)
        print(f"[飞书] 报告已发送")
    except Exception as e:
        print(f"[飞书] 发送失败: {e}")

# 修改main末尾，加入补充数据
def main_with_full():
    print("=" * 60)
    print(f"PTA宏观综合分析  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60 + "\n")
    
    # 补充数据
    print("[1/3] 抓取原油+美债...")
    oil = get_oil_prices()
    bonds = get_us_bond_yields()
    print(f"  布伦特: {oil.get('brent')}  WTI: {oil.get('wti')}  美10Y: {bonds.get('us10y')}%")
    
    # 新闻采集
    print("[2/3] 抓取产业新闻...")
    news = fetch_pta_news(days=3)
    print(f"  共采集 {len(news)} 篇")
    
    # 综合判断
    print("[3/3] 生成分析...")
    summary = generate_macro_summary(news) if news else None
    
    # 打印
    if summary:
        print(f"\n【宏观综合判断】 {summary['label']}({summary['score']:+d})")
        print(f"  理由: {'; '.join(summary['reasons'])}")
    
    # 发飞书
    send_macro_report(news, summary, oil, bonds)
    return news, summary, oil, bonds

if __name__ == "__main__":
    main_with_full()
