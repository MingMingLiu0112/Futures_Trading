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


# ===================== 全球宏观大事件模块 =====================

def fetch_global_macro_events():
    """
    从凤凰财经抓取全球宏观大事件
    分类：地缘风险、美联储/央行、宏观经济数据、市场情绪
    返回: list of {type, title, url, impact_pta}
    """
    url = 'https://finance.ifeng.com/'
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml',
        })
        with urllib.request.urlopen(req, timeout=12) as r:
            html = r.read().decode('utf-8', errors='replace')
    except Exception as e:
        return [{"type": "error", "title": f"抓取失败: {e}", "url": "", "impact_pta": ""}]

    # 清理
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)

    # 提取所有文字链接
    text_links = re.findall(
        r'<a[^>]+href="(https?://[^\"]{15,})"[^>]*>(.*?)</a>',
        html, flags=re.DOTALL
    )

    # 分类关键词
    TYPE_KW = {
        "地缘风险": ["地缘", "制裁", "中东", "俄乌", "红海", "以色列", "伊朗", "霍尔木兹", "胡塞", "袭击", "冲突", "战争", " OPEC", "欧佩克"],
        "美联储/央行": ["美联储", "降息", "加息", "缩表", "扩表", "央行", "鲍威尔", "利率", "美债", "债券", "流动性"],
        "宏观经济": ["CPI", "PPI", "GDP", "非农", "就业", "制造业", "PMI", "通胀", "衰退", "经济", "消费", "数据", "褐皮书"],
        "市场情绪": ["黑天鹅", "灰犀牛", "恐慌", "避险", "美股", "A股", "港股", "大跌", "大涨", "跳水", "飙升", "资金流", "抛售", "涌入"],
        "贸易/关税": ["关税", "贸易战", "制裁", "出口", "进口", "毛衣", "特朗普"],
        "大宗商品": ["原油", "黄金", "铜", "铝", "大宗商品", "商品", "油价", "能源"],
    }

    # PTA影响判断
    PTA_IMPACT = {
        "地缘风险": "原油供给担忧，成本推升，利好PTA",
        "美联储/央行": "降息预期→美元弱→大宗商品强；加息→资金流向美元→大宗弱",
        "宏观经济": "经济好→需求强→利好PTA；衰退预期→需求弱→利空PTA",
        "市场情绪": "避险→原油/黄金强；风险偏好→商品强",
        "贸易/关税": "关税→贸易收缩→商品需求弱→利空；供给制裁→成本升→利好",
        "大宗商品": "原油/能源涨→PTA成本推升；黄金/铝涨→资金配置变化",
    }

    results = []
    seen_titles = set()

    for raw_url, raw_text in text_links:
        text = re.sub(r'<[^>]+>', '', raw_text).strip()
        if len(text) < 8 or text in seen_titles:
            continue
        seen_titles.add(text)

        for event_type, keywords in TYPE_KW.items():
            if any(k in text for k in keywords):
                impact = PTA_IMPACT.get(event_type, "")
                results.append({
                    "type": event_type,
                    "title": text,
                    "url": raw_url,
                    "impact_pta": impact,
                    "datetime": datetime.now().strftime("%Y-%m-%d %H:%M"),
                })
                break  # 每个标题只归一类

    # 按类型优先级排序（地缘 > 美联储 > 宏观 > 市场 > 贸易 > 商品）
    type_order = ["地缘风险", "美联储/央行", "宏观经济", "市场情绪", "贸易/关税", "大宗商品"]
    results.sort(key=lambda x: type_order.index(x["type"]) if x["type"] in type_order else 99)
    return results[:12]  # 最多12条


def generate_risk_sentiment(events):
    """
    基于全球宏观事件判断当前风险情绪
    """
    if not events:
        return None, "无数据"

    type_count = {}
    for e in events:
        t = e["type"]
        type_count[t] = type_count.get(t, 0) + 1

    # 判断逻辑
    signals = []

    if type_count.get("地缘风险", 0) >= 2:
        signals.append("地缘风险密集（避险情绪偏强）")
    elif type_count.get("地缘风险", 0) == 1:
        signals.append("局部地缘事件（影响待观察）")

    if type_count.get("市场情绪", 0) >= 2:
        signals.append("市场波动加剧（情绪敏感期）")

    if type_count.get("美联储/央行", 0) >= 1:
        signals.append("央行政策窗口期（波动放大）")

    # 总体判断
    risk_score = 0
    risk_score += type_count.get("地缘风险", 0) * 2
    risk_score += type_count.get("市场情绪", 0) * 1
    risk_score += type_count.get("美联储/央行", 0) * 1
    risk_score -= type_count.get("宏观经济", 0) * 0.5  # 经济数据好可以部分抵消风险

    if risk_score >= 4:
        sentiment = "风险偏好下降（避险模式）"
        sentiment_score = -1
    elif risk_score >= 2:
        sentiment = "风险偏好谨慎（观望模式）"
        sentiment_score = -0.5
    elif risk_score <= -2:
        sentiment = "风险偏好强（进攻模式）"
        sentiment_score = 1
    else:
        sentiment = "风险偏好中性"
        sentiment_score = 0

    summary = {
        "sentiment": sentiment,
        "sentiment_score": sentiment_score,
        "event_count": len(events),
        "type_breakdown": type_count,
        "signals": signals,
        "top_events": [e["title"] for e in events[:5]],
    }

    return sentiment_score, sentiment, summary


def fetch_and_analyze_global_macro():
    """
    抓取并分析全球宏观大事件
    """
    events = fetch_global_macro_events()
    if not events or (len(events) == 1 and events[0].get("type") == "error"):
        return None, None, {}

    sentiment_score, sentiment, summary = generate_risk_sentiment(events)
    return events, sentiment_score, summary


if __name__ == "__main__":
    print("=== 全球宏观大事件抓取 ===\n")
    events = fetch_global_macro_events()
    if events and events[0].get("type") != "error":
        sentiment_score, sentiment, summary = generate_risk_sentiment(events)
        print(f"风险情绪: {sentiment} ({sentiment_score})\n")
        print("事件摘要:")
        for e in events:
            print(f"  [{e['type']}] {e['title']}")
            print(f"    -> {e['impact_pta']}")
        print(f"\n关键信号: {summary.get('signals', [])}")
    else:
        print("抓取失败")
