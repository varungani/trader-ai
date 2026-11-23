"""
Audit Yearly Breakdown of Apex 2.25% Risk Model (+41.87% CAGR, ₹402k ending capital)
"""
import os
import sys
import pandas as pd
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from analysis.apex_creative_compounder import run_apex_simulation, STARTING_CASH

res = run_apex_simulation(
    min_dist_ema200=0.20,
    min_vol_asymmetry=2.0,
    risk_pct_equity=0.0225,
    max_slots=4,
)

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
print("📅 YEAR-BY-YEAR PERFORMANCE (APEX 2.25% RISK MODEL - +41.87% CAGR)")
print("="*70)
print(df_yearly.to_string(index=False))

print("\n" + "="*70)
print("🏆 TOP 15 WINNERS")
print("="*70)
top_wins = tr.sort_values(by="net_pnl_inr", ascending=False).head(15)
for _, r in top_wins.iterrows():
    print(f"  • {r['symbol']:<12} | Entry: {str(r['entry_date'])[:10]} | Exit: {str(r['exit_date'])[:10]} | "
          f"Held: {r['holding_days']:3d}d | Gain: {r['net_pnl_pct']:+6.1f}% | Net PnL: ₹{r['net_pnl_inr']:+8,.2f}")

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
