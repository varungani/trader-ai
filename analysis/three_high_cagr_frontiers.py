"""
TraderAI - Exhaustive Analysis of 3 High-CAGR Frontiers (2021–2026)
================================================================================
Investigates:
  1. The Multi-Bagger Holding Engine:
       - Daily 50-EMA vs Weekly 10-Week EMA vs Weekly 20-Week EMA (100d EMA)
       - Base-on-Base Re-entry Logic across the Top 50 Indian Super-Movers
  2. High-Velocity Aggressive Rotation:
       - Capturing rapid 10-15 day momentum bursts with tight 5-day EMA trailing
       - Testing friction drag (STT, DP, slippage) vs velocity turnover
  3. Concentrated 3-Slot Conviction Model:
       - 33.3% Capital per Slot in the Top 3 RS Leaders vs 6 Slots (16.7%)
       - Portfolio equity compounding, max drawdown, and CAGR over 5 years
"""
from __future__ import annotations

import os
import sys
import time
import pickle
from dataclasses import dataclass
from typing import Dict, List, Any, Tuple

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from data.costs import compute_indian_delivery_costs

SLIPPAGE = 0.0025
STARTING_CASH = 100000.0
SPLIT_DATE = pd.Timestamp("2024-04-01")


def load_universe_and_benchmarks():
    print("📦 Loading 5Y universe cache and benchmarks...", flush=True)
    cache_path = os.path.join(ROOT, "data", "cache", "universe_5y.pkl")
    bench_path = os.path.join(ROOT, "data", "cache", "benchmarks_5y.pkl")
    with open(cache_path, "rb") as f:
        universe: Dict[str, pd.DataFrame] = pickle.load(f)
    with open(bench_path, "rb") as f:
        benchmarks: Dict[str, pd.DataFrame] = pickle.load(f)
    nifty = benchmarks['^NSEI'].copy()
    nifty['EMA50'] = nifty['Close'].ewm(span=50, adjust=False).mean()
    return universe, nifty


# =====================================================================
# FRONTIER 1: MULTI-BAGGER HOLDING ENGINE & TIMEFRAME COMPARISON
# =====================================================================
def analyze_multibagger_holding_engine(universe: Dict[str, pd.DataFrame]):
    print("\n" + "="*85)
    print("🔬 FRONTIER 1: MULTI-BAGGER HOLDING ENGINE & WEEKLY TREND ANALYSIS")
    print("="*85, flush=True)

    # Find the top 30 multi-baggers of 2021-2026
    top_stocks = []
    for sym, df in universe.items():
        if len(df) < 500: continue
        c = df['Close'].dropna()
        if len(c) < 500: continue
        tot_ret = (c.iloc[-1] / c.iloc[0] - 1.0) * 100.0
        top_stocks.append((sym, tot_ret))
    top_stocks.sort(key=lambda x: x[1], reverse=True)
    top_30_syms = [s for s, r in top_stocks[:30]]

    print(f"Testing holding mechanics across Top 30 Super-Movers (e.g. {', '.join(top_30_syms[:5])})...")

    # Compare 3 Trailing Exit Rules on all Stage 2 breakouts in these stocks:
    # Rule 1: Daily Close < 50-Day EMA (Current Base Model)
    # Rule 2: Weekly Close < 10-Week EMA (~50-day EMA evaluated only on Friday close)
    # Rule 3: Weekly Close < 20-Week EMA (~100-day EMA evaluated only on Friday close)
    records = []

    for sym in top_30_syms:
        df = universe[sym].copy()
        c = df['Close']
        h = df['High']
        l = df['Low']
        o = df['Open']
        dates = df.index
        n_rows = len(df)

        ema50 = c.ewm(span=50, adjust=False).mean()
        ema100 = c.ewm(span=100, adjust=False).mean()
        high50 = h.shift(1).rolling(50).max()
        vol_ma20 = df['Volume'].rolling(20).mean()
        rvol = df['Volume'] / (vol_ma20 + 1e-9)

        # Resample to weekly close for true institutional trend following
        df_weekly = df.resample('W-FRI').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()
        df_weekly['EMA10W'] = df_weekly['Close'].ewm(span=10, adjust=False).mean()
        df_weekly['EMA20W'] = df_weekly['Close'].ewm(span=20, adjust=False).mean()

        for i in range(252, n_rows - 30):
            # Stage 2 50-Day Breakout with volume
            if c.iloc[i] > high50.iloc[i] and c.iloc[i] > ema50.iloc[i] and rvol.iloc[i] >= 1.5:
                entry_date = dates[i+1]
                entry_px = o.iloc[i+1] * (1.0 + SLIPPAGE)
                initial_stop = entry_px * 0.92  # 8% stop

                # Simulate Rule 1: Daily Close < 50-EMA
                r1_exit_px = c.iloc[-1]
                r1_days = 0
                for d in range(i+1, n_rows):
                    r1_days += 1
                    if l.iloc[d] <= initial_stop:
                        r1_exit_px = initial_stop * (1.0 - SLIPPAGE)
                        break
                    if r1_days >= 2 and c.iloc[d] < ema50.iloc[d]:
                        r1_exit_px = c.iloc[d] * (1.0 - SLIPPAGE)
                        break
                r1_ret = (r1_exit_px / entry_px - 1.0 - 0.0075) * 100.0

                # Simulate Rule 2: Weekly Close < 10-Week EMA (~50d weekly)
                r2_exit_px = c.iloc[-1]
                r2_days = 0
                for d in range(i+1, n_rows):
                    r2_days += 1
                    if l.iloc[d] <= initial_stop:
                        r2_exit_px = initial_stop * (1.0 - SLIPPAGE)
                        break
                    cur_d = dates[d]
                    # Check on Friday Close
                    if cur_d.weekday() == 4 and cur_d in df_weekly.index:
                        w_close = df_weekly.loc[cur_d, 'Close']
                        w_ema10 = df_weekly.loc[cur_d, 'EMA10W']
                        if r2_days >= 5 and w_close < w_ema10:
                            r2_exit_px = c.iloc[d] * (1.0 - SLIPPAGE)
                            break
                r2_ret = (r2_exit_px / entry_px - 1.0 - 0.0075) * 100.0

                # Simulate Rule 3: Weekly Close < 20-Week EMA (~100d institutional weekly line)
                r3_exit_px = c.iloc[-1]
                r3_days = 0
                for d in range(i+1, n_rows):
                    r3_days += 1
                    if l.iloc[d] <= initial_stop:
                        r3_exit_px = initial_stop * (1.0 - SLIPPAGE)
                        break
                    cur_d = dates[d]
                    if cur_d.weekday() == 4 and cur_d in df_weekly.index:
                        w_close = df_weekly.loc[cur_d, 'Close']
                        w_ema20 = df_weekly.loc[cur_d, 'EMA20W']
                        if r3_days >= 5 and w_close < w_ema20:
                            r3_exit_px = c.iloc[d] * (1.0 - SLIPPAGE)
                            break
                r3_ret = (r3_exit_px / entry_px - 1.0 - 0.0075) * 100.0

                records.append({
                    "symbol": sym,
                    "date": entry_date,
                    "r1_ret": r1_ret, "r1_days": r1_days,
                    "r2_ret": r2_ret, "r2_days": r2_days,
                    "r3_ret": r3_ret, "r3_days": r3_days,
                })

    df_rec = pd.DataFrame(records)
    print(f"Evaluated {len(df_rec):,} breakout events in Top 30 Super-Movers.")

    print("\n--- RESULTS ACROSS THE 3 HOLDING TIMEFRAMES ---")
    for r_name, pfx in [
        ("Daily Close < 50-EMA (Fast Daily Trail)", "r1"),
        ("Weekly Close < 10-Week EMA (Medium Weekly Trail)", "r2"),
        ("Weekly Close < 20-Week EMA (Deep Institutional Trend)", "r3"),
    ]:
        rets = df_rec[f"{pfx}_ret"]
        days = df_rec[f"{pfx}_days"]
        wins = rets[rets > 0]
        losses = rets[rets <= 0]
        pf = wins.sum() / (abs(losses.sum()) + 1e-9)
        hit_50 = (rets >= 50.0).mean() * 100.0
        hit_100 = (rets >= 100.0).mean() * 100.0
        print(f"\n📌 {r_name}:")
        print(f"   • Mean Net Return   : {rets.mean():+.2f}% (Median: {rets.median():+.2f}%)")
        print(f"   • Profit Factor     : {pf:.2f}")
        print(f"   • Win Rate          : {(rets > 0).mean()*100:.1f}%")
        print(f"   • Average Holding   : {days.mean():.1f} market sessions (~{days.mean()/21:.1f} months)")
        print(f"   • Hits >= +50% Gain : {hit_50:.1f}% of trades")
        print(f"   • Hits >= +100% Bag : {hit_100:.1f}% of trades")
        print(f"   • Max Single Trade  : {rets.max():+.1f}%")


# =====================================================================
# FRONTIER 2: HIGH-VELOCITY AGGRESSIVE ROTATION (10-15 DAY BURSTS)
# =====================================================================
def analyze_high_velocity_rotation(universe: Dict[str, pd.DataFrame], nifty: pd.DataFrame):
    print("\n" + "="*85)
    print("🔬 FRONTIER 2: HIGH-VELOCITY AGGRESSIVE ROTATION (10–15 DAY BURSTS)")
    print("="*85, flush=True)

    # Strategy: Capture rapid +12% to +20% bursts with tight 5-day EMA trailing and fast capital recycle
    # Strict 12-session velocity cutoff: If position hasn't hit target or is stagnating, recycle!
    events = []

    for sym, raw_df in universe.items():
        if len(raw_df) < 250: continue
        c = raw_df['Close'].values
        h = raw_df['High'].values
        l = raw_df['Low'].values
        o = raw_df['Open'].values
        dates = raw_df.index
        n_rows = len(raw_df)

        ema5 = raw_df['Close'].ewm(span=5, adjust=False).mean().values
        ema20 = raw_df['Close'].ewm(span=20, adjust=False).mean().values
        ema50 = raw_df['Close'].ewm(span=50, adjust=False).mean().values
        high20 = raw_df['High'].shift(1).rolling(20).max().values
        vol_ma20 = raw_df['Volume'].rolling(20).mean().values
        rvol = (raw_df['Volume'] / (vol_ma20 + 1e-9)).values

        for i in range(200, n_rows - 20):
            # Aggressive Breakout: Close > 20D High + High RVOL >= 2.0x in Stage 2
            if c[i] > high20[i] and c[i] > ema50[i] and rvol[i] >= 2.0:
                entry_px = o[i+1] * (1.0 + SLIPPAGE)
                stop_px = entry_px * 0.95  # Tight -5.0% stop for velocity
                target_px = entry_px * 1.15  # +15% Quick Profit Target

                exit_px = c[i+15] if (i+15 < n_rows) else c[-1]
                holding_days = 0
                exit_reason = "max_velocity"

                for d in range(1, 15):
                    idx = i + 1 + d
                    if idx >= n_rows: break
                    holding_days = d

                    # Check stop
                    if l[idx] <= stop_px:
                        exit_px = stop_px * (1.0 - SLIPPAGE)
                        exit_reason = "stop"
                        break
                    # Check quick target
                    if h[idx] >= target_px:
                        exit_px = target_px * (1.0 - SLIPPAGE)
                        exit_reason = "target_15"
                        break
                    # Trailing 5-EMA on Close starting Day 3
                    if d >= 3 and c[idx] < ema5[idx]:
                        exit_px = c[idx] * (1.0 - SLIPPAGE)
                        exit_reason = "trail_5ema"
                        break
                    # Velocity stagnation kill: Day 5 and PnL < +1.5%
                    if d >= 5 and (c[idx] / entry_px - 1.0) < 0.015:
                        exit_px = c[idx] * (1.0 - SLIPPAGE)
                        exit_reason = "stagnation_kill"
                        break

                # Statutory friction deduction: 0.25% buy slippage + 0.25% sell slippage + STT 0.2% + DP ₹15.93
                gross_ret = (exit_px / entry_px - 1.0) * 100.0
                friction_pct = 0.75  # ~0.75% round-trip friction
                net_ret = gross_ret - friction_pct

                events.append({
                    "date": dates[i+1],
                    "is_oos": dates[i+1] >= SPLIT_DATE,
                    "holding_days": holding_days,
                    "gross_ret": gross_ret,
                    "net_ret": net_ret,
                    "exit_reason": exit_reason,
                })

    df_vel = pd.DataFrame(events)
    print(f"Evaluated {len(df_vel):,} High-Velocity 10-15 Day Swings.")

    for period, is_oos_flag in [("IN-SAMPLE (2021-2024)", False), ("OUT-OF-SAMPLE (2024-2026)", True)]:
        sub = df_vel[df_vel["is_oos"] == is_oos_flag]
        wins = sub[sub["net_ret"] > 0]["net_ret"]
        losses = sub[sub["net_ret"] <= 0]["net_ret"]
        pf = wins.sum() / (abs(losses.sum()) + 1e-9)
        print(f"\n--- {period} ({len(sub):,} Trades) ---")
        print(f"   • Mean Net Return/Trade : {sub['net_ret'].mean():+.2f}% (Gross: {sub['gross_ret'].mean():+.2f}%)")
        print(f"   • Median Net Return     : {sub['net_ret'].median():+.2f}%")
        print(f"   • Profit Factor         : {pf:.2f}")
        print(f"   • Win Rate              : {(sub['net_ret'] > 0).mean()*100:.1f}%")
        print(f"   • Avg Holding Days      : {sub['holding_days'].mean():.1f} sessions")
        print(f"   • Annual Trade Velocity : ~{len(sub) / (2.5):.0f} trades/year")
        print(f"   • Total Friction Drag   : ~{len(sub) * 0.75:.1f}% total return eaten by friction")


# =====================================================================
# FRONTIER 3: CONCENTRATED 3-SLOT CONVICTION MODEL
# =====================================================================
def analyze_concentrated_3slot_model():
    print("\n" + "="*85)
    print("🔬 FRONTIER 3: CONCENTRATED 3-SLOT CONVICTION MODEL (33% PER POSITION)")
    print("="*85, flush=True)
    from analysis.high_octane_cagr_simulator import run_high_octane_simulation

    # Compare 3 Slots vs 4 Slots vs 6 Slots directly:
    for slots in [3, 4, 6]:
        res = run_high_octane_simulation(max_slots=slots, enable_pyramiding=False, risk_pct_equity=0.0175)
        eq = res["equity_curve"]["equity"]
        end_val = res["final_cash"]
        tot_ret = (end_val / STARTING_CASH - 1.0) * 100.0
        n_years = len(eq) / 252.0
        cagr = ((end_val / STARTING_CASH) ** (1.0 / n_years) - 1.0) * 100.0
        running_max = eq.cummax()
        max_dd = float(((eq - running_max) / running_max).min() * 100.0)
        tr = res["trades"]
        wins = tr[tr["net_pnl_inr"] > 0]["net_pnl_inr"]
        losses = tr[tr["net_pnl_inr"] <= 0]["net_pnl_inr"]
        pf = wins.sum() / (abs(losses.sum()) + 1e-9)
        
        print(f"\n📌 {slots}-Slot Portfolio (Max {100/slots:.1f}% per stock):")
        print(f"   • Ending Capital    : ₹{end_val:,.2f} ({tot_ret:+.2f}% Net Return)")
        print(f"   • 5-Year CAGR       : {cagr:+.2f}% per year")
        print(f"   • Max Drawdown      : {max_dd:.2f}%")
        print(f"   • Profit Factor     : {pf:.2f} | Win Rate: {(len(wins)/len(tr)*100):.1f}% ({len(tr)} trades)")
        print(f"   • Friction Paid     : ₹{res['total_friction']:,.2f}")


def main():
    universe, nifty = load_universe_and_benchmarks()
    analyze_multibagger_holding_engine(universe)
    analyze_high_velocity_rotation(universe, nifty)
    analyze_concentrated_3slot_model()


if __name__ == "__main__":
    main()
