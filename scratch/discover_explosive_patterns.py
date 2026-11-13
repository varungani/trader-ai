import os, sys, pickle, math, time
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.market_data import _load_all_caches

cache = _load_all_caches()
nifty_df = cache.get("^NSEI")
if nifty_df is None:
    nifty_df = cache.get("NIFTYBEES.NS")

nifty_sma50 = None
if nifty_df is not None:
    nifty_df = nifty_df.copy()
    if isinstance(nifty_df.columns, pd.MultiIndex):
        nifty_df.columns = [c[0] if isinstance(c, tuple) else c for c in nifty_df.columns]
    nifty_df.index = nifty_df.index.strftime("%Y-%m-%d")
    nifty_df = nifty_df[~nifty_df.index.duplicated(keep="last")]
    if "Close" in nifty_df.columns:
        nifty_sma50 = nifty_df["Close"].rolling(50).mean()

records = []
tickers = [k for k, v in cache.items() if not k.startswith("^") and not k.endswith("BEES.NS") and len(v) >= 300]

print(f"Scanning {len(tickers)} liquid Indian stocks over 5 years for explosive 1-Month (+15% to +40%) moves...")
t0 = time.time()

for ticker in tickers:
    df = cache[ticker].copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df.index = df.index.strftime("%Y-%m-%d")
    df = df[~df.index.duplicated(keep="last")]
    
    if len(df) < 100 or not all(col in df.columns for col in ["Open", "High", "Low", "Close", "Volume"]):
        continue
        
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float)
    
    # Precompute indicators
    sma_20 = close.rolling(20).mean()
    sma_50 = close.rolling(50).mean()
    ema_10 = close.ewm(span=10).mean()
    ema_20 = close.ewm(span=20).mean()
    vol_sma_20 = volume.rolling(20).mean()
    rvol = volume / (vol_sma_20 + 1e-6)
    
    # 20-day Donchian High
    high_20 = high.rolling(20).max().shift(1)
    
    # Bollinger Bands for Squeeze detection (vectorized)
    bb_mid = sma_20
    bb_std = close.rolling(20).std()
    bb_width = (bb_std * 4.0) / (bb_mid + 1e-6)
    bb_min_60 = bb_width.rolling(60).min()
    bb_squeeze = bb_width <= (bb_min_60 * 1.25)
    
    # 14-day RSI
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-6)
    rsi_14 = 100 - (100 / (1 + rs))

    # Look ahead 21 sessions (1 month)
    fwd_ret_21 = (close.shift(-21) - close) / close * 100.0
    fwd_max_21 = (high.rolling(21).max().shift(-21) - close) / close * 100.0
    fwd_min_21 = (low.rolling(21).min().shift(-21) - close) / close * 100.0
    
    for i in range(60, len(df) - 22):
        d_str = df.index[i]
        c_px = close.iloc[i]
        
        # Check market regime (Nifty above 50 SMA)
        mkt_bull = True
        if nifty_sma50 is not None and d_str in nifty_sma50.index and d_str in nifty_df.index:
            n_px = nifty_df["Close"].loc[d_str]
            n_sma = nifty_sma50.loc[d_str]
            mkt_bull = (n_px >= n_sma) if not math.isnan(n_sma) else True
            
        is_breakout = (c_px >= high_20.iloc[i]) if not math.isnan(high_20.iloc[i]) else False
        is_ema_stacked = (ema_10.iloc[i] > ema_20.iloc[i] > sma_50.iloc[i]) if not math.isnan(sma_50.iloc[i]) else False
        rv = rvol.iloc[i] if not math.isnan(rvol.iloc[i]) else 1.0
        rsi = rsi_14.iloc[i] if not math.isnan(rsi_14.iloc[i]) else 50.0
        sq = bb_squeeze.iloc[i] if not math.isnan(bb_squeeze.iloc[i]) else False
        
        records.append({
            "ticker": ticker,
            "date": d_str,
            "close": c_px,
            "mkt_bull": mkt_bull,
            "breakout_20d": is_breakout,
            "ema_stacked": is_ema_stacked,
            "rvol": rv,
            "rsi": rsi,
            "bb_squeeze": sq,
            "fwd_ret_21": fwd_ret_21.iloc[i],
            "fwd_max_21": fwd_max_21.iloc[i],
            "fwd_min_21": fwd_min_21.iloc[i],
        })

print(f"Processed in {time.time()-t0:.2f}s")
df_all = pd.DataFrame(records).dropna(subset=["fwd_ret_21"])
print(f"Total analyzed 1-Month observation windows: {len(df_all):,}")

# Filter for monster 1-month winners (>= +15% and >= +20%)
monsters = df_all[df_all["fwd_ret_21"] >= 15.0]
print(f"Instances where stock gained >= +15% in 21 sessions: {len(monsters)} ({len(monsters)/len(df_all)*100:.1f}%)")
super_monsters = df_all[df_all["fwd_ret_21"] >= 20.0]
print(f"Instances where stock gained >= +20% in 21 sessions: {len(super_monsters)} ({len(super_monsters)/len(df_all)*100:.1f}%)")

# Compare feature averages between ALL vs MONSTERS
print("\n=== FEATURE COMPARISON: ALL STOCKS vs EXPLOSIVE +15% 1-MONTH RUNNERS ===")
features = ["mkt_bull", "breakout_20d", "ema_stacked", "rvol", "rsi", "bb_squeeze"]
for f in features:
    all_val = df_all[f].mean()
    mon_val = monsters[f].mean()
    if f in ["mkt_bull", "breakout_20d", "ema_stacked", "bb_squeeze"]:
        print(f"• {f:15s}: All={all_val*100:5.1f}%  |  Explosive Winners={mon_val*100:5.1f}%  (Alpha Multiplier: {mon_val/max(1e-4, all_val):.2f}x)")
    else:
        print(f"• {f:15s}: All={all_val:5.2f}   |  Explosive Winners={mon_val:5.2f}")

# Now test specific strategy rule combinations
print("\n=== EMPIRICAL TEST OF HIGH-CONVICTION RULES OVER 1-MONTH HOLDING ===")

rules = [
    ("Baseline (Random Entry)", df_all["close"] > 0),
    ("Rule 1: Market Bull Only (Nifty > 50 SMA)", df_all["mkt_bull"] == True),
    ("Rule 2: Market Bull + 20-Day Breakout", (df_all["mkt_bull"] == True) & (df_all["breakout_20d"] == True)),
    ("Rule 3: Market Bull + 20-Day Breakout + RVOL >= 1.5x", (df_all["mkt_bull"] == True) & (df_all["breakout_20d"] == True) & (df_all["rvol"] >= 1.5)),
    ("Rule 4: Market Bull + EMA Stack (10>20>50) + RSI 58-75 + RVOL >= 1.4x", 
     (df_all["mkt_bull"] == True) & (df_all["ema_stacked"] == True) & (df_all["rsi"].between(58, 75)) & (df_all["rvol"] >= 1.4)),
    ("Rule 5: INSTITUTIONAL IGNITION: Mkt Bull + 20d High Breakout + EMA Stack + RVOL >= 1.5x + RSI 58-75",
     (df_all["mkt_bull"] == True) & (df_all["breakout_20d"] == True) & (df_all["ema_stacked"] == True) & (df_all["rvol"] >= 1.5) & (df_all["rsi"].between(58, 75)))
]

for name, mask in rules:
    sub = df_all[mask]
    avg_21d = sub["fwd_ret_21"].mean()
    win_pct = (sub["fwd_ret_21"] > 0).mean() * 100.0
    avg_max = sub["fwd_max_21"].mean()
    hit_15 = (sub["fwd_max_21"] >= 15.0).mean() * 100.0
    hit_20 = (sub["fwd_max_21"] >= 20.0).mean() * 100.0
    print(f"\n{name}")
    print(f"  Count: {len(sub):,} | Avg 1-Mo Return: {avg_21d:+.2f}% | Win Rate: {win_pct:.1f}% | Avg Peak: +{avg_max:.2f}% | Reached +15%: {hit_15:.1f}% | Reached +20%: {hit_20:.1f}%")
