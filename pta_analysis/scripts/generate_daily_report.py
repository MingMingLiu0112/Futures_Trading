#!/usr/bin/env python3
"""
PTA市场日报生成器 v2.1
生成市场日报JSON数据，用于前端页面展示和飞书推送
定时任务：每天08:30运行

更新日志 v2.1:
- 使用 futures_spot_price_daily 获取PTA/PX/涤纶短纤等现货数据（含近月基差）
- 接入SHMET金属网快讯作为产业快讯来源
- 优化宏观快讯（凤凰财经 + 百度财经新闻）
- 充实产业链上下游开工率、库存数据展示
- 完善section1/2/3的详细解读文本
"""
import os, sys, json, re, warnings, requests
from datetime import datetime, timedelta
from typing import Optional, Dict, List

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import akshare as ak
import pandas as pd
import numpy as np

warnings.filterwarnings('ignore')

WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_PATH = os.path.join(WORKSPACE, 'data', 'fundamental', 'daily_report.json')
USD_CNY = 7.2


def fetch(url: str, timeout: int = 12) -> str:
    """通用HTTP GET"""
    try:
        req = requests.Request('GET', url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        resp = requests.Session().send(req.prepare(), timeout=timeout)
        for enc in ['utf-8', 'gbk', 'gb2312']:
            try:
                return resp.content.decode(enc)
            except:
                pass
    except:
        pass
    return ''


def _is_trading_day(date_str: str) -> bool:
    """检查是否为交易日（简单判断：非周末）"""
    try:
        d = datetime.strptime(date_str, '%Y%m%d')
        return d.weekday() < 5
    except:
        return False


def get_latest_trading_date():
    """获取最近交易日"""
    today = datetime.now()
    for delta in range(8):
        d = today - timedelta(days=delta)
        if d.weekday() < 5:
            return d.strftime("%Y%m%d"), d.strftime("%Y-%m-%d")
    return today.strftime("%Y%m%d"), today.strftime("%Y-%m-%d")


# ==================== 数据获取函数 ====================

def get_crude_oil() -> Dict:
    """获取原油数据"""
    data = {}
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://quote.eastmoney.com/',
        }
        url = ('https://futsseapi.eastmoney.com/list/COMEX,NYMEX,COBOT,SGX,NYBOT,LME,MDEX,TOCOM,IPE'
               '?orderBy=dm&sort=asc&pageSize=500&pageIndex=0'
               '&token=58b2fa%2E%2E%2E089c'
               '&field=dm,sc,name,p,zsjd,zde,zdf,f152,o,h,l,zjsj,vol,wp,np,ccl')
        r = requests.get(url, headers=headers, timeout=15)
        items = {item['dm']: item for item in r.json().get('list', [])}

        b00y = items.get('B00Y', {})
        if b00y and b00y.get('p', 0) > 0:
            data['brent'] = {
                'price': float(b00y['p']),
                'change_pct': float(b00y.get('zdf', 0)),
                'volume': int(b00y.get('vol', 0)),
                'contract': str(b00y.get('name', '布伦特')),
            }

        cl00y = items.get('CL00Y', {})
        if cl00y and cl00y.get('p', 0) > 0:
            data['wti'] = {
                'price': float(cl00y['p']),
                'change_pct': float(cl00y.get('zdf', 0)),
                'volume': int(cl00y.get('vol', 0)),
                'contract': str(cl00y.get('name', 'WTI')),
            }
    except Exception as e:
        print(f"原油数据错误: {e}")
    return data


def get_spot_daily(symbols: List[str], days: int = 5) -> Dict[str, Dict]:
    """批量获取现货每日价格（使用futures_spot_price_daily，更权威）"""
    result = {}
    today_str = datetime.now().strftime('%Y%m%d')
    start_str = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
    
    # 只取有数据的交易日
    trading_dates = [start_str]
    for i in range(1, days + 5):
        d = datetime.now() - timedelta(days=i)
        if d.weekday() < 5:
            trading_dates.append(d.strftime('%Y%m%d'))
        if len(trading_dates) >= 5:
            break
    
    try:
        df = ak.futures_spot_price_daily(
            start_day=trading_dates[-1],
            end_day=trading_dates[0],
            vars_list=symbols
        )
        if df is not None and not df.empty:
            for sym in symbols:
                sym_df = df[df['symbol'] == sym].tail(3)
                if not sym_df.empty:
                    latest = sym_df.iloc[-1]
                    prev = sym_df.iloc[-2] if len(sym_df) >= 2 else latest
                    change = round(float(latest.get('spot_price', 0)) - float(prev.get('spot_price', 0)), 2) if prev is not None else 0
                    result[sym] = {
                        'spot_price': float(latest.get('spot_price', 0)),
                        'near_contract': str(latest.get('near_contract', '')),
                        'near_price': float(latest.get('near_contract_price', 0)),
                        'dominant_contract': str(latest.get('dominant_contract', '')),
                        'dominant_price': float(latest.get('dominant_contract_price', 0)),
                        'near_basis': float(latest.get('near_basis', 0)),
                        'dom_basis': float(latest.get('dom_basis', 0)),
                        'date': str(latest.get('date', '')),
                        'change': change,
                        'change_pct': round((change / float(prev.get('spot_price', 1))) * 100, 2) if prev.get('spot_price', 0) else 0,
                        'source': '郑商所每日现货参考价格表'
                    }
    except Exception as e:
        print(f"  现货每日价格获取失败 {symbols}: {e}")
    return result


def get_px_data() -> Dict:
    """获取PX数据"""
    data = {}
    date_str, date_disp = get_latest_trading_date()
    
    # 优先使用 futures_spot_price_daily
    spot_data = get_spot_daily(['PX'], days=5)
    if 'PX' in spot_data:
        data = spot_data['PX']
        return data
    
    # Fallback: 郑商所每日现货表
    try:
        df = ak.futures_spot_price(date=date_str, vars_list=["PX"])
        if df is not None and not df.empty:
            px_rows = df[df['symbol'] == 'PX']
            if not px_rows.empty:
                r = px_rows.iloc[0]
                data['spot_price'] = float(r['spot_price'])
                data['near_contract'] = str(r['near_contract'])
                data['near_price'] = float(r['near_contract_price'])
                data['dominant_contract'] = str(r['dominant_contract'])
                data['dominant_price'] = float(r['dominant_contract_price'])
                data['dom_basis'] = float(r['dom_basis'])
                data['date'] = str(r['date'])
                data['source'] = '郑商所每日现货参考价格表'
    except Exception as e:
        print(f"PX郑商所数据错误: {e}")
    
    # 备用东方财富数据
    if not data:
        try:
            df_em = ak.futures_spot_stock(symbol='化工')
            if df_em is not None and not df_em.empty:
                px_row = df_em[df_em['商品名称'] == 'PX']
                if not px_row.empty:
                    r = px_row.iloc[0]
                    data['spot_price'] = float(r['最新价格'])
                    data['change_pct'] = float(r.get('近半年涨跌幅', 0))
                    data['date'] = date_disp
                    data['source'] = '东方财富现货'
        except:
            pass
    return data


def get_pta_data() -> Dict:
    """获取PTA数据"""
    data = {}
    date_str, date_disp = get_latest_trading_date()

    # 优先使用 futures_spot_price_daily（含近月基差）
    spot_data = get_spot_daily(['TA'], days=5)
    if 'TA' in spot_data:
        data = spot_data['TA']
    else:
        # Fallback: 郑商所每日现货表
        try:
            df = ak.futures_spot_price(date=date_str, vars_list=["PTA"])
            if df is not None and not df.empty:
                ta_rows = df[df['symbol'] == 'TA']
                if not ta_rows.empty:
                    r = ta_rows.iloc[0]
                    data['spot_price'] = float(r['spot_price'])
                    data['near_contract'] = str(r['near_contract'])
                    data['near_price'] = float(r['near_contract_price'])
                    data['dominant_contract'] = str(r['dominant_contract'])
                    data['dominant_price'] = float(r['dominant_contract_price'])
                    data['dom_basis'] = float(r['dom_basis'])
                    data['date'] = str(r['date'])
        except Exception as e:
            print(f"PTA现货数据错误: {e}")

    # PTA期货日行情
    try:
        df_fut = ak.get_czce_daily(date=date_str)
        if df_fut is not None and not df_fut.empty:
            ta_fut = df_fut[df_fut['品种代码'].str.contains('TA', na=False)]
            if not ta_fut.empty:
                r = ta_fut.iloc[-1]
                data['future'] = {
                    'symbol': str(r.get('品种代码', 'TA')),
                    'settle': float(r.get('结算价', 0)),
                    'close': float(r.get('收盘价', 0)),
                    'volume': int(r.get('成交量', 0)),
                    'open_interest': int(r.get('持仓量', 0)),
                }
                prev_close = float(r.get('昨收盘', 0))
                if prev_close > 0:
                    change = float(r.get('收盘价', 0)) - prev_close
                    data['future']['change'] = round(change, 2)
                    data['future']['change_pct'] = round((change / prev_close) * 100, 2)
    except Exception as e:
        print(f"PTA期货数据错误: {e}")

    return data


def get_inventory_data() -> Dict:
    """获取库存数据"""
    data = {}
    try:
        # 苯乙烯库存（东方财富有数据）
        try:
            df_sm = ak.futures_inventory_em(symbol="苯乙烯")
            if df_sm is not None and not df_sm.empty:
                r = df_sm.iloc[-1]
                stock = float(r.get('库存', r.get('库存量', 0)))
                change = float(r.get('增减', r.get('环比变化', 0)))
                data['sm'] = {
                    'stock': stock,
                    'change': change,
                    'date': str(r.get('日期', '')),
                }
        except Exception as e:
            print(f"苯乙烯库存错误: {e}")

        # MEG库存（东方财富可用）
        try:
            df_meg = ak.futures_inventory_em(symbol="乙二醇")
            if df_meg is not None and not df_meg.empty:
                r = df_meg.iloc[-1]
                stock = float(r.get('库存', r.get('库存量', 0)))
                change = float(r.get('增减', r.get('环比变化', 0)))
                data['meg'] = {
                    'stock': stock,
                    'change': change,
                    'date': str(r.get('日期', '')),
                }
        except Exception as e:
            print(f"MEG库存错误: {e}")

        # PTA库存（东方财富无PTA，用spot数据或期货仓单代替）
        # 尝试从郑商所获取PTA仓单数据
        try:
            # 通过期货现货价格表中的库存变化来估算
            spot_data = get_spot_daily(['TA'], days=5)
            if 'TA' in spot_data:
                # 库存数据需订阅，这里仅做说明
                pass
        except:
            pass

    except Exception as e:
        print(f"库存数据错误: {e}")
    return data


def get_downstream_spot() -> Dict:
    """获取下游现货数据（含涤纶短纤/乙二醇/苯乙烯/甲醇等）"""
    data = {}
    
    # 使用 futures_spot_price_daily 批量获取（包含CY涤纶短纤、EG乙二醇、EB苯乙烯、MA甲醇）
    symbol_map = {
        '涤纶短纤': 'CY',
        '乙二醇': 'EG',
        '苯乙烯': 'EB',
        '甲醇MA': 'MA',
    }
    
    # 一次性获取所有下游品种
    spot_all = get_spot_daily(['CY', 'EG', 'EB', 'MA', 'PF'], days=5)
    
    for name, sym in symbol_map.items():
        if sym in spot_all:
            s = spot_all[sym]
            data[name] = {
                'name': name,
                'price': s.get('spot_price'),
                'near_contract': s.get('near_contract'),
                'near_price': s.get('near_price'),
                'near_basis': s.get('near_basis'),
                'date': s.get('date'),
                'change': s.get('change'),
                'change_pct': s.get('change_pct'),
            }
    
    # 如果批量获取失败，用老方法兜底
    if not data:
        date_str, date_disp = get_latest_trading_date()
        try:
            df_spot = ak.futures_spot_price(date=date_str)
            if df_spot is not None and not df_spot.empty:
                for _, row in df_spot.iterrows():
                    name = str(row.get('symbol', ''))
                    if name in symbol_map:
                        key = symbol_map[name]
                        data[key] = {
                            'name': name,
                            'price': float(row.get('spot_price', 0)),
                            'near_contract': str(row.get('near_contract', '')),
                            'near_price': float(row.get('near_contract_price', 0)),
                            'near_basis': float(row.get('near_basis', 0)),
                            'date': str(row.get('date', '')),
                        }
        except Exception as e:
            print(f"下游现货数据错误: {e}")
    
    return data


def get_industry_rates() -> Dict:
    """获取产业链开工率数据
    注：akshare暂无自动获取接口，需专业订阅（隆众资讯/卓创资讯/CCF）
    这里返回说明信息，并标注数据获取现状
    """
    return {
        'note': 'akshare暂无自动获取接口，需专业订阅或人工录入。数据来源：隆众资讯/卓创资讯/CCF中国化纤信息网',
        'data': {
            'px': {
                'name': 'PX装置开工率',
                'value': None,
                'unit': '%',
                'source': '隆众资讯/卓创资讯/CCF',
                'status': '需订阅'
            },
            'pta': {
                'name': 'PTA装置开工率',
                'value': None,
                'unit': '%',
                'source': '隆众资讯/卓创资讯',
                'status': '需订阅'
            },
            'polyester': {
                'name': '聚酯开工率',
                'value': None,
                'unit': '%',
                'source': 'CCF/隆众资讯',
                'status': '需订阅'
            },
            'weaving': {
                'name': '织造开工率',
                'value': None,
                'unit': '%',
                'source': 'CCF/隆众资讯',
                'status': '需订阅'
            },
            'meg': {
                'name': 'MEG装置开工率',
                'value': None,
                'unit': '%',
                'source': '隆众资讯/卓创资讯',
                'status': '需订阅'
            },
        },
        # 从下游数据推断开工情况的参考指标
        'proxy_indicators': {
            'description': '以下指标可辅助判断开工率变化趋势（基于公开数据推算）',
            'pta_social_inventory': '关注PTA社会库存变化，库存累积通常意味着开工率偏高',
            'meg_import': 'MEG进口量及港口库存可反映 MEG装置开工情况',
            'polyester_spot': '聚酯产品现货价格变化可辅助判断聚酯开工率趋势'
        }
    }


def get_macro_news() -> Dict:
    """获取宏观及产业快讯
    来源：凤凰财经 + SHMET金属网 + 百度财经
    """
    news = {'geo': [], 'fed': [], 'industry': [], 'macro': []}

    # ---- SHMET金属网快讯 ----
    try:
        df_shmet = ak.futures_news_shmet(symbol='全部')
        if df_shmet is not None and not df_shmet.empty:
            for _, row in df_shmet.head(10).iterrows():
                content = str(row.get('内容', ''))
                if not content or len(content) < 10:
                    continue
                # 产业快讯：PTA/PX/聚酯/织机/原油/MEG/乙二醇相关
                ind_kws = ['PTA', 'PX', '聚酯', '涤纶', 'MEG', '乙二醇', '苯乙烯', '原油', '期货', '石化', 'pta']
                geo_kws = ['中东', '霍尔木兹', '伊朗', '以色列', '俄乌', '红海', '胡塞', '地缘', '制裁']
                fed_kws = ['美联储', '降息', '加息', '鲍威尔', '利率', 'CPI', 'PPI', '美元']
                macro_kws = ['宏观', '经济', 'GDP', '通胀', '出口', '进口', '制造业', 'PMI']
                
                if any(kw.lower() in content.lower() for kw in geo_kws) and len(news['geo']) < 2:
                    news['geo'].append(content[:100])
                elif any(kw in content for kw in fed_kws) and len(news['fed']) < 2:
                    news['fed'].append(content[:100])
                elif any(kw.lower() in content.lower() for kw in ind_kws) and len(news['industry']) < 4:
                    news['industry'].append(content[:100])
                elif any(kw in content for kw in macro_kws) and len(news['macro']) < 2:
                    news['macro'].append(content[:100])
    except Exception as e:
        print(f"SHMET快讯错误: {e}")

    # ---- 凤凰财经宏观快讯 ----
    try:
        html = fetch('https://finance.ifeng.com/')
        if html:
            html_clean = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
            html_clean = re.sub(r'<style[^>]*>.*?</style>', '', html_clean, flags=re.DOTALL)
            links = re.findall(r'<a[^>]+href="(https?://[^\"]{10,})"[^>]*>(.*?)</a>', html_clean, flags=re.DOTALL)

            geo_kws = ['地缘', '中东', '俄乌', '红海', '以色列', '伊朗', '霍尔木兹', '胡塞', '制裁']
            fed_kws = ['美联储', '降息', '加息', '鲍威尔', '利率', 'CPI', 'PPI']
            ind_kws = ['PTA', 'PX', '聚酯', '织机', '原油', '期货', '石化']

            seen = set()
            for href, title in links:
                title_text = re.sub(r'<[^>]+>', '', title).strip()
                if not title_text or len(title_text) < 5 or title_text in seen:
                    continue

                for kw in geo_kws:
                    if kw in title_text and len(news['geo']) < 3:
                        news['geo'].append(title_text[:80])
                        seen.add(title_text)
                        break
                for kw in fed_kws:
                    if kw in title_text and len(news['fed']) < 3:
                        news['fed'].append(title_text[:80])
                        seen.add(title_text)
                        break
                for kw in ind_kws:
                    if kw in title_text and len(news['industry']) < 6:
                        news['industry'].append(title_text[:80])
                        seen.add(title_text)
                        break
    except Exception as e:
        print(f"凤凰财经快讯错误: {e}")

    # ---- 百度财经宏观新闻 ----
    try:
        df_baidu = ak.news_economic_baidu()
        if df_baidu is not None and not df_baidu.empty:
            for _, row in df_baidu.head(15).iterrows():
                title = str(row.get('标题', ''))
                if not title or len(title) < 5:
                    continue
                geo_kws = ['中东', '伊朗', '以色列', '霍尔木兹', '俄乌', '地缘', '红海', '制裁']
                macro_kws = ['降息', '加息', '美联储', 'CPI', 'PPI', '经济', 'GDP', '通胀']
                ind_kws = ['PTA', 'PX', '聚酯', '原油', '石化', '化工']
                
                if any(kw in title for kw in geo_kws) and len(news['geo']) < 4:
                    news['geo'].append(title[:80])
                elif any(kw in title for kw in macro_kws) and len(news['macro']) < 3:
                    news['macro'].append(title[:80])
                elif any(kw in title for kw in ind_kws) and len(news['industry']) < 6:
                    news['industry'].append(title[:80])
    except Exception as e:
        print(f"百度财经新闻错误: {e}")

    # 去重
    for key in news:
        seen = set()
        news[key] = [x for x in news[key] if not (x in seen or seen.add(x))]

    return news


def get_option_data() -> Dict:
    """获取期权数据"""
    data = {
        'highlights': [],
        'pcr_spot': None,
        'pcr_hold': None,
        'key_levels': {'bottom': None, 'top': None}
    }

    try:
        td = None
        for d in [datetime.now().strftime('%Y%m%d')] + \
                 [(datetime.now() - timedelta(days=i)).strftime('%Y%m%d') for i in range(1, 8)]:
            try:
                df_o = ak.option_hist_czce(symbol='PTA期权', trade_date=d)
                if df_o is not None and len(df_o) > 100:
                    td = d
                    break
            except:
                pass

        if td:
            def get_strike(code):
                m = re.search(r'[PC](\d+)', code)
                return int(m.group(1)) if m else None

            df_o['行权价'] = df_o['合约代码'].apply(get_strike)
            puts = df_o[df_o['合约代码'].str.contains('P', na=False)].copy()
            calls = df_o[df_o['合约代码'].str.contains('C', na=False)].copy()

            puts['iv'] = pd.to_numeric(puts['隐含波动率'], errors='coerce')
            calls['iv'] = pd.to_numeric(calls['隐含波动率'], errors='coerce')

            cv = calls['成交量(手)'].sum()
            pv = puts['成交量(手)'].sum()
            co = calls['持仓量'].sum()
            po = puts['持仓量'].sum()

            data['pcr_spot'] = round(pv / cv, 4) if cv else None
            data['pcr_hold'] = round(po / co, 4) if co else None

            # 关键PUT（持仓量最大的5个）
            top_puts = puts.nlargest(5, '持仓量')
            for _, r in top_puts.iterrows():
                strike = int(r['行权价']) if pd.notna(r.get('行权价')) else 0
                data['highlights'].append({
                    'type': 'P',
                    'strike': strike,
                    'change': f"+{int(r['持仓量']):,}手",
                    'iv': f"{r['iv']:.4f}" if pd.notna(r.get('iv')) else "N/A",
                    'signal': '底部防线' if strike < 6500 else '支撑位'
                })

            # 关键CALL（持仓量最大的5个）
            top_calls = calls.nlargest(5, '持仓量')
            for _, r in top_calls.iterrows():
                strike = int(r['行权价']) if pd.notna(r.get('行权价')) else 0
                data['highlights'].append({
                    'type': 'C',
                    'strike': strike,
                    'change': f"+{int(r['持仓量']):,}手",
                    'iv': f"{r['iv']:.4f}" if pd.notna(r.get('iv')) else "N/A",
                    'signal': '上行压制' if strike > 6500 else '阻力位'
                })

            data['trade_date'] = td

            # 估算核心区间：基于持仓量Top5的PUT/CALL
            # 底部 = top5 PUT中的最高行权价，压制 = top5 CALL中的最低行权价
            if not puts.empty:
                top5_puts = puts.nlargest(5, '持仓量')
                valid = top5_puts.dropna(subset=['行权价'])
                if len(valid) > 0:
                    data['key_levels']['bottom'] = int(valid['行权价'].max())

            if not calls.empty:
                top5_calls = calls.nlargest(5, '持仓量')
                valid = top5_calls.dropna(subset=['行权价'])
                if len(valid) > 0:
                    data['key_levels']['top'] = int(valid['行权价'].min())

    except Exception as e:
        print(f"期权数据错误: {e}")

    return data


def generate_report() -> Dict:
    """生成完整日报数据"""
    report = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'section1': None,  # 期权数据解读
        'section2': None,  # 宏观与基本面
        'section3': None,  # 策略建议
        'industry_rates': None,  # 开工率与库存
        'macro_news': None,  # 宏观产业快讯
    }

    print("[1/7] 获取原油数据...")
    crude = get_crude_oil()

    print("[2/7] 获取PX数据...")
    px = get_px_data()

    print("[3/7] 获取PTA数据...")
    pta = get_pta_data()

    print("[4/7] 获取库存数据...")
    inventory = get_inventory_data()

    print("[5/7] 获取下游现货...")
    downstream = get_downstream_spot()

    print("[6/7] 获取开工率数据...")
    rates = get_industry_rates()

    print("[7/7] 获取宏观快讯...")
    macro_news = get_macro_news()

    # 计算成本利润
    cost_data = {}
    if px.get('spot_price') and px.get('spot_price') > 0:
        cost_data['pta_cost'] = round(px['spot_price'] * 0.655, 0)
    if pta.get('spot_price') and cost_data.get('pta_cost'):
        cost_data['profit'] = round(pta['spot_price'] - cost_data['pta_cost'], 0)
        cost_data['profit_pct'] = round((cost_data['profit'] / cost_data['pta_cost']) * 100, 1) if cost_data['pta_cost'] else 0

    # 成本区间估算
    cost_low = None
    cost_high = None
    if px.get('spot_price'):
        cost_low = round(px['spot_price'] * 0.655 + 300, 0)
        cost_high = round(px['spot_price'] * 0.655 + 800, 0)

    report['industry_rates'] = rates
    report['macro_news'] = macro_news
    report['crude'] = crude
    report['px'] = px
    report['pta'] = pta
    report['inventory'] = inventory
    report['downstream'] = downstream
    report['cost'] = cost_data
    report['cost_range'] = {'low': cost_low, 'high': cost_high}

    # 期权数据
    print("  获取期权数据...")
    opt = get_option_data()
    report['option'] = opt

    # 生成结构化分析
    report['section1'] = generate_option_analysis(opt)
    report['section2'] = generate_macro_analysis(crude, px, pta, rates, inventory, macro_news, cost_data, cost_low, cost_high)
    report['section3'] = generate_strategy_suggestions(opt, pta, cost_data, cost_low, cost_high)

    return report


def generate_option_analysis(opt: Dict) -> Dict:
    """生成期权数据分析（按用户模板格式）"""
    highlights = opt.get('highlights', [])
    bottom = opt.get('key_levels', {}).get('bottom')
    top = opt.get('key_levels', {}).get('top')
    pcr_spot = opt.get('pcr_spot')
    pcr_hold = opt.get('pcr_hold')
    trade_date = opt.get('trade_date', '')

    # 筛选关键PUT（底部防线）和CALL（上行压制）
    all_puts = [h for h in highlights if h['type'] == 'P']
    all_calls = [h for h in highlights if h['type'] == 'C']

    # 按持仓量排序，取Top6构建表格
    all_puts.sort(key=lambda x: int(x.get('change', '0').replace(',','').replace('+','').replace('手','')) if x.get('change') else 0, reverse=True)
    all_calls.sort(key=lambda x: int(x.get('change', '0').replace(',','').replace('+','').replace('手','')) if x.get('change') else 0, reverse=True)

    # 取前6个PUT和6个CALL用于表格
    table_puts = all_puts[:6]
    table_calls = all_calls[:6]
    table_items = table_puts + table_calls
    table_items.sort(key=lambda x: x['strike'])

    # 生成结论（4条）
    conclusions = []

    # 底部判断
    if bottom and top:
        if bottom >= 6500:
            conclusions.append(f"✅ 底部防线系统性上移至{bottom}元，底部区间已明确上移，市场对底部区间的认知已升级。")
        elif bottom >= 6000:
            conclusions.append(f"⚠️ 底部仍在{bottom}元，需警惕进一步下移风险")
        else:
            conclusions.append(f"⚠️ 底部区间下移至{bottom}元，市场信心不足")

    # PCR判断
    if pcr_hold:
        if pcr_hold > 1.2:
            conclusions.append(f"📉 PCR持仓={pcr_hold:.2f}>1.2，空头力量偏强，下行风险需警惕")
        elif pcr_hold < 0.8:
            conclusions.append(f"📈 PCR持仓={pcr_hold:.2f}<0.8，多头力量偏强，上行动能充足")
        else:
            conclusions.append(f"⚖️ PCR持仓={pcr_hold:.2f}，多空相对均衡，区间震荡格局")

    if pcr_spot:
        if pcr_spot > 1.0:
            conclusions.append(f"📊 成交PCR={pcr_spot:.2f}>1.0，当日成交偏空，短线情绪偏弱")
        elif pcr_spot < 0.7:
            conclusions.append(f"📊 成交PCR={pcr_spot:.2f}<0.7，当日成交偏多，短线情绪偏强")

    # 核心区间
    if bottom and top:
        conclusions.append(f"📌 核心震荡区间确立为【{bottom}，{top}】元，产业资金已用真金白银画出新战场。")

    # 生成叙述文本
    if bottom and top and pcr_hold:
        if pcr_hold >= 1.0:
            narrative = (
                f"最新期权数据显示，交易重心已从前期的低位上移。"
                f"底部防线已系统性前移至{bottom}元，{bottom}元已成为新的铁底。"
                f"PCR持仓为{pcr_hold:.2f}，多空相对均衡，"
                f"核心区间【{bottom}，{top}】已成为产业资金的新战场。"
            )
        else:
            narrative = (
                f"最新期权数据显示市场情绪偏多，成交PCR为{pcr_spot:.2f}。"
                f"底部防线在{bottom}元，上方压制在{top}元，"
                f"核心区间【{bottom}，{top}】内运行。"
            )
    else:
        narrative = "期权数据获取中，具体分析待更新。"

    return {
        'title': '一、 期权数据解读',
        'subtitle': f"防线{'系统性上移' if bottom and bottom >= 6500 else '动态调整'}，{bottom or '待确认'}成新'铁底'" if bottom else '期权结构分析',
        'summary': narrative,
        'highlights': table_items if table_items else highlights[:8],
        'conclusions': conclusions if conclusions else ['数据获取中，具体分析待更新'],
        'key_levels': {
            'bottom': str(bottom) if bottom else '—',
            'top': str(top) if top else '—',
            'pcr_spot': f"{pcr_spot:.4f}" if pcr_spot else '—',
            'pcr_hold': f"{pcr_hold:.4f}" if pcr_hold else '—'
        }
    }


def generate_macro_analysis(crude, px, pta, rates, inventory, macro_news, cost_data, cost_low, cost_high) -> Dict:
    """生成宏观与基本面分析（详细解读版）"""
    brent_price = crude.get('brent', {}).get('price')
    wti_price = crude.get('wti', {}).get('price')
    pta_spot = pta.get('spot_price')
    pta_future = pta.get('future', {})

    geo_items = macro_news.get('geo', [])[:2]
    industry_items = macro_news.get('industry', [])[:4]
    macro_items = macro_news.get('macro', [])[:2]
    fed_items = macro_news.get('fed', [])[:2]

    # 综合评估
    assessment = []
    oil_signal = ''
    if brent_price and brent_price > 90:
        oil_signal = '🛢️ 原油高位运行，成本支撑坚挺'
        assessment.append('原油高位，成本支撑强')
    elif brent_price and brent_price > 80:
        oil_signal = '🛢️ 原油中高位，成本支撑尚可'
        assessment.append('原油中高位，成本支撑尚可')
    else:
        oil_signal = '🛢️ 原油偏弱，成本支撑减弱'
        assessment.append('原油偏弱，成本支撑有限')

    if cost_low and pta_spot:
        if pta_spot < cost_low:
            assessment.append('PTA深度亏损，供应端有收缩预期')
        elif pta_spot > cost_high:
            assessment.append('PTA高估，上游利润偏高')
        else:
            assessment.append('PTA利润正常，产业链运行平稳')

    # 库存评估
    inv_summary = ''
    if inventory.get('sm', {}).get('stock'):
        sm_change = inventory['sm'].get('change', 0)
        inv_summary += f"苯乙烯库存{inventory['sm']['stock']:.0f}吨({'增' if sm_change > 0 else '降'}{abs(sm_change):.0f})；"
    if inventory.get('meg', {}).get('stock'):
        meg_change = inventory['meg'].get('change', 0)
        inv_summary += f"MEG库存{inventory['meg']['stock']:.0f}吨({'增' if meg_change > 0 else '降'}{abs(meg_change):.0f})"

    return {
        'title': '二、 宏观与基本面',
        'subtitle': '成本支撑与供需博弈',
        'geo': {
            'title': '🌍 地缘政治',
            'content': geo_items[0][:60] if geo_items else '地缘局势总体平稳',
            'detail': '；'.join(geo_items[:2]) if geo_items else '暂无重大地缘事件',
            'status': '⚠️ 需关注' if geo_items else '✅ 平稳'
        },
        'macro': {
            'title': '📊 宏观经济',
            'items': macro_items + fed_items,
        },
        'industry': {
            'title': '🏭 产业快讯',
            'items': industry_items,
        },
        'oil': {
            'title': '🛢️ 原油市场',
            'wti': {
                'price': str(wti_price) if wti_price else '—',
                'change': f"+{crude.get('wti', {}).get('change_pct', 0):.2f}" if crude.get('wti') else '—',
                'unit': 'USD/桶'
            },
            'brent': {
                'price': str(brent_price) if brent_price else '—',
                'change': f"+{crude.get('brent', {}).get('change_pct', 0):.2f}" if crude.get('brent') else '—',
                'unit': 'USD/桶'
            },
            'signal': oil_signal,
            'outlook': '；'.join(assessment) if assessment else '原油价格波动，关注成本变化'
        },
        'pta': {
            'title': '📦 PTA产业',
            'supply_rate': rates.get('data', {}).get('pta', {}).get('value') or '需订阅',
            'px_price': str(px.get('spot_price', '—')),
            'px_unit': 'CNY/吨' if px.get('spot_price') else '',
            'polyester_rate': rates.get('data', {}).get('polyester', {}).get('value') or '需订阅',
            'weaving_rate': rates.get('data', {}).get('weaving', {}).get('value') or '需订阅',
            'assessment': '；'.join(assessment) if assessment else '成本支撑逻辑主导'
        },
        'inventory': {
            'pta': inventory.get('pta', {}).get('stock'),
            'meg': inventory.get('meg', {}).get('stock'),
            'sm': inventory.get('sm', {}).get('stock'),
            'summary': inv_summary or '库存数据获取中'
        },
        'cost_range': {
            'low': cost_low,
            'high': cost_high
        },
        'inventory_note': '⚠️ 库存数据需订阅隆众/卓创资讯，PTA社会库存暂无免费数据源',
        'rates_note': '⚠️ 开工率数据需订阅隆众资讯/卓创资讯/CCF，可辅助判断供需格局'
    }


def generate_strategy_suggestions(opt: Dict, pta: Dict, cost_data: Dict, cost_low, cost_high) -> Dict:
    """生成策略建议（详细解读版）"""
    strategies = []
    bottom = opt.get('key_levels', {}).get('bottom') or 6000
    top = opt.get('key_levels', {}).get('top') or 7000
    pta_price = pta.get('spot_price') or pta.get('future', {}).get('close', 0)
    pta_spot = pta.get('spot_price')
    
    profit = cost_data.get('profit', 0)
    pcr_hold = opt.get('pcr_hold')

    # ---- 区间位置判断 ----
    if pta_price > 0:
        position = ''
        if pta_price > top:
            strategies.append({
                'action': '⚠️ 价格突破区间上沿',
                'detail': f'当前价格{pta_price:.0f}已突破区间上沿{top}，突破有效性待确认',
                'suggestion': '卖方注意止损保护，关注是否有效突破（3日确认原则）；可考虑在更高行权价建立新头寸'
            })
        elif pta_price < bottom:
            strategies.append({
                'action': '🔍 价格接近区间下沿',
                'detail': f'当前价格{pta_price:.0f}接近区间下沿{bottom}，关注支撑强度',
                'suggestion': '卖方注意风控，底部区域不宜过度追空；可关注底部防线6500P的防守情况'
            })
        else:
            mid = (bottom + top) / 2
            if pta_price > mid:
                strategies.append({
                    'action': '📍 价格处于区间上半部',
                    'detail': f'价格{pta_price:.0f}在【{bottom}，{top}】区间中部偏上运行',
                    'suggestion': '卖方可在区间上沿附近布空单，注意严格止损；关注6900C附近压制'
                })
            else:
                strategies.append({
                    'action': '📍 价格处于区间下半部',
                    'detail': f'价格{pta_price:.0f}在【{bottom}，{top}】区间中部偏下运行',
                    'suggestion': '卖方可在区间内高抛低吸，关注底部防线6500P的防守情况'
                })

    # ---- 成本利润分析 ----
    if profit > 300:
        strategies.append({
            'action': '💰 PTA利润偏高',
            'detail': f'当前利润约{profit:.0f}元/吨，高利润刺激供应释放',
            'suggestion': '关注装置重启/提负动态，高利润下供应压力将在1-2周后显现'
        })
    elif profit > 0:
        strategies.append({
            'action': '✅ PTA利润正常',
            'detail': f'当前利润约{profit:.0f}元/吨，产业运行平稳',
            'suggestion': '产业链利润分配均衡，关注下游需求变化'
        })
    elif profit > -300:
        strategies.append({
            'action': '⚠️ PTA小幅亏损',
            'detail': f'当前亏损约{abs(profit):.0f}元/吨，供应端有收缩压力',
            'suggestion': '关注PTA装置检修计划，亏损扩大可能触发更多停车'
        })
    else:
        strategies.append({
            'action': '🚨 PTA深度亏损',
            'detail': f'当前亏损约{abs(profit):.0f}元/吨，产业亏损严重',
            'suggestion': '停车检修预期增强，供应端有望主动收缩，底部支撑逻辑强化'
        })

    # ---- PCR信号 ----
    if pcr_hold:
        if pcr_hold > 1.2:
            strategies.append({
                'action': '📉 PCR持仓偏高警示',
                'detail': f'持仓量PCR={pcr_hold:.2f}>1.2，空头力量偏强',
                'suggestion': '注意下行风险，底部区域做好对冲保护；卖方底部头寸可适度加仓'
            })
        elif pcr_hold < 0.8:
            strategies.append({
                'action': '📈 PCR持仓偏低警示',
                'detail': f'持仓量PCR={pcr_hold:.2f}<0.8，多头力量偏强',
                'suggestion': '注意上行风险，上方空间或打开；卖方注意止损保护'
            })
        else:
            strategies.append({
                'action': '⚖️ PCR处于中性区间',
                'detail': f'持仓量PCR={pcr_hold:.2f}，多空力量均衡',
                'suggestion': '市场进入相持阶段，区间震荡为主，适宜卖方收租策略'
            })

    if not strategies:
        strategies.append({
            'action': '⏳ 等待数据更新',
            'detail': '期权数据获取中，策略建议待更新',
            'suggestion': '请稍后刷新页面获取最新分析'
        })

    # ---- 核心思路 ----
    if pta_price and bottom and top:
        mid = (bottom + top) / 2
        if pta_price > top:
            position_desc = '价格已突破区间上沿，区间上沿防线已由产业资金重新布防'
            risk_desc = '注意价格回踩确认，警惕突破失败后的快速回调风险'
        elif pta_price > mid:
            position_desc = f'价格{pta_price:.0f}处于区间【{bottom}，{top}】上半部'
            risk_desc = '卖方可依托区间上沿布空，注意严格止损'
        elif pta_price > bottom:
            position_desc = f'价格{pta_price:.0f}处于区间【{bottom}，{top}】下半部'
            risk_desc = '底部区域卖方注意风控，不宜过度追空'
        else:
            position_desc = f'价格{pta_price:.0f}已触及区间下沿附近'
            risk_desc = '底部防线区域，关注6500P防线是否有效'
    else:
        position_desc = '核心区间已确立'
        risk_desc = '建议轻仓操作'

    core_idea = (
        f"核心思路：{position_desc}。"
        f"{risk_desc}。"
        f"建议卖方仓位严格控制在总资金30%以下，"
        f"继续在更高新平台上执行'收租'策略，"
        f"跟随产业资金完成从'被动防守'到'主动布局'的切换。"
    )

    return {
        'title': '三、 市场日报及策略建议',
        'subtitle': '跟随产业资金，动态调整持仓',
        'strategies': strategies[:5],  # 最多5条
        'core_idea': core_idea
    }


def save_report(report: Dict):
    """保存日报到JSON文件"""
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"日报已保存: {OUTPUT_PATH}")


def generate_feishu_message(report: Dict) -> str:
    """生成飞书推送消息（Markdown格式，完整日报结构）"""
    s1 = report.get('section1', {}) or {}
    s2 = report.get('section2', {}) or {}
    s3 = report.get('section3', {}) or {}
    pta = report.get('pta', {})
    px = report.get('px', {})
    crude = report.get('crude', {})
    opt = report.get('option', {})
    cost = report.get('cost', {})
    rates = report.get('industry_rates', {})
    inv = report.get('inventory', {})
    news = report.get('macro_news', {}) or {}
    downstream = report.get('downstream', {})

    date_str = datetime.now().strftime('%Y年%m月%d日 %H:%M')
    hls = s1.get('highlights', [])
    kl = s1.get('key_levels', {})

    lines = [
        f"📊 **PTA市场日报** | {date_str}",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"**{s1.get('subtitle', '期权数据分析')}**",
        "",
        s1.get('summary', ''),
        "",
        f"**核心区间：** 【{kl.get('bottom', '—')}，{kl.get('top', '—')}】元",
        f"**成交PCR：** {kl.get('pcr_spot', '—')} | **持仓PCR：** {kl.get('pcr_hold', '—')}",
        "",
    ]

    # 期权高光表格（字段名：change/signal/iv/strike/type）
    if hls:
        lines += [
            "| 行权价 | 类型 | 持仓变化 | 隐波 | 信号含义 |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
        for h in hls[:8]:
            strike = h.get('strike', '')
            typ = 'P' if h.get('type') == 'P' else 'C'
            change = h.get('change', '—')
            iv = h.get('iv', '—')
            signal = h.get('signal', '—')
            lines.append(f"| **{strike}** | {'看跌P' if typ=='P' else '看涨C'} | {change} | {iv} | {signal} |")

    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "**结论要点：**",
    ]
    for c in (s1.get('conclusions') or [])[:4]:
        lines.append(f"• {c}")

    # 二、宏观与基本面
    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"**{s2.get('title', '二、宏观与基本面')}**",
        "",
    ]

    # 原油
    wti_price = crude.get('wti', {}).get('price', '—')
    wti_chg = crude.get('wti', {}).get('change', '—')
    brent_price = crude.get('brent', {}).get('price', '—')
    brent_chg = crude.get('brent', {}).get('change', '—')
    lines += [
        f"🛢️ **原油市场：** WTI ${wti_price} ({wti_chg}%) | 布伦特 ${brent_price} ({brent_chg}%)",
        f"原油信号：{s2.get('oil', {}).get('signal', '数据获取中')}",
        f"综合评估：{s2.get('oil', {}).get('outlook', '数据获取中')}",
        "",
    ]

    # 地缘政治
    geo_detail = s2.get('geo', {}).get('detail') or s2.get('geo', {}).get('content', '暂无数据')
    lines.append(f"🌍 **地缘政治：** {geo_detail}")
    lines.append("")

    # 宏观/美联储
    macro_items = (s2.get('macro', {}) or {}).get('items') or []
    fed_items = macro_items[:2]
    if fed_items:
        lines.append("📊 **宏观/美联储：**")
        for item in fed_items:
            lines.append(f"• {item}")
        lines.append("")

    # 产业快讯
    ind_items = (s2.get('industry', {}) or {}).get('items') or []
    if ind_items:
        lines.append("🏭 **产业快讯：**")
        for item in ind_items[:4]:
            lines.append(f"• {item}")
        lines.append("")

    # PTA产业
    px_price = px.get('spot_price', '—')
    pta_price = pta.get('spot_price', '—')
    pta_rate = (rates.get('data', {}).get('pta', {}).get('value') or '需订阅→隆众/卓创')
    poly_rate = (rates.get('data', {}).get('polyester', {}).get('value') or '需订阅→CCF')
    weave_rate = (rates.get('data', {}).get('weaving', {}).get('value') or '需订阅→CCF')
    lines += [
        f"📦 **PTA产业：**",
        f"  • PX参考价：{px_price}元/吨",
        f"  • PTA现货：{pta_price}元/吨",
        f"  • PTA评估：{s2.get('pta', {}).get('assessment', '数据获取中')}",
        "",
        f"📈 **开工率：** PTA装置 {pta_rate}% | 聚酯 {poly_rate}% | 织造 {weave_rate}%",
        "",
    ]

    # 库存
    inv_summary = s2.get('inventory', {}).get('summary', '')
    if inv_summary:
        lines.append(f"📊 **库存：** {inv_summary}")
        lines.append("")
    if s2.get('inventory_note'):
        lines.append(s2.get('inventory_note'))
    if s2.get('rates_note'):
        lines.append(s2.get('rates_note'))

    # 三、策略建议
    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"**{s3.get('title', '三、策略建议')}**",
        "",
        f"**核心思路：** {s3.get('core_idea', '')}",
        "",
    ]
    for st in (s3.get('strategies') or [])[:5]:
        lines += [
            f"◆ **{st.get('action', '')}**：{st.get('detail', '')}",
            f"  → {st.get('suggestion', '')}",
            "",
        ]

    lines += [
        "━━━━━━━━━━━━━━━━━━━━━━",
        "⚠️ 本报告仅供参考，不构成投资建议",
        "PTA市场日报 v2.1 | 数据：郑商所/东方财富/SHMET/公开媒体",
    ]

    return '\n'.join(lines)


def push_feishu(message: str):
    """推送飞书消息"""
    try:
        # 从环境变量或配置文件获取webhook
        webhook = os.environ.get('FEISHU_WEBHOOK_PTA', 'https://open.feishu.cn/open-apis/bot/v2/hook/8148922b-04f5-469f-994e-ae3e17d6b256')
        resp = requests.post(webhook, json={
            'msg_type': 'text',
            'content': {'text': message}
        }, timeout=10)
        if resp.status_code == 200:
            result = resp.json()
            if result.get('code') == 0:
                print("✅ 飞书推送成功")
                return True
        print(f"❌ 飞书推送失败: {resp.text[:100]}")
    except Exception as e:
        print(f"❌ 飞书推送异常: {e}")
    return False


def main():
    print("=" * 50)
    print("PTA市场日报生成器")
    print("=" * 50)

    report = generate_report()
    save_report(report)

    # 生成飞书消息
    feishu_msg = generate_feishu_message(report)
    print("\n" + "=" * 50)
    print("飞书消息预览:")
    print("=" * 50)
    print(feishu_msg)

    # 推送飞书（可选，通过参数控制）
    if '--push' in sys.argv:
        push_feishu(feishu_msg)

    return report


if __name__ == '__main__':
    main()
