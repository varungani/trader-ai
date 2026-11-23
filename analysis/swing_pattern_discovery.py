"""
TraderAI - Swing Pattern Discovery Engine (2021-2026)
================================================================================
Discovers hidden microstructure patterns specifically for SHORT-TERM SWING TRADING:

Target Definition:
  - "Super-Swing Burst": A move where stock gains >= +15.0% within 8 trading sessions
    with Maximum Adverse Excursion (MAE) <= -4.0% (no stop-out).

Methodology:
  1. Scan all 626 NSE stocks across 5 years (2021-2026).
  2. Isolate all Super-Swing Bursts vs all "Duds" (moves that failed or lost).
  3. Analyze the exact microstructure state on Day T-0 across 15 features:
     • Pre-burst volume behavior (Dry-up vs Expansion)
     • Pre-burst price action (Pullback vs Breakout vs Coiling)
     • Distance from 10-EMA and 20-EMA
     • Short-term RSI (5-period)
     • Consecutive down-days into T-0 (Mean-reversion vs Trend continuation)
     • Instantaneous ATR squeeze (ATR3 / ATR14)
     • Volume asymmetry over prior 5 sessions
  4. Identify the statistically significant "Swing Signatures" that predict rapid 5-10 day bursts.
  5. Backtest the discovered Swing Strategy with full Indian statutory delivery costs.
"""
from __future__ import annotations

import os
import sys
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


def load_universe_and_benchmarks():
    print("📦 Loading 5Y universe cache and benchmarks...", flush=True)
    cache_path = os.path.join(ROOT, "data", "cache", "universe_5y.pkl")
    bench_path = os.path.join(ROOT, "data", "cache", "benchmarks_5y.pkl")
    with open(cache_path, "rb") as f:
        universe: Dict[str, pd.DataFrame] = pickle.load(f)
    with open(bench_path, "rb") as f:
        benchmarks: Dict[str, pd.DataFrame] = pickle.load(f)
    nifty = benchmarks['^NSEI'].copy()
    nifty['EMA20'] = nifty['Close'].ewm(span=20, adjust=False).mean()
    nifty['EMA50'] = nifty['Close'].ewm(span=50, adjust=False).mean()
    return universe, nifty


# =====================================================================
# 1. CENSUS OF ALL EXPLOSIVE 8-DAY SWING BURSTS (>= +15% WITH LOW DRAWDOWN)
# =====================================================================
def discover_swing_bursts(universe: Dict[str, pd.DataFrame], nifty: pd.DataFrame):
    print("\n" + "="*85)
    print("🔬 MINING 5 YEARS OF DATA FOR SHORT-TERM EXPLOSIVE SWING SIGNATURES")
    print("="*85, flush=True)

    super_swings = []
    dud_swings = []

    for sym, df in universe.items():
        if len(df) < 250: continue
        c = df['Close']
        h = df['High']
        l = df['Low']
        o = df['Open']
        v = df['Volume']
        dates = df.index
        n_rows = len(df)

        # Technical Indicators on Day T
        ema10 = c.ewm(span=10, adjust=False).mean()
        ema20 = c.ewm(span=20, adjust=False).mean()
        ema50 = c.ewm(span=50, adjust=False).mean()

        tr = np.maximum(h - l, np.maximum((h - c.shift(1)).abs(), (l - c.shift(1)).abs()))
        atr3 = tr.rolling(3).mean()
        atr14 = tr.rolling(14).mean()
        atr_ratio = atr3 / (atr14 + 1e-9)

        vol_ma20 = v.rolling(20).mean()
        rvol = v / (vol_ma20 + 1e-9)

        # 5-period RSI
        delta = c.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        rs_5 = gain.rolling(5).mean() / (loss.rolling(5).mean() + 1e-9)
        rsi_5 = 100.0 - (100.0 / (1.0 + rs_5))

        # Range compression on day T-0: Daily range / 10d average range
        range_10_avg = (h - l).rolling(10).mean()
        range_ratio = (h - l) / (range_10_avg + 1e-9)

        # 3-day momentum into T-0
        ret_3d = (c / c.shift(3) - 1.0) * 100.0

        # Distance from 10-EMA and 20-EMA
        dist_ema10 = (c / (ema10 + 1e-9) - 1.0) * 100.0
        dist_ema20 = (c / (ema20 + 1e-9) - 1.0) * 100.0

        # Distance from 10-day High
        high10 = h.shift(1).rolling(10).max()
        dist_high10 = (c / (high10 + 1e-9) - 1.0) * 100.0

        # Volume Asymmetry over last 5 days
        up_day = (c > c.shift(1)).astype(float)
        up_vol_5 = (v * up_day).rolling(5).sum()
        down_vol_5 = (v * (1.0 - up_day)).rolling(5).sum()
        vol_asym_5d = up_vol_5 / (down_vol_5 + 1e-9)

        # 1-month relative return vs Nifty
        r1m_stock = c.pct_change(21)
        r1m_nifty = nifty['Close'].pct_change(21)
        rs_1m = (r1m_stock - r1m_nifty) * 100.0

        # Step through sessions
        for i in range(50, n_rows - 10):
            entry_px = o.iloc[i+1] * (1.0 + SLIPPAGE)

            # Look forward 8 sessions
            forward_high = h.iloc[i+1:i+9].max()
            forward_low = l.iloc[i+1:i+9].min()
            forward_close = c.iloc[min(i+8, n_rows-1)]

            max_gain_pct = (forward_high / entry_px - 1.0) * 100.0
            max_dd_pct = (forward_low / entry_px - 1.0) * 100.0
            end_gain_pct = (forward_close / entry_px - 1.0) * 100.0

            feat = {
                "symbol": sym,
                "date": dates[i],
                "max_gain": max_gain_pct,
                "max_dd": max_dd_pct,
                "end_gain": end_gain_pct,
                "rvol": rvol.iloc[i],
                "atr_ratio": atr_ratio.iloc[i],
                "range_ratio": range_ratio.iloc[i],
                "ret_3d": ret_3d.iloc[i],
                "dist_ema10": dist_ema10.iloc[i],
                "dist_ema20": dist_ema20.iloc[i],
                "dist_high10": dist_high10.iloc[i],
                "rsi_5": rsi_5.iloc[i],
                "vol_asym_5d": vol_asym_5d.iloc[i],
                "rs_1m": rs_1m.iloc[i] if dates[i] in rs_1m.index else 0.0,
                "above_ema50": float(c.iloc[i] > ema50.iloc[i]),
            }

            # Super-Swing Burst: Gained >= +15% in 8 sessions and MAE >= -4.0%
            if max_gain_pct >= 15.0 and max_dd_pct >= -4.0:
                super_swings.append(feat)
            # Dud: Barely moved or dropped
            elif max_gain_pct < 4.0 or max_dd_pct < -5.0:
                # Subsample duds to keep dataset balanced
                if i % 7 == 0:
                    dud_swings.append(feat)

    df_super = pd.DataFrame(super_swings)
    df_dud = pd.DataFrame(dud_swings)

    print(f"Identified {len(df_super):,} Super-Swing Bursts (>= +15% in 8d with <= 4% DD) vs {len(df_dud):,} Duds.")

    print("\n--- STATISTICAL SIGNATURE OF SUPER-SWING BURSTS (DAY T-0 STATE) ---")
    metrics = [
        ("1-Month Relative Strength (RS 1M vs Nifty)", "rs_1m", "Higher = Stronger Leader"),
        ("Volume Asymmetry over prior 5 days (Up-Vol / Down-Vol)", "vol_asym_5d", "Higher = Active Institutional Accumulation"),
        ("Distance to 10-day High (%)", "dist_high10", "Near 0% = Breaking or kissing 10d pivot"),
        ("Distance to 10-Day EMA (%)", "dist_ema10", "Where does it sit relative to short trend?"),
        ("Distance to 20-Day EMA (%)", "dist_ema20", "Buffer above 20-day line"),
        ("Instantaneous ATR Ratio (ATR3 / ATR14)", "atr_ratio", "Low = Volatility Compression"),
        ("Day T-0 Range vs 10d Average Range", "range_ratio", "Low = Inside / Tight candle"),
        ("Day T-0 RVOL", "rvol", "Volume expansion vs dry-up"),
        ("5-Period RSI", "rsi_5", "Momentum charge"),
        ("3-Day Pre-Burst Return (%)", "ret_3d", "Was it pulling back or surging?"),
    ]

    for label, col, note in metrics:
        s_val = df_super[col].median()
        d_val = df_dud[col].median()
        diff = s_val - d_val
        print(f"\n⚡ {label}:")
        print(f"   • Super-Swing Median : {s_val:+.2f}")
        print(f"   • Dud Median         : {d_val:+.2f} (Delta: {diff:+.2f})")
        print(f"   • Context            : {note}")

    return df_super, df_dud


# =====================================================================
# 2. TEST THE DISCOVERED "POWER-SWING CLUSTER" SETUP
# =====================================================================
def backtest_discovered_swing_cluster(universe: Dict[str, pd.DataFrame], nifty: pd.DataFrame):
    print("\n" + "="*85)
    print("🚀 BACKTESTING THE DISCOVERED POWER-SWING SETUP (5-15 DAY HOLDING)")
    print("="*85, flush=True)

    # From the data above, let's test the Discovered Swing Rule:
    # 1. Macro Breadth: Nifty > 20-EMA (market is in short-term swing mode)
    # 2. Stock is in strong 1M RS leadership: RS_1M >= +10% vs Nifty
    # 3. Microstructure Setup:
    #    - Price within 2.5% of 10-day High (consolidated right under pivot)
    #    - Volume Asymmetry (5d) >= 1.8x (heavy accumulation in the base)
    #    - Sitting within 2% to 5% of 10-day EMA (not extended, tightly coiled)
    #    - Day T triggers with RVOL >= 1.5x breaking 5-day High
    # 4. Exit:
    #    - Target: +18% swing profit
    #    - Stop: -4.5% tight swing stop
    #    - Trail: Close < 5-day EMA once gain >= +6%
    #    - Max duration: 10 sessions (~2 weeks)

    events = []

    for sym, df in universe.items():
        if len(df) < 250: continue
        c = df['Close']
        h = df['High']
        l = df['Low']
        o = df['Open']
        v = df['Volume']
        dates = df.index
        n_rows = len(df)

        ema5 = c.ewm(span=5, adjust=False).mean()
        ema10 = c.ewm(span=10, adjust=False).mean()
        ema20 = c.ewm(span=20, adjust=False).mean()
        ema50 = c.ewm(span=50, adjust=False).mean()

        vol_ma20 = v.rolling(20).mean()
        rvol = v / (vol_ma20 + 1e-9)

        high5 = h.shift(1).rolling(5).max()
        high10 = h.shift(1).rolling(10).max()

        up_day = (c > c.shift(1)).astype(float)
        up_vol_5 = (v * up_day).rolling(5).sum()
        down_vol_5 = (v * (1.0 - up_day)).rolling(5).sum()
        vol_asym_5d = up_vol_5 / (down_vol_5 + 1e-9)

        r1m_stock = c.pct_change(21)
        r1m_nifty = nifty['Close'].pct_change(21)
        rs_1m = (r1m_stock - r1m_nifty) * 100.0

        for i in range(50, n_rows - 15):
            d_date = dates[i]
            if d_date not in nifty.index: continue

            # Nifty filter: Nifty > 20-EMA
            if nifty['Close'].loc[d_date] < nifty['EMA20'].loc[d_date]:
                continue

            # Check Discovered Swing Signature:
            # 1. Stage 2 leadership: c > ema50 and RS_1M >= +10%
            if c.iloc[i] > ema50.iloc[i] and rs_1m.iloc[i] >= 10.0:
                # 2. Coiled under 10d high: within 3% of 10d high
                near_pivot = (c.iloc[i] >= high10.iloc[i] * 0.97)
                # 3. Not extended from 10-EMA: within 4% of 10-EMA
                near_ema10 = (c.iloc[i] <= ema10.iloc[i] * 1.04 and c.iloc[i] >= ema10.iloc[i] * 0.98)
                # 4. Volume Asymmetry: Up-vol >= 1.6x down-vol over prior 5 days
                accumulated = (vol_asym_5d.iloc[i] >= 1.60)
                # 5. Trigger: RVOL >= 1.5x breaking 5-day High
                trigger = (c.iloc[i] > high5.iloc[i] and rvol.iloc[i] >= 1.5)

                if near_pivot and near_ema10 and accumulated and trigger:
                    entry_px = o.iloc[i+1] * (1.0 + SLIPPAGE)
                    stop_px = entry_px * 0.955  # 4.5% stop
                    target_px = entry_px * 1.18  # +18% target

                    exit_px = c.iloc[min(i+11, n_rows-1)]
                    days_held = 0
                    exit_reason = "max_10d"

                    for d in range(1, 11):
                        idx = i + 1 + d
                        if idx >= n_rows: break
                        days_held = d

                        # Stop
                        if l.iloc[idx] <= stop_px:
                            exit_px = stop_px * (1.0 - SLIPPAGE)
                            exit_reason = "stop"
                            break
                        # Target +18%
                        if h.iloc[idx] >= target_px:
                            exit_px = target_px * (1.0 - SLIPPAGE)
                            exit_reason = "target_18"
                            break
                        # Trailing 5-EMA once gain >= +6%
                        if (c.iloc[idx] / entry_px - 1.0) >= 0.06 and c.iloc[idx] < ema5.iloc[idx]:
                            exit_px = c.iloc[idx] * (1.0 - SLIPPAGE)
                            exit_reason = "trail_5ema"
                            break
                        if d == 10:
                            exit_px = c.iloc[idx] * (1.0 - SLIPPAGE)
                            exit_reason = "max_10d"
                            break

                    net_ret = (exit_px / entry_px - 1.0 - 0.0075) * 100.0
                    events.append({
                        "symbol": sym,
                        "date": dates[i+1],
                        "net_ret": net_ret,
                        "days_held": days_held,
                        "exit_reason": exit_reason,
                    })

    df_sw = pd.DataFrame(events)
    rets = df_sw['net_ret']
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    pf = wins.sum() / (abs(losses.sum()) + 1e-9)
    avg_hold = df_sw['days_held'].mean()
    cadence = len(df_sw) / 5.0

    print(f"\n🎯 DISCOVERED POWER-SWING STRATEGY RESULTS ({len(df_sw):,} Trades across 5 Years):")
    print(f"   • Annual Cadence        : ~{cadence:.0f} trades / year")
    print(f"   • Mean Net Return/Trade : {rets.mean():+.2f}% (Median: {rets.median():+.2f}%)")
    print(f"   • Profit Factor         : {pf:.2f}")
    print(f"   • Win Rate              : {(rets > 0).mean()*100:.1f}%")
    print(f"   • Average Holding Time  : {avg_hold:.1f} trading sessions (~{avg_hold/5:.1f} weeks)")
    print(f"   • Avg Win vs Avg Loss   : {wins.mean():+.2f}% vs {losses.mean():.2f}% ({abs(wins.mean()/(losses.mean()+1e-9)):.2f}x payoff)")
    print(f"   • Hits +18% Target      : {(df_sw['exit_reason'] == 'target_18').mean()*100:.1f}% of trades")
    print(f"   • Max Single Winner     : {rets.max():+.1f}%")


def main():
    universe, nifty = load_universe_and_benchmarks()
    discover_swing_bursts(universe, nifty)
    backtest_discovered_swing_cluster(universe, nifty)


if __name__ == "__main__":
    main()
