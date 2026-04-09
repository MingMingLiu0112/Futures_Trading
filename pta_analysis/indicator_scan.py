"""
PTA期货 1-60分钟 MACD/KDJ/MACD面积 指标遍历
直接用requests拉新浪数据
"""
import requests, pandas as pd, json, re
from datetime import datetime

def get_1min_data(symbol='TA0', bars=800):
    """直接用requests获取新浪1分钟数据"""
    url = 'http://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData'
    params = {
        'symbol': 'nf_' + symbol,
        'scale': 1,
        'ma': 'no',
        'datalen': bars
    }
    resp = requests.get(url, params=params, timeout=10)
    data = resp.json()
    
    rows = []
    for item in data:
        rows.append({
            'datetime': item['d'],
            'open': float(item['o']),
            'high': float(item['h']),
            'low': float(item['l']),
            'close': float(item['c']),
            'volume': float(item['v'])
        })
    
    df = pd.DataFrame(rows)
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime').reset_index(drop=True)
    return df

def resample(df, period):
    df = df.set_index('datetime')
    resampled = df.resample(period).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last'
    }).dropna()
    return resampled.reset_index()

def calc_macd(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd = (dif - dea) * 2
    return dif, dea, macd

def calc_macd_area(macd):
    areas = []
    current_area = 0.0
    current_sign = 0
    bars_count = 0
    for val in macd:
        sign = 1 if val >= 0 else -1
        if sign == current_sign:
            current_area += float(val)
            bars_count += 1
        else:
            if current_sign != 0:
                areas.append({'sign': current_sign, 'area': round(current_area, 6), 'bars': bars_count})
            current_area = float(val)
            current_sign = sign
            bars_count = 1
    if current_sign != 0:
        areas.append({'sign': current_sign, 'area': round(current_area, 6), 'bars': bars_count})
    return areas

def calc_kdj(high, low, close, n=9, m1=3, m2=3):
    low_n = low.rolling(n).min()
    high_n = high.rolling(n).max()
    rsv = (close - low_n) / (high_n - low_n) * 100
    rsv = rsv.fillna(50)
    K = rsv.ewm(com=m1-1, adjust=False).mean()
    D = K.ewm(com=m2-1, adjust=False).mean()
    J = 3 * K - 2 * D
    return K, D, J

def analyze(df):
    close = df['close']
    dif, dea, macd = calc_macd(close)
    k, d, j = calc_kdj(df['high'], df['low'], close)
    areas = calc_macd_area(macd)
    last = df.iloc[-1]
    m = {'dif': round(float(dif.iloc[-1]), 4), 'dea': round(float(dea.iloc[-1]), 4), 'macd': round(float(macd.iloc[-1]), 4)}
    kj = {'K': round(float(k.iloc[-1]), 1), 'D': round(float(d.iloc[-1]), 1), 'J': round(float(j.iloc[-1]), 1)}
    return {'datetime': last['datetime'].strftime('%Y-%m-%d %H:%M'), 'close': round(float(last['close']), 0), 'bars': len(df), 'macd': m, 'kdj': kj, 'areas': areas[-3:]}

# 主程序
print("获取数据...")
df1 = get_1min_data('TA0', 800)
print("数据: %d根 %s ~ %s" % (len(df1), df1['datetime'].iloc[0].strftime('%m-%d %H:%M'), df1['datetime'].iloc[-1].strftime('%m-%d %H:%M')))
print("=" * 90)
print("%-6s | %-12s | %5s | %-25s | %s" % ("周期", "时间", "价格", "MACD(DIF/DEA/MACD/状态)", "KDJ(K/D/J)"))
print("-" * 90)

results = {}

for minute in range(1, 61):
    period = '%dT' % minute
    if minute == 1:
        df = df1
    else:
        df = resample(df1, period)
    
    if len(df) < 30:
        results[period] = {'period': period, 'error': '数据不足(%d根)' % len(df)}
        print("%-6s | 数据不足" % period)
        continue
    
    r = analyze(df)
    results[period] = r
    
    m = r['macd']
    kj = r['kdj']
    macd_state = '多头' if m['macd'] > 0 else '空头'
    macd_arrow = '▲' if m['macd'] > 0 else '▼'
    
    # 最新波段面积
    areas_str = ''
    if r['areas']:
        latest = r['areas'][-1]
        sign_str = '红' if latest['sign'] == 1 else '绿'
        areas_str = ' | 面积: %s%.4f(%d根)' % (sign_str, latest['area'], latest['bars'])
    
    print("[%2d分钟] %s | %5.0f | DIF:%8.4f DEA:%8.4f MACD:%8.4f %s[%s] | K:%5.1f D:%5.1f J:%6.1f%s" % (
        minute,
        r['datetime'][-5:],
        r['close'],
        m['dif'], m['dea'], m['macd'], macd_arrow, macd_state,
        kj['K'], kj['D'], kj['J'],
        areas_str
    ))

print("=" * 90)

# 保存
with open('indicator_results.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("已保存 indicator_results.json")
