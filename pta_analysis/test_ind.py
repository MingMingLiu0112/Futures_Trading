import akshare as ak, pandas as pd, numpy as np, warnings, json
from datetime import datetime
warnings.filterwarnings('ignore')

def get_1min_data(symbol='TA0', bars=800):
    df = ak.futures_zh_minute_sina(symbol=symbol, period='1')
    df.columns = [c.strip() for c in df.columns]
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime').tail(bars).reset_index(drop=True)
    return df

def resample(df, period='5T'):
    df = df.set_index('datetime')
    resampled = df.resample(period).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last'
    }).dropna()
    resampled = resampled.reset_index()
    return resampled

def calc_macd(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd = (dif - dea) * 2
    return dif, dea, macd

def calc_macd_area(macd_series):
    areas = []
    current_area = 0
    current_sign = 0
    bars_in_current = 0
    for i, val in enumerate(macd_series):
        sign = 1 if val >= 0 else -1
        if sign == current_sign:
            current_area += val
            bars_in_current += 1
        else:
            if current_sign != 0:
                areas.append({'sign': current_sign, 'area': round(current_area, 6), 'bars': bars_in_current})
            current_area = val
            current_sign = sign
            bars_in_current = 1
    if current_sign != 0:
        areas.append({'sign': current_sign, 'area': round(current_area, 6), 'bars': bars_in_current})
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

def analyze_period(df):
    close = df['close']
    dif, dea, macd = calc_macd(close)
    k, d, j = calc_kdj(df['high'], df['low'], close)
    areas = calc_macd_area(macd)
    last = df.iloc[-1]
    m = {'dif': round(float(dif.iloc[-1]), 4), 'dea': round(float(dea.iloc[-1]), 4), 'macd': round(float(macd.iloc[-1]), 4), 'state': '多头' if macd.iloc[-1] > 0 else '空头'}
    kj = {'K': round(float(k.iloc[-1]), 2), 'D': round(float(d.iloc[-1]), 2), 'J': round(float(j.iloc[-1]), 2)}
    return {'datetime': last['datetime'].strftime('%H:%M'), 'close': round(float(last['close']), 0), 'bars': len(df), 'macd': m, 'kdj': kj, 'areas': areas[-3:]}

periods = [('1分钟','1T'), ('5分钟','5T'), ('15分钟','15T'), ('30分钟','30T'), ('60分钟','60T')]
df1 = get_1min_data('TA0', 800)
print("Data loaded:", len(df1), "bars")
results = {}
for label, code in periods:
    df = df1 if code == '1T' else resample(df1, code)
    r = analyze_period(df)
    results[label] = r
    m = r['macd']
    kj = r['kdj']
    print(f"\n【{label}】{r['datetime']} 价格={r['close']:.0f} ({r['bars']}根)")
    print(f"  MACD: DIF={m['dif']:.4f} DEA={m['dea']:.4f} MACD={m['macd']:.4f} [{m['state']}]")
    print(f"  KDJ: K={kj['K']:.1f} D={kj['D']:.1f} J={kj['J']:.1f}")
    for i, a in enumerate(r['areas']):
        s = "红" if a['sign'] == 1 else "绿"
        print(f"  MACD面积{i+1}: {s} 面积={a['area']:.4f} {a['bars']}根")

with open('indicator_results.json', 'w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("\nSaved to indicator_results.json")
