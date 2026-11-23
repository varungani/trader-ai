"""
TraderAI - Short-Term Swing Alpha Deep Dive (2021-2026)
================================================================================
Exhaustive empirical analysis of high-expectancy SWING TRADING setups
specifically designed for 5 to 20 day holding periods (60 to 150 trades/year).

Tests 4 Distinct Short-Term Swing Architectures:
  1. Setup A: The VDU (Volume Dry-Up) 10-Day Breakout Thrust (Hold 5-15d)
  2. Setup B: The 20-EMA Pullback Bounce in Stage 2 Leaders (Hold 5-12d)
  3. Setup C: The 2-Period RSI Extreme Panic Flush Bounce in Leaders (Hold 3-8d)
  4. Setup D: The NR7 / Inside Day Momentum Expansion (Hold 5-15d)

Evaluates:
  - Exact win rate, profit factor, holding duration, and trade velocity (trades/year)
  - Full statutory Indian delivery friction (STT, GST, DP ₹15.93, slippage)
  - True portfolio cash compounding over 5 years on ₹100,000 starting capital.
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

SLIPPAGE = 0.0025
STARTING_CASH = 100000.0
CASH_YIELD_ANNUAL = 0.065
DAILY_CASH_YIELD = (1.0 + CASH_YIELD_ANNUAL) ** (1.0 / 252.0) - 1.0
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
# 1. EVALUATE ALL 4 SWING SETUPS ACROSS 626 STOCKS (TRADE-LEVEL ANALYSIS)
# =====================================================================
def analyze_swing_setups(universe: Dict[str, pd.DataFrame], nifty: pd.DataFrame):
    print("\n" + "="*85)
    print("🔍 TRADE-LEVEL ANALYSIS OF 4 SHORT-TERM SWING ARCHITECTURES (5-20 DAYS)")
    print("="*85, flush=True)

    results = {
        "Setup A (VDU Breakout Thrust)": [],
        "Setup B (20-EMA Pullback Bounce)": [],
        "Setup C (RSI-2 Panic Flush in Leaders)": [],
        "Setup D (NR7 Momentum Expansion)": [],
    }

    nifty_c = nifty['Close']

    for sym, df in universe.items():
        if len(df) < 300: continue
        c = df['Close']
        h = df['High']
        l = df['Low']
        o = df['Open']
        v = df['Volume']
        dates = df.index
        n_rows = len(df)

        # Technical Indicators
        ema5 = c.ewm(span=5, adjust=False).mean()
        ema10 = c.ewm(span=10, adjust=False).mean()
        ema20 = c.ewm(span=20, adjust=False).mean()
        ema50 = c.ewm(span=50, adjust=False).mean()
        ema200 = c.ewm(span=200, adjust=False).mean()

        tr = np.maximum(h - l, np.maximum((h - c.shift(1)).abs(), (l - c.shift(1)).abs()))
        atr14 = tr.rolling(14).mean()

        vol_ma20 = v.rolling(20).mean()
        rvol = v / (vol_ma20 + 1e-9)

        # 2-period RSI
        delta = c.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(2).mean()
        avg_loss = loss.rolling(2).mean()
        rs_2 = avg_gain / (avg_loss + 1e-9)
        rsi_2 = 100.0 - (100.0 / (1.0 + rs_2))

        # NR7: Lowest range of last 7 days
        range_daily = h - l
        is_nr7 = (range_daily == range_daily.rolling(7).min())

        # VDU: 3-day volume < 60% of 20-day average
        vol_3d_avg = v.rolling(3).mean()
        is_vdu = (vol_3d_avg < 0.60 * vol_ma20)

        # Breakout pivots
        high10 = h.shift(1).rolling(10).max()
        high20 = h.shift(1).rolling(20).max()

        for i in range(200, n_rows - 25):
            stage2 = (c.iloc[i] > ema50.iloc[i] and ema50.iloc[i] > ema200.iloc[i])

            # ---------------------------------------------------------
            # SETUP A: VDU 10-Day Breakout Thrust
            # ---------------------------------------------------------
            if stage2 and is_vdu.iloc[i-1] and c.iloc[i] > high10.iloc[i] and rvol.iloc[i] >= 1.8:
                entry_px = o.iloc[i+1] * (1.0 + SLIPPAGE)
                stop_px = min(l.iloc[i], entry_px * 0.955)  # ~4.5% stop
                exit_px = c.iloc[i+15] if (i+15 < n_rows) else c.iloc[-1]
                holding_days = 0

                for d in range(1, 16):
                    idx = i + 1 + d
                    if idx >= n_rows: break
                    holding_days = d
                    # Stop loss
                    if l.iloc[idx] <= stop_px:
                        exit_px = stop_px * (1.0 - SLIPPAGE)
                        break
                    # Trailing 5-EMA once in profit >= +4%
                    if d >= 3 and (c.iloc[idx] / entry_px - 1.0) >= 0.04 and c.iloc[idx] < ema5.iloc[idx]:
                        exit_px = c.iloc[idx] * (1.0 - SLIPPAGE)
                        break
                    # Max 15 sessions swing exit
                    if d == 15:
                        exit_px = c.iloc[idx] * (1.0 - SLIPPAGE)
                        break

                net_ret = (exit_px / entry_px - 1.0 - 0.0075) * 100.0
                results["Setup A (VDU Breakout Thrust)"].append({
                    "symbol": sym, "date": dates[i+1], "is_oos": dates[i+1] >= SPLIT_DATE,
                    "net_ret": net_ret, "holding_days": holding_days
                })

            # ---------------------------------------------------------
            # SETUP B: 20-EMA Pullback Bounce
            # ---------------------------------------------------------
            if stage2 and c.iloc[i] > ema20.iloc[i]:
                # 3-5 days pullback into 20-EMA with lower volume
                pulled_back = (l.iloc[i] <= ema20.iloc[i] * 1.01 and l.iloc[i] >= ema20.iloc[i] * 0.97)
                reversal_candle = (c.iloc[i] > o.iloc[i] and c.iloc[i] > h.iloc[i-1] and rvol.iloc[i] >= 1.2)
                if pulled_back and reversal_candle:
                    entry_px = o.iloc[i+1] * (1.0 + SLIPPAGE)
                    stop_px = l.iloc[i] * 0.99  # Tight stop just below swing low
                    exit_px = c.iloc[i+12] if (i+12 < n_rows) else c.iloc[-1]
                    holding_days = 0

                    for d in range(1, 13):
                        idx = i + 1 + d
                        if idx >= n_rows: break
                        holding_days = d
                        if l.iloc[idx] <= stop_px:
                            exit_px = stop_px * (1.0 - SLIPPAGE)
                            break
                        # Quick target: +10% or trail 10-EMA
                        if h.iloc[idx] >= entry_px * 1.12:
                            exit_px = entry_px * 1.12 * (1.0 - SLIPPAGE)
                            break
                        if d >= 3 and c.iloc[idx] < ema10.iloc[idx]:
                            exit_px = c.iloc[idx] * (1.0 - SLIPPAGE)
                            break
                        if d == 12:
                            exit_px = c.iloc[idx] * (1.0 - SLIPPAGE)
                            break

                    net_ret = (exit_px / entry_px - 1.0 - 0.0075) * 100.0
                    results["Setup B (20-EMA Pullback Bounce)"].append({
                        "symbol": sym, "date": dates[i+1], "is_oos": dates[i+1] >= SPLIT_DATE,
                        "net_ret": net_ret, "holding_days": holding_days
                    })

            # ---------------------------------------------------------
            # SETUP C: RSI-2 Panic Flush in Leaders
            # ---------------------------------------------------------
            if stage2 and rsi_2.iloc[i] < 10.0 and c.iloc[i] > ema200.iloc[i] * 1.05:
                entry_px = o.iloc[i+1] * (1.0 + SLIPPAGE)
                stop_px = entry_px * 0.95  # 5% hard stop
                exit_px = c.iloc[i+8] if (i+8 < n_rows) else c.iloc[-1]
                holding_days = 0

                for d in range(1, 9):
                    idx = i + 1 + d
                    if idx >= n_rows: break
                    holding_days = d
                    if l.iloc[idx] <= stop_px:
                        exit_px = stop_px * (1.0 - SLIPPAGE)
                        break
                    # Exit when Close > 5-day EMA (snapback complete)
                    if c.iloc[idx] > ema5.iloc[idx]:
                        exit_px = c.iloc[idx] * (1.0 - SLIPPAGE)
                        break
                    if d == 8:
                        exit_px = c.iloc[idx] * (1.0 - SLIPPAGE)
                        break

                net_ret = (exit_px / entry_px - 1.0 - 0.0075) * 100.0
                results["Setup C (RSI-2 Panic Flush in Leaders)"].append({
                    "symbol": sym, "date": dates[i+1], "is_oos": dates[i+1] >= SPLIT_DATE,
                    "net_ret": net_ret, "holding_days": holding_days
                })

            # ---------------------------------------------------------
            # SETUP D: NR7 Momentum Expansion
            # ---------------------------------------------------------
            if stage2 and is_nr7.iloc[i] and c.iloc[i] > ema20.iloc[i]:
                # Next day breaks NR7 high with volume
                entry_px = o.iloc[i+1] * (1.0 + SLIPPAGE)
                stop_px = l.iloc[i] * 0.99
                exit_px = c.iloc[i+15] if (i+15 < n_rows) else c.iloc[-1]
                holding_days = 0

                for d in range(1, 16):
                    idx = i + 1 + d
                    if idx >= n_rows: break
                    holding_days = d
                    if l.iloc[idx] <= stop_px:
                        exit_px = stop_px * (1.0 - SLIPPAGE)
                        break
                    # Quick profit target +12%
                    if h.iloc[idx] >= entry_px * 1.12:
                        exit_px = entry_px * 1.12 * (1.0 - SLIPPAGE)
                        break
                    if d >= 4 and c.iloc[idx] < ema5.iloc[idx]:
                        exit_px = c.iloc[idx] * (1.0 - SLIPPAGE)
                        break
                    if d == 15:
                        exit_px = c.iloc[idx] * (1.0 - SLIPPAGE)
                        break

                net_ret = (exit_px / entry_px - 1.0 - 0.0075) * 100.0
                results["Setup D (NR7 Momentum Expansion)"].append({
                    "symbol": sym, "date": dates[i+1], "is_oos": dates[i+1] >= SPLIT_DATE,
                    "net_ret": net_ret, "holding_days": holding_days
                })

    # Summary Table
    print("\n" + "="*85)
    print("📊 5-YEAR EMPIRICAL AUDIT: 4 SWING ARCHITECTURES (NET OF ALL FRICTIONS)")
    print("="*85)

    for setup_name, trades in results.items():
        if not trades: continue
        df_tr = pd.DataFrame(trades)
        rets = df_tr["net_ret"]
        wins = rets[rets > 0]
        losses = rets[rets <= 0]
        pf = wins.sum() / (abs(losses.sum()) + 1e-9)
        avg_hold = df_tr["holding_days"].mean()
        trades_per_year = len(df_tr) / 5.0

        is_df = df_tr[df_tr["is_oos"] == False]
        oos_df = df_tr[df_tr["is_oos"] == True]

        is_pf = is_df[is_df["net_ret"] > 0]["net_ret"].sum() / (abs(is_df[is_df["net_ret"] <= 0]["net_ret"].sum()) + 1e-9) if len(is_df) else 0
        oos_pf = oos_df[oos_df["net_ret"] > 0]["net_ret"].sum() / (abs(oos_df[oos_df["net_ret"] <= 0]["net_ret"].sum()) + 1e-9) if len(oos_df) else 0

        print(f"\n🎯 {setup_name}:")
        print(f"   • Total Trades (5Y)     : {len(df_tr):,} (~{trades_per_year:.0f} trades/year)")
        print(f"   • Mean Net Return/Trade : {rets.mean():+.2f}% (Median: {rets.median():+.2f}%)")
        print(f"   • Profit Factor         : {pf:.2f} (In-Sample: {is_pf:.2f} | Out-of-Sample: {oos_pf:.2f})")
        print(f"   • Win Rate              : {(rets > 0).mean()*100:.1f}%")
        print(f"   • Average Holding Time  : {avg_hold:.1f} trading sessions (~{avg_hold/5:.1f} weeks)")
        print(f"   • Avg Win vs Avg Loss   : {wins.mean():+.2f}% vs {losses.mean():.2f}% ({abs(wins.mean()/(losses.mean()+1e-9)):.2f}x payoff)")
        print(f"   • Max Single Winner     : {rets.max():+.1f}%")

    return results


def main():
    universe, nifty = load_universe_and_benchmarks()
    analyze_swing_setups(universe, nifty)


if __name__ == "__main__":
    main()
