"""
TraderAI - Base-on-Base Compounding Deep Dive (2021-2026)
================================================================================
Empirical Test of William O'Neil / Mark Minervini's "Base-on-Base" Phenomenon:
Does buying a secondary breakout (Base 2 / Base 3) of an established monster runner
outperform or underperform primary (Base 1) breakouts in Indian equities?

Metrics:
  - Base 1 vs Base 2 vs Base 3+ Win Rate, Profit Factor, Mean Return
  - Risk of failure: Does the base fail more often the higher it gets?
"""
import os
import sys
import pickle
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SLIPPAGE = 0.0025

cache_path = os.path.join(ROOT, "data", "cache", "universe_5y.pkl")
with open(cache_path, "rb") as f:
    universe = pickle.load(f)

print(f"Loaded {len(universe)} stocks. Analyzing Base-on-Base progressions...", flush=True)

base_1_trades = []
base_2_trades = []
base_3plus_trades = []

for sym, df in universe.items():
    if len(df) < 300: continue
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

    df_w = df.resample('W-FRI').agg({'Close': 'last'}).dropna()
    df_w['EMA10W'] = df_w['Close'].ewm(span=10, adjust=False).mean()

    # Track base count
    current_base = 0
    last_breakout_idx = -999

    for i in range(150, n_rows - 30):
        # 50-day breakout with volume in Stage 2
        if c.iloc[i] > high50.iloc[i] and c.iloc[i] > ema50.iloc[i] and rvol.iloc[i] >= 1.5:
            # Check elapsed time since last breakout
            elapsed_sessions = i - last_breakout_idx

            if elapsed_sessions > 120 or current_base == 0:
                # Reset to Base 1 (fresh cycle or new trend after long consolidation)
                current_base = 1
            elif 15 <= elapsed_sessions <= 120:
                # Secondary Base (Base-on-Base)
                current_base += 1
            else:
                # Too close (less than 15 days), just continuation noise
                continue

            last_breakout_idx = i

            entry_px = o.iloc[i+1] * (1.0 + SLIPPAGE)
            stop_px = entry_px * 0.92  # 8% stop

            exit_px = c.iloc[-1]
            days_held = 0
            for d in range(i+1, n_rows):
                days_held += 1
                if l.iloc[d] <= stop_px:
                    exit_px = stop_px * (1.0 - SLIPPAGE)
                    break
                cur_d = dates[d]
                if cur_d.weekday() == 4 and cur_d in df_w.index:
                    w_c = df_w.loc[cur_d, 'Close']
                    w_10 = df_w.loc[cur_d, 'EMA10W']
                    if days_held >= 5 and w_c < w_10:
                        exit_px = c.iloc[d] * (1.0 - SLIPPAGE)
                        break

            net_ret = (exit_px / entry_px - 1.0 - 0.0075) * 100.0
            trade_info = {
                "symbol": sym,
                "date": dates[i+1],
                "base_num": current_base,
                "net_ret": net_ret,
                "days_held": days_held,
            }

            if current_base == 1:
                base_1_trades.append(trade_info)
            elif current_base == 2:
                base_2_trades.append(trade_info)
            else:
                base_3plus_trades.append(trade_info)

df_b1 = pd.DataFrame(base_1_trades)
df_b2 = pd.DataFrame(base_2_trades)
df_b3 = pd.DataFrame(base_3plus_trades)

print("\n" + "="*80)
print("📊 BASE-ON-BASE PROGRESSION AUDIT ACROSS 5 YEARS (2021-2026)")
print("="*80)

for label, df_sub in [
    ("Base 1 (Primary Breakout - Fresh Stage 2)", df_b1),
    ("Base 2 (Secondary Breakout - Base-on-Base)", df_b2),
    ("Base 3+ (Late-Stage Extended Breakout)", df_b3),
]:
    r = df_sub["net_ret"]
    w = r[r > 0]
    l = r[r <= 0]
    pf = w.sum() / (abs(l.sum()) + 1e-9)
    hit_50 = (r >= 50.0).mean() * 100.0
    hit_100 = (r >= 100.0).mean() * 100.0

    print(f"\n📌 {label} ({len(df_sub):,} Trades):")
    print(f"   • Mean Net Return/Trade : {r.mean():+.2f}% (Median: {r.median():+.2f}%)")
    print(f"   • Profit Factor         : {pf:.2f}")
    print(f"   • Win Rate              : {(r > 0).mean()*100:.1f}%")
    print(f"   • Avg Holding Days      : {df_sub['days_held'].mean():.1f} sessions")
    print(f"   • Trades >= +50% Gain   : {hit_50:.1f}% of trades")
    print(f"   • Trades >= +100% (2x+) : {hit_100:.1f}% of trades")
    print(f"   • Max Single Winner     : {r.max():+.1f}%")
