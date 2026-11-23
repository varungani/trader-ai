"""
TraderAI - Risk Scaling & 40%+ CAGR Frontier Search
===================================================
Tests whether dynamic equity risk (2.0% -> 2.5%) on the Apex Model
(200-EMA >= +20% and Volume Asymmetry >= 2.0x) breaks through the 40%+ 5-Year CAGR barrier.
"""
import os
import sys
import pandas as pd
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from analysis.apex_creative_compounder import run_apex_simulation, STARTING_CASH

print("="*80)
print("🎯 TESTING EQUITY RISK SCALING ON APEX MODEL (TARGETING 40%+ CAGR)")
print("="*80)

for risk_pct in [0.0175, 0.020, 0.0225, 0.025, 0.0275]:
    res = run_apex_simulation(
        min_dist_ema200=0.20,
        min_vol_asymmetry=2.0,
        risk_pct_equity=risk_pct,
        max_slots=4,
    )
    end_val = res["final_equity"]
    eq = res["daily_equity"]["equity"]
    tr = res["trades"]
    fric = res["total_friction"]
    n_years = len(eq) / 252.0
    tot_ret = (end_val / STARTING_CASH - 1.0) * 100.0
    cagr = ((end_val / STARTING_CASH) ** (1.0 / n_years) - 1.0) * 100.0
    running_max = eq.cummax()
    max_dd = float(((eq - running_max) / running_max).min() * 100.0)
    wins = tr[tr["net_pnl_inr"] > 0]["net_pnl_inr"]
    losses = tr[tr["net_pnl_inr"] <= 0]["net_pnl_inr"]
    pf = wins.sum() / (abs(losses.sum()) + 1e-9)

    print(f"\n📌 Risk {risk_pct*100:.2f}% per trade:")
    print(f"   • Ending Capital : ₹{end_val:,.2f} ({tot_ret:+.2f}% Net Return)")
    print(f"   • 5-Year CAGR    : {cagr:+.2f}% per year")
    print(f"   • Max Drawdown   : {max_dd:.2f}%")
    print(f"   • Profit Factor  : {pf:.2f} | Win Rate: {(len(wins)/len(tr)*100):.1f}% ({len(tr)} trades)")
    print(f"   • Friction Paid  : ₹{fric:,.2f}")
