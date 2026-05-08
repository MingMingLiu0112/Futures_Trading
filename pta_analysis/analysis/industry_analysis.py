
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA产业基本面分析模块 v5
数据源质量评级（基于akshare）：
  ★★★ 郑商所每日现货参考价    futures_spot_price(date)         现货/近月/主力价格+基差
  ★★★ 郑商所期货日行情        get_czce_daily(date)             结算价/成交量/持仓量
  ★★★ 隆众资讯库存数据        futures_inventory_em(symbol)      PTA/MEG/苯乙烯社会库存
  ★★★ 新浪财经原油现货         futures_global_spot_em()          布伦特/WTI原油最新价
  ★★☆ 国内汽柴油批发价         energy_oil_hist()                 CNY/吨，非原油期货

  ★★★ akshare 无以下数据，需专业订阅或人工录入：
     - PX/PTA/下游装置开工率   → 隆众资讯、卓创资讯、CCF中国化纤信息网
     - PX/PTA/下游产销数据      → 隆众资讯、卓创资讯
     - 布伦特/WTI期货连续日频  → 新浪财经期货、CME官网

成本公式：
  PTA成本 = PX现货参考价 × 0.655（PX单耗，理论值）
  PTA利润 = PTA现货参考价 - PTA成本

基差：
  PTA基差 = PTA现货参考价 - TA主力结算价
"""

import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
import requests
warnings.filterwarnings('ignore')

USD_CNY = 7.2


def get_pta_industry_data():
    """获取PTA产业基本面数据 + AI产业点评"""
    result = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "success",
        "data": {}
    }

    try:
        upstream_data = {}
        pta_data = {}
        cost_data = {}
        downstream_data = {}

        # ===== 1. 上游原料 =====
        _load_crude_oil(upstream_data)
        _load_px_spot(upstream_data)
        _load_downstream(upstream_data)        # 下游纺织/塑料现货（东方财富，滞后约5日）
        _load_pta_chain_ths(upstream_data)     # PTA产业链情报（生意社/同花顺）
        _load_priceseek(upstream_data)         # PriceSeek提醒：外盘CFR+逸盛/恒力定价（生意社）
        _load_px_chain_spot(upstream_data)    # PX+PTA+下游现货价格涨跌榜（生意社/同花顺）
        _calc_naphtha_pxn(upstream_data)

        result["data"]["upstream"] = upstream_data

        # ===== 2. PTA自身 =====
        _load_pta_spot_and_future(pta_data)  # 现货 + 期货（含基差）
        _load_pta_inventory(pta_data)

        result["data"]["pta"] = pta_data

        # ===== 3. 下游 =====
        _load_downstream_spot(downstream_data)
        result["data"]["downstream"] = downstream_data

        # ===== 4. 成本利润 =====
        _calc_cost_profit(upstream_data, pta_data, cost_data)
        result["data"]["cost"] = cost_data

        # ===== 5. AI点评 =====
        commentary = _generate_ai_commentary(upstream_data, pta_data, downstream_data, cost_data)
        result["data"]["ai_commentary"] = commentary

        # 数据来源说明
        result["data"]["_data_sources"] = {
            "has": {
                "原油布伦特/美油": "futures_global_spot_em（新浪财经，布伦特主力 USD/桶）",
                "PX现货": "futures_spot_price 郑商所每日现货参考价",
                "PTA及下游现货": "futures_spot_price 郑商所每日现货参考价",
                "PTA库存": "futures_inventory_em 隆众资讯 PTA社会库存",
                "MEG/SM库存": "futures_inventory_em 隆众资讯 MEG乙二醇/SM苯乙烯库存",
                "PTA期货": "get_czce_daily 郑商所日行情（结算价/成交量/持仓量）",
                "国内汽柴油批发价": "energy_oil_hist CNY/吨",
            },
            "missing_akshare": {
                "PX/PTA/下游开工率": "需隆众资讯、卓创资讯、CCF中国化纤信息网订阅",
                "PX/PTA/下游产销数据": "需隆众资讯、卓创资讯、期货公司研报",
                "布伦特/WTI期货连续日频": "需新浪财经期货、CME官网、东方财富期货",
            }
        }

        print("产业基本面分析完成!")

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        import traceback
        traceback.print_exc()
        print(f"产业分析错误: {e}")

    return result


def _get_latest_trading_date():
    """获取最近交易日（工作日，不超过5天前）"""
    today = datetime.now()
    for delta in range(5):
        d = today - timedelta(days=delta)
        if d.weekday() < 5:  # 周一到周五
            return d.strftime("%Y%m%d"), d.strftime("%Y-%m-%d")
    return today.strftime("%Y%m%d"), today.strftime("%Y-%m-%d")


def _load_crude_oil(upstream_data):
    """
    原油数据 - 布伦特当月连续 B00Y ($109.2) + WTI当月连续 CL00Y
    直接调东方财富API，绕过akshare降序截断B00Y的问题
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://quote.eastmoney.com/',
        }
        url = ('https://futsseapi.eastmoney.com/list/COMEX,NYMEX,COBOT,SGX,NYBOT,LME,MDEX,TOCOM,IPE'
               '?orderBy=dm&sort=asc&pageSize=500&pageIndex=0'
               '&token=58b2fa%2E%2E%2E089c'
               '&field=dm,sc,name,p,zsjd,zde,zdf,f152,o,h,l,zjsj,vol,wp,np,ccl')

        r = requests.get(url, headers=headers, timeout=15)
        data = r.json()
        items = {item['dm']: item for item in data.get('list', [])}

        # 布伦特当月连续 B00Y = $109.2
        b00y = items.get('B00Y', {})
        if b00y and b00y.get('p', 0) > 0:
            upstream_data["brent"] = {
                "price": float(b00y["p"]),
                "change_pct": float(b00y.get("zdf", 0)),
                "volume": int(b00y.get("vol", 0)),
                "contract": str(b00y.get("name", "布伦特原油当月连续")),
                "note": "B00Y 当月连续，USD/桶"
            }

        # WTI当月连续 CL00Y
        cl00y = items.get('CL00Y', {})
        if cl00y and cl00y.get('p', 0) > 0:
            upstream_data["wti"] = {
                "price": float(cl00y["p"]),
                "change_pct": float(cl00y.get("zdf", 0)),
                "volume": int(cl00y.get("vol", 0)),
                "contract": str(cl00y.get("name", "WTI原油当月连续")),
                "note": "CL00Y 当月连续，USD/桶"
            }

        # 国内汽柴油批发价（CNY/吨），energy_oil_hist 是中国批发价，非美国零售价
        try:
            df_oil = ak.energy_oil_hist()
            if df_oil is not None and not df_oil.empty:
                latest = df_oil.iloc[-1]
                upstream_data["cn_gasoline_wholesale"] = {
                    "date": str(latest.get("调整日期", "")),
                    "price_cny_ton": float(latest.get("汽油价格", 0)),
                    "price_usd_bbl_estimate": round(float(latest.get("汽油价格", 0)) / USD_CNY / 8.4, 2),
                    "note": "中国汽油批发价，CNY/吨；USD/桶≈CNY/吨÷7.2÷8.4"
                }
        except Exception as e:
            print(f"国内汽柴油批发价获取失败: {e}")

    except Exception as e:
        print(f"原油数据错误: {e}")


def _load_px_spot(upstream_data):
    """
    PX现货：futures_spot_price(date) 郑商所每日现货参考价格
    - spot_price: 现货参考价（郑商所发布）
    - near_contract_price: 最近月合约收盘价
    - dominant_contract_price: 主力合约收盘价
    - dom_basis: 主力基差 = spot_price - dominant_contract_price
    """
    date_str, date_disp = _get_latest_trading_date()

    # 主数据源：郑商所每日现货表
    try:
        df = ak.futures_spot_price(date=date_str, vars_list=["PX"])
        found = df is not None and not df.empty

        # 如果当天没有，依次往前找最多4天
        if not found:
            print(f"PX现货数据为空（日期={date_str}），尝试前一天")
            for delta in range(1, 5):
                prev = datetime.now() - timedelta(days=delta)
                df = ak.futures_spot_price(date=prev.strftime("%Y%m%d"), vars_list=["PX"])
                if df is not None and not df.empty:
                    found = True
                    break

        if found:
            px_rows = df[df['symbol'] == 'PX']
            if not px_rows.empty:
                r = px_rows.iloc[0]
                upstream_data["px"] = {
                    "spot_price": float(r['spot_price']),                   # 现货参考价（郑商所发布）
                    "near_contract": str(r['near_contract']),              # 最近月合约
                    "near_price": float(r['near_contract_price']),          # 最近月收盘
                    "dominant_contract": str(r['dominant_contract']),      # 主力合约
                    "dominant_price": float(r['dominant_contract_price']), # 主力收盘
                    "dom_basis": float(r['dom_basis']),                    # 主力基差
                    "date": str(r['date']),
                    "source": "郑商所每日现货参考价格表"
                }
    except Exception as e:
        print(f"PX郑商所数据错误: {e}")

    # 备用：东方财富 futures_spot_stock(symbol='化工') PX现货
    # 当郑商所无数据时，也作为 px 主力数据源；总有数据时额外补充 px_em
    try:
        df_em = ak.futures_spot_stock(symbol='化工')
        if df_em is not None and not df_em.empty:
            px_row = df_em[df_em['商品名称'] == 'PX']
            if not px_row.empty:
                r = px_row.iloc[0]
                em_price = float(r['最新价格'])
                em_change = float(r.get('近半年涨跌幅', 0))
                if "px" not in upstream_data or not upstream_data.get("px", {}).get("spot_price"):
                    # 郑商所无数据，直接用东方财富 PX 数据作为 px 主力
                    upstream_data["px"] = {
                        "spot_price": em_price,
                        "change_pct": em_change,
                        "date": date_disp,
                        "source": "东方财富现货与股票(化工)"
                    }
                else:
                    # 郑商所有数据，东方财富数据存入 px_em 备用
                    upstream_data["px_em"] = {
                        "spot_price": em_price,
                        "change_pct": em_change,
                        "date": date_disp,
                        "source": "东方财富现货与股票(化工)"
                    }
    except Exception as e:
        print(f"PX东方财富数据错误: {e}")


def _load_downstream(upstream_data):
    """
    下游产业链数据：东方财富 futures_spot_stock
    - 纺织板块：PTA现货、涤纶短纤、涤纶DTY/POY/FDY、粘胶短纤、锦纶FDY、皮棉
    - 塑料板块：PET（聚酯切片）
    - 化工板块：PX
    注意：东方财富现货数据有约5日延迟，仅供趋势参考
    """
    try:
        date_str, date_disp = _get_latest_trading_date()

        # 纺织板块
        df_fz = ak.futures_spot_stock(symbol='纺织')
        if df_fz is not None and not df_fz.empty:
            items = {}
            for _, row in df_fz.iterrows():
                name = str(row.get('商品名称', '')).strip()
                price = row.get('最新价格')
                chg = row.get('近半年涨跌幅', 0)
                if price is not None and str(price) not in ('', '-') and float(price) > 0:
                    items[name] = {
                        "price": float(price),
                        "change_pct": float(chg) if chg and str(chg) not in ('', '-') else 0.0,
                        "date": date_disp,
                    }
            upstream_data["downstream"] = {
                "segment": "纺织",
                "source": "东方财富现货与股票(纺织)滞后约5日",
                "note": "数据有延迟，精确值请参考专业平台",
                "items": items,
            }

        # 塑料板块：PET（聚酯切片）
        df_pla = ak.futures_spot_stock(symbol='塑料')
        if df_pla is not None and not df_pla.empty:
            pet_row = df_pla[df_pla['商品名称'] == 'PET']
            if not pet_row.empty:
                r = pet_row.iloc[0]
                upstream_data["downstream_pet"] = {
                    "segment": "塑料",
                    "price": float(r['最新价格']),
                    "change_pct": float(r.get('近半年涨跌幅', 0)),
                    "date": date_disp,
                    "source": "东方财富现货与股票(塑料)滞后约5日",
                }
    except Exception as e:
        print(f"下游数据错误: {e}")


def _load_pta_chain_ths(upstream_data):
    """
    PTA产业链情报 - 同花顺 goodsfu.10jqka.com.cn
    数据来源：生意社PTA产业链数据，通过同花顺期货页面汇聚
    包含：产业链指数、基准价、外盘CFR、内盘暂结价、下游涨跌榜
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'http://stock.10jqka.com.cn/',
        }
        r = requests.get(
            'http://stock.10jqka.com.cn/getListPage.php?listid=cl_008002014',
            headers=headers, timeout=10
        )
        if r.status_code != 200:
            return

        text = r.text
        # 清洗HTML
        import re as _re
        text = _re.sub(r'<script[^>]*>.*?</script>', '', text, flags=_re.DOTALL)
        text = _re.sub(r'<style[^>]*>.*?</style>', '', text, flags=_re.DOTALL)
        text = _re.sub(r'<[^>]+>', ' ', text)
        text = _re.sub(r'\s+', ' ', text).strip()

        result = {}

        # 1. 产业链指数（取最新一条）
        idx_match = _re.search(r'生意社PTA产业链指数为([\d.]+)', text)
        if idx_match:
            result["chain_index"] = float(idx_match.group(1))
            # 历史对比：最高/最低
            peak_match = _re.search(r'最高点([\d.]+)点\((\d{4}-\d{2}-\d{2})\)', text)
            trough_match = _re.search(r'最低点([\d.]+)点\((\d{4}-\d{2}-\d{2})\)', text)
            if peak_match:
                result["index_high"] = float(peak_match.group(1))
                result["index_high_date"] = peak_match.group(2)
            if trough_match:
                result["index_low"] = float(trough_match.group(1))
                result["index_low_date"] = trough_match.group(2)

        # 2. PTA基准价（最新一条）
        price_match = _re.search(r'生意社PTA基准价为([\d.]+)元/吨', text)
        if price_match:
            result["spot_price_shengyishe"] = float(price_match.group(1))
            # 环比：与上月初相比
            mom_match = _re.search(r'与上月初\([^)]+\)相比，上涨了([\d.]+)%', text)
            if mom_match:
                result["price_mom_pct"] = float(mom_match.group(1))

        # 3. 外盘CFR中国PTA主流报价
        cfr_match = _re.search(r'外盘CFR中国PTA主流报价维持在([\d.]+)美元/吨', text)
        if cfr_match:
            result["cfr_china_usd"] = float(cfr_match.group(1))

        # 4. 逸盛内盘暂结价
        yisheng_match = _re.search(r'逸盛石化公布\d月PTA内盘暂结价至([\d.]+)元/吨', text)
        if yisheng_match:
            result["yisheng_settlement"] = float(yisheng_match.group(1))

        # 5. 基差（最新一条）
        basis_match = _re.search(r'PTA市场基差为([\d.]+)元/吨', text)
        if basis_match:
            result["basis_shengyishe"] = float(basis_match.group(1))

        # 6. 下游涨跌榜（最新一条）
        zhbox_match = _re.search(r'涨跌榜[^\n]*?(上涨的商品共(\d+)种[^\n]{0,200})', text)
        if zhbox_match:
            result["downstream_trend"] = zhbox_match.group(1).strip()[:200]

        if result:
            upstream_data["pta_chain_ths"] = {
                **result,
                "source": "同花顺 goodsfu.10jqka.com.cn / 生意社",
                "note": "产业链指数、基准价、基差来自生意社，下游涨跌榜实时更新"
            }

    except Exception as e:
        print(f"PTA产业链同花顺数据错误: {e}")


def _load_priceseek(upstream_data):
    """
    PriceSeek 提醒 - 抓取同花顺PTA列表页最新N篇，抓取内容中的关键数据
    包括：外盘CFR中国PTA、逸盛/恒力/中石化暂结价、产业链指数、基差
    通过列表页并发抓取多篇文章，速度快且数据全
    """
    try:
        import concurrent.futures

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://goodsfu.10jqka.com.cn/',
        }
        list_url = 'http://stock.10jqka.com.cn/getListPage.php?listid=cl_008002014&page=1'
        r = requests.get(list_url, headers=headers, timeout=10)
        if r.status_code != 200:
            return

        text = r.text
        import re as _re

        # 提取所有文章的 (date, cid, 标题关键词)
        # 格式: href=".../YYYYMMDD/cXXXXXXXX.shtml">标题
        all_arts = _re.findall(
            r'(\d{8})/c(\d{9})\.shtml"[^>]*>([^<]+)<',
            text
        )
        if not all_arts:
            return

        # 按日期降序（最新的在前）
        all_arts.sort(key=lambda x: x[0], reverse=True)

        # 找出最有价值的 cid（每类只取最新1个）
        taken_cids = set()
        priority_articles = []

        # 优先级顺序：
        # 1. 外盘CFR  2. 逸盛暂结价  3. 恒力/中石化预收款  4. 基差  5. 产业链指数  6. 基准价
        priority_keywords = [
            '外盘CFR',
            '逸盛',
            '恒力石化.*预收款',
            '中石化.*预收',
            'PTA市场基差',
            '产业链指数',
            'PTA基准价',
        ]

        for kw in priority_keywords:
            for date, cid, title in all_arts:
                if cid in taken_cids:
                    continue
                if _re.search(kw, title):
                    priority_articles.append((date, cid, kw))
                    taken_cids.add(cid)
                    break  # 该类取最新的一个

        # 最多并发取6篇
        priority_articles = priority_articles[:6]

        def fetch_article(date, cid, kw_type):
            try:
                url = f'http://goodsfu.10jqka.com.cn/{date}/c{cid}.shtml'
                r2 = requests.get(url, headers=headers, timeout=8)
                if r2.status_code != 200:
                    return {}

                body = r2.text
                body = _re.sub(r'<script[^>]*>.*?</script>', '', body, flags=_re.DOTALL)
                body = _re.sub(r'<style[^>]*>.*?</style>', '', body, flags=_re.DOTALL)
                body = _re.sub(r'<[^>]+>', ' ', body)
                body = _re.sub(r'\s+', ' ', body).strip()

                # 从正文中截取关键段落（从"生意社"或"PriceSeek"开始）
                for start_kw in ['生意社', 'PriceSeek', '多空评分']:
                    pos = body.find(start_kw)
                    if pos >= 0:
                        body = body[pos:]
                        break

                result = {'kw_type': kw_type, 'cid': cid, 'date': date}
                text_sample = body[:2000]  # 只取前2000字符

                # 外盘CFR中国PTA
                cfr = _re.search(r'外盘CFR中国PTA主流报价维持在?([\d.]+)美元/吨', text_sample)
                if cfr:
                    result['cfr_china_usd'] = float(cfr.group(1))
                    # 日期（如：4月29日）
                    d_match = _re.search(r'(\d{1,2}月\d{1,2}日)', text_sample)
                    if d_match:
                        result['cfr_date'] = d_match.group(1)

                # 逸盛/恒力/中石化暂结价/预收款
                yisheng = _re.search(r'逸盛石化公布.*?PTA内盘暂结价至?([\d.]+)元/吨', text_sample)
                if yisheng:
                    result['yisheng_settlement'] = float(yisheng.group(1))

                hengli = _re.search(r'恒力石化[^月]*月PTA预?收款?价格[为至]([\d.]+)元/吨', text_sample)
                if hengli:
                    result['hengli_settlement'] = float(hengli.group(1))

                sinopec = _re.search(r'中石化[^月]*月PTA预?收款?价格[为至]([\d.]+)元/吨', text_sample)
                if sinopec:
                    result['sinopec_price'] = float(sinopec.group(1))

                # 基差
                basis = _re.search(r'PTA市场基差为?([\d.]+)元/吨', text_sample)
                if basis:
                    result['basis_pta'] = float(basis.group(1))

                # 产业链指数
                idx = _re.search(r'生意社PTA产业链指数为([\d.]+)', text_sample)
                if idx:
                    result['chain_index'] = float(idx.group(1))

                # 基准价
                price = _re.search(r'生意社PTA基准价为?([\d.]+)元/吨', text_sample)
                if price:
                    result['spot_price_shengyishe'] = float(price.group(1))

                return result
            except Exception as e:
                return {}

        # 并发抓取
        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(fetch_article, d, c, kw): kw
                for d, c, kw in priority_articles
            }
            for future in concurrent.futures.as_completed(futures):
                data = future.result()
                if data:
                    kw = data.pop('kw_type')
                    cid = data.pop('cid')
                    date = data.pop('date')
                    results[kw] = {**data, 'cid': cid, 'article_date': date}

        if results:
            upstream_data["priceseek"] = {
                **results,
                "source": "同花顺/生意社 PriceSeek提醒",
                "note": "数据来自生意社，经同花顺期货通汇聚发布"
            }

    except Exception as e:
        print(f"PTA产业链同花顺数据错误: {e}")


def _load_px_chain_spot(upstream_data):
    """
    PTA产业链现货价格涨跌榜 - 同花顺/生意社
    数据来源：同花顺 goodsfu 每日发布的" PTA产业价格涨跌榜 "
    包含：PX、PTA、涤纶POY/DTY/FDY/短纤 的现货价格
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'http://stock.10jqka.com.cn/',
        }
        # 获取最新列表页，找到" PTA产业价格涨跌榜 " cid
        r = requests.get(
            'http://stock.10jqka.com.cn/getListPage.php?listid=cl_008002014',
            headers=headers, timeout=10
        )
        if r.status_code != 200:
            return

        text = r.text
        # 找最新一条涨跌榜文章的 cid
        # 格式: href=".../20260430/c676422903.shtml" ...>2026年04月30日PTA产业价格涨跌榜
        cid_match = re.search(
            r'href="[^"]*/(\d{8})/c(\d{9})\.shtml"[^>]*>[^<]*(\d{4}年\d{1,2}月\d{1,2}日PTA产业价格涨跌榜)',
            text
        )
        if not cid_match:
            return

        date_str, cid, title = cid_match.group(1), cid_match.group(2), cid_match.group(3)
        # 抓文章内容
        article_url = f'http://goodsfu.10jqka.com.cn/{date_str}/c{cid}.shtml'
        r2 = requests.get(article_url, headers=headers, timeout=10)
        if r2.status_code != 200:
            return

        article_text = r2.text
        article_text = re.sub(r'<script[^>]*>.*?</script>', '', article_text, flags=re.DOTALL)
        article_text = re.sub(r'<style[^>]*>.*?</style>', '', article_text, flags=re.DOTALL)
        article_text = re.sub(r'<[^>]+>', ' ', article_text)
        article_text = re.sub(r'\s+', ' ', article_text).strip()

        # 提取价格表格：商品 | 行业 | 昨日价格 | 今日价格 | 单位 | 日涨跌 | 同比涨跌
        result = {"article_date": date_str, "items": {}}

        # 找" PX 化工 9900.00 9900.00 "类似行
        price_rows = re.findall(
            r'(PX|PTA|涤纶POY|涤纶DTY|涤纶FDY|涤纶短纤|粘胶短纤|锦纶FDY|皮棉)\s+'
            r'(纺织|化工)\s+'
            r'([\d,.]+)\s+'
            r'([\d,.]+)\s+'
            r'元/吨\s+'
            r'([\+\-\d.]+%)?\s+'
            r'([\+\-\d.]+%)?',
            article_text
        )

        for name, industry, prev_price, curr_price, day_chg, year_chg in price_rows:
            prev_p = float(prev_price.replace(',', ''))
            curr_p = float(curr_price.replace(',', ''))
            day_pct = float(day_chg.replace('%', '').replace('+', '')) if day_chg and day_chg.strip() not in ('0.00%', '') else 0.0
            year_pct = float(year_chg.replace('%', '').replace('+', '')) if year_chg and year_chg.strip() not in ('0.00%', '') else 0.0

            key = name.strip()
            upstream_data[key] = {
                "industry": industry.strip(),
                "prev_price": prev_p,
                "price": curr_p,
                "day_chg_pct": day_pct,
                "year_chg_pct": year_pct,
                "date": date_str,
                "source": "生意社PTA产业价格涨跌榜",
                "article_url": article_url,
            }
            result["items"][key] = {
                "prev_price": prev_p,
                "price": curr_p,
                "day_chg_pct": day_pct,
            }

        if result.get("items"):
            upstream_data["px_chain_spot"] = {
                **result,
                "source": "同花顺 goodsfu / 生意社",
                "note": "PX为PTA上游原料，下游纺织品种来自同一产业链"
            }

    except Exception as e:
        print(f"PTA产业价格涨跌榜错误: {e}")


def _calc_naphtha_pxn(upstream_data):
    """
    石脑油估算 + PXN
    石脑油 CFR 亚洲 = 布伦特 USD/桶 × 7.5 + 运费/贴水 ≈ 布伦特 × 7.5 + 20
    PXN = PX USD/吨 - 石脑油 CFR USD/吨
    """
    brent = upstream_data.get("brent", {})
    px = upstream_data.get("px", {})
    px_em = upstream_data.get("px_em", {})

    # 优先用郑商所 px；备用东方财富 px_em
    if px and px.get("spot_price"):
        px_spot = px
    elif px_em and px_em.get("spot_price"):
        px_spot = px_em
    else:
        return  # 两边都没有 PX 数据

    if not brent or not brent.get("price"):
        return  # 布伦特数据也必须有

    # 布伦特：平台展示价（可能是CNY/桶），若>150则很可能已经是CNY/桶
    # 判断：如果 > 150，则可能为 CNY/桶；否则为 USD/桶
    brent_px = brent.get("price", 0)
    if brent_px > 150:
        # 假设为 CNY/桶，换算 USD/桶
        brent_usd = brent_px / USD_CNY
        naphtha_usd = brent_usd * 7.5 + 20  # CFR 亚洲 = 布伦特 × 7.5 + 运费贴水
        brent_note = f"布伦特原值为CNY/桶，换算USD={brent_px:.2f}/7.2={brent_usd:.2f}"
    else:
        # 假设为 USD/桶（合理范围 $60-$120）
        brent_usd = brent_px
        naphtha_usd = brent_usd * 7.5 + 20
        brent_note = "布伦特原值为USD/桶"

    px_usd = px_spot.get("spot_price", 0) / USD_CNY  # PX CNY → USD
    pxn = px_usd - naphtha_usd

    upstream_data["naphtha"] = {
        "price_usd_bbl": round(brent_usd, 2),
        "naphtha_cfr_estimate": round(naphtha_usd, 2),
        "unit": "USD/吨（CFR亚洲估算）",
        "note": f"石脑油CFR亚洲≈布伦特×7.5+20；{brent_note}"
    }
    upstream_data["pxn"] = {
        "px_usd": round(px_usd, 2),
        "naphtha_usd": round(naphtha_usd, 2),
        "spread_usd": round(pxn, 2),
        "level": "高" if pxn > 350 else "中" if pxn > 250 else "低",
        "note": "石脑油为CFR估算值，PXN仅供参考"
    }


def _load_pta_spot_and_future(pta_data):
    """
    PTA现货 + 期货：futures_spot_price(date) + get_czce_daily(date)
    现货参考价来自郑商所每日现货表，期货来自CZCE日行情
    """
    try:
        date_str, date_disp = _get_latest_trading_date()

        # 方法A：用郑商所每日现货表（快且全）
        df_spot = ak.futures_spot_price(date=date_str, vars_list=["TA"])
        if df_spot is None or df_spot.empty:
            for delta in range(1, 5):
                prev = datetime.now() - timedelta(days=delta)
                df_spot = ak.futures_spot_price(date=prev.strftime("%Y%m%d"), vars_list=["TA"])
                if df_spot is not None and not df_spot.empty:
                    date_disp = prev.strftime("%Y-%m-%d")
                    break

        if df_spot is not None and not df_spot.empty:
            r = df_spot[df_spot['symbol'] == 'TA'].iloc[0]
            pta_data["spot"] = {
                "price": float(r['spot_price']),                   # PTA现货参考价（郑商所发布）
                "near_contract": str(r['near_contract']),           # 最近月
                "near_price": float(r['near_contract_price']),      # 最近月收盘
                "dominant_contract": str(r['dominant_contract']),    # 主力
                "dominant_price": float(r['dominant_contract_price']),# 主力收盘
                "near_basis": float(r['near_basis']),              # 近月基差
                "dom_basis": float(r['dom_basis']),                # 主力基差
                "date": str(r['date']),
                "source": "郑商所每日现货参考价格表"
            }

        # 方法B：用 CZCE 日行情补充（结算价、成交量、持仓量）
        df_czce = None
        for delta in range(5):
            d = datetime.now() - timedelta(days=delta)
            df_czce = ak.get_czce_daily(date=d.strftime("%Y%m%d"))
            if df_czce is not None and not df_czce.empty and 'variety' in df_czce.columns:
                break

        if df_czce is not None and not df_czce.empty:
            ta = df_czce[df_czce['variety'] == 'TA'].sort_values('volume', ascending=False)
            if not ta.empty:
                main = ta.iloc[0]
                pta_data["future"] = {
                    "symbol": str(main['symbol']),
                    "settle": float(main['settle']),
                    "close": float(main['close']),
                    "pre_settle": float(main['pre_settle']),
                    "change_pct": round((float(main['settle']) - float(main['pre_settle'])) / float(main['pre_settle']) * 100, 2),
                    "volume": int(main['volume']),
                    "open_interest": int(main['open_interest'])
                }
                # 基差用 CZCE 主力结算价
                if "spot" in pta_data:
                    spot_px = pta_data["spot"]["price"]
                    fut_settle = float(main['settle'])
                    basis_val = spot_px - fut_settle
                    pta_data["basis"] = {
                        "value": round(basis_val, 1),
                        "premium": "现货升水" if basis_val > 0 else "现货贴水",
                        "level": "强" if abs(basis_val) > 150 else "中" if abs(basis_val) > 80 else "弱",
                        "note": f"现货参考价¥{spot_px} - TA{main['symbol']}结算¥{fut_settle}"
                    }

    except Exception as e:
        print(f"PTA数据错误: {e}")


def _load_inventory_all():
    """所有相关品种库存：PTA(隆众)、MEG乙二醇(隆众)、苯乙烯SM(隆众)"""
    inventories = {}
    symbols = [
        ("pta", "PTA"),
        ("meg", "乙二醇"),
        ("sm", "SM"),      # 苯乙烯期货库存
    ]
    for key, sym in symbols:
        try:
            df = ak.futures_inventory_em(symbol=sym)
            if df is not None and not df.empty:
                latest = df.iloc[-1]
                prev = df.iloc[-2] if len(df) >= 2 else latest
                inventories[key] = {
                    "stock": int(latest.get('库存', 0)),
                    "change": int(latest.get('增减', 0)),
                    "date": str(latest.get('日期', ''))
                }
        except Exception as e:
            print(f"{sym}库存加载错误: {e}")
    return inventories


def _load_pta_inventory(pta_data):
    """PTA社会库存（隆众资讯）+ MEG/SM库存"""
    inv = _load_inventory_all()
    if "pta" in inv:
        pta_data["social_inventory"] = inv["pta"]
    if "meg" in inv:
        pta_data["meg_inventory"] = inv["meg"]
    if "sm" in inv:
        pta_data["sm_inventory"] = inv["sm"]


def _load_downstream_spot(downstream_data):
    """下游现货：郑商所/大商所每日现货参考价格"""
    try:
        date_str, _ = _get_latest_trading_date()
        # 品种代码：CY=涤纶短纤, EG=乙二醇, EB=苯乙烯, MA=甲醇MA
        df = ak.futures_spot_price(date=date_str, vars_list=["CY", "EG", "EB", "MA"])
        if df is None or df.empty:
            for delta in range(1, 5):
                prev = datetime.now() - timedelta(days=delta)
                df = ak.futures_spot_price(date=prev.strftime("%Y%m%d"), vars_list=["CY", "EG", "EB", "MA"])
                if df is not None and not df.empty:
                    break

        if df is not None and not df.empty:
            names = {"CY": "涤纶短纤", "EG": "乙二醇", "EB": "苯乙烯", "MA": "甲醇MA"}
            for _, r in df.iterrows():
                sym = r['symbol']
                downstream_data[names.get(sym, sym)] = {
                    "code": sym,
                    "price": float(r['spot_price']),
                    "near_contract": str(r['near_contract']),
                    "near_price": float(r['near_contract_price']),
                    "dominant_contract": str(r['dominant_contract']),
                    "dominant_price": float(r['dominant_contract_price']),
                    "near_basis": float(r['near_basis']),
                    "dom_basis": float(r['dom_basis']),
                    "date": str(r['date']),
                    "source": "郑商所/大商所每日现货"
                }
    except Exception as e:
        print(f"下游现货错误: {e}")


def _calc_cost_profit(upstream_data, pta_data, cost_data):
    """PTA成本利润"""
    px = upstream_data.get("px", {})
    pta_spot = pta_data.get("spot", {})

    if not px or not px.get("spot_price"):
        return

    px_price = px["spot_price"]  # CNY/吨
    cost = px_price * 0.655

    cost_data["pta_cost"] = {
        "px_price": px_price,
        "formula": "PX现货 × 0.655",
        "pta_cost": round(cost, 0)
    }

    if pta_spot.get("price"):
        pta_price = pta_spot["price"]
        profit = pta_price - cost
        profit_pct = (profit / cost) * 100
        cost_data["profit"] = {
            "pta_price": pta_price,
            "profit": round(profit, 0),
            "profit_pct": round(profit_pct, 1),
            "level": "盈利良好" if profit > 400 else "小幅盈利" if profit > 0 else "亏损状态"
        }


def _generate_ai_commentary(upstream, pta, downstream, cost):
    parts = []
    signals = []
    bullish = bearish = neutral = 0

    brent = upstream.get("brent", {})
    px = upstream.get("px", {})
    pxn_info = upstream.get("pxn", {})
    pta_spot = pta.get("spot", {})
    pta_fut = pta.get("future", {})
    basis = pta.get("basis", {})
    inv = pta.get("social_inventory", {})
    meg_inv = pta.get("meg_inventory", {})
    sm_inv = pta.get("sm_inventory", {})
    pta_cost = cost.get("pta_cost", {})
    profit = cost.get("profit", {})
    us_gas = upstream.get("cn_gasoline_wholesale", {})
    dxFiber = downstream.get("涤纶短纤", {})
    eb = downstream.get("苯乙烯", {})
    meg = downstream.get("乙二醇", {})
    meoh = downstream.get("甲醇MA", {})

    # ===== 【原油/成本端】 =====
    cost_parts = []
    if brent:
        chg = brent["change_pct"]
        arrow = "▲" if chg > 0 else "▼" if chg < 0 else "─"
        lvl = "强势上涨" if chg > 3 else "大幅下跌" if chg < -3 else "小幅波动"
        cost_parts.append(f"布伦特{lvl}({arrow}${brent['price']:.2f},{chg:+.2f}%)")
        if chg > 3:
            signals.append(("利多", "原油大涨，成本支撑增强"))
            bullish += 1
        elif chg < -3:
            signals.append(("利空", "原油大跌，成本支撑减弱"))
            bearish += 1
        else:
            neutral += 1
    if us_gas:
        cost_parts.append(f"国内汽油批发¥{us_gas.get('price_cny_ton',0):.0f}/吨({us_gas.get('date','')})")
    if px:
        chg_px = (px.get("spot_price", 0) - px.get("dominant_price", 0)) / px.get("dominant_price", 1) * 100
        px_lv = "偏高" if px['spot_price'] > 10500 else "偏低" if px['spot_price'] < 8500 else "中性"
        cost_parts.append(f"PX({px_lv}¥{px['spot_price']:.0f},基差{px.get('dom_basis',0):+.0f})")
    cost_str = "，".join(cost_parts) if cost_parts else "数据缺失"
    parts.append(f"【成本】{cost_str}。")

    # ===== 【PTA基差】 =====
    if basis:
        bv = basis["value"]
        level = basis.get("level", "")
        prem = basis.get("premium", "")
        if abs(bv) > 150:
            if bv > 0:
                parts.append(f"【基差】{prem}¥{bv:.0f}({level})，现货偏紧，支撑近月。")
                signals.append(("利多", "强基差升水"))
                bullish += 1
            else:
                parts.append(f"【基差】{prem}¥{abs(bv):.0f}({level})，终端需求偏弱。")
                signals.append(("利空", "深贴水，现货压力偏大"))
                bearish += 1
        else:
            parts.append(f"【基差】{prem}¥{bv:.0f}({level})，基本正常。")
    else:
        parts.append("【基差】暂无数据。")

    # ===== 【利润】 =====
    profit_parts = []
    if profit:
        pv = profit["profit"]
        pct = profit.get("profit_pct", 0)
        profit_parts.append(f"PTA{'亏损' if pv < 0 else '盈利'}¥{abs(pv):.0f}({pct:+.1f}%)")
        if pv < -200:
            signals.append(("利多", f"PTA深度亏损({pv:.0f}元)，存在减产预期"))
            bullish += 1
        elif pv < 0:
            neutral += 1
        elif pv > 500:
            signals.append(("利空", f"PTA利润良好({pv:.0f}元)，工厂提负积极性高"))
            bearish += 1
        else:
            neutral += 1
    profit_str = "，".join(profit_parts) if profit_parts else "暂无数据"
    parts.append(f"【利润】{profit_str}。")

    # ===== 【库存】 =====
    inv_parts = []
    if inv:
        stock = inv.get("stock", 0)
        chg = inv.get("change", 0)
        chg_str = f"+{chg}" if chg > 0 else str(chg)
        inv_lv = "偏高" if stock > 250000 else "偏低" if stock < 150000 else "中性"
        inv_parts.append(f"PTA{int(stock/10000):.0f}万吨({chg_str}，{inv_lv})")
        if chg > 10000:
            signals.append(("利空", f"PTA库存大增{chg_str}吨"))
            bearish += 1
        elif chg < -10000:
            signals.append(("利多", f"PTA库存大降{abs(chg):.0d}吨"))
            bullish += 1
    if meg_inv:
        meg_stock = meg_inv.get("stock", 0)
        meg_chg = meg_inv.get("change", 0)
        inv_parts.append(f"MEG{meg_stock:,}吨({meg_chg:+d})")
    if sm_inv:
        sm_stock = sm_inv.get("stock", 0)
        sm_chg = sm_inv.get("change", 0)
        inv_parts.append(f"SM苯乙烯{sm_stock:,}吨({sm_chg:+d})")
    inv_str = "，".join(inv_parts) if inv_parts else "暂无库存数据"
    parts.append(f"【库存】{inv_str}。")

    # ===== 【下游】 =====
    dsparts = []
    if dxFiber:
        dsparts.append(f"涤纶短纤¥{dxFiber.get('price',0):.0f}(近月{dxFiber.get('near_basis',0):+.0f})")
    if eb:
        dsparts.append(f"苯乙烯¥{eb.get('price',0):.0f}(近月{eb.get('near_basis',0):+.0f})")
    if meg:
        dsparts.append(f"乙二醇¥{meg.get('price',0):.0f}(近月{meg.get('near_basis',0):+.0f})")
    ds_str = "，".join(dsparts) if dsparts else "暂无下游数据"
    parts.append(f"【下游】{ds_str}。")

    # ===== 【PXN】 =====
    if pxn_info:
        pxn_val = pxn_info.get("spread_usd", 0)
        level = pxn_info.get("level", "")
        parts.append(f"【裂解】PXN约${pxn_val:.0f}/吨({level})，{pxn_info.get('note','')}。")

    # ===== 【期货】 =====
    if pta_fut:
        sym = pta_fut.get("symbol", "TA")
        chg = pta_fut.get("change_pct", 0)
        lvl = "强势" if chg > 1.5 else "走弱" if chg < -1.5 else "平稳"
        parts.append(f"【期货】TA{sym[-3:]}({lvl}{chg:+.2f}%)。")

    # ===== 【综合评级】 =====
    if bullish > bearish + 1:
        rating = "偏多"
    elif bearish > bullish + 1:
        rating = "偏空"
    else:
        rating = "震荡"

    outlook_parts = []
    if rating == "偏多":
        outlook_parts.append("产业支撑偏强，短期偏多对待")
    elif rating == "偏空":
        outlook_parts.append("供需压力较大，短期偏空对待")
    else:
        outlook_parts.append("多空因素交织，震荡思路对待")

    if signals:
        top = [s[1] for s in signals[:3]]
        outlook_parts.extend(top)

    parts.append(f"【展望】{'；'.join(outlook_parts)}。")
    parts.append(f"【评级】整体：**{rating}**（利多{bullish}个，利空{bearish}个）。")

    return "\n".join(parts)


def test_industry_analysis():
    print("测试PTA产业基本面分析模块 v4...")
    print("=" * 60)
    data = get_pta_industry_data()
    if data["status"] == "success":
        print(f"✅ 分析完成 {data['timestamp']}")
        d = data["data"]

        up = d.get("upstream", {})
        pta = d.get("pta", {})
        cost = d.get("cost", {})
        ds = d.get("downstream", {})

        print("\n📊 关键产业指标")
        print("-" * 40)
        if "brent" in up:
            print(f"布伦特:  ${up['brent']['price']} ({up['brent']['change_pct']:+.2f}%) [{up['brent']['contract']}]")
        if "wti" in up:
            print(f"WTI:     ${up['wti']['price']} ({up['wti']['change_pct']:+.2f}%) [{up['wti']['contract']}]")
        if "cn_gasoline_wholesale" in up:
            u = up["cn_gasoline_wholesale"]
            print(f"国内汽油批发: ¥{u['price_cny_ton']}/吨 ({u['date']})  ≈ ${u['price_usd_bbl_estimate']}/桶")
        if "px" in up:
            px = up["px"]
            print(f"PX现货:   ¥{px['spot_price']:.0f} ({px.get('near_contract','?')})")
            print(f"  近月:{px.get('near_contract','?')} ¥{px.get('near_price',0):.0f}  主力:{px.get('dominant_contract','?')} ¥{px.get('dominant_price',0):.0f}  主基差:{px.get('dom_basis',0):+.0f}")
        if "naphtha" in up:
            print(f"石脑油:   ${up['naphtha']['naphtha_cfr_estimate']}/吨（估算）")
        if "pxn" in up:
            print(f"PXN:     ${up['pxn']['spread_usd']:.0f}/吨 ({up['pxn']['level']})")
        print()
        if "spot" in pta:
            s = pta["spot"]
            print(f"PTA现货:  ¥{s['price']:.2f} [{s['date']}]")
            print(f"  近月:{s.get('near_contract','?')} ¥{s.get('near_price',0):.0f}  主力:{s.get('dominant_contract','?')} ¥{s.get('dominant_price',0):.0f}  主基差:{s.get('dom_basis',0):+.0f}")
        if "future" in pta:
            f = pta["future"]
            print(f"PTA期货:  TA{f['symbol'][-3:]} 结算¥{f['settle']:.0f} ({f['change_pct']:+.2f}%)")
        if "basis" in pta:
            b = pta["basis"]
            print(f"PTA基差:  ¥{b['value']:.1f} ({b['premium']}, {b['level']})")
        if "social_inventory" in pta:
            inv = pta["social_inventory"]
            print(f"PTA库存:   {inv['stock']:,}吨 ({inv['change']:+d})")
        if "meg_inventory" in pta:
            inv = pta["meg_inventory"]
            print(f"MEG库存:   {inv['stock']:,}吨 ({inv['change']:+d})")
        if "sm_inventory" in pta:
            inv = pta["sm_inventory"]
            print(f"SM库存:    {inv['stock']:,}吨 ({inv['change']:+d})")
        print()
        if "pta_cost" in cost:
            print(f"成本:    ¥{cost['pta_cost']['pta_cost']:.0f} = PX({cost['pta_cost']['px_price']:.0f}) × 0.655")
        if "profit" in cost:
            p = cost["profit"]
            print(f"利润:    ¥{p['profit']:.0f} ({p['profit_pct']:+.1f}%) → {p['level']}")
        print()
        print("下游:", list(ds.keys()))

        print("\n🤖 AI产业点评")
        print("-" * 40)
        print(d.get("ai_commentary", ""))
    else:
        print(f"❌ 失败: {data.get('error', '未知错误')}")
    return data


if __name__ == "__main__":
    test_industry_analysis()
