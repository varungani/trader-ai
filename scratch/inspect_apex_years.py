import os, sys, pickle, math
from collections import Counter
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scratch.test_compounded_apex import run_compounded_apex

res = run_compounded_apex(compound=True, max_open=4, pos_pct=0.25, sl_pct=0.07, tp_pct=0.20)
trades = res["all_trades"]

print(f"Total Trades: {len(trades)}")
print(f"Total Net Return: {res['total_return']:+.2f}% (Rs. {res['net_pnl']:+,.1f})")
print(f"Final Capital: Rs. {res['final_capital']:,.2f}")
print(f"Win Rate: {res['win_rate']}%")
print(f"Total Statutory Friction Paid: Rs. {res['friction']:,.1f}")

# Group by year
trades_df = pd.DataFrame(trades)
trades_df["year"] = pd.to_datetime(trades_df["exit_date"]).dt.year

print("\n--- YEAR BY YEAR PERFORMANCE (AFTER ALL FRICTION & TAXES) ---")
for y, group in trades_df.groupby("year"):
    wins = group[group["pnl"] > 0]
    wr = len(wins) / len(group) * 100.0
    tot_pnl = group["pnl"].sum()
    print(f"Year {y}: {len(group):2d} trades | Win Rate: {wr:4.1f}% | Net P&L: Rs.{tot_pnl:+10,.1f} | Avg Gain: {group['pnl_percent'].mean():+4.1f}%")

print("\n--- TOP 10 GREATEST WINNING TRADES ---")
top_wins = trades_df.sort_values(by="pnl", ascending=False).head(10)
for idx, r in top_wins.iterrows():
    print(f"{r['ticker']:12s} | Entry: {r['entry_date']} -> Exit: {r['exit_date']} ({r['days_held']:2d}d) | PnL: {r['pnl_percent']:+5.1f}% (Rs.{r['pnl']:+7,.1f}) | {r['reason']}")

print("\n--- PERFORMANCE BY EXIT REASON ---")
reasons = Counter()
pnl_by_r = Counter()
for t in trades:
    r_key = t["reason"].split("(")[0].strip()
    reasons[r_key] += 1
    pnl_by_r[r_key] += t["pnl"]

for r, count in reasons.most_common():
    print(f"{r:25s}: {count:3d} trades | Total P&L: Rs.{pnl_by_r[r]:+10,.1f} | Avg: Rs.{pnl_by_r[r]/count:+6,.1f}")

