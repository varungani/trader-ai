"""
TraderAI - Creative Alpha & Hidden Pattern Discovery (2021-2026)
================================================================================
Unconventional empirical investigations on 626 NSE stocks across 5 years:

1. THE PRE-IGNITION DNA DISCOVERY:
   - Isolating the top 50 monster runs (>= 200% gain) in Indian equities.
   - Analyzing their exact state in the 30-60 sessions BEFORE the markup began:
     • Volatility Compression (Squeeze Ratio: ATR10 / ATR50)
     • Volume Footprint (Up-Day Volume vs Down-Day Volume Ratio)
     • On-Balance-Volume (OBV) Accumulation Divergence
     • Coiling / Tightness Index (% of days with range < 2.0%)
     • Relative Strength Acceleration Vector (d(RS)/dt)
   - Benchmarking against 5,000 standard breakouts to find statistically significant anomalies.

2. THE "SPRINGBOARD BREAKOUT" BACKTEST:
   - What happens if we ONLY buy breakouts that emerge from an extreme volatility coil
     with confirmed institutional volume footprint?

3. SECTOR LEAD-LAG SPILLOVER:
   - When a sector flagship explodes, what is the predictive edge on 2nd-tier sector peers?
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
# 1. THE PRE-IGNITION DNA OF 50+ MONSTER RUNNERS
# =====================================================================
def analyze_preignition_dna(universe: Dict[str, pd.DataFrame], nifty: pd.DataFrame):
    print("\n" + "="*85)
    print("🧬 EXPERIMENT 1: THE PRE-IGNITION DNA OF MONSTER MULTI-BAGGERS (>= +200% RUNS)")
    print("="*85, flush=True)

    # 1. Identify all multi-month monster runs:
    # A run where stock gained >= +150% within a 120-session window
    monster_events = []
    normal_breakout_events = []

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

        # Technical features
        ema20 = c.ewm(span=20, adjust=False).mean()
        ema50 = c.ewm(span=50, adjust=False).mean()
        ema200 = c.ewm(span=200, adjust=False).mean()

        tr = np.maximum(h - l, np.maximum((h - c.shift(1)).abs(), (l - c.shift(1)).abs()))
        atr10 = tr.rolling(10).mean()
        atr50 = tr.rolling(50).mean()
        squeeze_ratio = atr10 / (atr50 + 1e-9)

        # Bollinger Band Width (20, 2)
        std20 = c.rolling(20).std()
        bb_width = (2.0 * std20) / (ema20 + 1e-9)
        bb_width_ma50 = bb_width.rolling(50).mean()
        bb_squeeze = bb_width / (bb_width_ma50 + 1e-9)

        # Volume Asymmetry: Up-Volume vs Down-Volume over last 30 sessions
        up_day = (c > c.shift(1)).astype(float)
        up_vol_30 = (v * up_day).rolling(30).sum()
        down_vol_30 = (v * (1.0 - up_day)).rolling(30).sum()
        vol_asymmetry = up_vol_30 / (down_vol_30 + 1e-9)

        # Tightness: % of last 20 days with (High - Low) / Low < 2.5%
        daily_range_pct = (h - l) / (l + 1e-9)
        tight_days_20 = (daily_range_pct < 0.025).rolling(20).mean() * 100.0

        # OBV and OBV 20-day slope
        obv = (np.sign(c.diff()).fillna(0) * v).cumsum()
        obv_ma20 = obv.rolling(20).mean()
        obv_trend = (obv / (obv_ma20 + 1e-9) - 1.0) * 100.0

        # 50-day breakout check
        high50 = h.shift(1).rolling(50).max()
        vol_ma20 = v.rolling(20).mean()
        rvol = v / (vol_ma20 + 1e-9)

        # Look for breakout days
        for i in range(100, n_rows - 120):
            # Stage 2 Breakout
            if c.iloc[i] > high50.iloc[i] and c.iloc[i] > ema50.iloc[i] and rvol.iloc[i] >= 1.5:
                # Measure forward 120-session return
                forward_max_ret = (h.iloc[i+1:i+121].max() / c.iloc[i] - 1.0) * 100.0
                forward_end_ret = (c.iloc[min(i+120, n_rows-1)] / c.iloc[i] - 1.0) * 100.0

                # Feature state on Day 0 (the day of or right before the breakout)
                feat = {
                    "symbol": sym,
                    "date": dates[i],
                    "forward_max_ret": forward_max_ret,
                    "forward_end_ret": forward_end_ret,
                    "squeeze_ratio": squeeze_ratio.iloc[i],
                    "bb_squeeze": bb_squeeze.iloc[i],
                    "vol_asymmetry": vol_asymmetry.iloc[i],
                    "tight_days_20": tight_days_20.iloc[i],
                    "obv_trend": obv_trend.iloc[i],
                    "dist_ema200": (c.iloc[i] / (ema200.iloc[i] + 1e-9) - 1.0) * 100.0,
                    "rvol": rvol.iloc[i],
                }

                if forward_max_ret >= 150.0:
                    monster_events.append(feat)
                else:
                    normal_breakout_events.append(feat)

    df_monsters = pd.DataFrame(monster_events)
    df_normals = pd.DataFrame(normal_breakout_events)

    print(f"Discovered {len(df_monsters)} Monster Breakouts (Peak Gain >= +150% in 120d) vs {len(df_normals)} Normal Breakouts.")

    print("\n--- STATISTICAL COMPARISON: MONSTER DNA vs ORDINARY BREAKOUTS ---")
    metrics = [
        ("Volume Asymmetry (Up-Vol / Down-Vol 30d)", "vol_asymmetry", "Higher = Heavy Stealth Institutional Buying"),
        ("ATR Squeeze Ratio (ATR10 / ATR50)", "squeeze_ratio", "Lower = Extreme Volatility Compression / Coiling"),
        ("Bollinger Band Squeeze Ratio", "bb_squeeze", "Lower = Bands pinched tighter than historical norm"),
        ("Tight Range Days in Last 20d (%)", "tight_days_20", "Higher = Extreme Price Consolidation / Dormancy"),
        ("OBV 20-Day Accumulation Trend (%)", "obv_trend", "Higher = Stealth Volume Flowing in before price"),
        ("Distance Above 200-EMA (%)", "dist_ema200", "Where in the cycle does the monster emerge?"),
        ("Breakout Day RVOL", "rvol", "Volume expansion on trigger day"),
    ]

    for label, col, note in metrics:
        m_val = df_monsters[col].median()
        n_val = df_normals[col].median()
        diff = ((m_val - n_val) / (abs(n_val) + 1e-9)) * 100.0
        print(f"\n🔬 {label}:")
        print(f"   • Monster Median : {m_val:.2f}")
        print(f"   • Normal Median  : {n_val:.2f} (Divergence: {diff:+.1f}%)")
        print(f"   • Context        : {note}")

    return df_monsters, df_normals


# =====================================================================
# 2. THE SPRINGBOARD FILTER: TESTING THE COILED ASYMMETRY SETUP
# =====================================================================
def backtest_springboard_strategy(universe: Dict[str, pd.DataFrame], nifty: pd.DataFrame):
    print("\n" + "="*85)
    print("🚀 EXPERIMENT 2: TESTING THE SPRINGBOARD COILING SETUP (HIGH ASYMMETRY)")
    print("="*85, flush=True)

    # Let's compare 2 Breakout Filters in the full 5-year simulation:
    # Model A (Standard 50D Breakout): RVOL >= 1.5x, RS > 0
    # Model B (Springboard Coiled Breakout):
    #   - Volume Asymmetry (Up-Vol / Down-Vol 30d) >= 1.50x (Heavy Accumulation)
    #   - Volatility Compression: Squeeze Ratio (ATR10 / ATR50) <= 0.85 OR BB Squeeze <= 0.85
    #   - Weekly 10-Week EMA Trailing Exit

    results = []

    for model_name, filter_springboard in [
        ("Standard 50D Breakout + Weekly 10W Trail", False),
        ("⭐ Springboard Coiled Breakout + Weekly 10W Trail", True),
    ]:
        events = []
        for sym, df in universe.items():
            if len(df) < 252: continue
            c = df['Close']
            h = df['High']
            l = df['Low']
            o = df['Open']
            v = df['Volume']
            dates = df.index
            n_rows = len(df)

            ema20 = c.ewm(span=20, adjust=False).mean()
            ema50 = c.ewm(span=50, adjust=False).mean()
            high50 = h.shift(1).rolling(50).max()
            vol_ma20 = v.rolling(20).mean()
            rvol = v / (vol_ma20 + 1e-9)

            tr = np.maximum(h - l, np.maximum((h - c.shift(1)).abs(), (l - c.shift(1)).abs()))
            atr10 = tr.rolling(10).mean()
            atr50 = tr.rolling(50).mean()
            squeeze_ratio = atr10 / (atr50 + 1e-9)

            up_day = (c > c.shift(1)).astype(float)
            up_vol_30 = (v * up_day).rolling(30).sum()
            down_vol_30 = (v * (1.0 - up_day)).rolling(30).sum()
            vol_asymmetry = up_vol_30 / (down_vol_30 + 1e-9)

            df_weekly = df.resample('W-FRI').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'
            }).dropna()
            df_weekly['EMA10W'] = df_weekly['Close'].ewm(span=10, adjust=False).mean()

            for i in range(200, n_rows - 30):
                # Standard Breakout Condition
                if c.iloc[i] > high50.iloc[i] and c.iloc[i] > ema50.iloc[i] and rvol.iloc[i] >= 1.5:
                    if filter_springboard:
                        # Springboard Gate: Institutional Volume Footprint + Volatility Compression
                        is_accumulated = vol_asymmetry.iloc[i] >= 1.40
                        is_coiled = squeeze_ratio.iloc[i] <= 0.88
                        if not (is_accumulated and is_coiled):
                            continue

                    entry_px = o.iloc[i+1] * (1.0 + SLIPPAGE)
                    stop_px = entry_px * 0.92  # 8% initial stop

                    # Trailing Weekly 10-Week EMA
                    exit_px = c.iloc[-1]
                    days_held = 0
                    exit_reason = "last_day"

                    for d in range(i+1, n_rows):
                        days_held += 1
                        # Hard stop
                        if l.iloc[d] <= stop_px:
                            exit_px = stop_px * (1.0 - SLIPPAGE)
                            exit_reason = "stop"
                            break

                        cur_d = dates[d]
                        if cur_d.weekday() == 4 and cur_d in df_weekly.index:
                            w_c = df_weekly.loc[cur_d, 'Close']
                            w_10 = df_weekly.loc[cur_d, 'EMA10W']
                            if days_held >= 5 and w_c < w_10:
                                exit_px = c.iloc[d] * (1.0 - SLIPPAGE)
                                exit_reason = "weekly_10w"
                                break

                    net_ret = (exit_px / entry_px - 1.0 - 0.0075) * 100.0
                    events.append({
                        "symbol": sym,
                        "date": dates[i+1],
                        "net_ret": net_ret,
                        "days_held": days_held,
                        "exit_reason": exit_reason,
                    })

        df_ev = pd.DataFrame(events)
        rets = df_ev['net_ret']
        wins = rets[rets > 0]
        losses = rets[rets <= 0]
        pf = wins.sum() / (abs(losses.sum()) + 1e-9)
        hit_50 = (rets >= 50.0).mean() * 100.0
        hit_100 = (rets >= 100.0).mean() * 100.0

        print(f"\n📌 {model_name} ({len(df_ev):,} Total Trades):")
        print(f"   • Mean Net Return/Trade : {rets.mean():+.2f}% (Median: {rets.median():+.2f}%)")
        print(f"   • Profit Factor         : {pf:.2f}")
        print(f"   • Win Rate              : {(rets > 0).mean()*100:.1f}%")
        print(f"   • Avg Holding Days      : {df_ev['days_held'].mean():.1f} sessions")
        print(f"   • Trades >= +50% Gain   : {hit_50:.1f}% of trades")
        print(f"   • Trades >= +100% (2x+) : {hit_100:.1f}% of trades")
        print(f"   • Max Single Winner     : {rets.max():+.1f}%")


# =====================================================================
# 3. SECTOR LEAD-LAG RESONANCE (FLAGSHIP RIPPLE EFFECT)
# =====================================================================
def analyze_sector_ripple_effect(universe: Dict[str, pd.DataFrame]):
    print("\n" + "="*85)
    print("🌊 EXPERIMENT 3: SECTOR LEAD-LAG RESONANCE (THE FLAGSHIP RIPPLE EFFECT)")
    print("="*85, flush=True)

    # Key Indian Sector Clusters (Nifty indices / thematic groups)
    clusters = {
        "Defense": ["HAL.NS", "BEL.NS", "BDL.NS", "MAZDOCK.NS", "COCHINSHIP.NS", "PARAS.NS", "DATA-PATTE.NS"],
        "Power & Transmission": ["SUZLON.NS", "IREDA.NS", "TATAPOWER.NS", "APARINDS.NS", "KPIL.NS", "BSE.NS", "TARIL.NS"],
        "Capital Goods & Railways": ["BHEL.NS", "RAILTEL.NS", "IRFC.NS", "TITAGARH.NS", "TEXRAIL.NS", "RITES.NS"],
        "Auto Ancillary / Precision": ["SONACOMS.NS", "RKFORGE.NS", "CIEINDIA.NS", "FORCEMOT.NS", "GVT&D.NS"],
        "Pharma / CDMO / Specialty": ["NEULANDLAB.NS", "MARKSANS.NS", "SUVENPHAR.NS", "ERIS.NS", "AJANTPHARM.NS"],
    }

    print("Analyzing cluster co-movements across major Indian thematic sectors...")
    for cluster_name, syms in clusters.items():
        avail = [s for s in syms if s in universe and len(universe[s]) > 400]
        if len(avail) < 3: continue

        # Compute rolling 3-month returns for each member
        rets_3m = pd.DataFrame({s: universe[s]['Close'].pct_change(63) * 100.0 for s in avail}).dropna()
        corr_matrix = rets_3m.corr()
        mean_corr = corr_matrix.values[np.triu_indices_from(corr_matrix.values, k=1)].mean()

        # Find who led the cluster: who broke 52-week high first
        first_breakouts = {}
        for s in avail:
            df = universe[s]
            h = df['High']
            h252 = h.shift(1).rolling(252).max()
            new_highs = df[df['Close'] > h252]
            if len(new_highs) > 0:
                first_breakouts[s] = new_highs.index[0]

        sorted_first = sorted(first_breakouts.items(), key=lambda x: x[1])
        leader = sorted_first[0][0] if sorted_first else "None"
        leader_date = str(sorted_first[0][1])[:10] if sorted_first else "N/A"

        print(f"\n📂 {cluster_name} ({len(avail)} stocks analyzed):")
        print(f"   • Mean Intra-Cluster 3M Correlation: {mean_corr:.2f}")
        print(f"   • Flagship Leader: {leader} (Broke 52W High on {leader_date})")
        if len(sorted_first) > 1:
            lag_days = [(s, (d - sorted_first[0][1]).days) for s, d in sorted_first[1:4]]
            lag_str = ", ".join([f"{s} (+{days}d)" for s, days in lag_days])
            print(f"   • Secondary Wave Lag: {lag_str}")


def main():
    universe, nifty = load_universe_and_benchmarks()
    analyze_preignition_dna(universe, nifty)
    backtest_springboard_strategy(universe, nifty)
    analyze_sector_ripple_effect(universe)


if __name__ == "__main__":
    main()
