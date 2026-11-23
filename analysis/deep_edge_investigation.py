"""
TraderAI - Deep Quantitative Investigation: 3 Frontiers of Alpha
================================================================================
Investigates:
  1. Pullback / Dip Buying in Stage 2 (20-EMA vs 50-EMA vs Breakout Retest)
  2. Volatility-Adjusted Position Sizing (Fixed Capital vs Inverse-ATR Risk Parity)
  3. Multi-Timeframe Momentum Acceleration (1M vs 3M vs 6M RS & Momentum Freshness)

Evaluated across 626 NSE Equities (2021-2026) with In-Sample (2021-2024) and Out-of-Sample (2024-2026) splits.
"""
from __future__ import annotations

import os
import sys
import time
import pickle
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from data.costs import compute_indian_delivery_costs

SLIPPAGE = 0.0025  # 0.25%
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
# INVESTIGATION 1: PULLBACK / DIP BUYING VS BREAKOUTS
# =====================================================================
def analyze_pullback_dynamics(universe: Dict[str, pd.DataFrame], nifty: pd.DataFrame):
    print("\n" + "="*85)
    print("🔬 1. PULLBACK / DIP BUYING VS BREAKOUT ENTRY DYNAMICS")
    print("="*85, flush=True)
    
    events = []
    
    for sym, raw_df in universe.items():
        if len(raw_df) < 250:
            continue
        df = raw_df.copy()
        c = df['Close'].values
        h = df['High'].values
        l = df['Low'].values
        o = df['Open'].values
        dates = df.index
        n_rows = len(df)
        
        ema20 = df['Close'].ewm(span=20, adjust=False).mean().values
        ema50 = df['Close'].ewm(span=50, adjust=False).mean().values
        ema200 = df['Close'].ewm(span=200, adjust=False).mean().values
        high20 = df['High'].shift(1).rolling(20).max().values
        vol_ma20 = df['Volume'].rolling(20).mean().values
        rvol = (df['Volume'] / (vol_ma20 + 1e-9)).values

        # 14-day True Range
        prev_c = np.roll(c, 1)
        prev_c[0] = c[0]
        tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
        atr14 = pd.Series(tr).rolling(14).mean().values

        for i in range(200, n_rows - 30):
            d0_c = c[i]
            d0_l = l[i]
            d0_h = h[i]
            d0_date = dates[i]
            
            # Must be in Stage 2
            if not (d0_c > ema50[i] and ema50[i] > ema200[i]):
                continue
            
            # Setup A: Breakout 20-Day High
            is_breakout = (d0_c > high20[i]) and (rvol[i] >= 1.3)
            
            # Setup B: 20-EMA Pullback Bounce
            # Touched 20-EMA (Low within 1.0% of 20 EMA) and Closed above 20 EMA and > previous High
            is_ema20_pullback = (d0_l <= ema20[i] * 1.01) and (d0_c >= ema20[i]) and (d0_c > h[i-1])

            # Setup C: 50-EMA Deep Pullback Bounce
            # Touched 50-EMA (Low within 1.5% of 50 EMA) and Closed above 50 EMA and > previous High
            is_ema50_pullback = (d0_l <= ema50[i] * 1.015) and (d0_c >= ema50[i]) and (d0_c > h[i-1])

            if not (is_breakout or is_ema20_pullback or is_ema50_pullback):
                continue

            entry_px = o[i+1] * (1.0 + SLIPPAGE)
            fwd_high = h[i+1:i+21]
            fwd_low = l[i+1:i+21]
            fwd_close = c[i+1:i+21]
            if len(fwd_close) < 20:
                continue

            fwd20_ret = (fwd_close[-1] / entry_px - 1.0) * 100.0
            hit_10 = (np.max(fwd_high) >= entry_px * 1.10)
            hit_15 = (np.max(fwd_high) >= entry_px * 1.15)
            dip_4 = (np.min(fwd_low) <= entry_px * 0.96)
            dip_6 = (np.min(fwd_low) <= entry_px * 0.94)
            dip_8 = (np.min(fwd_low) <= entry_px * 0.92)
            dip_atr2 = (np.min(fwd_low) <= entry_px - (2.0 * atr14[i]))

            setup_type = "20D Breakout" if is_breakout else ("20-EMA Pullback" if is_ema20_pullback else "50-EMA Pullback")
            events.append({
                "symbol": sym,
                "date": d0_date,
                "is_oos": d0_date >= SPLIT_DATE,
                "setup": setup_type,
                "fwd20_ret": fwd20_ret,
                "hit_10": hit_10,
                "hit_15": hit_15,
                "dip_4": dip_4,
                "dip_6": dip_6,
                "dip_8": dip_8,
                "dip_atr2": dip_atr2,
            })

    df_p = pd.DataFrame(events)
    print(f"Evaluated {len(df_p):,} setup occurrences across 5 years.")

    for period, is_oos_flag in [("IN-SAMPLE (2021-2024)", False), ("OUT-OF-SAMPLE (2024-2026)", True)]:
        sub = df_p[df_p["is_oos"] == is_oos_flag]
        print(f"\n--- {period} ({len(sub):,} Trades) ---")
        agg = sub.groupby("setup").agg(
            trades=("fwd20_ret", "count"),
            mean_ret=("fwd20_ret", "mean"),
            median_ret=("fwd20_ret", "median"),
            hit_10=("hit_10", lambda x: np.mean(x)*100),
            hit_15=("hit_15", lambda x: np.mean(x)*100),
            dip_4=("dip_4", lambda x: np.mean(x)*100),
            dip_6=("dip_6", lambda x: np.mean(x)*100),
            dip_8=("dip_8", lambda x: np.mean(x)*100),
            dip_atr2=("dip_atr2", lambda x: np.mean(x)*100),
        )
        print(agg.round(2).to_string())


# =====================================================================
# INVESTIGATION 2: VOLATILITY-ADJUSTED POSITION SIZING
# =====================================================================
def analyze_volatility_sizing(universe: Dict[str, pd.DataFrame]):
    print("\n" + "="*85)
    print("🔬 2. VOLATILITY-ADJUSTED SIZING: FIXED CAPITAL VS INVERSE-ATR RISK PARITY")
    print("="*85, flush=True)

    # Compare 2 Sizing Models across all breakouts with 8% stop vs 2x ATR stop:
    # Model A: Fixed ₹20k Capital allocation per trade.
    # Model B: Inverse-ATR Sizing: Target risk ₹1,000 per trade. Sizing = ₹1,000 / (2.0 * ATR%).
    trades = []

    for sym, raw_df in universe.items():
        if len(raw_df) < 250:
            continue
        c = raw_df['Close'].values
        h = raw_df['High'].values
        l = raw_df['Low'].values
        o = raw_df['Open'].values
        dates = raw_df.index
        n_rows = len(raw_df)

        ema50 = raw_df['Close'].ewm(span=50, adjust=False).mean().values
        ema200 = raw_df['Close'].ewm(span=200, adjust=False).mean().values
        high50 = raw_df['High'].shift(1).rolling(50).max().values
        vol_ma20 = raw_df['Volume'].rolling(20).mean().values
        rvol = (raw_df['Volume'] / (vol_ma20 + 1e-9)).values

        prev_c = np.roll(c, 1)
        prev_c[0] = c[0]
        tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
        atr14 = pd.Series(tr).rolling(14).mean().values

        for i in range(200, n_rows - 30):
            if c[i] > high50[i] and c[i] > ema50[i] and ema50[i] > ema200[i] and rvol[i] >= 1.5:
                entry_px = o[i+1] * (1.0 + SLIPPAGE)
                atr = atr14[i]
                atr_pct = atr / entry_px

                # Sizing model comparison
                fixed_capital = 20000.0
                
                # Risk parity sizing: Risk exactly ₹1,000 on 2.0x ATR stop
                stop_dist_pct = max(0.04, min(0.12, 2.0 * atr_pct))
                risk_parity_capital = 1000.0 / stop_dist_pct
                # Cap allocation between ₹5,000 and ₹35,000
                risk_parity_capital = max(5000.0, min(35000.0, risk_parity_capital))

                # Simulate with 2.0 ATR stop and 50-EMA trailing exit
                stop_px = entry_px * (1.0 - stop_dist_pct)
                fwd_o = o[i+1:i+31]
                fwd_h = h[i+1:i+31]
                fwd_l = l[i+1:i+31]
                fwd_c = c[i+1:i+31]
                fwd_ema50 = ema50[i+1:i+31]

                exit_px = fwd_c[-1] * (1.0 - SLIPPAGE)
                for d in range(len(fwd_o)):
                    if fwd_l[d] <= stop_px:
                        exit_px = stop_px * (1.0 - SLIPPAGE)
                        break
                    if d >= 1 and fwd_c[d] < fwd_ema50[d]:
                        exit_px = fwd_c[d] * (1.0 - SLIPPAGE)
                        break

                pnl_pct = (exit_px / entry_px - 1.0 - 0.0075) * 100.0
                rupees_fixed = fixed_capital * (pnl_pct / 100.0)
                rupees_parity = risk_parity_capital * (pnl_pct / 100.0)

                trades.append({
                    "date": dates[i],
                    "is_oos": dates[i] >= SPLIT_DATE,
                    "atr_pct": atr_pct * 100.0,
                    "pnl_pct": pnl_pct,
                    "rupees_fixed": rupees_fixed,
                    "rupees_parity": rupees_parity,
                    "parity_capital": risk_parity_capital,
                })

    df_sz = pd.DataFrame(trades)
    print(f"Evaluated {len(df_sz):,} trade events across sizing models.")

    for period, is_oos_flag in [("IN-SAMPLE (2021-2024)", False), ("OUT-OF-SAMPLE (2024-2026)", True)]:
        sub = df_sz[df_sz["is_oos"] == is_oos_flag]
        print(f"\n--- {period} ({len(sub):,} Trades) ---")
        
        # Fixed Capital stats
        fix_pnl = sub["rupees_fixed"].sum()
        fix_wins = sub[sub["rupees_fixed"] > 0]["rupees_fixed"].sum()
        fix_losses = abs(sub[sub["rupees_fixed"] <= 0]["rupees_fixed"].sum())
        fix_pf = fix_wins / (fix_losses + 1e-9)

        # Risk Parity stats
        par_pnl = sub["rupees_parity"].sum()
        par_wins = sub[sub["rupees_parity"] > 0]["rupees_parity"].sum()
        par_losses = abs(sub[sub["rupees_parity"] <= 0]["rupees_parity"].sum())
        par_pf = par_wins / (par_losses + 1e-9)

        print(f"  Fixed ₹20k Sizing  : Net PnL = ₹{fix_pnl:+,.0f} | Profit Factor = {fix_pf:.2f} | Win Rate = {(sub['pnl_pct']>0).mean()*100:.1f}%")
        print(f"  Risk-Parity Sizing : Net PnL = ₹{par_pnl:+,.0f} | Profit Factor = {par_pf:.2f} | Avg Allocation = ₹{sub['parity_capital'].mean():,.0f}")
        improvement = ((par_pf - fix_pf) / fix_pf) * 100.0
        print(f"  Profit Factor Lift : {improvement:+.1f}% under Volatility Risk Parity")


# =====================================================================
# INVESTIGATION 3: MULTI-TIMEFRAME RS ACCELERATION
# =====================================================================
def analyze_momentum_acceleration(universe: Dict[str, pd.DataFrame], nifty: pd.DataFrame):
    print("\n" + "="*85)
    print("🔬 3. MULTI-TIMEFRAME RS ACCELERATION: FRESH MOMENTUM VS STALE EXHAUSTION")
    print("="*85, flush=True)

    # Compute 1-Month (21d), 3-Month (63d), and 6-Month (126d) returns vs Nifty across all stocks
    nifty_c = nifty['Close']
    n_ret_1m = (nifty_c / nifty_c.shift(21) - 1.0) * 100.0
    n_ret_3m = (nifty_c / nifty_c.shift(63) - 1.0) * 100.0
    n_ret_6m = (nifty_c / nifty_c.shift(126) - 1.0) * 100.0

    rs_events = []

    for sym, raw_df in universe.items():
        if len(raw_df) < 250:
            continue
        c = raw_df['Close']
        h = raw_df['High']
        l = raw_df['Low']
        o = raw_df['Open']
        dates = raw_df.index
        n_rows = len(raw_df)

        ret_1m = (c / c.shift(21) - 1.0) * 100.0
        ret_3m = (c / c.shift(63) - 1.0) * 100.0
        ret_6m = (c / c.shift(126) - 1.0) * 100.0

        ema50 = c.ewm(span=50, adjust=False).mean()
        ema200 = c.ewm(span=200, adjust=False).mean()
        high20 = h.shift(1).rolling(20).max()
        vol_ma20 = raw_df['Volume'].rolling(20).mean()
        rvol = raw_df['Volume'] / (vol_ma20 + 1e-9)

        for i in range(200, n_rows - 30):
            d0_date = dates[i]
            if d0_date not in nifty.index:
                continue

            # Breakout condition
            if c.iloc[i] > high20.iloc[i] and c.iloc[i] > ema50.iloc[i] and ema50.iloc[i] > ema200.iloc[i] and rvol.iloc[i] >= 1.3:
                rs_1m = ret_1m.iloc[i] - n_ret_1m.get(d0_date, 0.0)
                rs_3m = ret_3m.iloc[i] - n_ret_3m.get(d0_date, 0.0)
                rs_6m = ret_6m.iloc[i] - n_ret_6m.get(d0_date, 0.0)

                # Classify Momentum Profile:
                # 1. Fresh Acceleration: 1M RS > 3M RS > 0 (Momentum is rapidly speeding up!)
                # 2. Steady Leader: 1M RS > 0 and 3M RS > 0 and 6M RS > 0
                # 3. Exhausted Leader: 6M RS > +30% but 1M RS < 0 (Stale momentum roll-over!)
                # 4. Laggard Breakout: 6M RS < 0 and 1M RS > 0 (Bottom rebound breakout)
                if rs_1m > rs_3m and rs_1m > 0:
                    profile = "Fresh Acceleration (1M > 3M > 0)"
                elif rs_1m > 0 and rs_3m > 0 and rs_6m > 0:
                    profile = "Steady Compounder (All Horizons > 0)"
                elif rs_6m > 25.0 and rs_1m < 0:
                    profile = "Exhausted Leader (6M > +25%, 1M < 0)"
                elif rs_6m < 0 and rs_1m > 0:
                    profile = "Turnaround Rebound (6M < 0, 1M > 0)"
                else:
                    profile = "Mixed / Neutral"

                entry_px = o.iloc[i+1] * (1.0 + SLIPPAGE)
                fwd_c = c.iloc[i+1:i+21].values
                fwd_h = h.iloc[i+1:i+21].values
                fwd_l = l.iloc[i+1:i+21].values
                if len(fwd_c) < 20:
                    continue

                fwd20_ret = (fwd_c[-1] / entry_px - 1.0) * 100.0
                hit_10 = (np.max(fwd_h) >= entry_px * 1.10)
                dip_4 = (np.min(fwd_l) <= entry_px * 0.96)
                dip_8 = (np.min(fwd_l) <= entry_px * 0.92)

                rs_events.append({
                    "date": d0_date,
                    "is_oos": d0_date >= SPLIT_DATE,
                    "profile": profile,
                    "rs_1m": rs_1m,
                    "rs_3m": rs_3m,
                    "rs_6m": rs_6m,
                    "fwd20_ret": fwd20_ret,
                    "hit_10": hit_10,
                    "dip_4": dip_4,
                    "dip_8": dip_8,
                })

    df_rs = pd.DataFrame(rs_events)
    print(f"Evaluated {len(df_rs):,} momentum breakout profiles.")

    for period, is_oos_flag in [("IN-SAMPLE (2021-2024)", False), ("OUT-OF-SAMPLE (2024-2026)", True)]:
        sub = df_rs[df_rs["is_oos"] == is_oos_flag]
        print(f"\n--- {period} ({len(sub):,} Trades) ---")
        agg = sub.groupby("profile").agg(
            trades=("fwd20_ret", "count"),
            mean_ret=("fwd20_ret", "mean"),
            median_ret=("fwd20_ret", "median"),
            hit_10=("hit_10", lambda x: np.mean(x)*100),
            dip_4=("dip_4", lambda x: np.mean(x)*100),
            dip_8=("dip_8", lambda x: np.mean(x)*100),
        )
        print(agg.round(2).to_string())


def main():
    universe, nifty = load_universe_and_benchmarks()
    analyze_pullback_dynamics(universe, nifty)
    analyze_volatility_sizing(universe)
    analyze_momentum_acceleration(universe, nifty)


if __name__ == "__main__":
    main()
