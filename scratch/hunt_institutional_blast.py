import os, sys, pickle, math
from collections import Counter
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.market_data import _load_all_caches

cache = _load_all_caches()
nifty_df = cache.get("^NSEI")
if nifty_df is None:
    nifty_df = cache.get("NIFTYBEES.NS")

ndf = nifty_df.copy()
if isinstance(ndf.columns, pd.MultiIndex):
    ndf.columns = [c[0] if isinstance(c, tuple) else c for c in ndf.columns]
ndf.index = ndf.index.strftime("%Y-%m-%d")
ndf = ndf[~ndf.index.duplicated(keep="last")]
ndf["nifty_sma50"] = ndf["Close"].astype(float).rolling(50).mean()

# Load all 160 tickers
tickers = [k for k, v in cache.items() if not k.startswith("^") and not k.endswith("BEES.NS") and len(v) >= 150]

episodes = []

for ticker in tickers:
    df = cache[ticker].copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df.columns = [str(c).capitalize() for c in df.columns]
    if not all(c in df.columns for c in ["Open", "High", "Low", "Close", "Volume"]):
        continue
    df.index = df.index.strftime("%Y-%m-%d")
    df = df[~df.index.duplicated(keep="last")]
    
    c = df["Close"].astype(float)
    h = df["High"].astype(float)
    l = df["Low"].astype(float)
    v = df["Volume"].astype(float)
    o = df["Open"].astype(float)
    
    vol_sma20 = v.rolling(20).mean()
    rvol = v / (vol_sma20 + 1e-6)
    
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr_14 = tr.rolling(14).mean()
    
    # Range expansion factor: Today's range vs 14-day ATR
    range_ratio = (h - l) / (atr_14 + 1e-6)
    
    # Close location in bar (0 to 1)
    bar_range = (h - l).replace(0, np.nan)
    close_loc = (c - l) / bar_range
    
    # Daily return
    daily_ret = (c - c.shift(1)) / c.shift(1) * 100.0
    
    # Nifty daily return
    n_c = ndf["Close"].reindex(df.index, method="ffill").astype(float)
    n_ret = (n_c - n_c.shift(1)) / n_c.shift(1) * 100.0
    rs_daily = daily_ret - n_ret
    
    # Forward returns: 5-day, 10-day, 15-day, 21-day
    fwd_ret_5 = (c.shift(-5) - c) / c * 100.0
    fwd_max_5 = (h.rolling(5).max().shift(-5) - c) / c * 100.0
    fwd_ret_10 = (c.shift(-10) - c) / c * 100.0
    fwd_max_10 = (h.rolling(10).max().shift(-10) - c) / c * 100.0
    fwd_ret_21 = (c.shift(-21) - c) / c * 100.0
    fwd_max_21 = (h.rolling(21).max().shift(-21) - c) / c * 100.0

    # 52w high proximity
    high_52w = h.rolling(250).max().shift(1)
    pct_from_52w = ((c - high_52w) / high_52w) * 100.0

    for i in range(50, len(df) - 22):
        # Look for INSTITUTIONAL IGNITION BLAST:
        # 1. Range expansion: Bar range >= 2.0x average ATR
        # 2. Volume explosion: RVOL >= 2.0x 20-day average
        # 3. Strong close: Closed in top 80% of day's bar (close_loc >= 0.80)
        # 4. Decoupling: Gained at least +4.0% today, beating Nifty by >= +3%
        # 5. Near 52-week high: within 15% of 52W high
        if range_ratio.iloc[i] >= 1.8 and rvol.iloc[i] >= 2.0 and close_loc.iloc[i] >= 0.75 and daily_ret.iloc[i] >= 4.0:
            if pct_from_52w.iloc[i] >= -20.0 and not math.isnan(fwd_ret_10.iloc[i]):
                episodes.append({
                    "ticker": ticker,
                    "date": df.index[i],
                    "price": c.iloc[i],
                    "rvol": rvol.iloc[i],
                    "range_ratio": range_ratio.iloc[i],
                    "daily_ret": daily_ret.iloc[i],
                    "pct_from_52w": pct_from_52w.iloc[i],
                    "fwd_ret_5": fwd_ret_5.iloc[i],
                    "fwd_max_5": fwd_max_5.iloc[i],
                    "fwd_ret_10": fwd_ret_10.iloc[i],
                    "fwd_max_10": fwd_max_10.iloc[i],
                    "fwd_ret_21": fwd_ret_21.iloc[i],
                    "fwd_max_21": fwd_max_21.iloc[i],
                })

df_ep = pd.DataFrame(episodes)
print(f"Total Institutional Ignition Blasts detected: {len(df_ep):,}")

print("\n--- PERFORMANCE OF THE INSTITUTIONAL IGNITION BLAST ---")
print(f"• In 5 Sessions (1 Week):")
print(f"  Average Return:       {df_ep['fwd_ret_5'].mean():+.2f}%")
print(f"  Win Rate (>0%):       {(df_ep['fwd_ret_5'] > 0).mean()*100:.1f}%")
print(f"  Average Max Peak:     +{df_ep['fwd_max_5'].mean():.2f}%")
print(f"  Hit >= +10% in 5 days: {(df_ep['fwd_max_5'] >= 10.0).mean()*100:.1f}%")
print(f"  Hit >= +15% in 5 days: {(df_ep['fwd_max_5'] >= 15.0).mean()*100:.1f}%")

print(f"\n• In 10 Sessions (2 Weeks):")
print(f"  Average Return:       {df_ep['fwd_ret_10'].mean():+.2f}%")
print(f"  Win Rate (>0%):       {(df_ep['fwd_ret_10'] > 0).mean()*100:.1f}%")
print(f"  Average Max Peak:     +{df_ep['fwd_max_10'].mean():.2f}%")
print(f"  Hit >= +10% in 10d:   {(df_ep['fwd_max_10'] >= 10.0).mean()*100:.1f}%")
print(f"  Hit >= +15% in 10d:   {(df_ep['fwd_max_10'] >= 15.0).mean()*100:.1f}%")
print(f"  Hit >= +20% in 10d:   {(df_ep['fwd_max_10'] >= 20.0).mean()*100:.1f}%")

print(f"\n• In 21 Sessions (1 Month):")
print(f"  Average Return:       {df_ep['fwd_ret_21'].mean():+.2f}%")
print(f"  Win Rate (>0%):       {(df_ep['fwd_ret_21'] > 0).mean()*100:.1f}%")
print(f"  Average Max Peak:     +{df_ep['fwd_max_21'].mean():.2f}%")
print(f"  Hit >= +15% in 21d:   {(df_ep['fwd_max_21'] >= 15.0).mean()*100:.1f}%")
print(f"  Hit >= +20% in 21d:   {(df_ep['fwd_max_21'] >= 20.0).mean()*100:.1f}%")
print(f"  Hit >= +30% in 21d:   {(df_ep['fwd_max_21'] >= 30.0).mean()*100:.1f}%")

print("\n--- SAMPLE GREATEST 10-DAY EXPLOSIONS ---")
top_10d = df_ep.sort_values(by="fwd_max_10", ascending=False).head(15)
for idx, r in top_10d.iterrows():
    print(f"{r['ticker']:12s} | Date: {r['date']} | Day0 Gain: +{r['daily_ret']:4.1f}% (RVOL {r['rvol']:4.1f}x) | 10d Peak: +{r['fwd_max_10']:5.1f}% | 21d Peak: +{r['fwd_max_21']:5.1f}%")

