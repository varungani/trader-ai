"""
TraderAI - Test Strategy under Unshackled Exit Policy
Compares Strategy (Score >= 65) under:
1. Current Choked Policy (Breakeven ratchet + tight trailing stop)
2. Clean Stop & Target Policy (No premature ratchet/trail)
"""
import os
import sys
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scratch.exit_audit_and_pnl_waterfall import load_data, run_detailed_exit_audit

def main():
    data, nifty = load_data()
    print("Testing Strategy (Score >= 65, Regime ON) under different exit policies:\n")
    
    # 1. Current Choked Policy
    t_choked, eq_choked = run_detailed_exit_audit(data, nifty, entry_mode="strategy", exit_policy="current")
    # 2. Clean Stop & Target Policy
    t_clean, eq_clean = run_detailed_exit_audit(data, nifty, entry_mode="strategy", exit_policy="stop_and_target_no_ratchet")
    # 3. Fixed 15d Hold
    t_fixed, eq_fixed = run_detailed_exit_audit(data, nifty, entry_mode="strategy", exit_policy="fixed_15d_hold")
    
    for name, t_df in [("Current Choked (Ratchet+Trail)", t_choked), ("Clean Stop & Target (No Ratchet)", t_clean), ("Fixed 15-Day Hold", t_fixed)]:
        n_t = len(t_df)
        g_pnl = t_df["gross_pnl"].sum()
        f_pnl = t_df["friction"].sum()
        n_pnl = t_df["net_pretax_pnl"].sum()
        wins = t_df[t_df["net_pretax_pnl"] > 0]
        w_rate = (len(wins) / n_t * 100) if n_t else 0.0
        t1_count = len(t_df[t_df["reason"].str.contains("TARGET", na=False)])
        print(f"Policy: {name}")
        print(f"  Trades: {n_t} | Win Rate: {w_rate:.1f}% | Reached T1: {t1_count} ({t1_count/n_t*100:.1f}%)")
        print(f"  Gross P&L: Rs {g_pnl:+,.2f} (Rs {g_pnl/n_t:+.2f}/tr)")
        print(f"  Friction:  Rs {f_pnl:,.2f} (Rs {f_pnl/n_t:.2f}/tr)")
        print(f"  Net P&L:   Rs {n_pnl:+,.2f} (Rs {n_pnl/n_t:+.2f}/tr)\n")

if __name__ == "__main__":
    main()
