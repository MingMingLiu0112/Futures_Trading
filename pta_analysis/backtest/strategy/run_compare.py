#!/usr/bin/env python3
"""优化方案对比回测 - 逐方案独立运行 + 结果汇总"""
import sys, os, sqlite3, copy
sys.path.insert(0, 'backtest/strategy')
import importlib, numpy as np, pandas as pd
import option_oiwall_seller
importlib.reload(option_oiwall_seller)
from option_oiwall_seller import OptionOIWallSellerV4, OptionDataLoader, OIWallDetector

DB = 'option_history.db'
conn = sqlite3.connect(DB)
cur = conn.cursor()
cur.execute('SELECT MIN(trade_date), MAX(trade_date) FROM option_daily')
min_d, max_d = cur.fetchone()
conn.close()

def run(name, modify):
    """创建基准策略 → apply modify → run → return stats"""
    s = OptionOIWallSellerV4()
    modify(s)
    s.name = name
    df = s.run_backtest(min_d, max_d, initial=100_000)

    seller = [t for t in s.closed_trades if t.direction == 'sell']
    buyer  = [t for t in s.closed_trades if t.direction == 'buy']
    all_df = pd.DataFrame([{'pnl':t.pnl,'open':t.open_date,'exit':t.exit_reason} for t in s.closed_trades])

    fe = s.equity_curve[-1]['equity'] if s.equity_curve else 100_000
    cs = all_df.sort_values('open')['pnl'].cumsum() + 100_000
    peak = cs.iloc[0]; max_dd = 0
    for v in cs:
        if v > peak: peak = v
        dd = (peak - v) / peak * 100 if peak > 0 else 0
        if dd > max_dd: max_dd = dd

    grp = all_df.copy(); grp['month'] = grp['open'].str[:6]
    monthly = grp.groupby('month')['pnl'].sum()
    sharpe = monthly.mean() / monthly.std() * np.sqrt(12) if monthly.std() > 0 else 0

    dd_stops = sum(1 for t in s.closed_trades if 'global' in t.exit_reason)
    n_sell = len(seller); n_buy = len(buyer)
    sell_mean = np.mean([t.pnl for t in seller]) if seller else 0
    buy_mean  = np.mean([t.pnl for t in buyer])  if buyer  else 0

    print(f"  {name:<22} 权益={fe:>12,.0f} 收益={((fe-100000)/100000*100):>6.1f}% "
          f"夏普={sharpe:.2f} DD={max_dd:.1f}% 卖均值={sell_mean:>6.0f} 买均值={buy_mean:>6.0f} 止损={dd_stops}")

    return dict(name=name, equity=fe, ret=(fe-100000)/100000*100,
                sharpe=sharpe, max_dd=max_dd,
                seller_n=n_sell, seller_mean=sell_mean,
                buyer_n=n_buy,  buyer_mean=buy_mean,
                dd_stops=dd_stops)

results = []

print("=" * 90)
print("基准 v4.4")
print("=" * 90)
r0 = run("v4.4基准",       lambda s: None)
results.append(r0)

print("=" * 90)
print("S1: IV Rank过滤（IV Rank>80%时不追卖）")
print("=" * 90)
r1 = run("S1_IVRank<80",   lambda s: setattr(s, 'iv_rank_filter', 0.80))
results.append(r1)

print("=" * 90)
print("S2: 全局回撤止损收紧（10%→5%）")
print("=" * 90)
r2 = run("S2_5%DD止损",    lambda s: setattr(s, 'max_dd_stop_pct', 0.05))
results.append(r2)

print("=" * 90)
print("S3: 买方止盈止损优化（止盈130%→120%，止损50%→40%）")
print("=" * 90)
def apply_s3(s):
    s.buyer_profit_pct = 1.20
    s.buyer_stop_loss_pct = 0.40
    s.buyer_time_stop_days = 4
    s.buyer_time_profit_pct = 1.10
r3 = run("S3_买方优化",    apply_s3)
results.append(r3)

print("=" * 90)
print("S4: 墙密度加权仓位")
print("=" * 90)
r4 = run("S4_密度加权",    lambda s: setattr(s, 'density_weighted', True))
results.append(r4)

print("=" * 90)
print("S5: IV择时入场（IV不上升才开仓）")
print("=" * 90)
r5 = run("S5_IV择时入场",  lambda s: setattr(s, 'iv_entry_filter', 0.0))
results.append(r5)

print("=" * 90)
print("S6: 全组合（IV Rank<80% + 5%DD + 买方优化 + 密度加权 + IV择时）")
print("=" * 90)
def apply_s6(s):
    s.iv_rank_filter = 0.80
    s.max_dd_stop_pct = 0.05
    s.buyer_profit_pct = 1.20
    s.buyer_stop_loss_pct = 0.40
    s.buyer_time_stop_days = 4
    s.buyer_time_profit_pct = 1.10
    s.density_weighted = True
    s.iv_entry_filter = 0.0
r6 = run("S6_组合方案",   apply_s6)
results.append(r6)

# ===================== 汇总表 =====================
print()
print("=" * 110)
print("综合对比总表")
print("=" * 110)
print(f"{'方案':<22} {'期末权益':>12} {'收益率':>8} {'夏普':>6} {'最大DD':>8} {'卖方均值':>8} {'买方均值':>9} {'DD止损':>6}")
print("-" * 110)
for r in results:
    print(f"{r['name']:<22} {r['equity']:>12,.0f} {r['ret']:>7.1f}% {r['sharpe']:>6.2f} "
          f"{r['max_dd']:>7.1f}% {r['seller_mean']:>8.0f} {r['buyer_mean']:>9.0f} {r['dd_stops']:>6}")
print("=" * 110)

best_eq = max(results, key=lambda x: x['equity'])
best_sh = max(results, key=lambda x: x['sharpe'])
best_dd = min(results, key=lambda x: x['max_dd'])
print(f"\n🎯 收益最高:  {best_eq['name']} ({best_eq['ret']:.1f}%，权益 {best_eq['equity']:,.0f})")
print(f"🎯 夏普最高:  {best_sh['name']} (夏普 {best_sh['sharpe']:.2f})")
print(f"🎯 回撤最低:  {best_dd['name']} (最大回撤 {best_dd['max_dd']:.1f}%)")