#!/usr/bin/env python3
"""
Walk-Forward 滚动验证：等长窗口，多轮回测
- 窗口长度：252交易日（约1年）
- 步进长度：63交易日（约1季度）
- 初始窗口：20220104起，20220104+252天→20230103
- 滚动：每轮向前63天，共5轮
"""
import sys, os, sqlite3
sys.path.insert(0, 'backtest/strategy')
import importlib, numpy as np, pandas as pd
import option_oiwall_seller
importlib.reload(option_oiwall_seller)
from option_oiwall_seller import OptionOIWallSellerV4, OptionDataLoader

DB = 'option_history.db'
conn = sqlite3.connect(DB)
cur = conn.cursor()
cur.execute('SELECT MIN(trade_date), MAX(trade_date) FROM option_daily')
full_min, full_max = cur.fetchone()
cur.execute('SELECT COUNT(DISTINCT trade_date) FROM option_daily')
total_days = cur.fetchone()[0]
conn.close()

# -------- 窗口参数 --------
WINDOW = 252   # 训练/测试窗口长度（交易日）
STEP   = 63    # 步进长度（交易日）
INIT_OFFSET = WINDOW  # 初始窗口后才开始第一轮测试

# -------- 生成滚动窗口 --------
trade_dates_all = []
conn = sqlite3.connect(DB)
cur = conn.cursor()
cur.execute('SELECT DISTINCT trade_date FROM option_daily ORDER BY trade_date')
all_td = [r[0] for r in cur.fetchall()]
conn.close()

print(f"总数据：{full_min} ~ {full_max}，共{total_days}个交易日")
print(f"窗口{WINDOW}天，步进{STEP}天")
print()

# 计算各轮窗口
rounds = []
offset = WINDOW  # 第0轮：offset=252，测试[252:252+STEP]
while offset + STEP <= total_days:
    train_start_i = offset - WINDOW
    train_end_i   = offset - 1
    test_start_i  = offset
    test_end_i    = offset + STEP - 1
    train_start = all_td[train_start_i]
    train_end   = all_td[train_end_i]
    test_start  = all_td[test_start_i]
    test_end    = all_td[test_end_i]
    rounds.append({
        'round': len(rounds),
        'train_start': train_start, 'train_end': train_end,
        'test_start': test_start,  'test_end': test_end,
        'train_n': WINDOW, 'test_n': STEP
    })
    offset += STEP

print(f"共 {len(rounds)} 轮滚动验证：")
for r in rounds:
    print(f"  第{r['round']}轮: 训练={r['train_start']}~{r['train_end']} "
          f"({r['train_n']}日) | 测试={r['test_start']}~{r['test_end']} ({r['test_n']}日)")
print()

# -------- 方案定义 --------
SCHEMES = [
    ("v4.4基准",       lambda s: None),
    ("S1_IVRank<80",  lambda s: setattr(s, 'iv_rank_filter', 0.80)),
    ("S2_5%DD止损",   lambda s: setattr(s, 'max_dd_stop_pct', 0.05)),
    ("S3_买方优化",    lambda s: (
        setattr(s, 'buyer_profit_pct', 1.20),
        setattr(s, 'buyer_stop_loss_pct', 0.40),
        setattr(s, 'buyer_time_stop_days', 4),
        setattr(s, 'buyer_time_profit_pct', 1.10),
    )),
    ("S4_密度加权",    lambda s: setattr(s, 'density_weighted', True)),
    ("S5_IV择时入场",  lambda s: setattr(s, 'iv_entry_filter', 0.0)),
    ("S6_组合方案",    lambda s: (
        setattr(s, 'iv_rank_filter', 0.80),
        setattr(s, 'max_dd_stop_pct', 0.05),
        setattr(s, 'buyer_profit_pct', 1.20),
        setattr(s, 'buyer_stop_loss_pct', 0.40),
        setattr(s, 'buyer_time_stop_days', 4),
        setattr(s, 'buyer_time_profit_pct', 1.10),
        setattr(s, 'density_weighted', True),
        setattr(s, 'iv_entry_filter', 0.0),
    )),
]

# -------- 单轮回测函数 --------
def run_single(start, end, modify_fn, scheme_name):
    """在指定区间运行策略"""
    s = OptionOIWallSellerV4()
    modify_fn(s)
    s.name = scheme_name
    try:
        df = s.run_backtest(start, end, initial=100_000)
    except Exception as e:
        return None, str(e)

    if not s.equity_curve:
        return None, "无权益曲线"

    fe = s.equity_curve[-1]['equity']
    ret = (fe - 100_000) / 100_000 * 100

    # 最大回撤
    curve = pd.DataFrame(s.equity_curve)
    cs = curve['equity'].cummax()
    dd = (cs - curve['equity']) / cs * 100
    max_dd = dd.max()

    # 夏普（月度）
    all_df = pd.DataFrame([{'pnl': t.pnl, 'open': t.open_date} for t in s.closed_trades])
    if len(all_df) >= 2:
        grp = all_df.copy()
        grp['month'] = grp['open'].str[:6]
        monthly = grp.groupby('month')['pnl'].sum()
        sharpe = monthly.mean() / monthly.std() * np.sqrt(12) if monthly.std() > 0 else 0
    else:
        sharpe = 0

    n_trades = len(s.closed_trades)
    seller = [t for t in s.closed_trades if t.direction == 'sell']
    buyer  = [t for t in s.closed_trades if t.direction == 'buy']
    sell_mean = np.mean([t.pnl for t in seller]) if seller else 0
    buy_mean  = np.mean([t.pnl for t in buyer])  if buyer  else 0

    return {
        'scheme': scheme_name,
        'train_start': start, 'train_end': end,
        'equity': fe, 'ret': ret, 'sharpe': sharpe,
        'max_dd': max_dd, 'n_trades': n_trades,
        'seller_n': len(seller), 'seller_mean': sell_mean,
        'buyer_n': len(buyer),  'buyer_mean': buy_mean,
    }, None

# -------- 逐轮运行 --------
print("=" * 80)
print("Walk-Forward 滚动回测开始")
print("=" * 80)

all_results = []   # {scheme_name: {round_i: result}}
scheme_names = [s[0] for s in SCHEMES]
for name in scheme_names:
    all_results.append({'scheme': name, 'rounds': {}})

for rnd in rounds:
    print(f"\n{'='*60}")
    print(f"第{rnd['round']}轮 | 训练={rnd['train_start']}~{rnd['train_end']} | 测试={rnd['test_start']}~{rnd['test_end']}")
    print(f"{'='*60}")

    for (name, modify_fn), result_dict in zip(SCHEMES, all_results):
        r, err = run_single(rnd['test_start'], rnd['test_end'], modify_fn, name)
        if r:
            r['round'] = rnd['round']
            r['train_start'] = rnd['train_start']
            r['train_end']   = rnd['train_end']
            result_dict['rounds'][rnd['round']] = r
            print(f"  {name:<18} 权益={r['equity']:>11,.0f} 收益={r['ret']:>6.1f}% "
                  f"夏普={r['sharpe']:.2f} DD={r['max_dd']:.1f}% 卖={r['seller_n']:>3}笔 均值={r['seller_mean']:>6.0f}")
        else:
            result_dict['rounds'][rnd['round']] = None
            print(f"  {name:<18} ❌ {err}")

# -------- 汇总统计 --------
print()
print("=" * 110)
print("Walk-Forward 各轮 OOS（Out-of-Sample）表现汇总")
print("=" * 110)
print(f"{'方案':<20} | {'R0_equity':>11} | {'R0_ret':>7} | {'R1_equity':>11} | {'R1_ret':>7} | "
      f"{'R2_equity':>11} | {'R2_ret':>7} | {'R3_equity':>11} | {'R3_ret':>7} | {'R4_equity':>11} | {'R4_ret':>7}")
print("-" * 110)

summary_rows = []
for result_dict in all_results:
    name = result_dict['scheme']
    vals = []
    for ri in range(len(rounds)):
        r = result_dict['rounds'].get(ri)
        if r:
            vals.extend([r['equity'], r['ret']])
        else:
            vals.extend([None, None])
    summary_rows.append((name, vals))

for name, vals in summary_rows:
    line = f"{name:<20} |"
    for i, v in enumerate(vals):
        if v is None:
            line += f" {'N/A':>11} | {'—':>7} |"
        else:
            line += f" {v:>11,.0f} | {vals[i+1]:>6.1f}% |"
    print(line.rstrip(' |'))

# 汇总表（均值）
print()
print("=" * 100)
print("OOS 汇总统计（各轮等权平均）")
print("=" * 100)
print(f"{'方案':<20} {'OOS均值_收益':>12} {'OOS均值_夏普':>12} {'OOS均值_DD':>10} "
      f"{'OOS胜率':>8} {'OOS总权益':>12} {'OOS夏普':>8} {'OOS最大DD':>10} {'OOS卖方均值':>10}")
print("-" * 100)

best_oos_eq_scheme = None
best_oos_sh_scheme = None
best_oos_dd_scheme = None

for result_dict in all_results:
    name = result_dict['scheme']
    rs = [result_dict['rounds'][ri] for ri in range(len(rounds)) if result_dict['rounds'].get(ri)]

    if not rs:
        print(f"{name:<20} 数据不足")
        continue

    oos_eq_mean = np.mean([r['equity'] for r in rs])
    oos_sh_mean = np.mean([r['sharpe'] for r in rs])
    oos_dd_mean = np.mean([r['max_dd'] for r in rs])

    # OOS内有多少轮跑赢基准
    base_rs = result_dict['rounds']
    # 汇总值
    oos_total_eq = np.prod([r['equity'] / 100_000 for r in rs]) ** (1/len(rs))  # 几何平均权益因子
    oos_sharpe   = np.mean([r['sharpe'] for r in rs])
    oos_max_dd   = np.max([r['max_dd'] for r in rs])
    oos_sell_mean = np.mean([r['seller_mean'] for r in rs if r['seller_mean'] != 0])
    oos_win_rate = sum(1 for r in rs if r['ret'] > 0) / len(rs) * 100

    print(f"{name:<20} {oos_eq_mean:>12,.0f} {oos_sh_mean:>12.2f} {oos_dd_mean:>10.1f}% "
          f"{oos_win_rate:>7.0f}% {'':<5}{'':>6}{'':>6}"
          f"几何因子={oos_total_eq:.3f} 夏普={oos_sharpe:.2f} DD={oos_max_dd:.1f}% 均值={oos_sell_mean:>6.0f}")

    if best_oos_eq_scheme is None or oos_eq_mean > all_results[scheme_names.index(best_oos_eq_scheme)]['mean_eq']:
        best_oos_eq_scheme = name
    if best_oos_sh_scheme is None or oos_sh_mean > all_results[scheme_names.index(best_oos_sh_scheme)]['mean_sh']:
        best_oos_sh_scheme = name
    if best_oos_dd_scheme is None or oos_dd_mean < all_results[scheme_names.index(best_oos_dd_scheme)]['mean_dd']:
        best_oos_dd_scheme = name

# -------- IS vs OOS 对比 --------
print()
print("=" * 100)
print("IS（全区间）vs OOS（滚动均值）对比")
print("=" * 100)

# 先跑全区间
print("\n正在计算全区间IS结果...")
full_results = {}
for name, modify_fn in SCHEMES:
    s = OptionOIWallSellerV4()
    modify_fn(s)
    s.name = name
    df = s.run_backtest(full_min, full_max, initial=100_000)
    fe = s.equity_curve[-1]['equity']
    all_df = pd.DataFrame([{'pnl': t.pnl, 'open': t.open_date} for t in s.closed_trades])
    curve = pd.DataFrame(s.equity_curve)
    cs = curve['equity'].cummax()
    dd = (cs - curve['equity']) / cs * 100
    max_dd = dd.max()
    grp = all_df.copy(); grp['month'] = grp['open'].str[:6]
    monthly = grp.groupby('month')['pnl'].sum()
    sharpe = monthly.mean() / monthly.std() * np.sqrt(12) if monthly.std() > 0 else 0
    full_results[name] = {'equity': fe, 'sharpe': sharpe, 'max_dd': max_dd}

print(f"\n{'方案':<20} {'IS_收益':>10} {'IS_夏普':>8} {'IS_DD':>8} | "
      f"{'OOS_收益均值':>12} {'OOS_夏普均值':>12} {'OOS_DD均值':>10} | {'IS-OOS收益gap':>12} {'gap%':>6}")
print("-" * 100)

for result_dict in all_results:
    name = result_dict['scheme']
    rs = [result_dict['rounds'][ri] for ri in range(len(rounds)) if result_dict['rounds'].get(ri)]
    if not rs:
        continue
    oos_eq = np.mean([r['equity'] for r in rs])
    oos_sh = np.mean([r['sharpe'] for r in rs])
    oos_dd = np.mean([r['max_dd'] for r in rs])
    fi = full_results.get(name, {})
    is_eq = fi.get('equity', 0)
    is_sh = fi.get('sharpe', 0)
    is_dd = fi.get('max_dd', 0)
    gap   = is_eq - oos_eq
    gap_pct = (is_eq - oos_eq) / oos_eq * 100 if oos_eq > 0 else 0
    print(f"{name:<20} {is_eq:>10,.0f} {is_sh:>8.2f} {is_dd:>7.1f}% | "
          f"{oos_eq:>12,.0f} {oos_sh:>12.2f} {oos_dd:>9.1f}% | "
          f"{gap:>12,.0f} {gap_pct:>5.1f}%")

print()
print("=" * 100)
print("稳健性结论")
print("=" * 100)
print("""
评估维度：
1. OOS胜率：各轮中跑赢基准的频率
2. IS vs OOS gap：检验过拟合程度（gap<20%为可接受）
3. OOS夏普：去掉单期噪声后的真实夏普
4. OOS最大DD：极端情况下的最大回撤
""")