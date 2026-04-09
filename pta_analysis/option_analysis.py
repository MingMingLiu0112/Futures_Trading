"""PTA期权分析模块 - OI最大TopN档位版"""
import re
from datetime import datetime, timedelta

def _s(x):
    m = re.search(r'[CP](\d+)', str(x))
    return int(m.group(1)) if m else None

def _t(x):
    return 'C' if 'C' in str(x) else 'P'

def _iv(x):
    try:
        return float(x)
    except:
        return None

def analyze(df, fp=7000, t=None):
    """期权分析：按OI最大取TopN档位，过滤极深度虚值"""
    df = df.copy()
    df['k'] = df['合约代码'].apply(_s)
    df['t'] = df['合约代码'].apply(_t)
    c = df[df['t'] == 'C'].copy()
    p = df[df['t'] == 'P'].copy()

    tcv = int(c['成交量(手)'].sum())
    tpv = int(p['成交量(手)'].sum())
    pcr = round(tpv / tcv, 4) if tcv > 0 else None

    # 成交量Top3（短期博弈焦点）
    t3c = [[str(r[0]), int(r[1]), int(r[2])] for r in c.nlargest(3, '成交量(手)')[['合约代码', 'k', '成交量(手)']].values.tolist()]
    t3p = [[str(r[0]), int(r[1]), int(r[2])] for r in p.nlargest(3, '成交量(手)')[['合约代码', 'k', '成交量(手)']].values.tolist()]

    cz = c[c['k'] > fp].copy()
    fz = p[p['k'] < fp].copy()

    # 过滤极深度虚值（地板>=fp*0.78，天花板<=fp*1.30）
    fz_eff = fz[fz['k'] >= fp * 0.78]
    cz_eff = cz[cz['k'] <= fp * 1.30]

    # 按OI排序取Top5(地板)/Top3(天花板)
    floor_top = fz_eff.nlargest(5, '持仓量')
    ceil_top = cz_eff.nlargest(3, '持仓量')

    # 构建楼层列表（每个档位取OI最大的合约）
    def build_level(zone_df, strikes_series, direction):
        result = []
        for _, row in strikes_series.items():
            k = int(row)
            sub = zone_df[zone_df['k'] == k]
            if sub.empty:
                continue
            oi_val = int(sub['持仓量'].sum())
            vol_val = int(sub['成交量(手)'].sum())
            top = sub.nlargest(1, '持仓量').iloc[0]
            iv_val = _iv(top['隐含波动率'])
            dist = k - fp
            if dist == 0:
                pos = 'ATM'
            elif dist > 0:
                pos = 'ATM+%d' % dist
            else:
                pos = 'ATM%d' % dist
            # 技术印证
            tl = ''
            if t:
                piv = t.get('pivots', {})
                if direction == 'floor':
                    if abs(k - piv.get('s2', 0)) <= 100:
                        tl = 'S2'
                    elif abs(k - piv.get('s1', 0)) <= 100:
                        tl = 'S1'
                else:
                    if abs(k - piv.get('r1', 0)) <= 100:
                        tl = 'R1'
            result.append({
                'strike': k, 'oi': oi_val, 'vol': vol_val,
                'code': str(top['合约代码']), 'top_oi': int(top['持仓量']),
                'iv': iv_val, 'position': pos, 'tech_label': tl
            })
        return result

    floor_lv = build_level(fz_eff, floor_top['k'], 'floor')
    ceil_lv = build_level(cz_eff, ceil_top['k'], 'ceil')

    ftot = sum(x['oi'] for x in floor_lv)
    ctot = sum(x['oi'] for x in ceil_lv)
    gr = round(ftot / ctot, 2) if ctot > 0 else None

    # IV曲面（ATM附近，正负3%）
    lo_iv, hi_iv = int(fp * 0.97), int(fp * 1.03)
    ac = c[(c['k'] >= lo_iv) & (c['k'] <= hi_iv)]
    ap = p[(p['k'] >= lo_iv) & (p['k'] <= hi_iv)]
    civ = round(float(ac['隐含波动率'].mean()), 1) if not ac.empty else None
    piv = round(float(ap['隐含波动率'].mean()), 1) if not ap.empty else None
    ivd = round(piv - civ, 1) if (civ and piv) else None

    # 评分
    sg = []
    ts, lb = 0, '期权中性'
    if gr:
        if gr > 2.0:
            ts = 2; lb = '强烈偏多'; sg.append('地板%d>天花板%d防%.2fx极强' % (ftot, ctot, gr))
        elif gr > 1.5:
            ts = 1; lb = '偏多'; sg.append('地板%d>天花板%d防%.2fx' % (ftot, ctot, gr))
        elif gr < 0.6:
            ts = -2; lb = '强烈偏空'
    if ivd:
        if ivd > 5:
            sg.append('IV差+%.1f%%恐慌底' % ivd)
        elif ivd < -5:
            sg.append('IV差%.1f%%狂热顶' % ivd)

    # 日间变化（按日期去重，每天只保留OI变化最大的合约）
    dc = []
    dates = sorted(df['日期'].unique(), reverse=True)[:5]
    for d in dates:
        ddf = df[df['日期'] == d].copy()
        ddc = ddc_oi = ddc_vol = None
        for _, row in ddf.iterrows():
            code = row['合约代码']
            oi_chg = int(row.get('持仓量变化', 0) or 0)
            vol_chg = int(row.get('成交量变化', 0) or 0)
            iv_now = _iv(row.get('隐含波动率'))
            if abs(oi_chg) >= 2000:
                if not ddc or abs(oi_chg) > abs(ddc['oi_chg']):
                    ddc = {'date': d, 'code': code, 'strike': int(row['k']),
                           'type': row['t'], 'oi_chg': oi_chg, 'vol_chg': vol_chg,
                           'iv_chg': None}
        if ddc:
            dc.append(ddc)

    return {
        'pcr': pcr, 'pcr_display': '%.2f' % pcr if pcr else 'N/A',
        't3c': t3c, 't3p': t3p,
        'floor_lv': floor_lv, 'ceil_lv': ceil_lv,
        'ftot': ftot, 'ctot': ctot, 'gr': gr,
        'civ': civ, 'piv': piv, 'ivd': ivd,
        'score': ts, 'label': lb,
        'detail': ';'.join(sg) if sg else '信息不足',
        'dc': dc, 'tech': t,
    }

def report(r, fp=7000):
    """完整报告"""
    if not r:
        return 'No data'

    lines = []
    lines.append('[期权] %s(%+d) PCR=%s' % (r['label'], r['score'], r.get('pcr_display', 'N/A')))
    lines.append('  短期博弈(成交量Top3):')
    for c in r.get('t3c', []):
        lines.append('    购 %s: %d手' % (c[0], c[2]))
    for p in r.get('t3p', []):
        lines.append('    沽 %s: %d手' % (p[0], p[2]))

    ftot = r.get('ftot', 0)
    ctot = r.get('ctot', 0)
    structure_clear = ftot + ctot > 100000
    cost_note = '' if structure_clear else '成本仅供参考'
    lines.append('  地板防线(OI=%d):%s' % (ftot, (' (' + cost_note + ')') if cost_note else ''))
    for lv in r.get('floor_lv', []):
        tl = (' ' + lv['tech_label']) if lv['tech_label'] else ''
        iv_str = ('IV=%.1f%%' % lv['iv']) if lv['iv'] is not None else ''
        lines.append('    P%d: OI=%d(V=%d,%s) [%s]%s' % (
            lv['strike'], lv['oi'], lv['vol'], iv_str, lv['position'], tl))

    lines.append('  天花板防线(OI=%d):' % ctot)
    for lv in r.get('ceil_lv', []):
        tl = (' ' + lv['tech_label']) if lv['tech_label'] else ''
        iv_str = ('IV=%.1f%%' % lv['iv']) if lv['iv'] is not None else ''
        lines.append('    C%d: OI=%d(V=%d,%s) [%s]%s' % (
            lv['strike'], lv['oi'], lv['vol'], iv_str, lv['position'], tl))

    lines.append('  梯度=%.2f IV:Call=%.1f%% Put=%.1f%% Diff=%.1f%% | %s' % (
        r.get('gr', 0) or 0, r.get('civ', 0) or 0, r.get('piv', 0) or 0, r.get('ivd', 0) or 0, r['detail']))

    if r.get('dc'):
        by_day = {}
        for c in r['dc']:
            day_key = c.get('date', c['code'])
            if day_key not in by_day or abs(c['oi_chg']) > abs(by_day[day_key]['oi_chg']):
                by_day[day_key] = c
        daily = sorted(by_day.values(), key=lambda x: x['oi_chg'], reverse=True)[:5]
        lines.append('  日间OI变化:')
        if daily:
            for c in daily:
                oi, vo, ivv = c['oi_chg'], c['vol_chg'], c['iv_chg']
                if abs(oi) >= 2000 or abs(vo) >= 5000 or (ivv is not None and abs(ivv) >= 0.5):
                    tag = '★' if (abs(oi) >= 10000 or abs(vo) >= 20000) else ''
                    lines.append('    %s(%s,行权价%d): OI%+d Vol%+d %s' % (
                        c['code'], c['type'], c['strike'], oi, vo, tag))
        else:
            lines.append('    (无显著日间变化)')

    return '\n'.join(lines)

# 测试
if __name__ == '__main__':
    import akshare as ak
    from datetime import datetime, timedelta
    now = datetime.now()
    for i in range(1, 8):
        d = (now - timedelta(days=i)).strftime('%Y%m%d')
        try:
            df = ak.option_hist_czce(symbol='PTA期权', trade_date=d)
            ta = df[df['合约代码'].str.startswith('TA605')].copy()
            if not ta.empty:
                ta['日期'] = d
                print('=' * 50)
                print('期权墙分析 %s' % d)
                print('=' * 50)
                r = analyze(ta, fp=7000)
                print(report(r, fp=7000))
                break
        except Exception as e:
            print('%s: %s' % (d, e))
