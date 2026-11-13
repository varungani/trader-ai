import os, sys, pickle, math
from collections import Counter
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scratch.test_fast_backtest import fast_backtest
from data.market_data import _load_all_caches

cache = _load_all_caches()
tickers = [k for k, v in cache.items() if not k.startswith("^") and not k.endswith("BEES.NS") and len(v) >= 200][:80]

res = fast_backtest(tickers, period="2y")
trades = res["all_trades"]
print(f"Total trades: {len(trades)}")

# Group by exit reason
reasons = Counter()
pnl_by_reason = Counter()
for t in trades:
    r_key = t["reason"].split("(")[0].strip()
    reasons[r_key] += 1
    pnl_by_reason[r_key] += t["pnl"]

print("\n--- PERFORMANCE BY EXIT REASON ---")
for r, count in reasons.most_common():
    tot_pnl = pnl_by_reason[r]
    avg_pnl = tot_pnl / count
    print(f"{r:25s}: {count:3d} trades | Net PnL: Rs. {tot_pnl:+10,.1f} | Avg: Rs. {avg_pnl:+6,.1f}")

# Friction impact
total_friction = sum(t["friction_costs"] for t in trades)
total_gross = sum(t["gross_pnl"] for t in trades)
total_net = sum(t["pnl"] for t in trades)
print(f"\n--- FRICTION & TURNOVER IMPACT ---")
print(f"Gross PnL:     Rs. {total_gross:+10,.1f}")
print(f"Total Friction: Rs. {total_friction:10,.1f} (DP fees, STT, GST, Slippage)")
print(f"Net PnL:       Rs. {total_net:+10,.1f}")

# Look at losing trades
print("\n--- SAMPLE LOSING TRADES ---")
losses = sorted([t for t in trades if t["pnl"] < 0], key=lambda x: x["pnl"])[:10]
for l in losses:
    print(f"{l['ticker']:12s} | Entry: {l['entry_date']} (Rs.{l['entry_price']}) | Exit: {l['exit_date']} (Rs.{l['exit_price']}) | Held: {l['days_held']}d | Net PnL: {l['pnl_percent']:+.1f}% (Rs.{l['pnl']:+,.1f}) | {l['reason']}")

# Look at top winning trades
print("\n--- TOP WINNING TRADES ---")
wins = sorted([t for t in trades if t["pnl"] > 0], key=lambda x: x["pnl"], reverse=True)[:10]
for w in wins:
    print(f"{w['ticker']:12s} | Entry: {w['entry_date']} (Rs.{w['entry_price']}) | Exit: {w['exit_date']} (Rs.{w['exit_price']}) | Held: {w['days_held']}d | Net PnL: {w['pnl_percent']:+.1f}% (Rs.{w['pnl']:+,.1f}) | {w['reason']}")

