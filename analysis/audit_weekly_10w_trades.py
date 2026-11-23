"""
Audit the Weekly 10-Week EMA Trailing Strategy:
- Year-by-year CAGR and returns
- Top 15 biggest winning trades
- Loss distribution and trade duration
- In-sample (2021-2024) vs Out-of-sample (2024-2026) split
"""
import os
import sys
import pandas as pd
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from analysis.institutional_weekly_compounder import run_weekly_trend_compounding, STARTING_CASH, SPLIT_DATE

res = run_weekly_trend_compounding(max_slots=4, trailing_mode="weekly_10w", risk_pct_equity=0.02)
eq = res["daily_equity"].copy()
tr = res["trades"].copy()

eq["year"] = pd.to_datetime(eq["date"]).dt.year
yearly = []
for y, g in eq.groupby("year"):
    start_eq = g["equity"].iloc[0]
    end_eq = g["equity"].iloc[-1]
    y_ret = (end_eq / start_eq - 1.0) * 100.0
    running_m = g["equity"].cummax()
    y_dd = float(((g["equity"] - running_m) / running_m).min() * 100.0)
    yearly.append({"Year": y, "Start Equity": start_eq, "End Equity": end_eq, "Return %": y_ret, "Max DD %": y_dd})

df_yearly = pd.DataFrame(yearly)
print("\n" + "="*70)
print("📅 YEAR-BY-YEAR PERFORMANCE (WEEKLY 10-WEEK EMA - 4 SLOTS)")
print("="*70)
print(df_yearly.to_string(index=False))

print("\n" + "="*70)
print("🏆 TOP 15 WINNING TRADES")
print("="*70)
top_wins = tr.sort_values(by="net_pnl_inr", ascending=False).head(15)
for _, r in top_wins.iterrows():
    print(f"  • {r['symbol']:<12} | Entry: {str(r['entry_date'])[:10]} | Exit: {str(r['exit_date'])[:10]} | "
          f"Held: {r['holding_days']:3d}d | Gain: {r['net_pnl_pct']:+6.1f}% | Net PnL: ₹{r['net_pnl_inr']:+8,.2f} | Reason: {r['exit_reason']}")

print("\n" + "="*70)
print("⚠️ LOSS DISTRIBUTION")
print("="*70)
losses = tr[tr["net_pnl_pct"] <= 0]
print(f"Total Losing Trades: {len(losses)} / {len(tr)} ({len(losses)/len(tr)*100:.1f}%)")
print(f"Mean Loss %       : {losses['net_pnl_pct'].mean():.2f}%")
print(f"Median Loss %     : {losses['net_pnl_pct'].median():.2f}%")
print(f"Worst Single Loss : {losses['net_pnl_pct'].min():.2f}%")

print("\n" + "="*70)
print("🔬 IN-SAMPLE VS OUT-OF-SAMPLE SPLIT")
print("="*70)
is_tr = tr[tr["is_oos"] == False]
oos_tr = tr[tr["is_oos"] == True]

for label, sub in [("In-Sample (2021-10 to 2024-03)", is_tr), ("Out-of-Sample (2024-04 to 2026-11)", oos_tr)]:
    w = sub[sub["net_pnl_inr"] > 0]["net_pnl_inr"]
    l = sub[sub["net_pnl_inr"] <= 0]["net_pnl_inr"]
    pf = w.sum() / (abs(l.sum()) + 1e-9)
    print(f"\n📌 {label} ({len(sub)} trades):")
    print(f"   • Win Rate      : {(len(w)/len(sub)*100):.1f}%")
    print(f"   • Profit Factor : {pf:.2f}")
    print(f"   • Total Net PnL : ₹{sub['net_pnl_inr'].sum():+,.2f}")
    print(f"   • Avg Win       : ₹{w.mean():+,.2f} ({sub[sub['net_pnl_pct']>0]['net_pnl_pct'].mean():+.1f}%)")
    print(f"   • Avg Loss      : ₹{l.mean():+,.2f} ({sub[sub['net_pnl_pct']<=0]['net_pnl_pct'].mean():+.1f}%)")
    print(f"   • Win/Loss Ratio: {abs(w.mean() / (l.mean() + 1e-9)):.2f}x payoff ratio")
