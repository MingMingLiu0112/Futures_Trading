#!/usr/bin/env python3
"""S1扩展实验：阈值寻优 + 组合优化"""
import sys, os, sqlite3
sys.path.insert(0, 'backtest/strategy')
import importlib, numpy as np, pandas as pd
import option_oiwall_seller
importlib.reload(option_oiwall_seller)
from option_oiwall_seller import OptionOIWallSellerV4

DB = 'option_history.db'
conn = sqlite3.connect(DB)
cur = conn.cursor()
cur.execute('SELECT MIN(trade_date), MAX(trade_date) FROM option_daily')
min_d, max_d = cur.fetchone()
conn.close()

def run(name, modify):
    s = OptionOIWallSellerV4()
    modify(s)
    s.name = name
    df = s.run_backtest(min_d, max_d, initial=100_000)

    seller = [t for t in s.closed_trades if t.direction == 'sell']
    buyer  = [t for t in s.closed_trades if t.direction == 'buy']
    all_df = pd.DataFrame([{'pnl':t.pnl,'open':t.open_date} for t in s.closed_trades])

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
print("基准 S1（IV Rank<80%）")
print("=" * 90)
r0 = run("S1_IVRank<80基准", lambda s: setattr(s, 'iv_rank_filter', 0.80))
results.append(r0)

print("=" * 90)
print("阈值寻优：测试60%、70%、90%、95%")
print("=" * 90)
for thr in [0.60, 0.70, 0.90, 0.95]:
    r = run(f"S1_IVRank<{int(thr*100)}", lambda s, t=thr: setattr(s, 'iv_rank_filter', t))
    results.append(r)

print("=" * 90)
print("S1 + S4组合（IV Rank<80% + 密度加权）")
print("=" * 90)
r = run("S1+S4_IVRank+密度", lambda s: (
    setattr(s, 'iv_rank_filter', 0.80),
    setattr(s, 'density_weighted', True),
))
results.append(r)

print("=" * 90)
print("S1 + S3组合（IV Rank<80% + 买方优化）")
print("=" * 90)
r = run("S1+S3_IVRank+买方", lambda s: (
    setattr(s, 'iv_rank_filter', 0.80),
    setattr(s, 'buyer_profit_pct', 1.20),
    setattr(s, 'buyer_stop_loss_pct', 0.40),
    setattr(s, 'buyer_time_stop_days', 4),
    setattr(s, 'buyer_time_profit_pct', 1.10),
))
results.append(r)

print("=" * 90)
print("S1 + S3 + S4组合（IV Rank<80% + 买方优化 + 密度加权）")
print("=" * 90)
r = run("S1+S3+S4_全组合", lambda s: (
    setattr(s, 'iv_rank_filter', 0.80),
    setattr(s, 'density_weighted', True),
    setattr(s, 'buyer_profit_pct', 1.20),
    setattr(s, 'buyer_stop_loss_pct', 0.40),
    setattr(s, 'buyer_time_stop_days', 4),
    setattr(s, 'buyer_time_profit_pct', 1.10),
))
results.append(r)

# S1+S4 with 70%
print("=" * 90)
print("S1(70%) + S4组合（IV Rank<70% + 密度加权）")
print("=" * 90)
r = run("S1_70%+S4", lambda s: (
    setattr(s, 'iv_rank_filter', 0.70),
    setattr(s, 'density_weighted', True),
))
results.append(r)

# ===================== 汇总表 =====================
print()
print("=" * 110)
print("S1扩展实验综合对比总表")
print("=" * 110)
print(f"{'方案':<22} {'期末权益':>12} {'收益率':>8} {'夏普':>6} {'最大DD':>8} {'卖方均值':>8} {'买方均值':>9} {'DD止损':>6}")
print("-" * 110)
for r in results:
    print(f"{r['name']:<22} {r['equity']:>12,.0f} {r['ret']:>7.1f}% {r['sharpe']:>6.2f} "
          f"{r['max_dd']:>7.1f}% {r['seller_mean']:>8.0f} {r['buyer_mean']:>9.0f} {r['dd_stops']:>6}")
print("=" * 110)

best_eq  = max(results, key=lambda x: x['equity'])
best_sh  = max(results, key=lambda x: x['sharpe'])
best_dd  = min(results, key=lambda x: x['max_dd'])
print(f"\n🏆 收益最高:  {best_eq['name']} ({(best_eq['ret']):.1f}%，权益 {best_eq['equity']:,.0f})")
print(f"🏆 夏普最高:  {best_sh['name']} (夏普 {best_sh['sharpe']:.2f})")
print(f"🏆 回撤最低:  {best_dd['name']} (最大回撤 {best_dd['max_dd']:.1f}%)")

# 综合评分（标准化：夏普×0.4 + 收益×0.3 + 回撤控制×0.3）
print("\n综合评分（夏普40% + 收益30% + 回撤控制30%）：")
all_sharpe = [r['sharpe'] for r in results]
all_ret    = [r['ret']    for r in results]
all_dd     = [r['max_dd'] for r in results]
for r in results:
    s_norm = r['sharpe'] / max(all_sharpe)
    r_norm = r['ret']    / max(all_ret)
    dd_norm = 1 - r['max_dd'] / max(all_dd)  # 回撤越低越好
    score = s_norm * 0.4 + r_norm * 0.3 + dd_norm * 0.3
    print(f"  {r['name']:<22} 综合分={score:.3f} (夏普={s_norm:.2f} 收益={r_norm:.2f} 回撤={dd_norm:.2f})")