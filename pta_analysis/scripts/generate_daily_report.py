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
INTRADAY_REPORT_DIR = os.path.join(WORKSPACE, 'data', 'reports', 'intraday')
CLOSE_REPORT_DIR = os.path.join(WORKSPACE, 'data', 'reports')
MANUAL_MACRO_INPUT_PATH = os.path.join(WORKSPACE, 'data', 'fundamental', 'manual_macro_input.json')
PX_EXTERNAL_SCRAPE_PATH = os.path.join(WORKSPACE, 'data', 'fundamental', 'px_external_scrape.json')
USD_CNY = 7.2

# 引入 PX 外盘双路径合并（人工 + 抓取，谁最新用谁）
from macro.px_external_source import (
    merge_pick_winner, format_winner, load_scrape as _load_px_scrape,
)


def _is_pta_trading_session(now: Optional[datetime] = None) -> bool:
    """PTA交易时段：9:00-11:30, 13:30-15:00, 21:00-23:00；整15分钟快照允许收盘边界入档。"""
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return _pta_session_minute_allowed(minutes)


def _pta_session_minute_allowed(minutes: int) -> bool:
    """快照槽位判定：包含 09:00、11:30、13:30、15:00、21:00、23:00 边界。

    生成任务通常按15分钟触发；若用半开区间 `<11:30`/`<15:00`，会漏掉 11:30 和 15:00
    这种关键整点/半点收盘快照，导致全天复盘缺少 XX:00/XX:30 节点。
    """
    return (
        9*60 <= minutes <= 11*60 + 30
        or 13*60 + 30 <= minutes <= 15*60
        or 21*60 <= minutes <= 23*60
    )


def _slot_is_pta_trading_session(slot: str) -> bool:
    try:
        text = str(slot).zfill(4)
        minutes = int(text[:2]) * 60 + int(text[2:4])
    except Exception:
        return False
    return _pta_session_minute_allowed(minutes)


def _clean_news_text(text: str, max_len: int = 240) -> str:
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    text = re.sub(r'^(SHMET|财联社|金十数据)?\d{2}月\d{2}日讯[，,：:]*', '', text).strip()
    text = re.sub(r'^(【快讯】|快讯[:：])', '', text).strip()
    bad_fragments = ['广州期货交易所', '仓单日报']
    if any(x in text for x in bad_fragments):
        return ''
    if len(text) < 18 or text.endswith('】'):
        return ''
    # 不在固定100字处硬截断，优先在标点收尾，避免半句话。
    if len(text) > max_len:
        cut = max(text.rfind(p, 0, max_len) for p in ['。', '；', '，', ',', ';'])
        text = text[:cut + 1] if cut >= 80 else text[:max_len]
    return text.strip(' ，,;；')


def load_manual_macro_input() -> Dict:
    """读取用户盘前/休盘后喂入的宏观基本面材料；自动抓取只作为补充。"""
    if not os.path.exists(MANUAL_MACRO_INPUT_PATH):
        return {}
    try:
        with open(MANUAL_MACRO_INPUT_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception as e:
        print(f'手工宏观基本面读取失败: {e}')
    return {}


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

    # 只取有数据的交易日
    trading_dates = []
    for i in range(0, days + 5):
        d = datetime.now() - timedelta(days=i)
        if d.weekday() < 5:
            trading_dates.append(d.strftime('%Y%m%d'))
        if len(trading_dates) >= days:
            break

    try:
        df = ak.futures_spot_price_daily(
            start_day=trading_dates[-1],
            end_day=today_str,  # v2.11.53+ 修复：end_day 必须用今天
                                # 之前用 trading_dates[0] (=今天-5天)，
                                # 若其中含周末/节假日，akshare会返回空，
                                # 触发 get_px_data 走东方财富脏数据 fallback。
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


def _parse_px_asia_price_from_text(text: str) -> Optional[float]:
    """从宏观/生意社快讯文本中提取亚洲PX CFR中国美元价。"""
    if not text:
        return None
    s = str(text).replace(',', '')
    patterns = [
        r'亚洲\s*PX[^\d]{0,20}(\d{3,4}(?:\.\d+)?)\s*美元\s*/?吨\s*CFR\s*中国',
        r'PX[^\d]{0,20}(\d{3,4}(?:\.\d+)?)\s*美元\s*/?吨\s*CFR\s*中国',
        r'CFR\s*中国[^\d]{0,20}PX[^\d]{0,20}(\d{3,4}(?:\.\d+)?)\s*美元',
        r'PX[^\d]{0,20}收(?:于|盘|报)?\s*(\d{3,4}(?:\.\d+)?)\s*美元',
    ]
    for pat in patterns:
        m = re.search(pat, s, re.I)
        if m:
            try:
                val = float(m.group(1))
                if 500 <= val <= 2000:
                    return val
            except Exception:
                pass
    return None


def get_pta_shengyishe_benchmark() -> Dict:
    """获取生意社PTA每日基准价（同花顺goodsfu汇聚页）。

    用于研报/盘面快照的PTA现货锚。郑商所futures_spot_price_daily在到期/换月附近可能滞后，
    因此只作为合约/基差字段fallback；现货价优先采用生意社当日基准价。
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'http://stock.10jqka.com.cn/',
        }
        url = 'http://stock.10jqka.com.cn/getListPage.php?listid=cl_008002014&page=1'
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return {}
        text = re.sub(r'\s+', ' ', r.text)
        m = re.search(r'(\d{8})/c(\d{9})\.shtml"[^>]*>(?:\d{1,2}月\d{1,2}日)?生意社PTA基准价为([\d.]+)元/吨', text)
        if not m:
            m2 = re.search(r'生意社PTA基准价为([\d.]+)元/吨', text)
            if not m2:
                return {}
            return {
                'spot_price': float(m2.group(1)),
                'date': datetime.now().strftime('%Y%m%d'),
                'source': '生意社PTA基准价（同花顺goodsfu汇聚）',
                'article_url': url,
            }
        date_str, cid, price = m.group(1), m.group(2), float(m.group(3))
        return {
            'spot_price': price,
            'date': date_str,
            'source': '生意社PTA基准价（同花顺goodsfu汇聚）',
            'article_url': f'http://goodsfu.10jqka.com.cn/{date_str}/c{cid}.shtml',
        }
    except Exception as e:
        print(f"生意社PTA基准价获取失败: {e}")
    return {}


def _is_recent_date(date_value, max_age_days: int = 10) -> bool:
    """判断数据日期是否足够新。外盘/汇率日频数据允许周末和节假日自然滞后。"""
    if not date_value:
        return False
    try:
        dt = pd.to_datetime(str(date_value)).to_pydatetime()
        return (datetime.now() - dt).days <= max_age_days
    except Exception:
        return False


def _normalize_cny_middle_rate(value) -> Optional[float]:
    """SAFE/中行中间价通常以100美元兑人民币报价(如681.50)，统一转成USD/CNY=6.8150。"""
    try:
        rate = float(value)
    except Exception:
        return None
    if 100 <= rate <= 1000:
        rate = rate / 100.0
    if 5.0 <= rate <= 9.0:
        return round(rate, 4)
    return None


def get_usd_cny_rate() -> Dict:
    """获取美元人民币中间价。优先外管局/SAFE日频中间价，拒绝使用日期明显陈旧的新浪中行数据。"""
    warnings_seen = []

    # Primary: 外管局/SAFE人民币汇率中间价。实测 ak.currency_boc_safe() 持续更新到当日/上一工作日。
    try:
        df = ak.currency_boc_safe()
        if df is not None and not df.empty and '美元' in df.columns:
            valid = df.dropna(subset=['美元'])
            if not valid.empty:
                r = valid.iloc[-1]
                rate = _normalize_cny_middle_rate(r.get('美元'))
                date = str(r.get('日期', ''))
                if rate and _is_recent_date(date, max_age_days=10):
                    return {'rate': rate, 'source': '外管局/SAFE人民币汇率中间价', 'date': date, 'warning': ''}
                if rate:
                    warnings_seen.append(f'SAFE中间价日期偏旧({date})')
    except Exception as e:
        warnings_seen.append(f'SAFE中间价获取失败: {e}')

    # Fallback: 新浪中行接口。此前该接口停在2023-11-10；只在日期新鲜时采用。
    try:
        df = ak.currency_boc_sina()
        if df is not None and not df.empty and '央行中间价' in df.columns:
            valid = df.dropna(subset=['央行中间价'])
            if not valid.empty:
                r = valid.iloc[-1]
                rate = _normalize_cny_middle_rate(r.get('央行中间价'))
                date = str(r.get('日期', ''))
                if rate and _is_recent_date(date, max_age_days=10):
                    return {'rate': rate, 'source': '央行中间价/中行新浪', 'date': date, 'warning': '; '.join(warnings_seen)}
                if rate:
                    warnings_seen.append(f'中行新浪中间价日期偏旧({date})，已拒绝')
    except Exception as e:
        warnings_seen.append(f'中行新浪中间价获取失败: {e}')

    # Last live fallback: 即期报价仅作兜底，保留warning提示它不是央行/SAFE中间价。
    try:
        df = ak.fx_spot_quote()
        if df is not None and not df.empty:
            row = df[df['货币对'].astype(str).str.upper().eq('USD/CNY')]
            if not row.empty:
                r = row.iloc[0]
                vals = [float(r.get(c)) for c in ['买报价', '卖报价'] if pd.notna(r.get(c)) and float(r.get(c)) > 0]
                if vals:
                    rate = sum(vals) / len(vals)
                    if 5.0 <= rate <= 9.0:
                        warnings_seen.append('使用USD/CNY即期报价兜底，非央行/SAFE中间价')
                        return {'rate': round(rate, 4), 'source': 'USD/CNY即期报价 fallback', 'date': datetime.now().strftime('%Y-%m-%d'), 'warning': '; '.join(warnings_seen)}
    except Exception as e:
        warnings_seen.append(f'即期汇率获取失败: {e}')

    warnings_seen.append('汇率接口不可用，使用默认USD_CNY')
    return {'rate': USD_CNY, 'source': '默认兜底', 'date': '', 'warning': '; '.join(warnings_seen)}


def get_px_external_data(macro_news: Dict = None, manual_macro: Dict = None) -> Dict:
    """获取/提取PX亚洲收盘价，并按用户公式计算外盘PTA动态成本。

    数据源（三路双路径，谁最新用谁）：
      1) 人工 dict：manual_macro.px_external（人工填入的生意社/同花顺PX亚洲收盘价 USD/吨）
      2) 抓取 dict：data/fundamental/px_external_scrape.json（macro/px_external_scraper.py 写入）
      3) 文本正则：macro_news / manual_macro 文本中正则匹配（无明确日期，20h 闸门）

    合并策略由 macro.px_external_source.merge_pick_winner 统一处理：
      过滤价格 500-2000，按 date DESC / fetched_at DESC 排序，manual 优先于并列。
    """
    macro_news = macro_news or {}
    manual_macro = manual_macro or {}

    # 文本正则候选（仅当 manual / scrape 都没拿到时使用）
    text_extracted: Dict = {}
    candidates_text = []

    def _collect_texts(label: str, obj):
        if isinstance(obj, str):
            candidates_text.append((label, obj))
        elif isinstance(obj, list):
            for item in obj:
                _collect_texts(label, item)
        elif isinstance(obj, dict):
            for item in obj.values():
                _collect_texts(label, item)

    _collect_texts('人工宏观基本面', manual_macro)
    _collect_texts('自动宏观快讯', macro_news)
    for src, text in candidates_text:
        val = _parse_px_asia_price_from_text(text)
        if val:
            text_extracted = {
                'px_asia_close_usd': val,
                'date': manual_macro.get('as_of_date') or datetime.now().strftime('%Y-%m-%d'),
                'fetched_at': manual_macro.get('updated_at') or datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                'source': src,
                'source_text': _clean_news_text(text, 180),
            }
            break

    # 读抓取文件
    scrape = _load_px_scrape(PX_EXTERNAL_SCRAPE_PATH)

    # 三路合并
    winner, all_valid = merge_pick_winner(
        manual_macro=manual_macro,
        scrape=scrape,
        text_extracted=text_extracted,
    )

    px_price = None
    px_source = ''
    source_text = ''
    px_warning = ''
    if winner is None:
        # 候选都被新鲜度/价格区间筛掉
        reasons = []
        if isinstance(scrape, dict) and scrape.get('status') == 'failed':
            reasons.append(f"抓取未成功({scrape.get('error','')[:60]})")
        if manual_macro.get('px_external', {}).get('px_asia_close_usd'):
            reasons.append('人工PX外盘价超出合理区间或日期偏旧')
        if not reasons:
            reasons.append('无任何 PX 外盘数据')
        px_warning = '; '.join(reasons)
    else:
        px_price = float(winner['px_asia_close_usd'])
        px_source = winner.get('source', '')
        source_text = winner.get('source_text', '')
        # 若用的是文本正则，文本路径有 20h 闸门；赢家已被 _is_valid_record 过滤过

    rate_info = get_usd_cny_rate()
    result = {
        'px_asia_close_usd': px_price,
        'currency': 'USD/吨',
        'source': px_source or '待更新',
        'source_text': source_text,
        'usd_cny': rate_info.get('rate'),
        'usd_cny_source': rate_info.get('source'),
        'usd_cny_date': rate_info.get('date'),
        'formula': 'PX亚洲收盘价 * 0.655 * 1.01 * 1.13 * USD/CNY',
        'pta_external_cost': None,
        'candidate_count': len(all_valid),
        'candidates': [
            {
                'source_kind': c.get('source_kind'),
                'date': c.get('date'),
                'px_asia_close_usd': c.get('px_asia_close_usd'),
            } for c in all_valid
        ],
        'warning': '; '.join([x for x in [rate_info.get('warning') or '', px_warning] if x]),
    }
    if px_price and result.get('usd_cny'):
        result['pta_external_cost'] = round(px_price * 0.655 * 1.01 * 1.13 * float(result['usd_cny']), 0)
    else:
        result['warning'] = '; '.join([x for x in [result.get('warning') or '', 'PX亚洲收盘价暂未提取，外盘成本待更新'] if x])
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

    # v2.11.53+: 锁定郑商所单一数据源。
    # 删除原东方财富 futures_spot_stock fallback —— 该接口把期货月价当现货价
    # (如 9900/7500 实际是 PX608/PX610 月价)，污染 PX现货/PTA估算成本/PTA利润。
    # 郑商所接口异常时返回空 dict，让 daily_report.json 保留上一周期值。
    if not data:
        print(f"  PX郑商所两路都未取到数据，PX现货保留 daily_report.json 旧值 (date={date_disp})")
    return data


def get_pta_data() -> Dict:
    """获取PTA数据。

    盘面快照里的PTA现货价优先采用生意社每日基准价；郑商所/akshare现货表只保留合约、
    基差等辅助字段，并在生意社不可用时兜底，避免到期/换月时显示滞后的参考价。
    """
    data = {}
    date_str, date_disp = get_latest_trading_date()

    # 先取郑商所/akshare表作为合约与基差辅助字段（不是主现货口径）
    spot_aux = {}
    spot_data = get_spot_daily(['TA'], days=5)
    if 'TA' in spot_data:
        spot_aux = spot_data['TA']
    else:
        try:
            df = ak.futures_spot_price(date=date_str, vars_list=["PTA"])
            if df is not None and not df.empty:
                ta_rows = df[df['symbol'] == 'TA']
                if not ta_rows.empty:
                    r = ta_rows.iloc[0]
                    spot_aux = {
                        'spot_price': float(r['spot_price']),
                        'near_contract': str(r['near_contract']),
                        'near_price': float(r['near_contract_price']),
                        'dominant_contract': str(r['dominant_contract']),
                        'dominant_price': float(r['dominant_contract_price']),
                        'dom_basis': float(r['dom_basis']),
                        'date': str(r['date']),
                        'source': '郑商所每日现货参考价格表',
                    }
        except Exception as e:
            print(f"PTA现货辅助数据错误: {e}")

    if spot_aux:
        data.update(spot_aux)

    shengyishe = get_pta_shengyishe_benchmark()
    if shengyishe:
        old_spot = float(data.get('spot_price') or 0)
        data.update(shengyishe)
        data['spot_price_shengyishe'] = shengyishe['spot_price']
        data['spot_price_aux'] = old_spot or None
        if old_spot:
            data['aux_spot_diff'] = round(shengyishe['spot_price'] - old_spot, 2)
        data['spot_source_note'] = 'PTA现货价=生意社每日基准价；郑商所现货表仅作合约/基差辅助'
    elif not data:
        data = {'spot_price': None, 'date': date_disp, 'source': 'PTA现货暂缺'}

    # PTA期货日行情（CZCE日行情，英文列名：symbol/settle/close/volume/open_interest/pre_settle/variety）
    try:
        df_fut = ak.get_czce_daily(date=date_str)
        if df_fut is not None and not df_fut.empty:
            # 按variety或symbol筛选TA品种，按成交量降序取主力合约
            if 'variety' in df_fut.columns:
                ta_fut = df_fut[df_fut['variety'] == 'TA'].sort_values('volume', ascending=False)
            else:
                ta_fut = df_fut[df_fut['symbol'].str.startswith('TA', na=False)].sort_values('volume', ascending=False)
            if not ta_fut.empty:
                r = ta_fut.iloc[0]  # 成交量最大 = 主力合约
                data['future'] = {
                    'symbol': str(r.get('symbol', 'TA')),
                    'settle': float(r.get('settle', 0)),
                    'close': float(r.get('close', 0)),
                    'volume': int(r.get('volume', 0)),
                    'open_interest': int(r.get('open_interest', 0)),
                    'pre_settle': float(r.get('pre_settle', 0)),
                }
                pre_settle = float(r.get('pre_settle', 0))
                if pre_settle > 0:
                    change = float(r.get('close', 0)) - pre_settle
                    data['future']['change'] = round(change, 2)
                    data['future']['change_pct'] = round((change / pre_settle) * 100, 2)
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
                    news['geo'].append(_clean_news_text(content))
                elif any(kw in content for kw in fed_kws) and len(news['fed']) < 2:
                    news['fed'].append(_clean_news_text(content))
                elif any(kw.lower() in content.lower() for kw in ind_kws) and len(news['industry']) < 4:
                    news['industry'].append(_clean_news_text(content))
                elif any(kw in content for kw in macro_kws) and len(news['macro']) < 2:
                    news['macro'].append(_clean_news_text(content))
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
                
                cleaned_title = _clean_news_text(title, 160)
                if not cleaned_title:
                    continue
                if any(kw in title for kw in geo_kws) and len(news['geo']) < 4:
                    news['geo'].append(cleaned_title)
                elif any(kw in title for kw in macro_kws) and len(news['macro']) < 3:
                    news['macro'].append(cleaned_title)
                elif any(kw in title for kw in ind_kws) and len(news['industry']) < 6:
                    news['industry'].append(cleaned_title)
    except Exception as e:
        print(f"百度财经新闻错误: {e}")

    # 统一清洗去重，去掉半截句、标题噪音和空值。
    for key in news:
        seen = set()
        cleaned = []
        for x in news[key]:
            t = _clean_news_text(x)
            if t and t not in seen:
                seen.add(t)
                cleaned.append(t)
        news[key] = cleaned

    return news


def get_gex_data() -> Dict:
    """从本地iv_smile服务获取GEX/Pain/OI数据"""
    data = {
        'summary': {}, 'gex_bars': [], 'pain_curve': [], 'oi_dist': [],
        'available': False
    }
    try:
        resp = requests.get('http://127.0.0.1:8424/api/iv_smile/gex', timeout=30)
        if resp.status_code == 200:
            raw = resp.json()
            data['summary'] = raw.get('summary', {})
            data['gex_bars'] = raw.get('gex_bars', [])
            data['pain_curve'] = raw.get('pain_curve', [])
            data['oi_dist'] = raw.get('oi_dist', [])
            data['available'] = bool(data['summary'])
            print(f"  GEX数据OK: net_gex={data['summary'].get('net_gex')}, "
                  f"max_pain={data['summary'].get('max_pain')}, "
                  f"gex_flip={data['summary'].get('gex_flip')}")
    except Exception as e:
        print(f"  GEX数据获取失败: {e}")
    return data


def get_iv_curve_data() -> Dict:
    """从本地iv_smile服务获取IV曲线/偏度数据"""
    data = {'available': False}
    try:
        resp = requests.get('http://127.0.0.1:8424/api/iv_smile/curve', timeout=30)
        if resp.status_code == 200:
            raw = resp.json()
            data.update(raw)
            data['available'] = True
    except Exception as e:
        print(f"  IV曲线数据获取失败: {e}")
    return data


# ===== v2.11.63b+: 性质判定 × 合成信号（按 skill 2.3.2 三层判定流程）=====

# OI 变化阈值（绝对量 / 相对量）
# 用 sum(total_OI) 的相对变化判定"上升/下降/不变"——避免绝对量在 OI 规模不同时不可比
# 阈值 1.0%：PTA 主力单日 OI 变化常态在 ±2-5% 区间，1% 是显著信号起点。
# 用 1% 而非 2% 是为了把"轻微但一致的方向"识别出来（实战中 1.5% OI 变化对应 ~5K 手也是清晰信号）。
_NATURE_OI_REL_THRESHOLD = 0.01  # |delta/total_prev| ≥ 1% 算"上升"或"下降"，否则"不变"
# IV 变化阈值（百分点）
# PTA 主力 IV 平时在 20-35% 区间，1 个百分点变化是显著信号
_NATURE_IV_ABS_THRESHOLD = 0.5   # |delta_pp| ≥ 0.5pp 算"上升"或"下降"，否则"不变"
# 形态判定（v2.11.63 阈值）：Call OI / Put OI 比值
_SHAPE_RATIO_THRESHOLD = 1.15     # ≥ 1.15 → 左缓右陡；≤ 1/1.15 → 左陡右缓；否则 对称

# 5 种性质判定标签
_NATURE_LABELS = {
    'spec_buy':    '投机买权',
    'hedge_sell':  '套保卖权',
    'hedge_buy':   '套保买保',
    'close_push':  '平仓推动',
    'double_exit': '双边撤退',
}


def _judge_nature(oi_delta_pct: float, iv_delta_pp: float) -> str:
    """按 skill 2.3.1 性质判定表把 (OI 变化%, IV 变化pp) 映射到 5 种性质之一。

    输入:
        oi_delta_pct: OI 相对变化 = (cur - prev) / prev * 100
        iv_delta_pp:  IV 绝对变化 = cur - prev（IV 已经是 %）

    返回: 'spec_buy' / 'hedge_sell' / 'hedge_buy' / 'close_push' / 'double_exit' / 'unknown'

    阈值:
        OI: |x| ≥ 1% 算变化，否则"不变"
        IV: |x| ≥ 0.5pp 算变化，否则"不变"
    """
    oi_up = oi_delta_pct >= _NATURE_OI_REL_THRESHOLD * 100
    oi_dn = oi_delta_pct <= -_NATURE_OI_REL_THRESHOLD * 100
    iv_up = iv_delta_pp >= _NATURE_IV_ABS_THRESHOLD
    iv_dn = iv_delta_pp <= -_NATURE_IV_ABS_THRESHOLD

    if oi_up and iv_up:
        return 'spec_buy'        # ↑↑ 投机买权（情绪驱动）
    if oi_up and iv_dn:
        return 'hedge_sell'      # ↑↓ 套保卖权（产业端真实意愿，被行权即接受）
    if oi_up and not iv_up and not iv_dn:
        return 'hedge_buy'       # ↑— 套保买保（产业端无情绪溢价，看跌/看涨避险）
    if oi_dn and iv_up:
        return 'close_push'      # ↓↑ 平仓推动（卖方买回平仓 + 剩余风险溢价上升）
    if oi_dn and iv_dn:
        return 'double_exit'     # ↓↓ 双边撤退（情绪消退+对冲盘撤离）
    if oi_dn and not iv_up and not iv_dn:
        return 'double_exit'     # ↓— OI 下降 + IV 不变 = 对冲盘撤离（双边撤退性质）
    if not oi_up and not oi_dn:
        if iv_up:
            return 'spec_buy'
        if iv_dn:
            return 'close_push'
    return 'unknown'


def _judge_shape(call_oi: float, put_oi: float) -> str:
    """形态判定：Call OI / Put OI 比值 → 'rightSteep' / 'leftSteep' / 'sym'"""
    if not call_oi or not put_oi:
        return 'unknown'
    ratio = call_oi / put_oi
    if ratio >= _SHAPE_RATIO_THRESHOLD:
        return 'rightSteep'   # Call OI 集中
    if ratio <= 1 / _SHAPE_RATIO_THRESHOLD:
        return 'leftSteep'    # Put OI 集中
    return 'sym'


def _judge_position(futures_price, max_pain) -> str:
    """位置判定：F vs MP → 'aboveMP' / 'atMP' / 'belowMP'  (P ≈ MP 是 ±2%)"""
    if not futures_price or not max_pain:
        return 'unknown'
    try:
        diff_pct = (float(futures_price) - float(max_pain)) / float(max_pain) * 100
    except (TypeError, ValueError):
        return 'unknown'
    if diff_pct > 2:
        return 'aboveMP'
    if diff_pct < -2:
        return 'belowMP'
    return 'atMP'


def _synthesize_signal(put_nature: str, call_nature: str,
                       pcr_now: float, pcr_prev: float) -> Dict:
    """第三层：合成信号（同向共振 / 反向矛盾 / 单边 / 观望）

    业务语义（v2.11.63a 陷阱 9 + 6.29 实战边界修订）:
        - hedge_buy（套保买保）= **中性**（看跌/看涨避险 = 抛/购意愿抑制，不站队方向）
        - hedge_sell（套保卖权）= **中性**（收租不站队方向）
        - double_exit（双边撤退）= **中性**
        - spec_buy（投机买权）= 站队方向（看空/看多，情绪驱动）
        - close_push（平仓推动）= 方向加速（卖方对冲压力释放）

    返回: {'label': str, 'intensity': str, 'description': str, 'put_dir': str, 'call_dir': str, 'pcr_label': str}
    """
    PUT_DIR = {
        'spec_buy':   'bearish',  # 投机买 Put（看空，恐慌）
        'hedge_sell': 'neutral',  # 卖 Put 集中（收租不站队方向）
        'hedge_buy':  'neutral',  # 买 Put 防存货减值（看跌避险，软底效应）——**不是看空/看多**
        'close_push': 'bearish',  # Put 卖方平仓（下方对冲卖压释放 = 下跌加速 = 看空）
        'double_exit':'neutral',  # 认沽买盘消失（看跌买盘撤退 + 恐慌消退 = 中性）
    }
    CALL_DIR = {
        'spec_buy':   'bullish',  # 投机买 Call（看多，情绪回暖）
        'hedge_sell': 'neutral',  # 卖 Call 收租（锁定销售顶价 = 中性，不站队方向）
        'hedge_buy':  'neutral',  # 买 Call 锁采购顶价（看涨避险，软顶效应）——**不是看多/看空**
        'close_push': 'bullish',  # Call 卖方平仓（上方对冲买压释放 = 上涨加速 = 看多）
        'double_exit':'neutral',  # 认购买盘消失（看涨买盘撤退 + 情绪降温 = 中性）
    }

    p_dir = PUT_DIR.get(put_nature, 'unknown')
    c_dir = CALL_DIR.get(call_nature, 'unknown')

    pcr_delta = 0
    if pcr_now and pcr_prev:
        pcr_delta = pcr_now - pcr_prev
    pcr_label = '↑' if pcr_delta > 0.02 else ('↓' if pcr_delta < -0.02 else '—')

    # PCR 变化业务解读（v2.11.63c+ 新增）
    pcr_meaning = ''
    if pcr_delta > 0.02:
        pcr_meaning = f'PCR↑ = Put 持仓增速 > Call 持仓增速（{pcr_now:.3f}↑ vs {pcr_prev:.3f}）'
    elif pcr_delta < -0.02:
        pcr_meaning = f'PCR↓ = Call 持仓增速 > Put 持仓增速（{pcr_now:.3f}↓ vs {pcr_prev:.3f}）'
    else:
        pcr_meaning = f'PCR— 持仓相对均衡（{pcr_now:.3f}）'

    if p_dir == c_dir and p_dir in ('bullish', 'bearish'):
        dir_word = '看多' if p_dir == 'bullish' else '看空'
        return {
            'label': f'{dir_word}共振',
            'intensity': '强',
            'description': f'Put 端({_NATURE_LABELS.get(put_nature, "未知")}) + Call 端({_NATURE_LABELS.get(call_nature, "未知")}) 同向加强 = {dir_word}共振',
            'put_dir': p_dir, 'call_dir': c_dir,
            'pcr_delta': pcr_delta, 'pcr_label': pcr_label, 'pcr_meaning': pcr_meaning,
        }
    if p_dir != c_dir and p_dir in ('bullish', 'bearish') and c_dir in ('bullish', 'bearish'):
        return {
            'label': '信号矛盾',
            'intensity': '观望',
            'description': f'Put 端({_NATURE_LABELS.get(put_nature, "未知")})看{p_dir} + Call 端({_NATURE_LABELS.get(call_nature, "未知")})看{c_dir} = 方向矛盾，观望',
            'put_dir': p_dir, 'call_dir': c_dir,
            'pcr_delta': pcr_delta, 'pcr_label': pcr_label, 'pcr_meaning': pcr_meaning,
        }
    if p_dir == 'neutral' and c_dir == 'neutral':
        return {
            'label': '中性',
            'intensity': '观望',
            'description': f'Put 端({_NATURE_LABELS.get(put_nature, "未知")})中性 + Call 端({_NATURE_LABELS.get(call_nature, "未知")})中性 = 方向不明，观望',
            'put_dir': p_dir, 'call_dir': c_dir,
            'pcr_delta': pcr_delta, 'pcr_label': pcr_label, 'pcr_meaning': pcr_meaning,
        }
    the_dir = p_dir if p_dir != 'neutral' else c_dir
    the_side = 'Put' if p_dir != 'neutral' else 'Call'
    the_nature = put_nature if the_side == 'Put' else call_nature
    dir_word = '看多' if the_dir == 'bullish' else '看空'
    return {
        'label': f'单边{dir_word}',
        'intensity': '中',
        'description': f'{the_side} 端({_NATURE_LABELS.get(the_nature, "未知")})给出{dir_word}信号，另一侧中性',
        'put_dir': p_dir, 'call_dir': c_dir,
        'pcr_delta': pcr_delta, 'pcr_label': pcr_label, 'pcr_meaning': pcr_meaning,
    }


def _compute_nature_and_synthesis(iv_table_rows: list, atm_strike,
                                   max_pain, futures_price,
                                   pcr_now, pcr_call_oi, pcr_put_oi) -> Dict:
    """汇总全档 Put/Call 总量 OI/IV 变化 + 性质判定 + 合成信号

    返回结构（供 narrative 模板渲染）:
        {
            'available': bool, 'note': '',
            'put': {oi_cur, oi_prev, oi_delta_pct, iv_cur, iv_prev, iv_delta_pp, nature, nature_label, business_meaning},
            'call': {...},
            'shape': 'rightSteep' / 'leftSteep' / 'sym',
            'position': 'aboveMP' / 'atMP' / 'belowMP',
            'pcr_now': float, 'pcr_prev': float, 'pcr_delta': float,
            'synthesis': {label, intensity, description, put_dir, call_dir, pcr_label},
        }
    """
    result = {'available': False, 'put': {}, 'call': {}, 'synthesis': {}}

    if not iv_table_rows:
        return result

    put_oi_cur = put_oi_prev = 0
    call_oi_cur = call_oi_prev = 0
    put_iv_cur_w = put_iv_prev_w = 0.0
    put_iv_cur_n = put_iv_prev_n = 0
    call_iv_cur_w = call_iv_prev_w = 0.0
    call_iv_cur_n = call_iv_prev_n = 0
    has_prev_data = False

    # v2.11.63c 修订: scope 必须用全档（不限 ATM±N 档）
    # 原因: PTA OI 集中在深度虚值档 (4800-5300 Put 端 ~30K 手、6000-6500 Call 端 ~40K 手)
    # 限 ATM±N 档会漏掉 80% 的 OI 数据，导致判定严重偏离真实业务含义
    # IV 加权也必须用全档 OI 作权重（虚值档虽然 IV 高，但 OI 加权后不会拉偏太大）
    scope = iv_table_rows

    for r in scope:
        oc = r.get('oi_call') or 0
        op = r.get('oi_put') or 0
        oc_p = r.get('oi_call_prev') or 0
        op_p = r.get('oi_put_prev') or 0
        if oc_p > 0 or op_p > 0:
            has_prev_data = True
        call_oi_cur += oc
        call_oi_prev += oc_p
        put_oi_cur += op
        put_oi_prev += op_p
        iv_c = r.get('iv_call')
        iv_p = r.get('iv_put')
        iv_c_p = r.get('iv_call_prev')
        iv_p_p = r.get('iv_put_prev')
        if iv_c is not None and oc > 0:
            call_iv_cur_w += iv_c * oc
            call_iv_cur_n += oc
        if iv_c_p is not None and oc_p > 0:
            call_iv_prev_w += iv_c_p * oc_p
            call_iv_prev_n += oc_p
        if iv_p is not None and op > 0:
            put_iv_cur_w += iv_p * op
            put_iv_cur_n += op
        if iv_p_p is not None and op_p > 0:
            put_iv_prev_w += iv_p_p * op_p
            put_iv_prev_n += op_p

    if not has_prev_data:
        return {
            **result,
            'note': 'alert_data 无前次基准（昨日 15:00 收盘未写入或当前在非交易日），无法做性质判定',
        }

    call_oi_delta_pct = ((call_oi_cur - call_oi_prev) / call_oi_prev * 100) if call_oi_prev > 0 else 0
    put_oi_delta_pct = ((put_oi_cur - put_oi_prev) / put_oi_prev * 100) if put_oi_prev > 0 else 0
    call_iv_cur_avg = call_iv_cur_w / call_iv_cur_n if call_iv_cur_n else 0
    call_iv_prev_avg = call_iv_prev_w / call_iv_prev_n if call_iv_prev_n else 0
    put_iv_cur_avg = put_iv_cur_w / put_iv_cur_n if put_iv_cur_n else 0
    put_iv_prev_avg = put_iv_prev_w / put_iv_prev_n if put_iv_prev_n else 0
    call_iv_delta = call_iv_cur_avg - call_iv_prev_avg
    put_iv_delta = put_iv_cur_avg - put_iv_prev_avg

    put_nature = _judge_nature(put_oi_delta_pct, put_iv_delta)
    call_nature = _judge_nature(call_oi_delta_pct, call_iv_delta)

    shape = _judge_shape(call_oi_cur, put_oi_cur)
    position = _judge_position(futures_price, max_pain)

    pcr_prev = (put_oi_prev / call_oi_prev) if call_oi_prev > 0 else None

    synthesis = _synthesize_signal(put_nature, call_nature, pcr_now or 0, pcr_prev or 0)

    PUT_MEANING = {
        'spec_buy':   '投机买 Put（看空，恐慌情绪推动）',
        'hedge_sell': '卖 Put 集中（左侧加速器加码 = 投机/做市商认为下方有支撑收租）',
        'hedge_buy':  '产业买 Put 防存货减值（看跌避险，形成软底效应）',
        'close_push': 'Put 卖方买回平仓（下方对冲卖压释放 = 下跌加速）',
        'double_exit':'认沽买盘消失（看跌买盘撤退 + 恐慌消退）',
    }
    CALL_MEANING = {
        'spec_buy':   '投机买 Call（看多，情绪回暖推动）',
        'hedge_sell': '卖 Call 收租（产业锁定销售顶价 = 中性，不站队方向）',
        'hedge_buy':  '产业买 Call 锁采购顶价（看涨避险，形成软顶效应）',
        'close_push': 'Call 卖方买回平仓（上方对冲买压释放 = 上涨加速）',
        'double_exit':'认购买盘消失（看涨买盘撤退 + 情绪降温）',
    }
    SHAPE_LABEL = {'rightSteep': '[左缓右陡]', 'leftSteep': '[左陡右缓]', 'sym': '[左右对称]', 'unknown': '[形态未知]'}
    POS_LABEL = {'aboveMP': '高位(P>MP)', 'atMP': '中位(P≈MP)', 'belowMP': '低位(P<MP)', 'unknown': '位置未知'}

    return {
        'available': True,
        'put': {
            'oi_cur': put_oi_cur, 'oi_prev': put_oi_prev,
            'oi_delta_pct': put_oi_delta_pct,
            'iv_cur': put_iv_cur_avg, 'iv_prev': put_iv_prev_avg,
            'iv_delta_pp': put_iv_delta,
            'nature': put_nature, 'nature_label': _NATURE_LABELS[put_nature],
            'business_meaning': PUT_MEANING.get(put_nature, '未知'),
        },
        'call': {
            'oi_cur': call_oi_cur, 'oi_prev': call_oi_prev,
            'oi_delta_pct': call_oi_delta_pct,
            'iv_cur': call_iv_cur_avg, 'iv_prev': call_iv_prev_avg,
            'iv_delta_pp': call_iv_delta,
            'nature': call_nature, 'nature_label': _NATURE_LABELS[call_nature],
            'business_meaning': CALL_MEANING.get(call_nature, '未知'),
        },
        'shape': shape, 'shape_label': SHAPE_LABEL[shape],
        'position': position, 'position_label': POS_LABEL[position],
        'pcr_now': pcr_now, 'pcr_prev': pcr_prev, 'pcr_delta': (pcr_now - pcr_prev) if (pcr_now and pcr_prev) else 0,
        'synthesis': synthesis,
        'note': '',
    }


def _render_nature_synthesis_section(ns: Dict) -> str:
    """渲染'6.5 性质判定 × 合成信号'段落（按 skill 2.3.2 三层判定）"""
    if not ns or not ns.get('available'):
        note = (ns or {}).get('note') or '数据不足，无法做性质判定'
        return f"5.5 性质判定 × 合成信号（v2.11.63b+）\n{note}"

    put = ns.get('put') or {}
    call = ns.get('call') or {}
    synth = ns.get('synthesis') or {}

    def _fmt_pct(x):
        if x is None:
            return '--'
        return f"{x:+.1f}%"

    def _fmt_pp(x):
        if x is None:
            return '--'
        return f"{x:+.2f}pp"

    def _fmt_oi(x):
        if x is None or x == 0:
            return '0'
        return f"{int(x):,}"

    table = _table(
        ['维度', '当前', '前次', '变化', '性质', '业务解读'],
        [
            [
                'Put',
                _fmt_oi(put.get('oi_cur')),
                _fmt_oi(put.get('oi_prev')),
                f"OI {_fmt_pct(put.get('oi_delta_pct'))}\nIV {_fmt_pp(put.get('iv_delta_pp'))}",
                put.get('nature_label') or '--',
                put.get('business_meaning') or '--',
            ],
            [
                'Call',
                _fmt_oi(call.get('oi_cur')),
                _fmt_oi(call.get('oi_prev')),
                f"OI {_fmt_pct(call.get('oi_delta_pct'))}\nIV {_fmt_pp(call.get('iv_delta_pp'))}",
                call.get('nature_label') or '--',
                call.get('business_meaning') or '--',
            ],
        ]
    )

    pcr_now = ns.get('pcr_now')
    pcr_prev = ns.get('pcr_prev')
    pcr_label = (synth.get('pcr_label') or '—')
    if pcr_now and pcr_prev:
        pcr_text = f"PCR {pcr_now:.3f}{pcr_label}（前日 {pcr_prev:.3f}）"
    elif pcr_prev:
        pcr_text = f"PCR --（前日 {pcr_prev:.3f}）"
    else:
        pcr_text = "PCR --"

    synth_label = synth.get('label') or '未判定'
    synth_intensity = synth.get('intensity') or '弱'
    synth_desc = synth.get('description') or ''

    return (
        "5.5 性质判定 × 合成信号（v2.11.63c+ 实战）\n"
        f"形态：{ns.get('shape_label', '--')}；位置：{ns.get('position_label', '--')}；{pcr_text}\n"
        f"PCR 业务解读：{synth.get('pcr_meaning', '')}\n"
        f"基准：今日 15:00 当前 vs 昨日 15:00 收盘（alert_data OI/IV prev 字段）。\n"
        + table
        + "\n"
        + f"合成信号：{synth_label}（{synth_intensity}）\n"
        + synth_desc
    )


def get_iv_table_data() -> Dict:
    """从本地iv_smile服务获取T型报价表数据（与iv_smile页面T表完全一致）
    数据源：/api/iv_smile/alert_data — 包含iv_call/iv_put/iv_call_prev/iv_put_prev等
    """
    data = {'available': False, 'rows': []}
    try:
        resp = requests.get('http://127.0.0.1:8424/api/iv_smile/alert_data', timeout=30)
        if resp.status_code == 200:
            raw = resp.json()
            data['rows'] = raw.get('rows', [])
            data['atm_strike'] = raw.get('atm_strike')
            data['available'] = bool(data['rows'])
    except Exception as e:
        print(f"  T表数据获取失败: {e}")
    return data


def get_option_data() -> Dict:
    """获取期权数据（郑商所历史数据）"""
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

            # 核心区间：Put最大持仓的行权价=底部，Call最大持仓的行权价=顶部
            # 修复bug：不能用top5的max/min，应取持仓量最大的单个行权价
            if not puts.empty:
                max_put = puts.nlargest(1, '持仓量').iloc[0]
                data['key_levels']['bottom'] = int(max_put['行权价'])

            if not calls.empty:
                max_call = calls.nlargest(1, '持仓量').iloc[0]
                data['key_levels']['top'] = int(max_call['行权价'])

    except Exception as e:
        print(f"期权数据错误: {e}")

    return data


def get_industry_analysis_data() -> Dict:
    """从 industry_analysis 获取产业链综合数据（含AI四维评分）

    HTTP 自调用本进程 /api/fundamental 风险极大：HTTP 工作线程有限，
    在 K线/TqSdk 繁忙时容易 30 秒超时，并影响整个 generate_report 流程。
    优先读取本地缓存文件（产业链综合分析总是会写到 daily_report.json 同目录），
    都没有再 HTTP 兜底且用短超时。
    """
    # 1) 优先从本地缓存文件读
    try:
        from pathlib import Path as _P
        import time as _t
        import json as _j
        candidates = [
            _P('data/fundamental/daily_report.json'),
            _P('data/industry_dynamic.json'),
        ]
        for fp in candidates:
            if fp.exists() and (_t.time() - fp.stat().st_mtime) < 24 * 3600:
                try:
                    cached = _j.loads(fp.read_text(encoding='utf-8'))
                except Exception:
                    continue
                # 取最里面的 industry_analysis 段；daily_report 自身通常也有
                for key in ('industry_analysis', 'industry_dynamic', 'data'):
                    inner = cached.get(key)
                    if isinstance(inner, dict) and inner:
                        return inner
                if isinstance(cached, dict) and cached:
                    return cached
    except Exception:
        pass
    # 2) 短超时 HTTP 兜底
    try:
        resp = requests.get('http://127.0.0.1:8424/api/fundamental', timeout=5)
        if resp.status_code == 200:
            result = resp.json()
            return result.get('data', result)
    except Exception as e:
        print(f"  ⚠️ industry_analysis数据获取失败(已降级): {e}")
    return {}


def _market_session(now: Optional[datetime] = None) -> str:
    now = now or datetime.now()
    hm = now.hour * 100 + now.minute
    if 900 <= hm < 1130:
        return '上午盘'
    if 1330 <= hm < 1500:
        return '下午盘'
    if 1500 <= hm < 2100:
        return '收盘后'
    if 2100 <= hm < 2300:
        return '夜盘'
    return '非交易时段'


def generate_report(report_type: str = 'intraday') -> Dict:
    """生成完整日报数据。report_type=intraday用于15分钟滚动研报。"""
    now = datetime.now()
    report = {
        'timestamp': now.strftime('%Y-%m-%d %H:%M:%S'),
        'report_type': report_type,
        'market_session': _market_session(now),
        'refresh_interval_minutes': 15,
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
    manual_macro = load_manual_macro_input()
    if manual_macro:
        report['manual_macro_input'] = manual_macro
        # 用户盘前/休盘后手工输入优先，自动快讯只作补充。
        manual_news = manual_macro.get('news') or manual_macro.get('macro_news') or {}
        if isinstance(manual_news, dict):
            for k, vals in manual_news.items():
                if isinstance(vals, str):
                    vals = [vals]
                if isinstance(vals, list):
                    macro_news.setdefault(k, [])
                    macro_news[k] = [_clean_news_text(x) for x in vals if _clean_news_text(x)] + macro_news.get(k, [])
        elif isinstance(manual_news, list):
            macro_news.setdefault('macro', [])
            macro_news['macro'] = [_clean_news_text(x) for x in manual_news if _clean_news_text(x)] + macro_news.get('macro', [])

    # 外盘PX/汇率/外盘动态成本：用户指定公式
    px_external = get_px_external_data(macro_news, manual_macro)

    # 计算成本利润
    cost_data = {}
    # ---- 人工 spot_main_overrides（v2.11.37+）：现货价同步到 profit ----
    _manual_macro_c = load_manual_macro_input()
    _spot_ovr_c = (_manual_macro_c or {}).get('spot_main_overrides') or {}
    if _spot_ovr_c.get('spot_price') is not None and float(_spot_ovr_c.get('spot_price') or 0) > 0:
        pta = dict(pta or {})
        pta['spot_price'] = float(_spot_ovr_c['spot_price'])
    if px.get('spot_price') and px.get('spot_price') > 0:
        cost_data['pta_cost'] = round(px['spot_price'] * 0.655, 0)
    if px_external.get('pta_external_cost'):
        cost_data['pta_external_cost'] = px_external.get('pta_external_cost')
        cost_data['px_asia_close_usd'] = px_external.get('px_asia_close_usd')
        cost_data['usd_cny'] = px_external.get('usd_cny')
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
    report['px_external'] = px_external
    report['pta'] = pta
    report['inventory'] = inventory
    report['downstream'] = downstream
    report['cost'] = cost_data
    report['cost_range'] = {'low': cost_low, 'high': cost_high}

    # 期权数据（郑商所历史）
    print("  获取期权数据...")
    opt = get_option_data()
    report['option'] = opt

    # GEX/Pain/OI数据（本地iv_smile服务）
    print("[8/10] 获取GEX/Pain数据...")
    gex = get_gex_data()
    report['gex'] = gex

    # IV曲线数据
    print("[9/10] 获取IV曲线数据...")
    iv_curve = get_iv_curve_data()
    report['iv_curve'] = iv_curve

    # T表数据（与iv_smile页面T表一致的IV变动）
    print("[9.5/10] 获取T表IV数据...")
    iv_table = get_iv_table_data()

    # 产业链综合数据（含AI四维评分）
    print("[10/10] 获取产业链综合分析...")
    industry = get_industry_analysis_data()
    report['industry_analysis'] = industry

    # 生成结构化分析（整合GEX数据）
    report['section1'] = generate_option_analysis(opt, gex, iv_curve, iv_table)
    report['section2'] = generate_macro_analysis(crude, px, pta, rates, inventory, macro_news, cost_data, cost_low, cost_high, industry)
    report['section3'] = generate_strategy_suggestions(opt, pta, cost_data, cost_low, cost_high, gex, industry)

    # 新主展示：盘中综合研判。旧 section1/2/3 只作为兼容数据源和降级展示。
    intraday_analysis = generate_intraday_analysis(report)
    report['intraday_analysis'] = intraday_analysis
    report['market_brief'] = intraday_analysis
    report['narrative_report'] = intraday_analysis.get('narrative')

    return report


def generate_option_analysis(opt: Dict, gex: Dict = None, iv_curve: Dict = None, iv_table: Dict = None) -> Dict:
    """生成期权数据分析（整合GEX/Pain/IV曲线/Skew/Curvature）"""
    gex = gex or {}
    iv_curve = iv_curve or {}
    highlights = opt.get('highlights', [])
    bottom = opt.get('key_levels', {}).get('bottom')
    top = opt.get('key_levels', {}).get('top')
    pcr_spot = opt.get('pcr_spot')
    pcr_hold = opt.get('pcr_hold')

    # GEX数据
    gs = gex.get('summary', {})
    net_gex = gs.get('net_gex')
    gex_flip = gs.get('gex_flip')
    max_pain = gs.get('max_pain')
    futures_price = gs.get('futures_price')
    days_left = gs.get('days_left')
    gex_direction = gs.get('gex_direction')
    total_call_oi = gs.get('total_call_oi')
    total_put_oi = gs.get('total_put_oi')
    expiry = gs.get('expiry', '')[:10] if gs.get('expiry') else ''

    # 持仓PCR必须与 /iv_smile 指标栏一致：使用T型表显示口径，而不是GEX 21档OI口径。
    # 口径：当前持仓非0用当前；当前持仓为0且前次有值时，用前次存量兜底。
    # GEX/MaxPain/Flip仍沿用 /api/iv_smile/gex 的21档Gamma口径。
    pcr_val = gs.get('pcr') or pcr_hold
    pcr_call_oi = total_call_oi
    pcr_put_oi = total_put_oi
    if iv_table and iv_table.get('rows'):
        t_call_oi = 0
        t_put_oi = 0
        for r in iv_table.get('rows', []):
            cur_call = r.get('oi_call') or 0
            cur_put = r.get('oi_put') or 0
            prev_call = r.get('oi_call_prev') or 0
            prev_put = r.get('oi_put_prev') or 0
            t_call_oi += cur_call if cur_call != 0 else prev_call
            t_put_oi += cur_put if cur_put != 0 else prev_put
        if t_call_oi > 0:
            pcr_val = t_put_oi / t_call_oi
            pcr_call_oi = t_call_oi
            pcr_put_oi = t_put_oi

    # OI分布——找最大Call压力位和Put支撑位 + 次大持仓位
    oi_dist = gex.get('oi_dist', [])
    max_call_strike = max_put_strike = None
    max_call_oi = max_put_oi = 0
    call_oi_list = []  # (strike, oi)
    put_oi_list = []
    for o in oi_dist:
        co = o.get('call_oi', 0) or 0
        po = o.get('put_oi', 0) or 0
        if co > 0:
            call_oi_list.append((o['strike'], co))
        if po > 0:
            put_oi_list.append((o['strike'], po))
        if co > max_call_oi:
            max_call_oi = co
            max_call_strike = o['strike']
        if po > max_put_oi:
            max_put_oi = po
            max_put_strike = o['strike']

    call_oi_list.sort(key=lambda x: x[1], reverse=True)
    put_oi_list.sort(key=lambda x: x[1], reverse=True)

    # 用GEX数据优化区间判断（优先于郑商所历史数据）
    if max_put_strike:
        bottom = max_put_strike
    if max_call_strike:
        top = max_call_strike

    # ===== 精细核心区间分析 =====
    # 找OI加权的有效区间（不是简单max put/call，而是OI集中区间）
    effective_support = bottom
    effective_resistance = top
    oi_concentration = None
    if futures_price and oi_dist:
        # 计算以期货价为中心±500点范围内OI集中度
        near_call = sum(o.get('call_oi', 0) or 0 for o in oi_dist
                        if abs(o['strike'] - futures_price) <= 500)
        near_put = sum(o.get('put_oi', 0) or 0 for o in oi_dist
                       if abs(o['strike'] - futures_price) <= 500)
        total_oi = (total_call_oi or 0) + (total_put_oi or 0)
        if total_oi > 0:
            oi_concentration = round((near_call + near_put) / total_oi * 100, 1)

        # 如果max_put和max_call区间太宽(>600点)，尝试用次大持仓收窄
        if bottom and top and (top - bottom) > 600:
            # 找更靠近当前价的次大持仓
            inner_puts = [(s, oi) for s, oi in put_oi_list if s > bottom and s <= futures_price]
            inner_calls = [(s, oi) for s, oi in call_oi_list if s < top and s >= futures_price]
            if inner_puts:
                effective_support = inner_puts[0][0]
            if inner_calls:
                effective_resistance = inner_calls[0][0]
            # 如果收窄后反而没意义（比如support>resistance），回退
            if effective_support and effective_resistance and effective_support >= effective_resistance:
                effective_support = bottom
                effective_resistance = top

    # ===== Max Pain 收敛分析 =====
    pain_convergence = None
    if max_pain and futures_price and days_left:
        diff = abs(futures_price - max_pain)
        diff_pct = diff / futures_price * 100
        deviation_dir = 1 if futures_price > max_pain else -1
        # 基于剩余天数和偏离幅度判断收敛概率
        if days_left <= 2:
            if diff_pct <= 1.5:
                pain_convergence = {'probability': '高', 'desc': f'仅剩{days_left:.1f}天，偏差{diff:.0f}点({diff_pct:.1f}%)较小，收敛概率高'}
            elif diff_pct <= 3:
                pain_convergence = {'probability': '中', 'desc': f'仅剩{days_left:.1f}天，偏差{diff:.0f}点({diff_pct:.1f}%)，有收敛动力但时间紧迫'}
            else:
                pain_convergence = {'probability': '低', 'desc': f'仅剩{days_left:.1f}天但偏差{diff:.0f}点({diff_pct:.1f}%)过大，完全收敛困难'}
        elif days_left <= 5:
            if diff_pct <= 2:
                pain_convergence = {'probability': '高', 'desc': f'剩余{days_left:.1f}天，偏差{diff:.0f}点({diff_pct:.1f}%)，正Gamma环境下收敛概率较高' if gex_direction == 'positive' else f'剩余{days_left:.1f}天，偏差{diff:.0f}点({diff_pct:.1f}%)适中'}
            elif diff_pct <= 4:
                pain_convergence = {'probability': '中', 'desc': f'剩余{days_left:.1f}天，偏差{diff:.0f}点({diff_pct:.1f}%)，有收敛倾向但需关注方向性驱动'}
            else:
                pain_convergence = {'probability': '低', 'desc': f'偏差{diff:.0f}点({diff_pct:.1f}%)显著，距到期{days_left:.1f}天，收敛需要强催化'}
        else:
            if diff_pct <= 3:
                pain_convergence = {'probability': '中高', 'desc': f'距到期{days_left:.1f}天时间充裕，偏差{diff:.0f}点({diff_pct:.1f}%)，大概率区间震荡回归'}
            else:
                pain_convergence = {'probability': '中低', 'desc': f'距到期{days_left:.1f}天，偏差{diff:.0f}点({diff_pct:.1f}%)，收敛存在不确定性'}
        # 补充前端需要的字段
        if pain_convergence:
            pain_convergence['deviation_pct'] = round(diff_pct * deviation_dir, 1)
            pain_convergence['days_left'] = round(days_left, 1)

    # ===== IV曲线解读（Skew/Curvature） =====
    iv_analysis = None
    svi_params = iv_curve.get('svi_params', {})
    iv_curve_data = iv_curve.get('curve', [])
    atm_strike = iv_curve.get('atm_strike')
    if svi_params:
        skew = svi_params.get('skew', 0)
        curvature = svi_params.get('curvature', 0)
        atm_vol = svi_params.get('atm_vol', 0)

        iv_analysis = {
            'atm_vol': round(atm_vol * 100, 1) if atm_vol else None,
            'skew': round(skew, 4) if skew else None,
            'curvature': round(curvature, 2) if curvature else None,
        }

        # Skew解读
        if skew:
            if skew < -0.15:
                iv_analysis['skew_desc'] = '深度左偏(看跌保护溢价极高)，市场恐慌情绪浓厚'
                iv_analysis['skew_level'] = 'extreme_left'
            elif skew < -0.08:
                iv_analysis['skew_desc'] = '左偏(看跌溢价偏高)，下行保护需求偏强'
                iv_analysis['skew_level'] = 'left'
            elif skew < -0.03:
                iv_analysis['skew_desc'] = '轻微左偏，正常的看跌保护溢价'
                iv_analysis['skew_level'] = 'slight_left'
            elif skew <= 0.03:
                iv_analysis['skew_desc'] = '对称，多空对隐波定价相对均衡'
                iv_analysis['skew_level'] = 'neutral'
            elif skew <= 0.08:
                iv_analysis['skew_desc'] = '轻微右偏，看涨端溢价略高'
                iv_analysis['skew_level'] = 'slight_right'
            else:
                iv_analysis['skew_desc'] = '右偏(看涨溢价偏高)，上行博弈需求旺盛'
                iv_analysis['skew_level'] = 'right'

        # Curvature解读
        if curvature:
            if curvature > 30:
                iv_analysis['curv_desc'] = '极高曲率(尾部风险定价极高)，市场预期可能出现剧烈波动'
                iv_analysis['curv_level'] = 'extreme'
            elif curvature > 15:
                iv_analysis['curv_desc'] = '高曲率(尾部风险溢价较高)，深虚值期权隐波偏高'
                iv_analysis['curv_level'] = 'high'
            elif curvature > 5:
                iv_analysis['curv_desc'] = '中等曲率，隐波曲线形态正常'
                iv_analysis['curv_level'] = 'normal'
            else:
                iv_analysis['curv_desc'] = '低曲率(曲线扁平)，市场对尾部风险定价不足'
                iv_analysis['curv_level'] = 'low'

        # ATM IV水平判断
        if atm_vol:
            atm_pct = atm_vol * 100
            if atm_pct > 40:
                iv_analysis['vol_level'] = '极高波动率环境'
                iv_analysis['vol_regime'] = 'extreme'
            elif atm_pct > 30:
                iv_analysis['vol_level'] = '高波动率'
                iv_analysis['vol_regime'] = 'high'
            elif atm_pct > 20:
                iv_analysis['vol_level'] = '中等波动率'
                iv_analysis['vol_regime'] = 'mid'
            elif atm_pct > 12:
                iv_analysis['vol_level'] = '低波动率'
                iv_analysis['vol_regime'] = 'low'
            else:
                iv_analysis['vol_level'] = '极低波动率(压缩态)'
                iv_analysis['vol_regime'] = 'compressed'

    # IV变动 — 直接取T表数据（与iv_smile页面T表完全一致）
    iv_changes = []
    iv_table = iv_table or {}
    t_rows = iv_table.get('rows', [])
    if t_rows and atm_strike:
        for r in t_rows:
            k = r.get('strike', 0)
            if abs(k - atm_strike) <= 300:
                iv_c = r.get('iv_call')
                iv_c_prev = r.get('iv_call_prev')
                iv_p = r.get('iv_put')
                iv_p_prev = r.get('iv_put_prev')
                # Call IV变动
                c_chg = round(iv_c - iv_c_prev, 2) if (iv_c is not None and iv_c_prev is not None) else None
                # Put IV变动
                p_chg = round(iv_p - iv_p_prev, 2) if (iv_p is not None and iv_p_prev is not None) else None
                # 取变动绝对值较大的一边作为代表
                if c_chg is not None or p_chg is not None:
                    iv_changes.append({
                        'strike': k,
                        'call_iv': round(iv_c, 1) if iv_c is not None else None,
                        'put_iv': round(iv_p, 1) if iv_p is not None else None,
                        'call_change': c_chg,
                        'put_change': p_chg,
                        'change': c_chg if c_chg is not None else p_chg,  # 兼容前端
                        'is_atm': k == atm_strike
                    })

    # 排序：取call/put变动绝对值的最大值，降序，Top3
    if iv_changes:
        iv_changes.sort(key=lambda x: max(abs(x.get('call_change') or 0), abs(x.get('put_change') or 0)), reverse=True)
        iv_changes = iv_changes[:3]

    # ===== v2.11.63b+: 性质判定 × 合成信号（按 skill 2.3.2 三层判定流程）=====
    # 全档 Put/Call 总量 OI/IV 变化汇总（数据源：alert_data 的 oi_call_prev/iv_call_prev = 昨日 15:00 收盘）
    nature_data = _compute_nature_and_synthesis(
        iv_table_rows=t_rows, atm_strike=atm_strike,
        max_pain=max_pain, futures_price=futures_price,
        pcr_now=pcr_val, pcr_call_oi=pcr_call_oi, pcr_put_oi=pcr_put_oi,
    )

    # 构建持仓表
    all_puts = [h for h in highlights if h['type'] == 'P']
    all_calls = [h for h in highlights if h['type'] == 'C']
    all_puts.sort(key=lambda x: int(x.get('change', '0').replace(',','').replace('+','').replace('手','')) if x.get('change') else 0, reverse=True)
    all_calls.sort(key=lambda x: int(x.get('change', '0').replace(',','').replace('+','').replace('手','')) if x.get('change') else 0, reverse=True)
    table_items = (all_puts[:5] + all_calls[:5])
    table_items.sort(key=lambda x: x['strike'])

    # ===== 结论 =====
    conclusions = []

    # GEX方向：只描述波动状态，不把正/负Gamma当方向预测
    if net_gex is not None:
        if gex_direction == 'positive':
            conclusions.append(
                f"🛡️ 净GEX为正(+{net_gex/1e6:.1f}M)：做市商对冲流倾向涨了卖、跌了买，压制波动，更偏震荡/均值回归；这不是看涨信号")
        else:
            conclusions.append(
                f"⚡ 净GEX为负({net_gex/1e6:.1f}M)：做市商对冲流倾向涨了买、跌了卖，放大波动，突破后趋势延续风险更高；这不是看跌信号")

    # Max Pain 收敛
    if pain_convergence:
        direction_hint = ''
        if max_pain and futures_price:
            if futures_price > max_pain:
                direction_hint = '，价格偏高于痛点→下行引力'
            else:
                direction_hint = '，价格偏低于痛点→上行引力'
        conclusions.append(f"🎯 痛点收敛({pain_convergence['probability']}): {pain_convergence['desc']}{direction_hint}")

    # GEX翻转点
    if gex_flip and futures_price:
        dist = futures_price - gex_flip
        if dist > 0:
            conclusions.append(f"📍 GEX翻转{gex_flip}，当前价{futures_price:.0f}在上方{dist:.0f}点：处于正Gamma状态；若回落接近/有效跌破翻转线，震荡假设减弱、波动放大风险上升")
        else:
            conclusions.append(f"📍 GEX翻转{gex_flip}，当前价{futures_price:.0f}在下方{abs(dist):.0f}点：处于负Gamma状态；若重新站上翻转线，波动可能重新受抑")

    # PCR
    if pcr_val:
        if pcr_val > 1.2:
            conclusions.append(f"📉 PCR={pcr_val:.3f}>1.2，看跌持仓偏重，空头力量偏强")
        elif pcr_val < 0.8:
            conclusions.append(f"📈 PCR={pcr_val:.3f}<0.8，看涨持仓偏重，多头力量偏强")
        else:
            conclusions.append(f"⚖️ PCR={pcr_val:.3f}，多空相对均衡")

    # 精细区间
    if effective_support and effective_resistance:
        range_width = effective_resistance - effective_support
        if bottom != effective_support or top != effective_resistance:
            conclusions.append(
                f"📌 有效博弈区间【{effective_support},{effective_resistance}】(宽度{range_width}点)，"
                f"外沿支撑{bottom}({max_put_oi:,}手) / 压力{top}({max_call_oi:,}手)")
        else:
            conclusions.append(
                f"📌 核心区间【{bottom},{top}】(宽度{range_width}点)，"
                f"支撑{bottom}({max_put_oi:,}手) / 压力{top}({max_call_oi:,}手)")

    # IV曲线结论
    if iv_analysis:
        iv_parts = []
        if iv_analysis.get('atm_vol'):
            iv_parts.append(f"ATM IV {iv_analysis['atm_vol']}%({iv_analysis.get('vol_level','')})")
        if iv_analysis.get('skew_desc'):
            iv_parts.append(f"Skew {iv_analysis['skew']:.4f} {iv_analysis['skew_desc']}")
        if iv_parts:
            conclusions.append(f"📈 隐波: {'，'.join(iv_parts)}")
        if iv_analysis.get('curv_desc'):
            conclusions.append(f"🌊 曲率={iv_analysis['curvature']:.1f}: {iv_analysis['curv_desc']}")

    # 到期倒计时
    if days_left:
        theta_note = ''
        if days_left <= 3:
            theta_note = '，Theta加速衰减，ATM Gamma极度集中'
        elif days_left <= 7:
            theta_note = '，时间价值侵蚀加快'
        conclusions.append(f"⏰ 距到期{days_left:.1f}天({expiry}){theta_note}")

    # ===== GEX数据概要（供前端渲染） =====
    gex_summary = None
    if gex.get('available'):
        gex_summary = {
            'net_gex': net_gex,
            'gex_direction': gex_direction,
            'gex_flip': gex_flip,
            'max_pain': max_pain,
            'futures_price': futures_price,
            'days_left': days_left,
            'expiry': expiry,
            'total_call_oi': pcr_call_oi,
            'total_put_oi': pcr_put_oi,
            'pcr': pcr_val,
            'pcr_source': 'T表显示口径：当前持仓非0用当前，当前为0用前次兜底',
            'gex_total_call_oi': total_call_oi,
            'gex_total_put_oi': total_put_oi,
            'gex_pcr': gs.get('pcr'),
            'max_call_strike': max_call_strike,
            'max_call_oi': max_call_oi,
            'max_put_strike': max_put_strike,
            'max_put_oi': max_put_oi,
            'effective_support': effective_support,
            'effective_resistance': effective_resistance,
            'oi_concentration': oi_concentration,
        }

    # Pain curve top5
    pain_highlights = []
    pain_curve = gex.get('pain_curve', [])
    if pain_curve:
        sorted_pain = sorted(pain_curve, key=lambda x: x.get('pain', 0))
        min_pain_strike = sorted_pain[0]['strike'] if sorted_pain else None
        for p in sorted_pain[:5]:
            pain_highlights.append({
                'strike': p['strike'],
                'pain': p.get('pain', 0),
                'is_min': p['strike'] == min_pain_strike
            })

    return {
        'title': '一、 期权数据解读',
        'subtitle': f"GEX{'正Gamma·压制波动' if gex_direction == 'positive' else '负Gamma·放大波动'}" if gex_direction else '期权结构分析',
        'summary': '',  # narrative 移除，用结构化conclusions代替
        'highlights': table_items if table_items else highlights[:8],
        'conclusions': conclusions if conclusions else ['数据获取中，具体分析待更新'],
        'key_levels': {
            'bottom': str(bottom) if bottom else '—',
            'top': str(top) if top else '—',
            'pcr_spot': f"{pcr_spot:.4f}" if pcr_spot else '—',
            'pcr_hold': f"{pcr_val:.4f}" if pcr_val else '—'
        },
        'gex_summary': gex_summary,
        'pain_highlights': pain_highlights,
        'pain_convergence': pain_convergence,
        'iv_analysis': iv_analysis,
        'iv_changes': iv_changes,
        'nature_synthesis': nature_data,  # v2.11.63b+ 性质判定 × 合成信号（skill 2.3.2 三层判定）
    }


def generate_macro_analysis(crude, px, pta, rates, inventory, macro_news, cost_data, cost_low, cost_high, industry: Dict = None) -> Dict:
    """生成宏观与基本面分析（整合产业链四维评分）"""
    industry = industry or {}
    brent_price = crude.get('brent', {}).get('price')
    wti_price = crude.get('wti', {}).get('price')
    brent_chg = crude.get('brent', {}).get('change_pct', 0)
    wti_chg = crude.get('wti', {}).get('change_pct', 0)
    pta_spot = pta.get('spot_price')

    # ---- 人工 spot_main_overrides（v2.11.37+）：仅覆盖 PTA 现货价；主力价/符号/涨跌幅/基差都交给K线 ----
    _manual_macro_m = load_manual_macro_input()
    _spot_overrides = (_manual_macro_m or {}).get('spot_main_overrides') or {}
    if _spot_overrides.get('spot_price') is not None and float(_spot_overrides.get('spot_price') or 0) > 0:
        pta_spot = float(_spot_overrides['spot_price'])
    pta_future = pta.get('future', {})
    profit = cost_data.get('profit', 0)
    profit_pct = cost_data.get('profit_pct', 0)
    pta_cost = cost_data.get('pta_cost', 0)

    # 从 industry_analysis 获取增强数据
    ind_upstream = industry.get('upstream', {})
    ind_pta = industry.get('pta', {})
    ind_downstream = industry.get('downstream', {})
    ind_cost = industry.get('cost', {})

    # AI四维评分数据
    ai_comm = industry.get('ai_commentary', {})
    ai_data = ai_comm.get('data', {}) if isinstance(ai_comm, dict) else {}
    ai_rating = ai_data.get('rating', '')
    ai_score = ai_data.get('total_score', 0)
    ai_outlook = ai_data.get('outlook', '')
    ai_dims = ai_data.get('dimensions', {})
    ai_text = ai_comm.get('text', ai_comm) if isinstance(ai_comm, dict) else str(ai_comm)

    # ===== 1. 产业链价格矩阵 =====
    chain_prices = []

    # 原油
    if brent_price:
        chain_prices.append({
            'name': '布伦特原油', 'price': brent_price, 'unit': 'USD/桶',
            'change': f"{brent_chg:+.2f}%",
            'signal': '利多' if brent_chg > 1 else ('利空' if brent_chg < -1 else '中性')
        })
    if wti_price:
        chain_prices.append({
            'name': 'WTI原油', 'price': wti_price, 'unit': 'USD/桶',
            'change': f"{wti_chg:+.2f}%",
            'signal': '利多' if wti_chg > 1 else ('利空' if wti_chg < -1 else '中性')
        })

    # PX
    px_price = px.get('spot_price')
    if px_price:
        px_basis = ind_upstream.get('px', {}).get('basis')
        chain_prices.append({
            'name': 'PX现货', 'price': px_price, 'unit': 'CNY/吨',
            'change': f"基差{px_basis:+.0f}" if px_basis else '—',
            'signal': '中性'
        })

    # 石脑油/PXN
    naphtha = ind_upstream.get('naphtha', {})
    pxn = ind_upstream.get('pxn', {})
    if pxn.get('spread'):
        chain_prices.append({
            'name': 'PXN价差', 'price': pxn['spread'], 'unit': 'USD/吨',
            'change': '偏高' if pxn['spread'] > 400 else ('偏低' if pxn['spread'] < 200 else '正常'),
            'signal': '利多' if pxn['spread'] > 400 else '中性'
        })

    # PTA现货/期货
    if pta_spot:
        basis = ind_pta.get('basis', {})
        basis_val = basis.get('value', 0)
        # 基差统一用 (人工spot - pta_future.settle) 自然计算（v2.11.37+ 修正）
        # 注：generate_macro_analysis 内没有 K线 main 价，只能用 pta_future.settle 兜底；
        # 字段层 intraday_analysis 的 K线覆盖会再把 main_futures_price 替换成实时K线。
        _basis_anchor = pta_future.get('settle') if isinstance(pta_future, dict) else None
        if pta_spot and _basis_anchor:
            basis_val = round(float(pta_spot) - float(_basis_anchor), 2)
            basis = dict(basis or {})
            basis['value'] = basis_val
            basis['level'] = '强' if basis_val > 200 else ('偏弱' if basis_val < -100 else '中性')
            ind_pta = dict(ind_pta or {})
            ind_pta['basis'] = basis
            industry = dict(industry or {})
            industry['pta'] = ind_pta
        chain_prices.append({
            'name': 'PTA现货', 'price': pta_spot, 'unit': 'CNY/吨',
            'change': f"基差{basis_val:+.0f}({basis.get('level', '')})" if basis_val else '—',
            'signal': '利多' if basis_val > 200 else ('利空' if basis_val < -100 else '中性')
        })

    if pta_future.get('settle'):
        chain_prices.append({
            'name': f"{pta_future.get('symbol', 'TA主力')}", 'price': pta_future['settle'], 'unit': 'CNY/吨',
            'change': f"{pta_future.get('change_pct', 0):+.2f}%",
            'signal': '中性'
        })

    # 汽油批发价
    gasoline = ind_upstream.get('cn_gasoline_wholesale', {})
    if gasoline.get('price_cny_ton'):
        chain_prices.append({
            'name': '国内汽油批发', 'price': gasoline['price_cny_ton'], 'unit': 'CNY/吨',
            'change': f"({gasoline.get('date', '')})",
            'signal': '中性'
        })

    # ===== 2. 成本利润结构 =====
    cost_profit = {
        'pta_cost': pta_cost,
        'profit': profit,
        'profit_pct': profit_pct,
        'cost_low': cost_low,
        'cost_high': cost_high,
        'signal': '⚠️ 高利润供应压力' if profit > 300 else ('✅ 利润正常' if profit > 0 else '🔴 亏损收缩预期'),
        'detail': ''
    }
    if profit > 500:
        cost_profit['detail'] = f'利润{profit:.0f}元(+{profit_pct:.1f}%)，处于高位，装置提负/重启概率大，供应端偏空'
    elif profit > 200:
        cost_profit['detail'] = f'利润{profit:.0f}元(+{profit_pct:.1f}%)，工厂维持高开工积极性'
    elif profit > 0:
        cost_profit['detail'] = f'利润{profit:.0f}元(+{profit_pct:.1f}%)，产业运行平稳'
    elif profit is not None and profit <= 0:
        cost_profit['detail'] = f'亏损{abs(profit):.0f}元，部分装置面临停车压力'

    # ===== 3. 库存数据 =====
    inv_items = []
    # PTA社会库存（从industry或akshare）
    pta_inv = ind_pta.get('social_inventory', {}) or inventory.get('pta', {})
    if pta_inv.get('stock'):
        chg = pta_inv.get('change', 0)
        stock = pta_inv['stock']
        level = '偏低' if stock < 200000 else ('偏高' if stock > 400000 else '中性')
        inv_items.append({
            'name': 'PTA社会库存', 'stock': stock, 'unit': '吨',
            'change': chg, 'change_str': f"{'+'if chg>0 else ''}{chg}",
            'level': level, 'date': pta_inv.get('date', '')
        })

    # MEG库存
    meg_inv = ind_pta.get('meg_inventory', {}) or inventory.get('meg', {})
    if meg_inv.get('stock'):
        chg = meg_inv.get('change', 0)
        inv_items.append({
            'name': 'MEG乙二醇库存', 'stock': meg_inv['stock'], 'unit': '吨',
            'change': chg, 'change_str': f"{'+'if chg>0 else ''}{chg}",
            'level': '中性', 'date': meg_inv.get('date', '')
        })

    # SM苯乙烯库存
    sm_inv = ind_pta.get('sm_inventory', {}) or inventory.get('sm', {})
    if sm_inv.get('stock'):
        chg = sm_inv.get('change', 0)
        inv_items.append({
            'name': 'SM苯乙烯库存', 'stock': sm_inv['stock'], 'unit': '吨',
            'change': chg, 'change_str': f"{'+'if chg>0 else ''}{chg}",
            'level': '中性', 'date': sm_inv.get('date', '')
        })

    # ===== 4. 下游需求 =====
    downstream_items = []
    for name, info in ind_downstream.items():
        if isinstance(info, dict) and info.get('price'):
            dom_basis = info.get('dom_basis', 0)
            downstream_items.append({
                'name': name, 'price': info['price'], 'unit': 'CNY/吨',
                'dom_contract': info.get('dominant_contract', ''),
                'dom_price': info.get('dominant_price', 0),
                'basis': dom_basis,
                'basis_str': f"基差{dom_basis:+.0f}" if dom_basis else '—'
            })

    # ===== 5. 宏观快讯（自动抓取 + 人工宏观补充） =====
    geo_items = list(macro_news.get('geo', [])[:2])
    macro_items = list(macro_news.get('macro', [])[:2])
    fed_items = list(macro_news.get('fed', [])[:2])
    industry_items = list(macro_news.get('industry', [])[:4])

    # 人工宏观基本面：把核心矛盾 / 机构观点 / 关键变量 / 事件驱动 补到对应通道
    manual_macro = load_manual_macro_input()
    if manual_macro:
        manual_core = _clean_news_text(manual_macro.get('core_takeaway') or manual_macro.get('summary') or '', 280)
        if manual_core:
            geo_items.insert(0, '【人工】' + manual_core)
            geo_items = geo_items[:3]
        for inst in (manual_macro.get('institutions') or [])[:3]:
            if isinstance(inst, dict):
                txt = f'【机构】{inst.get("name","?")}·{inst.get("view","?")}：{inst.get("logic","")}'
                txt = _clean_news_text(txt, 220)
                if txt:
                    industry_items.append(txt)
        for kv in (manual_macro.get('key_variables') or [])[:2]:
            if isinstance(kv, dict):
                txt = f'【关键变量】{kv.get("name","?")}（权重{kv.get("weight","")}）：{kv.get("desc","")}'
                txt = _clean_news_text(txt, 200)
                if txt:
                    macro_items.append(txt)
        for ev in (manual_macro.get('events') or [])[:2]:
            txt = _clean_news_text('【事件】' + str(ev), 200)
            if txt:
                macro_items.append(txt)
        industry_items = industry_items[:6]
        macro_items = macro_items[:3]

    # ===== 6. 综合评估叙述 =====
    narrative_parts = []
    # 成本端
    if brent_price:
        narrative_parts.append(f"原油{'高位运行' if brent_price > 90 else ('中位震荡' if brent_price > 75 else '偏弱运行')}(${brent_price:.1f},{brent_chg:+.1f}%)，成本支撑{'坚挺' if brent_price > 90 else ('尚可' if brent_price > 75 else '减弱')}")
    # 基差
    basis_val = ind_pta.get('basis', {}).get('value', 0)
    if basis_val:
        narrative_parts.append(f"现货{'升水' if basis_val > 0 else '贴水'}{abs(basis_val):.0f}元({'偏紧' if basis_val > 200 else '正常'})")
    # 利润
    if profit:
        narrative_parts.append(f"PTA{'盈利' if profit > 0 else '亏损'}{abs(profit):.0f}元({profit_pct:+.1f}%)")
    # 库存
    if pta_inv.get('stock'):
        inv_chg = pta_inv.get('change', 0)
        narrative_parts.append(f"PTA库存{pta_inv['stock']/10000:.1f}万吨({'去库' if inv_chg < 0 else '累库'}{abs(inv_chg)})")

    # 人工宏观基本面：核心矛盾 + 策略提示
    if manual_macro:
        hint = _clean_news_text(manual_macro.get('strategy_hint') or manual_macro.get('core_takeaway') or '', 220)
        if hint:
            narrative_parts.append(f"【DeepSeek综合】{hint}")

    # 拼接：避免末位 `。` 与句尾 `。` 拼出 `。。`
    narrative = '；'.join(narrative_parts)
    if narrative and not narrative.endswith('。'):
        narrative += '。'
    if not narrative:
        narrative = '基本面数据获取中。'

    return {
        'title': '二、 宏观与基本面',
        'subtitle': '产业链价格·成本利润·库存供需',
        'chain_prices': chain_prices,
        'cost_profit': cost_profit,
        'inventory': inv_items,
        'downstream': downstream_items,
        'news': {
            'geo': geo_items,
            'macro': macro_items + fed_items,
            'industry': industry_items,
        },
        'narrative': narrative,
        # AI四维评分（来自industry_analysis）
        'ai_rating': {
            'rating': ai_rating,
            'score': ai_score,
            'outlook': ai_outlook,
            'dimensions': ai_dims,
            'text': ai_text,
        } if ai_data else None,
    }


def generate_strategy_suggestions(opt: Dict, pta: Dict, cost_data: Dict, cost_low, cost_high, gex: Dict = None, industry: Dict = None) -> Dict:
    """生成策略建议（宏观+产业+期权三维度综合研判）"""
    gex = gex or {}
    industry = industry or {}
    gs = gex.get('summary', {})
    strategies = []

    # 从GEX获取更精确的区间
    oi_dist = gex.get('oi_dist', [])
    max_call_strike = gs.get('max_call_strike')
    max_put_strike = gs.get('max_put_strike')
    max_call_oi = gs.get('max_call_oi', 0) or 0
    max_put_oi = gs.get('max_put_oi', 0) or 0
    if not max_call_strike or not max_put_strike:
        for o in oi_dist:
            co = o.get('call_oi', 0) or 0
            po = o.get('put_oi', 0) or 0
            if co > max_call_oi:
                max_call_oi = co
                max_call_strike = o['strike']
            if po > max_put_oi:
                max_put_oi = po
                max_put_strike = o['strike']

    bottom = max_put_strike or opt.get('key_levels', {}).get('bottom') or 6000
    top = max_call_strike or opt.get('key_levels', {}).get('top') or 7000
    pta_price = gs.get('futures_price') or pta.get('spot_price') or pta.get('future', {}).get('close', 0)
    pta_spot = pta.get('spot_price')
    profit = cost_data.get('profit', 0)
    profit_pct = cost_data.get('profit_pct', 0)
    net_gex = gs.get('net_gex')
    gex_flip = gs.get('gex_flip')
    max_pain = gs.get('max_pain')
    days_left = gs.get('days_left')
    gex_direction = gs.get('gex_direction')
    pcr = gs.get('pcr')

    # AI四维评分
    ai_comm = industry.get('ai_commentary', {})
    ai_data = ai_comm.get('data', {}) if isinstance(ai_comm, dict) else {}
    ai_rating = ai_data.get('rating', '')
    ai_score = ai_data.get('total_score', 0)
    ai_dims = ai_data.get('dimensions', {})

    # 产业链数据
    ind_pta = industry.get('pta', {})
    basis_val = ind_pta.get('basis', {}).get('value', 0)
    pta_inv = ind_pta.get('social_inventory', {})
    inv_change = pta_inv.get('change', 0) if pta_inv else 0

    brent = industry.get('upstream', {}).get('brent', {})
    brent_price = brent.get('price', 0)
    brent_chg = brent.get('change_pct', 0)

    # ===== 三维度评分 =====
    # 每个维度: score [-2, +2], 正=利多, 负=利空
    dim_scores = {}

    # ---- 维度1: 宏观·成本驱动 ----
    macro_score = 0
    macro_reasons = []
    if brent_price:
        if brent_price > 90:
            macro_score += 0.8
            macro_reasons.append(f'原油${brent_price:.0f}高位，成本支撑坚挺')
        elif brent_price > 80:
            macro_score += 0.3
            macro_reasons.append(f'原油${brent_price:.0f}中位，成本有支撑')
        elif brent_price > 65:
            macro_reasons.append(f'原油${brent_price:.0f}，成本中性')
        else:
            macro_score -= 0.5
            macro_reasons.append(f'原油${brent_price:.0f}低位，成本坍塌')

        if brent_chg > 3:
            macro_score += 0.5
            macro_reasons.append(f'原油大涨{brent_chg:+.1f}%')
        elif brent_chg < -3:
            macro_score -= 0.5
            macro_reasons.append(f'原油大跌{brent_chg:+.1f}%')

    if profit is not None:
        if profit > 500:
            macro_score -= 0.6
            macro_reasons.append(f'高利润{profit:.0f}元，供应释放压力大')
        elif profit > 200:
            macro_score -= 0.2
            macro_reasons.append(f'利润{profit:.0f}元，开工积极性高')
        elif profit < -100:
            macro_score += 0.6
            macro_reasons.append(f'亏损{profit:.0f}元，供应收缩预期')
        elif profit < 0:
            macro_score += 0.3
            macro_reasons.append(f'微亏{profit:.0f}元，供应压力边际减轻')

    macro_score = max(-2, min(2, macro_score))
    dim_scores['macro'] = {
        'name': '宏观·成本', 'score': round(macro_score, 2), 'weight': 0.25,
        'label': '利多' if macro_score > 0.3 else ('利空' if macro_score < -0.3 else '中性'),
        'reasons': macro_reasons
    }

    # ---- 维度2: 产业·供需 ----
    industry_score = 0
    industry_reasons = []

    # 基差
    if basis_val:
        if basis_val > 200:
            industry_score += 0.8
            industry_reasons.append(f'现货升水{basis_val:.0f}(强)，现货偏紧')
        elif basis_val > 50:
            industry_score += 0.3
            industry_reasons.append(f'现货升水{basis_val:.0f}，正常')
        elif basis_val < -100:
            industry_score -= 0.6
            industry_reasons.append(f'现货贴水{basis_val:.0f}(弱)，需求偏弱')
        elif basis_val < 0:
            industry_score -= 0.2
            industry_reasons.append(f'现货小幅贴水{basis_val:.0f}')

    # 库存
    if pta_inv and pta_inv.get('stock'):
        stock = pta_inv['stock']
        if stock < 150000:
            industry_score += 0.5
            industry_reasons.append(f'PTA库存{stock/10000:.1f}万吨(偏低)')
        elif stock > 350000:
            industry_score -= 0.5
            industry_reasons.append(f'PTA库存{stock/10000:.1f}万吨(偏高)')

        if inv_change < -3000:
            industry_score += 0.4
            industry_reasons.append(f'去库加速({inv_change}吨/周)')
        elif inv_change > 3000:
            industry_score -= 0.4
            industry_reasons.append(f'累库加速(+{inv_change}吨/周)')
        elif inv_change < 0:
            industry_score += 0.1
            industry_reasons.append(f'小幅去库({inv_change}吨)')

    industry_score = max(-2, min(2, industry_score))
    dim_scores['industry'] = {
        'name': '产业·供需', 'score': round(industry_score, 2), 'weight': 0.35,
        'label': '利多' if industry_score > 0.3 else ('利空' if industry_score < -0.3 else '中性'),
        'reasons': industry_reasons
    }

    # ---- 维度3: 期权·微观 ----
    option_score = 0
    option_reasons = []

    # GEX方向：波动状态，不作为方向多空加分
    if gex_direction == 'positive':
        option_reasons.append(f'正Gamma(净GEX+{net_gex/1e6:.1f}M)，对冲流压制波动，偏震荡/均值回归')
    elif gex_direction == 'negative':
        option_reasons.append(f'负Gamma(净GEX{net_gex/1e6:.1f}M)，对冲流放大波动，趋势延续风险更高')

    # PCR
    if pcr:
        if pcr > 1.5:
            option_score += 0.5
            option_reasons.append(f'PCR={pcr:.3f}(极度看跌)，反转利多信号')
        elif pcr > 1.2:
            option_score += 0.2
            option_reasons.append(f'PCR={pcr:.3f}(偏空)，有保护性看跌')
        elif pcr < 0.7:
            option_score -= 0.3
            option_reasons.append(f'PCR={pcr:.3f}(偏多)，Call偏乐观')

    # 价格 vs Max Pain
    if max_pain and pta_price and pta_price > 0:
        diff = pta_price - max_pain
        if days_left and days_left <= 5:
            if diff > 100:
                option_score -= 0.5
                option_reasons.append(f'临近到期({days_left:.0f}天)，价格{pta_price:.0f}高于痛点{max_pain}达{diff:+.0f}，有回落压力')
            elif diff < -100:
                option_score += 0.5
                option_reasons.append(f'临近到期({days_left:.0f}天)，价格{pta_price:.0f}低于痛点{max_pain}达{diff:+.0f}，有反弹动力')
            else:
                option_reasons.append(f'临近到期，接近痛点{max_pain}，锚定较强')
        else:
            if abs(diff) > 150:
                score_adj = -0.3 if diff > 0 else 0.3
                option_score += score_adj
                option_reasons.append(f'价格偏离痛点{max_pain}达{diff:+.0f}')

    # GEX翻转点：状态切换线，不直接作为方向多空分
    if gex_flip and pta_price and pta_price > 0:
        dist = pta_price - gex_flip
        if dist > 0:
            option_reasons.append(f'价格{pta_price:.0f}在翻转点{gex_flip}上方{dist:.0f}点(正Gamma状态)')
        else:
            option_reasons.append(f'价格{pta_price:.0f}在翻转点{gex_flip}下方{abs(dist):.0f}点(负Gamma状态)')

    option_score = max(-2, min(2, option_score))
    dim_scores['option'] = {
        'name': '期权·微观', 'score': round(option_score, 2), 'weight': 0.40,
        'label': '利多' if option_score > 0.3 else ('利空' if option_score < -0.3 else '中性'),
        'reasons': option_reasons
    }

    # ===== 三维加权合成 =====
    total_score = sum(d['score'] * d['weight'] for d in dim_scores.values())
    if total_score > 0.6:
        overall_direction = '偏多'
    elif total_score > 0.2:
        overall_direction = '震荡偏多'
    elif total_score > -0.2:
        overall_direction = '震荡'
    elif total_score > -0.6:
        overall_direction = '震荡偏空'
    else:
        overall_direction = '偏空'

    # ===== 策略条目生成（保留原有的详细策略） =====
    # GEX环境
    if net_gex is not None and gex_direction:
        flip_note = ''
        if gex_flip and pta_price and pta_price > 0:
            dist = pta_price - gex_flip
            flip_note = f'；Flip={gex_flip}，当前价{pta_price:.0f}{"高于" if dist > 0 else "低于"}{gex_flip}{abs(dist):.0f}点'
        if gex_direction == 'positive':
            strategies.append({
                'action': '🛡️ 正Gamma波动环境',
                'detail': f'净GEX=+{net_gex/1e6:.1f}M，做市商对冲流倾向涨了卖、跌了买{flip_note}',
                'suggestion': '偏波动抑制/震荡回归，追突破谨慎；若价格接近或跌破Flip，波动放大风险上升。GEX不是方向预测'
            })
        else:
            strategies.append({
                'action': '⚡ 负Gamma波动环境',
                'detail': f'净GEX={net_gex/1e6:.1f}M，做市商对冲流倾向涨了买、跌了卖{flip_note}',
                'suggestion': '偏波动放大/趋势延续，卖方需控制尾部风险；若重新站上Flip，波动可能重新受抑。GEX不是方向预测'
            })

    # Max Pain / 到期
    if pta_price > 0:
        if max_pain and days_left and days_left <= 5:
            diff = pta_price - max_pain
            strategies.append({
                'action': '🎯 到期前痛点引力',
                'detail': f'距到期{days_left:.1f}天，期权链/期权服务标的价{pta_price:.0f} vs 痛点{max_pain}，偏差{diff:+.0f}',
                'suggestion': f'临近到期标的价倾向向痛点{max_pain}回归，'
                              f'{"上方Call卖方受益" if diff > 0 else "下方Put卖方受益"}，'
                              f'Theta加速衰减利好卖方'
            })
        elif max_pain:
            diff = pta_price - max_pain
            strategies.append({
                'action': '🎯 痛点参考',
                'detail': f'期权链/期权服务标的价{pta_price:.0f} vs 痛点{max_pain}，偏差{diff:+.0f}',
                'suggestion': f'关注标的价向痛点{max_pain}的回归倾向'
            })

    # 产业基本面策略
    if basis_val > 200:
        strategies.append({
            'action': '📈 强基差升水',
            'detail': f'现货升水{basis_val:.0f}元，现货偏紧',
            'suggestion': '强基差支撑近月合约，正套(买近卖远)机会；若基差回落是做空信号'
        })
    elif basis_val < -100:
        strategies.append({
            'action': '📉 深贴水',
            'detail': f'现货贴水{abs(basis_val):.0f}元，需求偏弱',
            'suggestion': '贴水反映弱需求，反套(卖近买远)或做空偏多'
        })

    # 成本利润
    if profit > 300:
        strategies.append({
            'action': '💰 高利润供应压力',
            'detail': f'利润{profit:.0f}元/吨(+{profit_pct:.1f}%)，上游供给释放',
            'suggestion': '高利润→装置提负/重启→供应增加→中期偏空'
        })
    elif profit is not None and profit <= 0:
        strategies.append({
            'action': '⚠️ 亏损成本支撑',
            'detail': f'亏损{abs(profit):.0f}元/吨，供应收缩',
            'suggestion': '亏损→停车/检修→供应缩减→中期利多'
        })

    # OI支撑/压力
    if max_put_strike and max_call_strike:
        strategies.append({
            'action': '📊 OI支撑压力区间',
            'detail': f'Put支撑{max_put_strike}({max_put_oi:,}手) ↔ Call压力{max_call_strike}({max_call_oi:,}手)',
            'suggestion': f'区间【{max_put_strike},{max_call_strike}】内震荡概率高'
        })

    if not strategies:
        strategies.append({
            'action': '⏳ 等待数据更新',
            'detail': '数据获取中，策略建议待更新',
            'suggestion': '请稍后刷新页面获取最新分析'
        })

    # ===== 核心研判（三维融合叙述） =====
    core_parts = []
    # 方向判断
    core_parts.append(f'三维综合评分{total_score:+.2f}，方向【{overall_direction}】')

    # 各维度概要（三维度都展示，缺理由时给中性占位）
    for key in ['macro', 'industry', 'option']:
        d = dim_scores[key]
        reason_text = d['reasons'][0] if d.get('reasons') else f'维度评分{d["score"]:+.2f}，{d.get("label","中性")}'
        core_parts.append(f"{d['name']}({d['label']}): {reason_text}")

    # AI评级参考
    if ai_rating:
        core_parts.append(f'AI产业评级: {ai_rating}({ai_score:+.2f})')

    # 区间位置
    if pta_price and bottom and top and pta_price > 0:
        mid = (bottom + top) / 2
        if pta_price > top:
            core_parts.append(f'期权链/期权服务标的价{pta_price:.0f}已突破压力位{top}')
        elif pta_price < bottom:
            core_parts.append(f'期权链/期权服务标的价{pta_price:.0f}跌破支撑位{bottom}')
        else:
            pos = '偏上' if pta_price > mid else '偏下'
            core_parts.append(f'期权链/期权服务标的价{pta_price:.0f}在【{bottom},{top}】区间{pos}')

    if days_left and days_left <= 5:
        core_parts.append(f'仅剩{days_left:.1f}天到期，Theta加速衰减')

    core_idea = "综合研判：" + "；".join(core_parts) + "。" if core_parts else "数据汇总中。"

    return {
        'title': '三、 策略建议',
        'subtitle': f'三维研判·{overall_direction}',
        'strategies': strategies[:6],
        'core_idea': core_idea,
        'direction': overall_direction,
        'total_score': round(total_score, 2),
        'dimensions': dim_scores,
    }



def _fmt_num(v, digits: int = 0, prefix: str = '') -> str:
    try:
        if v is None:
            return '--'
        x = float(v)
        return f"{prefix}{x:.{digits}f}"
    except Exception:
        return '--'


def _fmt_signed(v, digits: int = 0, suffix: str = '') -> str:
    try:
        if v is None:
            return '--'
        return f"{float(v):+.{digits}f}{suffix}"
    except Exception:
        return '--'


def _fmt_oi(v) -> str:
    try:
        return f"{int(float(v)):,}"
    except Exception:
        return '--'


def _pct_desc(v) -> str:
    try:
        x = float(v)
        return f"{x:+.2f}%"
    except Exception:
        return '--'


def _as_float(v):
    try:
        if v is None or v == '':
            return None
        return float(v)
    except Exception:
        return None


def _text_fingerprint(text: str) -> str:
    """用于研报短文本去重：去标签、去标点空白，保留核心中文/数字/英文。"""
    t = re.sub(r'【[^】]+】', '', str(text or ''))
    t = re.sub(r'<[^>]+>', '', t)
    t = re.sub(r'[\s，。；;,.、：:！!？?（）()\[\]【】"“”\'’`~\-—_]+', '', t)
    return t.lower()


def _dedupe_text_items(items, max_items: int = None):
    """近似去重：完全重复、包含关系都只保留信息更完整的一条。"""
    out = []
    fps = []
    for item in items or []:
        text = str(item or '').strip()
        if not text:
            continue
        fp = _text_fingerprint(text)
        if not fp:
            continue
        duplicate = False
        for old_fp in fps:
            if fp == old_fp or fp in old_fp or old_fp in fp:
                duplicate = True
                break
        if duplicate:
            continue
        out.append(text)
        fps.append(fp)
        if max_items and len(out) >= max_items:
            break
    return out


def _dedupe_narrative_notes(notes: Dict) -> Dict:
    if not isinstance(notes, dict):
        return notes
    return {k: _dedupe_text_items(v) if isinstance(v, list) else v for k, v in notes.items()}


def _remove_duplicate_note_bases(notes: Dict, base_map: Dict[str, str]) -> Dict:
    """避免 API/cache 层同时把同一段解读放在 xxx_interpretation 与 narrative_notes.xxx。"""
    if not isinstance(notes, dict):
        return notes
    cleaned = {}
    for key, vals in notes.items():
        if not isinstance(vals, list):
            cleaned[key] = vals
            continue
        base_fp = _text_fingerprint(base_map.get(key, ''))
        out = []
        for v in vals:
            fp = _text_fingerprint(v)
            if base_fp and fp and (fp == base_fp or fp in base_fp or base_fp in fp):
                continue
            out.append(v)
        cleaned[key] = out
    return cleaned


def _fmt_chain_value(value, unit: str = '', digits: int = 1) -> str:
    x = _as_float(value)
    if x is None:
        return '--'
    if abs(x - round(x)) < 1e-9 and digits > 0:
        txt = f"{x:.0f}"
    else:
        txt = f"{x:.{digits}f}"
    return f"{txt}{unit or ''}"


def _fmt_delta_arrow(current, prev, unit: str = '', digits: int = 1) -> str:
    cur = _as_float(current)
    old = _as_float(prev)
    if cur is None or old is None:
        return '暂无前值'
    diff = cur - old
    arrow = '↑' if diff > 0 else ('↓' if diff < 0 else '→')
    suffix = 'pct' if unit == '%' else (unit or '')
    if abs(diff) < 1e-9:
        return f"{arrow}0"
    return f"{arrow}{diff:+.{digits}f}{suffix}"


def build_chain_operation_snapshot(manual_macro: Dict) -> Dict:
    """从人工宏观基本面输入生成产业链开工率/库存快照；缺失不臆测。"""
    raw = (manual_macro or {}).get('chain_operation_snapshot') or {}
    if not isinstance(raw, dict):
        return {'as_of_date': (manual_macro or {}).get('as_of_date'), 'source': '人工宏观与基本面文本', 'items': [], 'table': []}
    aliases = {
        'px': 'PX', 'PX': 'PX', 'pta': 'PTA', 'PTA': 'PTA',
        'polyester': '聚酯', '聚酯': '聚酯', 'weaving': '织造', '织造': '织造'
    }
    raw_items = raw.get('items') if isinstance(raw.get('items'), list) else []
    if not raw_items:
        for key, name in aliases.items():
            val = raw.get(key)
            if isinstance(val, dict):
                item = dict(val)
                item.setdefault('name', name)
                raw_items.append(item)
    order = ['PX', 'PTA', '聚酯', '织造']
    by_name = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        name = aliases.get(str(item.get('name') or item.get('环节') or '').strip(), str(item.get('name') or item.get('环节') or '').strip())
        if name in order:
            it = dict(item)
            it['name'] = name
            by_name[name] = it
    items = []
    table = []
    for name in order:
        it = by_name.get(name, {'name': name})
        rate_unit = it.get('operating_rate_unit') or it.get('rate_unit') or '%'
        inv_unit = it.get('inventory_unit') or it.get('stock_unit') or ''
        rate = it.get('operating_rate', it.get('rate'))
        rate_prev = it.get('operating_rate_prev', it.get('rate_prev'))
        inv = it.get('inventory', it.get('stock'))
        inv_prev = it.get('inventory_prev', it.get('stock_prev'))
        inv_desc = it.get('inventory_desc') or it.get('stock_desc') or it.get('desc') or ''
        norm = {
            'name': name,
            'operating_rate': rate,
            'operating_rate_prev': rate_prev,
            'operating_rate_unit': rate_unit,
            'operating_rate_text': _fmt_chain_value(rate, rate_unit),
            'operating_rate_delta': _fmt_delta_arrow(rate, rate_prev, rate_unit),
            'inventory': inv,
            'inventory_prev': inv_prev,
            'inventory_unit': inv_unit,
            'inventory_text': _fmt_chain_value(inv, inv_unit),
            'inventory_delta': _fmt_delta_arrow(inv, inv_prev, inv_unit),
            'inventory_desc': inv_desc or ('文本未给出' if inv is None else ''),
        }
        items.append(norm)
        table.append([name, norm['operating_rate_text'], norm['operating_rate_delta'], norm['inventory_text'], norm['inventory_delta']])
    return {
        'as_of_date': raw.get('as_of_date') or (manual_macro or {}).get('as_of_date'),
        'source': raw.get('source') or '人工宏观与基本面文本',
        'items': items,
        'table': table,
    }


def _table(headers, rows) -> str:
    lines = ['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |']
    for row in rows:
        lines.append('| ' + ' | '.join(str(x) for x in row) + ' |')
    return '\n'.join(lines)


def _render_auto_news(macro_news_items):
    """渲染宏观快讯区：去重人工摘要 + 清洗每条尾标点，避免与句尾 `。` 拼出 `。。`"""
    auto_items = [m for m in (macro_news_items or [])[:6] if '【人工宏观基本面】' not in m]
    if not auto_items:
        return '宏观快讯：暂无独立自动快讯，人工基本面已在上方展示。'
    cleaned = [re.sub(r'[。；\s]+$', '', x)[:90] for x in auto_items]
    return '自动快讯（去重人工摘要）：' + '；'.join(cleaned) + '。'


def get_main_futures_price(symbol: str = 'TA609') -> Dict:
    """读取首页K线主力合约价，必须与期权链/期权服务标的价分开。默认与首页K线当前主力TA609一致。"""
    out = {'price': None, 'change_pct': None, 'symbol': symbol, 'source': '首页K线主力合约价'}
    for period in ('1min', '15min'):
        try:
            # 只需要最新价/最近20根变化，限制count避免K线接口默认取1000根导致研报生成超时。
            resp = requests.get(f'http://127.0.0.1:8424/api/kline/data?symbol={symbol}&period={period}&count=30', timeout=15)
            if not resp.ok:
                continue
            data = resp.json()
            out['price'] = data.get('current_price')
            out['change_pct'] = data.get('change_pct')
            out['symbol'] = data.get('symbol') or data.get('contract') or symbol
            out['period'] = period
            out['source_detail'] = data.get('source')
            out['fallback_warning'] = data.get('fallback_warning')
            bars = data.get('data') or []
            if out['price'] is None and bars:
                out['price'] = bars[-1].get('close')
            if bars:
                last = bars[-1] or {}
                prev = bars[-2] if len(bars) >= 2 else {}
                out['last_close'] = last.get('close')
                out['last_open'] = last.get('open')
                out['last_time'] = last.get('time') or last.get('datetime')
                if last.get('close') is not None and prev.get('close') is not None:
                    out['last_bar_change'] = last.get('close') - prev.get('close')
                if len(bars) >= 21 and bars[-21].get('close') is not None and last.get('close') is not None:
                    out['change_20_bars'] = last.get('close') - bars[-21].get('close')
            if out.get('price') is not None:
                break
        except Exception as e:
            out['error'] = str(e)
    return out



def _clean_report_text(text: str) -> str:
    text = str(text or '')
    for bad in ['TA609', '广州期货交易所', '仓单日报', '产业链/郑商所主力价']:
        text = text.replace(bad, '')
    return ' '.join(text.split())

def _snapshot_has_dirty_text(snapshot: Dict) -> bool:
    raw = json.dumps(snapshot, ensure_ascii=False)
    return any(bad in raw for bad in ['TA609', '广州期货交易所', '仓单日报', '产业链/郑商所主力价'])

def generate_intraday_analysis(report: Dict) -> Dict:
    """生成详尽版盘中综合研判：期货价格、GEX、Pain、OI、IV、宏观快讯、策略。"""
    s1 = report.get('section1') or {}
    s2 = report.get('section2') or {}
    s3 = report.get('section3') or {}
    gex = report.get('gex') or {}
    gex_summary = s1.get('gex_summary') or gex.get('summary') or {}
    pain_curve = gex.get('pain_curve') or []
    oi_dist = gex.get('oi_dist') or []
    iv_rows = (report.get('iv_table') or {}).get('rows') or []
    if not iv_rows:
        iv_rows = (report.get('iv_curve') or {}).get('curve') or []
    iv_analysis = s1.get('iv_analysis') or {}
    pta = report.get('pta') or {}
    px = report.get('px') or {}
    px_external = report.get('px_external') or {}
    crude = report.get('crude') or {}
    cost = report.get('cost') or {}
    news = report.get('macro_news') or {}
    manual_macro = report.get('manual_macro_input') or {}

    option_underlying_price = gex_summary.get('futures_price')
    # 盘面主力参考价: 严格用实时K线价;K线接口拿不到时**不再 fallback 到 dominant_price/near_price**
    # (那些是 TA609 上一交易日结算价 / TA606 近月合约价,跟"盘面主力参考价"不是一个口径,
    # fallback 后会被后续 _override_report_with_kline_price 用 K线价覆盖,但期间生成的
    # market_snapshot_table['基差'] 和 trader_report 第三节点的 near_basis 都会是错的)
    # 取不到就直接返回 None,让上层决策是否保留旧缓存
    main_px = get_main_futures_price()
    kline_price = main_px.get('price')
    if kline_price is not None:
        main_futures_price = float(kline_price)
        main_symbol = main_px.get('symbol') or pta.get('dominant_contract') or 'TA609'
    else:
        # K线接口无价:日志告警,保留 None;调用方需自己决定是否要保留 main_futures_price=None 的旧值
        app_logger = None  # generate_daily_report 不直接接 app.logger,用 print 兜底
        try:
            import logging
            logging.getLogger(__name__).warning('[研报] K线接口无价,main_futures_price=None (避开 fallback 到 dominant_price)')
        except Exception:
            pass
        main_futures_price = None
        main_symbol = pta.get('dominant_contract') or 'TA609'

    # ---- 人工 spot_main_overrides（v2.11.37+）：仅覆盖 PTA 现货价；
    # 盘面主力参考价/主力符号/涨跌幅/基差都来自实时K线 / 自然计算 ----
    spot_overrides = (manual_macro or {}).get('spot_main_overrides') or {}
    manual_spot = spot_overrides.get('spot_price')
    if manual_spot is not None and float(manual_spot) > 0:
        pta_spot_override = float(manual_spot)
    else:
        pta_spot_override = None

    direction = s3.get('direction') or '震荡'
    gex_dir = gex_summary.get('gex_direction')
    net_gex = _as_float(gex_summary.get('net_gex'))
    net_gex_m = net_gex / 1e6 if net_gex is not None else None
    max_pain = gex_summary.get('max_pain')
    gex_flip = gex_summary.get('gex_flip')
    pcr = gex_summary.get('pcr')
    days_left = gex_summary.get('days_left')
    total_call_oi = gex_summary.get('total_call_oi')
    total_put_oi = gex_summary.get('total_put_oi')
    max_put = gex_summary.get('effective_support') or gex_summary.get('max_put_strike')
    max_call = gex_summary.get('effective_resistance') or gex_summary.get('max_call_strike')
    max_put_oi = gex_summary.get('max_put_oi')
    max_call_oi = gex_summary.get('max_call_oi')

    gamma_desc = '正 Gamma 区，做市商对冲倾向抑制波动' if gex_dir == 'positive' else ('负 Gamma 区，做市商对冲更容易追涨杀跌、放大波动' if gex_dir == 'negative' else 'Gamma方向待确认')
    if direction == '震荡' and gex_dir == 'negative' and main_px.get('change_20_bars') and main_px.get('change_20_bars') < 0:
        headline_dir = '偏弱震荡'
    else:
        headline_dir = direction

    pta_spot = pta.get('spot_price') or pta.get('spot', {}).get('price')
    # 人工现货价覆盖（v2.11.37+）：manual_macro_input.spot_main_overrides.spot_price
    if pta_spot_override is not None:
        pta_spot = pta_spot_override
    # 盘面主力参考价只能来自实时K线；不再用 spot_main_overrides 覆盖。
    main_futures_label = main_symbol or 'TA主力'
    main_futures_display_price = main_futures_price
    # 同步把 main_futures_price 暴露给下游（trader_report / narrative 末尾的'盘面主力参考价 XX'复用）
    main_futures_price = main_futures_display_price
    # 基差口径（v2.11.46+）：严格按"PTA现货 − 盘面主力参考价"计算，akshare 郑商所表的 near_basis 已废弃
    near_basis = None
    if pta_spot is not None and main_futures_display_price:
        near_basis = round(float(pta_spot) - float(main_futures_display_price), 2)
    px_price = px.get('spot_price') or px.get('price')
    px_asia_close = px_external.get('px_asia_close_usd')
    pta_external_cost = px_external.get('pta_external_cost') or (cost.get('pta_external_cost') if isinstance(cost, dict) else None)
    usd_cny = px_external.get('usd_cny')
    profit = cost.get('profit') if isinstance(cost, dict) else None
    profit_pct = cost.get('profit_pct') if isinstance(cost, dict) else None
    pta_cost = cost.get('pta_cost') if isinstance(cost, dict) else None
    brent = crude.get('brent') or {}
    wti = crude.get('wti') or {}

    pain_rows = []
    for item in sorted(pain_curve, key=lambda x: abs((x.get('strike') or 0) - (max_pain or option_underlying_price or 0)))[:5]:
        pain_rows.append([_fmt_num(item.get('strike')), _fmt_oi(item.get('pain')), '最低' if item.get('strike') == max_pain else ''])
    if not pain_rows and max_pain:
        pain_rows.append([_fmt_num(max_pain), '--', '最低'])

    top_put_oi = sorted([x for x in oi_dist if (x.get('put_oi') or 0) > 0], key=lambda x: x.get('put_oi') or 0, reverse=True)[:5]
    top_call_oi = sorted([x for x in oi_dist if (x.get('call_oi') or 0) > 0], key=lambda x: x.get('call_oi') or 0, reverse=True)[:5]
    put_rows = [[_fmt_num(x.get('strike')), _fmt_oi(x.get('put_oi'))] for x in top_put_oi]
    call_rows = [[_fmt_num(x.get('strike')), _fmt_oi(x.get('call_oi'))] for x in top_call_oi]

    atm = (report.get('iv_curve') or {}).get('atm_strike') or max_pain or option_underlying_price
    def strike_val(row): return _as_float(row.get('strike')) or 0
    near_iv_rows = sorted(iv_rows, key=lambda r: abs(strike_val(r) - (atm or 0)))[:5]
    near_iv_rows = sorted(near_iv_rows, key=strike_val)
    iv_table_rows = []
    for r in near_iv_rows:
        c_iv = r.get('iv_call') or r.get('call_iv') or r.get('raw_C')
        p_iv = r.get('iv_put') or r.get('put_iv') or r.get('raw_P')
        svi = r.get('svi_iv') or r.get('smooth') or r.get('raw_avg')
        if c_iv is not None and abs(float(c_iv)) < 3: c_iv = float(c_iv) * 100
        if p_iv is not None and abs(float(p_iv)) < 3: p_iv = float(p_iv) * 100
        if svi is not None and abs(float(svi)) < 3: svi = float(svi) * 100
        iv_table_rows.append([_fmt_num(r.get('strike')), _fmt_num(c_iv, 2) + '%', _fmt_num(p_iv, 2) + '%', _fmt_num(svi, 2) + '%', f"C {_fmt_oi(r.get('call_oi') or r.get('oi_call'))} / P {_fmt_oi(r.get('put_oi') or r.get('oi_put'))}"])

    atm_iv = iv_analysis.get('atm_vol')
    skew_desc = iv_analysis.get('skew_desc') or ''
    curv_desc = iv_analysis.get('curv_desc') or ''

    macro_news_items = []
    if manual_macro:
        manual_summary = _clean_news_text(manual_macro.get('summary') or manual_macro.get('text') or manual_macro.get('comment') or '', 360)
        if manual_summary:
            macro_news_items.append('【人工宏观基本面】' + manual_summary)
        for key in ['crude', 'px', 'pta', 'cost', 'macro', 'events']:
            val = manual_macro.get(key)
            vals = val if isinstance(val, list) else ([val] if isinstance(val, str) else [])
            for x in vals:
                t = _clean_news_text(x, 260)
                if t and t not in macro_news_items:
                    macro_news_items.append(t)
    if isinstance(news, dict):
        for key in ['macro', 'geo', 'industry', 'fed']:
            vals = news.get(key) or []
            if isinstance(vals, list):
                for x in vals:
                    t = _clean_news_text(x, 240)
                    if t and t not in macro_news_items:
                        macro_news_items.append(t)
    elif isinstance(news, list):
        for x in news:
            t = _clean_news_text(x, 240)
            if t and t not in macro_news_items:
                macro_news_items.append(t)
    macro_news_items = _dedupe_text_items(macro_news_items)
    macro_news_items = macro_news_items[:6]
    chain_operation_snapshot = build_chain_operation_snapshot(manual_macro)
    chain_operation_table = chain_operation_snapshot.get('table') or []

    key_levels = []
    if gex_flip: key_levels.append([_fmt_num(gex_flip), 'GEX Flip，重新站上后负Gamma压力缓和' if gex_dir == 'negative' else 'GEX Flip，跌破后波动可能放大'])
    if max_pain: key_levels.append([_fmt_num(max_pain), 'Max Pain + 临近到期收敛锚'])
    if max_put: key_levels.append([_fmt_num(max_put), '近端Put防线/有效支撑'])
    if max_call: key_levels.append([_fmt_num(max_call), '近端Call压力/有效压力'])
    if top_call_oi:
        key_levels.append([f"{_fmt_num(top_call_oi[0].get('strike'))}", '上方最大Call持仓压力带'])
    if top_put_oi:
        key_levels.append([f"{_fmt_num(top_put_oi[0].get('strike'))}", '下方最大Put保护盘区域'])

    if max_pain and option_underlying_price:
        pain_diff = float(option_underlying_price) - float(max_pain)
        pain_comment = f"当前期权标的价距离Max Pain约{pain_diff:+.0f}点，临近到期存在向{_fmt_num(max_pain)}收敛的引力。"
    else:
        pain_comment = "Max Pain 数据暂缺，痛点收敛强度需等待下一轮期权刷新。"

    futures_bias = '短线偏弱' if (main_px.get('change_20_bars') or 0) < 0 else ('短线偏强' if (main_px.get('change_20_bars') or 0) > 0 else '短线震荡')
    conclusion = f"当前市场判断：短线“{headline_dir}”，但不是单边空头。" if '空' not in str(headline_dir) else f"当前市场判断：短线“{headline_dir}”，需要防范顺势扩散。"

    market_snapshot_table = [
        ['期权链标的参考价', _fmt_num(option_underlying_price), '用于GEX、Pain、OI和IV结构判断'],
        ['盘面主力参考价', f"{main_futures_label} {_fmt_num(main_futures_display_price)}", f"K线短线节奏：{futures_bias}"],
        ['最近20根K线', _fmt_signed(main_px.get('change_20_bars')), '观察日内强弱和追单风险'],
        ['PTA现货', _fmt_num(pta_spot), '现货/成本锚'],
        ['基差', _fmt_signed(near_basis), 'PTA现货 − 盘面主力参考价；升水偏强、贴水偏弱'],
    ]
    gex_table = [['标的价F', _fmt_num(option_underlying_price)], ['GEX Flip', _fmt_num(gex_flip)], ['净GEX', f"{_fmt_num(net_gex_m,1)}M"], ['Gamma方向', gex_dir or '--'], ['Max Pain', _fmt_num(max_pain)], ['PCR', _fmt_num(pcr,3)], ['剩余到期', f"{_fmt_num(days_left,1)}天"]]
    pain_table = pain_rows
    oi_tables = {'put': put_rows or [['--','--']], 'call': call_rows or [['--','--']]}
    iv_table = iv_table_rows or [['--','--','--','--','--']]
    macro_table = [
        ['Brent', f"{_fmt_num(brent.get('price'),2,'$')}，{_pct_desc(brent.get('change_pct'))}", '原油宏观成本'],
        ['WTI', f"{_fmt_num(wti.get('price'),2,'$')}，{_pct_desc(wti.get('change_pct'))}", '原油宏观成本'],
        ['PX现货', _fmt_num(px_price), '内盘成本端'],
        ['PX外盘现货价', f"{_fmt_num(px_asia_close,2,'$')}/吨" if px_asia_close else '--', f"{px_external.get('source','')}；汇率{_fmt_num(usd_cny,4)}" if px_asia_close else 'CFR中国/亚洲收盘价待更新'],
        ['PTA估算成本', _fmt_num(pta_cost), '内盘成本支撑区'],
        ['外盘PTA动态成本', _fmt_num(pta_external_cost), 'PX亚洲收盘价*0.655*1.01*1.13*USD/CNY'],
        ['PTA利润', f"{_fmt_num(profit)}，{_fmt_num(profit_pct,1)}%", '利润高则供应压力偏空'],
    ]

    futures_strategy = [
        f"{_fmt_num(gex_flip)} / {_fmt_num(max_call)}下方不宜追多，先按反抽压力处理。",
        f"跌破{_fmt_num(max_pain)}并放量增仓，负Gamma可能放大下跌，下一目标看{_fmt_num(max_put)}。",
        f"重新站回{_fmt_num(gex_flip)}，空头动能减弱，回到区间震荡。",
    ]
    option_seller_strategy = [
        "临近到期Theta衰减快，震荡时卖方有时间价值优势。",
        f"负Gamma环境不裸卖近端Put，尤其是{_fmt_num(max_pain)}失守后。",
        f"若站回{_fmt_num(gex_flip)}，可考虑更稳健的宽跨/价差结构。",
    ]
    option_buyer_strategy = [
        f"买Put触发点优先看{_fmt_num(max_pain)}有效跌破。",
        f"买Call触发点看重新站回{_fmt_num(gex_flip)}或压力位后的修复。",
        "夹在痛点和压力之间横盘时，买方容易被时间价值消耗。",
    ]
    strategy_blocks = {
        'futures_strategy': {'title': '期货操作', 'items': futures_strategy},
        'option_seller_strategy': {'title': '期权卖方策略', 'items': option_seller_strategy},
        'option_buyer_strategy': {'title': '期权买方策略', 'items': option_buyer_strategy},
    }

    market_snapshot_interpretation = f"期权链标的参考价{_fmt_num(option_underlying_price)}用于GEX、Pain、OI与IV等结构判断，盘面主力参考价{_fmt_num(main_futures_display_price)}负责K线节奏；两者各管一段，不要把结构位和短线信号混为一个价格。"
    gex_interpretation = f"GEX处在{gamma_desc}。交易上先盯两条线：{_fmt_num(max_pain)}若失守，负Gamma容易放大顺势波动；{_fmt_num(gex_flip)}若被重新收复，追涨杀跌压力会减轻。"
    oi_interpretation = f"持仓给出的不是单边方向，而是边界：Put集中区对应下方防线，Call集中区对应上方压力。当前更适合把{_fmt_num(max_pain)}—{_fmt_num(max_call)}当作区间框架，再等跌破或站回触发。"
    iv_interpretation = f"ATM隐波约{_fmt_num(atm_iv,1)}%，{skew_desc or '偏度待确认'}。如果左侧Put继续显著贵于Call，说明市场仍在为下跌尾部风险付费；若IV回落，卖方时间价值优势才更清晰。"
    macro_hint = '；'.join(macro_news_items[:3]) if macro_news_items else '暂无高质量宏观快讯'
    # 避免与外部句末 `。` 拼出 `。。`
    macro_hint = re.sub(r'[。；]+$', '', macro_hint)
    external_cost_hint = f"外盘PX{_fmt_num(px_asia_close,2,'$')}/吨，对应外盘PTA动态成本约{_fmt_num(pta_external_cost)}元/吨" if px_asia_close and pta_external_cost else "外盘PX/外盘PTA动态成本等待最新有效报价"
    macro_interpretation = f"宏观与成本端优先纳入人工宏观基本面、地缘风险、实时原油/PX变化和外盘成本。当前可参考：{macro_hint}。{external_cost_hint}；若地缘反复推升原油或PX继续偏强，下方成本支撑增强；若中东缓和、原油回落或PX转弱，则多头弹性受压。"
    strategy_logic = f"策略依据：先用盘面主力判断追单节奏，再用GEX/Pain确定触发位，用OI确认支撑压力，用IV决定买方还是卖方更占优，同时用原油/PX外盘成本确认顺势信号质量。当前重点是{_fmt_num(max_pain)}是否跌破、{_fmt_num(gex_flip)}是否收复；未触发前以区间和风控为主，触发后再顺势加速。"

    upper_zone = _fmt_num(max_call) if max_call else '6550-6600'
    support_zone = _fmt_num(max_put) if max_put else '6200'
    gex_flip_text = _fmt_num(gex_flip)
    max_pain_text = _fmt_num(max_pain)
    macro_core = macro_news_items[0].replace('【人工宏观基本面】', '') if macro_news_items else '基本面日内变化不大，重点看原油/PX事件驱动与期权结构触发。'
    # 若有更鲜明的核心矛盾（DeepSeek 综合），优先用其生成单句方向
    try:
        _mm = manual_macro or {}
        _core = (_mm.get('core_takeaway') or _mm.get('strategy_hint') or '').strip()
        if _core:
            macro_core = _core[:200]
    except Exception:
        pass
    trader_report = "\n".join([
        "PTA 最新综合研判",
        "",
        "一、核心结论",
        "当前 PTA 不适合简单看空。",
        f"产业链给出的底色是偏强震荡、有支撑但上方也有压制。当前核心区间先看{max_pain_text}—{upper_zone}，不是无脑追多，也不是在{max_pain_text}上方主动追空。",
        f"期权结构上，当前价格处于{gamma_desc}，这意味着一旦关键位置被突破，波动容易被放大。",
        "",
        "二、宏观与成本端",
        f"日内基本面不做机械重复改写，作为背景锚处理：{macro_core}",
        f"原油/PX若继续偏强，会给PTA下方托底；如果中东缓和、原油回落或PX转弱，则多头会受压。当前PTA利润约{_fmt_num(profit)}元，加工费偏高会限制上方持续单边拉涨空间。",
        "",
        "三、PTA自身基本面",
        f"现货参考{_fmt_num(pta_spot)}，基差{_fmt_signed(near_basis)}（即PTA现货 − 盘面主力参考价），PX参考{_fmt_num(px_price)}，PTA估算成本{_fmt_num(pta_cost)}。现货/成本仍提供支撑，但高加工费和装置重启预期会压制追多空间。",
        "",
        "四、当前期权结构",
        f"期权链标的参考价：{_fmt_num(option_underlying_price)}；Max Pain：{max_pain_text}；GEX Flip：{gex_flip_text}；净GEX：{_fmt_num(net_gex_m,1)}M；Gamma方向：{gex_dir or '--'}；PCR：{_fmt_num(pcr,3)}；剩余到期：约{_fmt_num(days_left,1)}天。",
        f"临近到期，{max_pain_text}对价格有明显吸引力；站回{gex_flip_text}后负Gamma压力缓和，跌破{max_pain_text}则负Gamma可能放大下跌。",
        "",
        "五、持仓压力与支撑",
        f"下方Put防线重点看{max_pain_text}、{support_zone}；上方Call压力重点看{upper_zone}以及更高Call集中区。持仓给出的不是单边方向，而是区间边界。",
        "",
        "六、隐波与风险情绪",
        f"ATM隐波约{_fmt_num(atm_iv,1)}%，{skew_desc or '偏度待确认'}。如果Put保护溢价继续高于Call，说明市场仍在为下跌尾部风险付费；临近到期买方不能在中间位置随意追。",
        "",
        "七、交易策略",
        "1. 期货操作",
        f"{max_pain_text}上方不追空；{gex_flip_text}下方不盲目追多；站回{gex_flip_text}才考虑短多延续；跌破{max_pain_text}才考虑顺势空头，下一层关注{support_zone}。",
        "2. 期权卖方策略",
        f"临近到期Theta衰减快，但负Gamma环境下不裸卖近端Put。若价格维持在{max_pain_text}上方，可优先考虑有保护的价差结构；若跌破{max_pain_text}，卖Put风险快速上升。",
        "3. 期权买方策略",
        f"买Put触发点看有效跌破{max_pain_text}，最好伴随原油/PX走弱或盘面放量；买Call触发点看重新站回{gex_flip_text}，否则容易被时间价值消耗。",
        "",
        "八、最终判断",
        f"基本面偏强支撑，期权结构偏震荡拉扯，短线处于负Gamma敏感区。{max_pain_text}不破，短期仍以偏强震荡对待；站上{gex_flip_text}，价格有机会继续试探{upper_zone}；跌破{max_pain_text}，负Gamma可能放大下跌，回看{support_zone}。",
    ])

    narrative_notes = {
        'market': [market_snapshot_interpretation],
        'gex': [gex_interpretation],
        'oi': [oi_interpretation],
        'iv': [iv_interpretation],
        'macro': [macro_interpretation],
        'strategy': [strategy_logic],
        'other': []
    }
    narrative_notes = _dedupe_narrative_notes(narrative_notes)
    narrative_notes = _remove_duplicate_note_bases(narrative_notes, {
        'market': market_snapshot_interpretation,
        'gex': gex_interpretation,
        'oi': oi_interpretation,
        'iv': iv_interpretation,
        'macro': macro_interpretation,
        'strategy': strategy_logic,
    })

    sections = [
        conclusion,
        "",
        "1. 期货价格层面（期货盘面）：短线节奏看盘面主力，期权结构看期权链标的参考价。",
        _table(['项目','当前值','交易含义'], market_snapshot_table),
        market_snapshot_interpretation,
        f"盘面主力参考价{_fmt_num(main_futures_display_price)}：最近一根变化{_fmt_signed(main_px.get('last_bar_change'))}点，过去20根累计{_fmt_signed(main_px.get('change_20_bars'))}点，节奏判定为{futures_bias}。期权链标的参考价{_fmt_num(option_underlying_price)}用于判断GEX、Pain和持仓压力，不与盘面价混在一起下结论。",
        "",
        "2. GEX结构：价格所处Gamma区决定波动是否容易被放大。",
        _table(['指标','当前值'], gex_table),
        gex_interpretation,
        f"核心含义：F={_fmt_num(option_underlying_price)} {'低于' if option_underlying_price and gex_flip and option_underlying_price < gex_flip else '高于或接近'} GEX Flip={_fmt_num(gex_flip)}，当前处在{gamma_desc}。若价格重新站回{_fmt_num(gex_flip)}/{_fmt_num(max_call)}上方，负Gamma压力会缓和；若跌破{_fmt_num(max_pain)}附近，波动可能更顺。",
        "",
        "3. Max Pain：临近到期关注痛点收敛，而不是简单看多看空。",
        _table(['行权价','Pain','备注'], pain_table),
        f"当前Max Pain={_fmt_num(max_pain)}。{pain_comment} 因此期权维度不是极端单边，而是上方Call压力、下方痛点/Put防线共同约束。",
        "",
        "4. 持仓结构：Put持仓偏多时要区分保护盘和主动空头。",
        f"当前总持仓：Call OI={_fmt_oi(total_call_oi)}，Put OI={_fmt_oi(total_put_oi)}，PCR={_fmt_num(pcr,3)}。",
        "Put持仓集中：\n" + _table(['Put行权价','Put OI'], oi_tables['put']),
        "Call持仓集中：\n" + _table(['Call行权价','Call OI'], oi_tables['call']),
        f"解读：Put集中在{', '.join(_fmt_num(x.get('strike')) for x in top_put_oi[:3]) or '--'}，Call压力集中在{', '.join(_fmt_num(x.get('strike')) for x in top_call_oi[:4]) or '--'}。大致结构是：{_fmt_num(max_pain)}为痛点锚，{_fmt_num(gex_flip)}为波动分界，{_fmt_num(max_call)}及以上为压力带。",
        "",
        "5. IV结构：看ATM隐波是否够高，也看左侧保护溢价。",
        _table(['K','C IV','P IV','SVI/平滑IV','OI结构'], iv_table),
        iv_interpretation,
        f"ATM附近隐波约{_fmt_num(atm_iv,1)}%，属于{s1.get('iv_analysis',{}).get('vol_level','中波/待确认')}；{skew_desc or 'Skew待确认'}；{curv_desc or '曲率待确认'}。左侧Put IV若显著高于ATM，说明市场对下跌尾部风险有定价。",
        "",
        _render_nature_synthesis_section(s1.get('nature_synthesis') or {}),
        "",
        "6. 基本面与宏观：先看宏观快讯和成本链，周频供需项暂不放入盘中主研判。",
        _table(['项目','当前值','解读'], macro_table),
        _table(['环节','开工率','较前值','库存','较前值'], chain_operation_table),
        macro_interpretation,
        _render_auto_news(macro_news_items),
        f"基本面不是单边空：现货/成本可能提供下方支撑；但加工利润{_fmt_num(profit)}元若处在偏高区域，容易限制上方弹性。",
        "",
        "综合结论",
        f"当前主线：{headline_dir}，核心区间关注{_fmt_num(max_pain)}—{_fmt_num(max_call)}。期权结构处在{gamma_desc}，真正的方向触发在{_fmt_num(max_pain)}跌破或{_fmt_num(gex_flip)}/{_fmt_num(max_call)}重新站上。",
        "",
        "关键价位",
        _table(['位置','含义'], key_levels or [['--','--']]),
        "",
        "操作思路，仅按结构说",
        "如果偏交易期货：\n• " + "\n• ".join(futures_strategy),
        "如果偏期权卖方：\n• " + "\n• ".join(option_seller_strategy),
        "如果偏买方：\n• " + "\n• ".join(option_buyer_strategy),
        "",
        f"一句话总结：当前不是强多盘，主线{futures_bias}；看{_fmt_num(max_pain)}是否守住——守住则向{_fmt_num(max_pain)}—{_fmt_num(max_call)}区间收敛，跌破则负Gamma会放大下跌。",
    ]
    narrative = '\n'.join(sections)

    return {
        'title': '盘中综合研判',
        'summary': '当前 PTA 不适合简单看空。',
        'conclusion': conclusion,
        'trader_report': trader_report,
        'futures_panel': sections[3],
        'option_structure': gamma_desc,
        'macro_fundamental': '宏观基本面：以宏观财经快讯和成本链为主，暂不展示周频供需项。',
        'strategy_judgement': sections[-2],
        'narrative': narrative,
        'bullets': [f"GEX：{gamma_desc}", f"Pain：{pain_comment}", f"宏观：Brent{_fmt_num(brent.get('price'),2,'$')}"],
        'narrative_notes': narrative_notes,
        'market_snapshot_interpretation': market_snapshot_interpretation,
        'gex_interpretation': gex_interpretation,
        'oi_interpretation': oi_interpretation,
        'iv_interpretation': iv_interpretation,
        'macro_interpretation': macro_interpretation,
        'strategy_logic': strategy_logic,
        'market_snapshot_table': market_snapshot_table,
        'gex_table': gex_table,
        'pain_table': pain_table,
        'oi_tables': oi_tables,
        'iv_table': iv_table,
        'macro_table': macro_table,
        'chain_operation_snapshot': chain_operation_snapshot,
        'chain_operation_table': chain_operation_table,
        'macro_news_items': macro_news_items,
        'strategy_blocks': strategy_blocks,
        'key_levels': key_levels,
        'option_underlying_price': option_underlying_price,
        'main_futures_price': main_futures_price,
        'main_futures_symbol': main_symbol,
        'nature_synthesis': s1.get('nature_synthesis') or {},  # v2.11.63b+ 性质判定 × 合成信号（供前端渲染）
    }


def _safe_date_text(value=None) -> str:
    text = value or datetime.now().strftime('%Y%m%d')
    return ''.join(ch for ch in str(text) if ch.isdigit())[:8] or datetime.now().strftime('%Y%m%d')


def save_intraday_snapshot(report: Dict, now: Optional[datetime] = None) -> Optional[str]:
    """保存盘中15分钟研报快照，供收盘总研报聚合；非交易时段不写入。"""
    now = now or datetime.now()
    if not _is_pta_trading_session(now):
        return None
    date_text = now.strftime('%Y%m%d')
    slot_minute = (now.minute // 15) * 15
    slot = now.replace(minute=slot_minute, second=0, microsecond=0).strftime('%H%M')
    if not _slot_is_pta_trading_session(slot):
        return None
    day_dir = os.path.join(INTRADAY_REPORT_DIR, date_text)
    os.makedirs(day_dir, exist_ok=True)
    path = os.path.join(day_dir, f'{slot}.json')
    payload = dict(report or {})
    payload['snapshot_slot'] = slot
    payload['snapshot_time'] = now.strftime('%Y-%m-%d %H:%M:%S')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path



def load_intraday_snapshots(date_text: Optional[str] = None) -> List[Dict]:
    """读取某交易日盘中15分钟研报快照。"""
    date_text = _safe_date_text(date_text)
    day_dir = os.path.join(INTRADAY_REPORT_DIR, date_text)
    if not os.path.isdir(day_dir):
        return []
    snapshots = []
    for name in sorted(os.listdir(day_dir)):
        if not name.endswith('.json'):
            continue
        try:
            with open(os.path.join(day_dir, name), 'r', encoding='utf-8') as f:
                item = json.load(f)
                if _slot_is_pta_trading_session(item.get('snapshot_slot') or name[:4]):
                    snapshots.append(item)
        except Exception:
            continue
    return snapshots


def load_previous_trading_day_close_report(date_text: Optional[str] = None) -> Optional[Dict]:
    """读取前一交易日收盘研报，用于动态对比。"""
    base = datetime.strptime(_safe_date_text(date_text), '%Y%m%d')
    for i in range(1, 8):
        d = base - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        path = os.path.join(CLOSE_REPORT_DIR, f"daily_close_report_{d.strftime('%Y%m%d')}.json")
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return None
    return None


def build_daily_comparison(current_report: Dict, previous_report: Optional[Dict], intraday_snapshots: List[Dict]) -> Dict:
    """生成全天总研报的日内变化和前日对比,并明确数据覆盖度。

    PTA 交易日边界定义:一个完整交易日 = 前一日夜盘 21:00 开盘 → 当日日盘 15:00 收盘(夜盘 21:00-23:00 + 日盘 09:00-15:00)。
    intraday_review.open_slot 应取该交易日**第一段**(夜盘 21:00 槽或当日 09:00 槽),而非只看 09:00。
    previous_day_dynamic.previous_close_price 取**上一交易日日盘 15:00 收盘价**(=前一交易日 baseline)。
    """
    def pick_price(r):
        ia = (r or {}).get('intraday_analysis') or {}
        # v2.11.49: 主力研报口径只取 TA609 主力合约(K线 main_futures_price),禁止回退到
        #   TA608 期权链标的价(option_underlying_price)。两个合约价格差近百点,
        #   一旦混入会导致研报"日内走势"/"基差"价格全错。
        #   K线接口无价的槽位返回 None,build_daily_comparison 会自动跳过(points 不含该槽)。
        price = _as_float(ia.get('main_futures_price'))
        if price is None:
            return None
        return price

    def pick_slot(r):
        """优先取 intraday_analysis.snapshot_slot(15分钟槽),否则 intraday_snapshots[0].slot,否则空。"""
        ia = (r or {}).get('intraday_analysis') or {}
        slot = ia.get('snapshot_slot')
        if slot:
            return str(slot)
        snaps = (r or {}).get('intraday_snapshots') or []
        if snaps and isinstance(snaps[0], dict):
            return str(snaps[0].get('snapshot_slot') or snaps[0].get('slot') or '')
        return ''

    def pick_bias(r):
        ia = (r or {}).get('intraday_analysis') or {}
        text = ' '.join(str(x or '') for x in [
            ia.get('summary'), ia.get('market_snapshot_interpretation'), ia.get('strategy_logic')
        ])
        if any(x in text for x in ['偏强', '反弹', '上行', '多头', '利多']):
            return '偏强'
        if any(x in text for x in ['偏弱', '回落', '下行', '空头', '利空']):
            return '偏弱'
        return '震荡'

    snapshot_count = len(intraday_snapshots)
    slots = [x.get('snapshot_slot') for x in intraday_snapshots if x.get('snapshot_slot')]
    # v2.11.49+: PTA 交易日 = 前夜盘 21:00 → 当日 15:00。open_slot 必须从 points 里找第一个 21xx 槽
    #   (夜盘起点),不再取字典序 pts[0] (会落到日盘 0900)。
    def _resolve_open_slot(pts: List[Dict], current_report_slot: str = '') -> Optional[str]:
        if not pts:
            return None
        # 1) 优先看 current_report_slot 是否是夜盘(>=2100 且 <2400)
        if current_report_slot and current_report_slot.isdigit():
            s_int = int(current_report_slot)
            if 2100 <= s_int < 2400:
                return current_report_slot
        # 2) 从 points 里显式遍历找第一个 21xx 槽(夜盘起点)
        for p in pts:
            s = p.get('slot')
            if s and str(s).isdigit():
                s_int = int(s)
                if 2100 <= s_int < 2400:
                    return str(s)
        # 3) 兜底:用 pts[0] (日盘 0900)
        return pts[0].get('slot') if pts else None

    points = []
    for x in intraday_snapshots:
        price = pick_price(x)
        if price is None:
            continue
        points.append({
            'slot': x.get('snapshot_slot'),
            'time': x.get('snapshot_time') or x.get('timestamp'),
            'price': price,
            'bias': pick_bias(x),
            'summary': _clean_report_text(((x.get('intraday_analysis') or {}).get('summary') or x.get('narrative_report') or ''))[:160],
        })
    # v2.11.49+: points 按"夜盘优先 + 时间正序"双键排序。
    #   排序键:(夜盘0/日盘1, 槽位分钟数)。这样 pts[0]=2100 槽(夜盘起点),pts[-1]=日盘末槽或夜盘末槽;
    #   open_price/close_price 才能与 open_slot/close_slot 一一对应。
    def _slot_sort_key(slot):
        s = str(slot).zfill(4)
        try:
            minutes = int(s[:2]) * 60 + int(s[2:4])
        except Exception:
            return (1, 9999)
        if 21 * 60 <= minutes < 24 * 60:
            return (0, minutes)
        return (1, minutes)
    points = sorted(points, key=lambda p: _slot_sort_key(p.get('slot') or '9999'))
    prices = [x['price'] for x in points]
    cur_price = pick_price(current_report)
    # v2.11.47+: 日内比较应覆盖完整交易日(前一日 21:00 → 当日 15:00)。
    # 若当前报告的前夜盘有 slot,优先取夜盘开盘的 slot/price 作为 open;否则用日盘 09:00 槽。
    cur_slot = pick_slot(current_report)
    prev_price = pick_price(previous_report) if previous_report else None
    previous_day_available = previous_report is not None

    if snapshot_count >= 12:
        intraday_coverage_status = '完整'
        intraday_note = f'已归档{snapshot_count}份整15分钟盘中研报，可进行较完整的日内过程复盘。'
    elif snapshot_count >= 3:
        intraday_coverage_status = '部分'
        intraday_note = f'已归档{snapshot_count}份整15分钟盘中研报，只能做阶段性日内对比。'
    else:
        intraday_coverage_status = '样本不足'
        intraday_note = f'仅归档{snapshot_count}份整15分钟盘中研报，日内动态对比样本不足。'

    # 走势分桶：日内按 bias 切换点拆段；并定位 peak/trough
    def _swing_segments(pts):
        segs = []
        if not pts:
            return segs
        cur = {'from_slot': pts[0]['slot'], 'from_price': pts[0]['price'], 'bias': pts[0]['bias'], 'points': [pts[0]]}
        for p in pts[1:]:
            if p['bias'] == cur['bias']:
                cur['points'].append(p)
            else:
                cur['to_slot'] = cur['points'][-1]['slot']
                cur['to_price'] = cur['points'][-1]['price']
                cur['change'] = cur['to_price'] - cur['from_price']
                segs.append(cur)
                cur = {'from_slot': p['slot'], 'from_price': p['price'], 'bias': p['bias'], 'points': [p]}
        cur['to_slot'] = cur['points'][-1]['slot']
        cur['to_price'] = cur['points'][-1]['price']
        cur['change'] = cur['to_price'] - cur['from_price']
        segs.append(cur)
        return segs

    segments = _swing_segments(points)
    segment_summaries = []
    for seg in segments:
        if seg['from_slot'] == seg['to_slot']:
            continue
        seg_high = max(x['price'] for x in seg['points'])
        seg_low = min(x['price'] for x in seg['points'])
        segment_summaries.append({
            'from_slot': seg['from_slot'], 'to_slot': seg['to_slot'],
            'from_price': seg['from_price'], 'to_price': seg['to_price'],
            'change': seg['change'],
            'bias': seg['bias'],
            'high': seg_high, 'low': seg_low,
        })
    peak_pt = max(points, key=lambda x: x['price']) if points else None
    trough_pt = min(points, key=lambda x: x['price']) if points else None

    intraday_review = {
        'points': points,
        # v2.11.47+: 完整交易日 open 槽优先取夜盘(2100),否则日盘(0900)。
        # 若 current_report.snapshot_slot 是夜盘(如 21:00/21:15),用它作 open。
        'open_slot': _resolve_open_slot(points, cur_slot),
        'close_slot': points[-1]['slot'] if points else None,
        'open_price': points[0]['price'] if points else None,  # points 本身已按时间排序
        'close_price': points[-1]['price'] if points else cur_price,
        'high': max(prices) if prices else None,
        'low': min(prices) if prices else None,
        'change': (points[-1]['price'] - points[0]['price']) if len(points) >= 2 else None,
        'segments': segment_summaries,
        'peak': {'slot': peak_pt['slot'], 'price': peak_pt['price']} if peak_pt else None,
        'trough': {'slot': trough_pt['slot'], 'price': trough_pt['price']} if trough_pt else None,
        # v2.11.47+: 标注交易日边界
        'trading_day_window': '前夜盘 21:00 → 当日 15:00(夜盘 + 日盘)',
    }
    if intraday_review['change'] is not None:
        chg = intraday_review['change']
        direction = '走强' if chg > 0 else ('走弱' if chg < 0 else '横盘')
        # 主体句：开收对比 + 区间
        main = (
            f"盘中从{intraday_review['open_slot']}的{intraday_review['open_price']:.0f}"
            f"到{intraday_review['close_slot']}的{intraday_review['close_price']:.0f}，"
            f"日内{direction}{chg:+.0f}点，区间{intraday_review['low']:.0f}-{intraday_review['high']:.0f}"
        )
        # 走势分桶：描述每一段的方向和幅度
        seg_lines = []
        for seg in segment_summaries:
            seg_dir = '走强' if seg['change'] > 0 else ('走弱' if seg['change'] < 0 else '横盘')
            seg_lines.append(
                f"{seg['from_slot']}→{seg['to_slot']}{seg['bias']}{seg_dir}{seg['change']:+.0f}"
            )
        segments_text = '；'.join(seg_lines) if seg_lines else '未出现明显bias切换'
        # 高低点
        peak = intraday_review.get('peak') or {}
        trough = intraday_review.get('trough') or {}
        extreme_text = ''
        if peak.get('slot') and trough.get('slot') and peak['slot'] != trough['slot']:
            extreme_text = f"；高点{peak['slot']} {peak['price']:.0f}，低点{trough['slot']} {trough['price']:.0f}"
        intraday_review['summary'] = f"{main}。走势分桶：{segments_text}{extreme_text}。"
    else:
        intraday_review['summary'] = intraday_note

    if previous_day_available and prev_price is not None and cur_price is not None:
        day_change = cur_price - prev_price
        # v2.11.47+: summary 明确这是"上一交易日日盘 15:00 收盘基准"(PTA 交易日 = 前夜盘 21:00 → 当日 15:00,
        # 所以"上一交易日"指上一个完整交易日;6/17 报告里 prev_price=5830 是 6/16 15:00 收盘价,正确)
        day_note = f'较上一交易日日盘 15:00 收盘基准变化{day_change:+.0f}点。'
        previous_day_dynamic = {
            'previous_close_price': prev_price,
            'previous_close_label': '上一交易日日盘 15:00 收盘基准',
            'current_price': cur_price,
            'change': day_change,
            'bias_yesterday': pick_bias(previous_report),
            'bias_today': pick_bias(current_report),
            'summary': f'今日日盘 15:00 收盘参考价较上一交易日日盘 15:00 收盘基准{day_change:+.0f}点;昨日结构{pick_bias(previous_report)},今日结构{pick_bias(current_report)}。',
        }
    else:
        day_note = '前一交易日收盘研报暂缺,日间动态对比暂不能完整展开。'
        previous_day_dynamic = {
            'previous_close_price': prev_price,
            'previous_close_label': '上一交易日日盘 15:00 收盘基准',
            'current_price': cur_price,
            'change': None,
            'bias_yesterday': None,
            'bias_today': pick_bias(current_report),
            'summary': day_note,
        }

    comparison_quality = '完整' if intraday_coverage_status == '完整' and previous_day_available else ('部分' if snapshot_count >= 3 or previous_day_available else '样本不足')
    data_limitation_note = '' if comparison_quality == '完整' else f'{intraday_note}{day_note}'
    full_summary = f"全天共归档{snapshot_count}份15分钟研报；{intraday_review.get('summary')}{day_note}"

    return {
        'snapshot_count': snapshot_count,
        'intraday_slots': slots,
        'intraday_coverage_status': intraday_coverage_status,
        'previous_day_available': previous_day_available,
        'comparison_quality': comparison_quality,
        'data_limitation_note': data_limitation_note,
        'intraday_price_range': {'low': min(prices) if prices else None, 'high': max(prices) if prices else None},
        'current_vs_previous_price_change': (cur_price - prev_price) if cur_price is not None and prev_price is not None else None,
        'intraday_review': intraday_review,
        'previous_day_dynamic': previous_day_dynamic,
        'summary': full_summary,
    }


def generate_close_report(base_report: Optional[Dict] = None) -> Dict:
    """生成15:00收盘后的全天总研报，综合当日15分钟盘中研报并与前一交易日对比。"""
    report = dict(base_report) if base_report else generate_report(report_type='close')
    now = datetime.now()
    date_text = now.strftime('%Y%m%d')
    intraday_snapshots = load_intraday_snapshots(date_text)
    previous_report = load_previous_trading_day_close_report(date_text)
    previous_day_comparison = build_daily_comparison(report, previous_report, intraday_snapshots)
    report['timestamp'] = now.strftime('%Y-%m-%d %H:%M:%S')
    report['report_type'] = 'close'
    report['market_session'] = '收盘后'
    report['intraday_snapshots'] = [
        {
            'slot': x.get('snapshot_slot'),
            'time': x.get('snapshot_time') or x.get('timestamp'),
            'summary': _clean_report_text((x.get('intraday_analysis') or {}).get('summary') or x.get('narrative_report') or '')[:180],
            'option_underlying_price': (x.get('intraday_analysis') or {}).get('option_underlying_price'),
            'main_futures_price': (x.get('intraday_analysis') or {}).get('main_futures_price'),
        }
        for x in intraday_snapshots
    ]
    report['previous_day_comparison'] = previous_day_comparison
    report['close_summary'] = {
        'title': '15:00收盘后全天总研报',
        'generated_at': report['timestamp'],
        'summary': _clean_report_text(previous_day_comparison.get('summary')),
        'source_sections': ['日内15分钟研报快照', '期权GEX/OI/IV结构', '宏观财经快讯', '前一交易日收盘研报'],
    }
    # 对外返回前清理旧历史快照/前日缓存中可能残留的脏标题。
    report = json.loads(_clean_report_text(json.dumps(report, ensure_ascii=False)))
    return report


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
    inv_raw = s2.get('inventory', {})
    inv_summary = inv_raw.get('summary', '') if isinstance(inv_raw, dict) else ''
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
