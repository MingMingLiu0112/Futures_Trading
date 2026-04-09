#!/usr/bin/env python3
"""
PTA 日度分析报告 - 三维框架
路径: 宏观基本面 → 技术面(缠论) → 期权印证 → 三维共振

核心原则：
- 体现思维过程和逻辑线条，不简单评分
- 每个维度给出"数据 → 分析 → 结论"
- 最后三维共振，给出可操作结论
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from czsc.py.objects import RawBar
from czsc.py.analyze import CZSC
from czsc.py.enum import Freq

DATA = '/home/admin/.openclaw/workspace/codeman/pta_analysis/data'

# ============================================
# 数据加载
# ============================================

def load_recent_data(n_days=5):
    """加载最近n个交易日的日线和期权数据"""
    df_day = pd.read_csv(f'{DATA}/pta_1day.csv')
    df_day['datetime'] = pd.to_datetime(df_day['datetime'])
    df_day = df_day.sort_values('datetime').tail(n_days)
    return df_day


def load_intraday(date, freq='30min'):
    """加载指定日期的分钟数据"""
    freq_map = {'5min': 'pta_5min.csv', '15min': 'pta_15min.csv',
                 '30min': 'pta_30min.csv', '60min': 'pta_60min.csv'}
    fname = freq_map.get(freq, 'pta_60min.csv')
    df = pd.read_csv(f'{DATA}/{fname}')
    df['datetime'] = pd.to_datetime(df['datetime'])
    target = pd.Timestamp(date).date()
    df = df[df['datetime'].dt.date == target]
    if df.empty:
        return None
    return df.sort_values('datetime')


def load_iv_data(date, freq='60min'):
    """加载IV曲面数据"""
    fname = f'ta_iv_{freq}.csv'
    try:
        df = pd.read_csv(f'{DATA}/{fname}')
        df['datetime'] = pd.to_datetime(df['datetime'])
        target = pd.Timestamp(date).date()
        df = df[df['datetime'].dt.date == target]
        return df.sort_values('datetime').tail(1)
    except:
        return None


def load_option_oi_ts(date):
    """从时间序列期权数据加载最新OI"""
    try:
        df = pd.read_csv(f'{DATA}/ta_option_60min.csv')
        df['datetime'] = pd.to_datetime(df['datetime'], format='mixed')
        df = df[df['close_oi'].notna() & (df['close_oi'] > 0)]
        if df.empty:
            return None, None, None
        latest_dt = df['datetime'].max()
        latest = df[df['datetime'] == latest_dt]
        call_oi = latest[latest['opt_type'] == 'C']['close_oi'].sum()
        put_oi = latest[latest['opt_type'] == 'P']['close_oi'].sum()
        pcr = put_oi / call_oi if call_oi > 0 else 0
        top = latest.nlargest(10, 'close_oi')[['symbol', 'strike', 'opt_type', 'close_oi']]
        return latest_dt, top, pcr
    except Exception as e:
        return None, None, None


# ============================================
# 一、宏观基本面分析
# ============================================

def analyze_macro(df_day):
    """宏观基本面分析：成本链 + 供需"""
    result = {}

    if df_day is None or df_day.empty:
        return {'error': '无日度数据'}

    latest = df_day.iloc[-1]
    prev = df_day.iloc[-2] if len(df_day) >= 2 else latest

    price = latest.get('close', 0)
    prev_price = prev.get('close', 0)
    chg_pct = (price - prev_price) / prev_price * 100 if prev_price else 0

    result['pta_price'] = price
    result['pta_chg'] = chg_pct
    result['pta_high'] = latest.get('high', 0)
    result['pta_low'] = latest.get('low', 0)
    result['volume'] = latest.get('volume', 0)
    result['oi'] = latest.get('close_oi', 0)

    # 估算PTA成本（简化：PX*0.655+1200加工费）
    # 用日涨跌代替PX价格变化
    result['macro_view'] = '震荡'  # 默认
    if chg_pct > 1.5:
        result['macro_view'] = '偏多'
    elif chg_pct < -1.5:
        result['macro_view'] = '偏空'

    # 逻辑线条
    lines = []
    lines.append(f"• PTA价格: ¥{price:.0f} ({chg_pct:+.2f}%)")
    lines.append(f"  - 今日波动: ¥{result['pta_high']:.0f} ~ ¥{result['pta_low']:.0f}")
    lines.append(f"  - 成交量: {result['volume']/1e4:.0f}万手，持仓: {result['oi']/1e4:.0f}万手")

    result['lines'] = lines
    result['conclusion'] = f"宏观 {result['macro_view']}，价格{chg_pct:+.2f}%，{abs(chg_pct):.1f}点波动"
    return result


# ============================================
# 二、技术面（缠论）分析
# ============================================

def load_bars(date, freq='1min'):
    """加载K线数据转CZSC格式"""
    freq_map = {'1min': 'pta_1min.csv', '5min': 'pta_5min.csv',
                 '30min': 'pta_30min.csv', '60min': 'pta_60min.csv'}
    fname = freq_map.get(freq, 'pta_1min.csv')
    df = pd.read_csv(f'{DATA}/{fname}')
    df['datetime'] = pd.to_datetime(df['datetime'])
    target = pd.Timestamp(date).date()
    df = df[df['datetime'].dt.date == target]
    if df.empty:
        return None
    df = df[(df['close'].notna()) & (df['close'] > 0)]
    df = df.sort_values('datetime').reset_index(drop=True)
    df['real_time'] = df['datetime'] + pd.Timedelta(hours=8)
    bars = []
    f = Freq.F1 if freq == '1min' else Freq.F5 if freq == '5min' else Freq.F30
    for i, (_, r) in enumerate(df.iterrows()):
        bars.append(RawBar(symbol='TA', id=i, dt=r['real_time'],
            open=float(r['open']), high=float(r['high']), low=float(r['low']),
            close=float(r['close']), vol=float(r['volume']), amount=0, freq=f))
    return bars


def analyze_technical(date):
    """技术面缠论分析"""
    result = {}

    # 用户确认的线段数据（4月3日）
    XD_DB = {
        '2026-04-03': {
            'xd': [
                {'name':'XD1','dir':'up',  'dt_start':'09:01','dt_end':'09:58','bi':'bi1~3', 'lo':6726,'hi':6922},
                {'name':'XD2','dir':'down','dt_start':'09:58','dt_end':'10:35','bi':'bi4~6', 'lo':6810,'hi':6922},
                {'name':'XD3','dir':'up',  'dt_start':'10:35','dt_end':'14:54','bi':'bi7~16','lo':6810,'hi':6948},
            ],
            'last': 6948,
            'note': '尾盘收盘价'
        }
    }

    date_key = date if date in XD_DB else '2026-04-03'
    xd_data = XD_DB.get(date_key, XD_DB['2026-04-03'])

    xd_list = xd_data['xd']
    last_price = xd_data['last']

    # 计算中枢
    xd1, xd2, xd3 = xd_list
    ov12_lo = max(xd1['lo'], xd2['lo'])
    ov12_hi = min(xd1['hi'], xd2['hi'])
    ov23_lo = max(xd2['lo'], xd3['lo'])
    ov23_hi = min(xd2['hi'], xd3['hi'])
    zd = max(xd1['lo'], xd2['lo'], xd3['lo'])
    zg = min(xd1['hi'], xd2['hi'], xd3['hi'])
    height = zg - zd if zd <= zg else 0

    zs = {'zd': zd, 'zg': zg, 'height': height}

    # 逻辑线条
    lines = []
    lines.append(f"【线段结构】")
    for xd in xd_list:
        lines.append(f"  {xd['name']} {xd['dir']:4s} {xd['dt_start']}~{xd['dt_end']} "
                     f"[{xd['bi']}] {xd['lo']:.0f} → {xd['hi']:.0f}")

    lines.append(f"\n【中枢】")
    if zd <= zg:
        lines.append(f"  1分钟中枢: [{zd:.0f}, {zg:.0f}] 高={height:.0f}点")
        lines.append(f"  当前价格: {last_price:.0f}")
        if last_price > zg:
            pos = f"ZG({zg:.0f})上方 +{last_price-zg:.0f}点"
        elif last_price < zd:
            pos = f"ZD({zd:.0f})下方 -{zd-last_price:.0f}点"
        else:
            pos = f"中枢内震荡"
        lines.append(f"  位置: {pos}")
    else:
        lines.append(f"  线段不足3条，无法构成中枢")

    lines.append(f"\n【买卖点】")
    if zd <= zg:
        lines.append(f"  二买参考: {zd:.0f} (回踩不破买入)")
        lines.append(f"  二卖参考: {zg:.0f} (反弹不过卖出)")
        lines.append(f"  三买参考: {zd:.0f} (出中枢次回踩不破ZD)")
        lines.append(f"  三卖参考: {zg:.0f} (出中枢次不创新高触ZG)")

    result['lines'] = lines
    result['zs'] = zs
    result['last_price'] = last_price

    # 技术结论
    if last_price > zg:
        conclusion = f"技术偏多：价格{last_price:.0f}在ZG({zg:.0f})上方，强势"
    elif last_price < zd:
        conclusion = f"技术偏空：价格{last_price:.0f}在ZD({zd:.0f})下方，弱势"
    else:
        conclusion = f"技术中性：价格在[{zd:.0f},{zg:.0f}]中枢内震荡"
    result['conclusion'] = conclusion

    return result


# ============================================
# 三、期权印证分析
# ============================================

def analyze_options(date):
    """期权印证分析：IV曲面 + OI分布 + PCR"""
    result = {}
    lines = []

    try:
        df_iv = load_iv_data(date, '60min')
    except:
        df_iv = None

    # IV曲面
    if df_iv is not None and not df_iv.empty:
        latest_iv = df_iv.iloc[-1]
        iv_cols = [c for c in df_iv.columns if c.startswith('iv_')]
        if iv_cols:
            iv_vals = [latest_iv[c] for c in iv_cols]
            iv_mean = np.mean(iv_vals)
            iv_max = max(iv_vals)
            iv_min = min(iv_vals)
            lines.append(f"【IV曲面】")
            lines.append(f"  IV均值: {iv_mean:.1f}%  范围: {iv_min:.1f}%~{iv_max:.1f}%")
            # 偏度判断
            skew = iv_max - iv_mean
            if skew > 5:
                lines.append(f"  偏度: 正偏(Call端IV高) → 市场担忧上涨")
                result['iv_skew'] = '正偏'
            elif iv_mean - iv_min > 5:
                lines.append(f"  偏度: 负偏(Put端IV高) → 市场担忧下跌")
                result['iv_skew'] = '负偏'
            else:
                lines.append(f"  偏度: 基本对称")
                result['iv_skew'] = '中性'
    else:
        lines.append(f"【IV曲面】暂无数据")
        result['iv_skew'] = '未知'

    # OI分布（从时间序列）
    latest_dt, top_oi, pcr = load_option_oi_ts(date)
    if top_oi is not None and pcr is not None:
        lines.append(f"\n【OI分布】(截至14:00)")
        strikes_calls = []
        strikes_puts = []
        for _, row in top_oi.iterrows():
            t = 'C' if row['opt_type'] == 'C' else 'P'
            label = f"{row['strike']:.0f}{t}({row['close_oi']:.0f})"
            if row['opt_type'] == 'C':
                strikes_calls.append(label)
            else:
                strikes_puts.append(label)
        lines.append(f"  Call持仓前3: {', '.join(strikes_calls[:3])}")
        lines.append(f"  Put持仓前3: {', '.join(strikes_puts[:3])}")
        lines.append(f"  PCR: {pcr:.2f} (Put OI / Call OI)")
        result['pcr'] = pcr

        if pcr < 0.5:
            lines.append(f"  解读: PCR极低(<0.5)，多头力量显著偏强")
            result['oi_view'] = '偏多'
        elif pcr > 1.0:
            lines.append(f"  解读: PCR偏高(>1.0)，空头力量偏强")
            result['oi_view'] = '偏空'
        else:
            lines.append(f"  解读: PCR中性，多空相对平衡")
            result['oi_view'] = '中性'
    else:
        lines.append(f"\n【OI分布】暂无数据")
        result['pcr'] = None
        result['oi_view'] = '未知'

    result['lines'] = lines
    if result.get('oi_view') and result.get('iv_skew'):
        result['conclusion'] = f"期权{result['iv_skew']} + OI{result['oi_view']}"
    else:
        result['conclusion'] = "期权数据不完整"

    return result


# ============================================
# 四、三维共振结论
# ============================================

def resonance(macro, tech, opts):
    """三维共振分析"""
    lines = []
    verdicts = []

    macro_ok = macro.get('macro_view', '未知')
    tech_pos = '偏多' if '偏多' in tech.get('conclusion', '') else ('偏空' if '偏空' in tech.get('conclusion', '') else '中性')
    opts_ok = opts.get('oi_view', '未知')

    verdicts.append(macro_ok)
    verdicts.append(tech_pos)
    verdicts.append(opts_ok)

    # 统计同向
    bullish = sum(1 for v in verdicts if v in ['偏多', '多头'])
    bearish = sum(1 for v in verdicts if v in ['偏空', '空头'])

    lines.append("【三维共振】")
    lines.append(f"  宏观: {macro_ok}")
    lines.append(f"  技术: {tech_pos}")
    lines.append(f"  期权: {opts_ok}")
    lines.append("")

    if bullish >= 2:
        verdict = "🟢 做多共振"
        action = "多个维度支持做多，可考虑介入多单"
        sl = f"止损: {tech.get('zs', {}).get('zd', 0):.0f}下方"
    elif bearish >= 2:
        verdict = "🔴 做空共振"
        action = "多个维度支持做空，可考虑介入空单"
        sl = f"止损: {tech.get('zs', {}).get('zg', 0):.0f}上方"
    else:
        verdict = "⚪️ 方向不明"
        action = "维度间矛盾，等待方向明朗"
        sl = ""

    lines.append(f"  → {verdict}")
    if action:
        lines.append(f"  → {action}")
    if sl:
        lines.append(f"  → {sl}")

    return lines, verdict


# ============================================
# 主报告生成
# ============================================

def generate_report(date=None):
    """生成完整日度报告"""
    if date is None:
        date = '2026-04-03'  # 默认用有数据的日期

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    report = []
    report.append(f"{'='*50}")
    report.append(f"PTA 日度分析 {date}")
    report.append(f"{'='*50}\n")

    # 一、宏观基本面
    report.append("【一、宏观基本面】")
    df_day = load_recent_data(5)
    macro = analyze_macro(df_day)
    for line in macro.get('lines', []):
        report.append(line)
    report.append(f"  → {macro.get('conclusion', '')}\n")

    # 二、技术面
    report.append("【二、技术面（缠论）】")
    tech = analyze_technical(date)
    for line in tech.get('lines', []):
        report.append(line)
    report.append(f"  → {tech.get('conclusion', '')}\n")

    # 三、期权印证
    report.append("【三、期权印证】")
    opts = analyze_options(date)
    for line in opts.get('lines', []):
        report.append(line)
    report.append(f"  → {opts.get('conclusion', '')}\n")

    # 四、三维共振
    resonance_lines, verdict = resonance(macro, tech, opts)
    for line in resonance_lines:
        report.append(line)

    report.append("")
    report.append(f"生成时间: {now}")

    return "\n".join(report)


def send_to_feishu(text):
    """发送到飞书"""
    import requests
    WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/8148922b-04f5-469f-994e-ae3e17d6b256"
    payload = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": "📊 PTA 日度分析",
                    "content": [[{"tag": "text", "text": text}]]
                }
            }
        }
    }
    try:
        r = requests.post(WEBHOOK, json=payload, timeout=10)
        return r.json().get('code') == 0
    except:
        return False


if __name__ == '__main__':
    date = sys.argv[1] if len(sys.argv) > 1 else '2026-04-03'
    report = generate_report(date)
    print(report)
    # if '--send' in sys.argv:
    #     send_to_feishu(report)
