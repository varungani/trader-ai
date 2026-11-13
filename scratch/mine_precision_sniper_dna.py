"""
TraderAI - Precision Sniper DNA Miner
Isolates the exact Day 0 characteristics of stocks that gain +15% to +30% in 21 days.
Goal: Maximize precision (Win Rate of hitting +20% target).
"""
import pickle
import pandas as pd
import numpy as np

# Load universes
hb_cache = pickle.load(open('data/cache/high_beta_universe.pkl', 'rb'))
broad_cache = pickle.load(open('data/cache/universe_5y.pkl', 'rb'))
benchmarks = pickle.load(open('data/cache/benchmarks_5y.pkl', 'rb'))

ndf = benchmarks['^NSEI'].copy()
if isinstance(ndf.columns, pd.MultiIndex):
    ndf.columns = [c[0] if isinstance(c, tuple) else c for c in ndf.columns]
ndf.index = pd.to_datetime(ndf.index)
ndf = ndf[~ndf.index.duplicated(keep='last')].sort_index()
n_close = ndf['Close'].astype(float)
n_sma50 = n_close.rolling(50).mean()
n_ema20 = n_close.ewm(span=20).mean()

# Combine universes (150+ stocks)
all_cache = {**broad_cache, **hb_cache}
tickers = [k for k in all_cache.keys() if k.endswith('.NS')]

episodes = []

for t in tickers:
    df = all_cache[t].copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df.columns = [str(c).capitalize() for c in df.columns]
    if not all(c in df.columns for c in ['Open', 'High', 'Low', 'Close', 'Volume']):
        continue
    df.index = pd.to_datetime(df.index)
    df = df[~df.index.duplicated(keep='last')].sort_index()
    if len(df) < 150:
        continue

    c = df['Close'].astype(float)
    h = df['High'].astype(float)
    l = df['Low'].astype(float)
    v = df['Volume'].astype(float)
    o = df['Open'].astype(float)

    # 21-day forward max gain & return
    fwd_max_21 = (h.rolling(21).max().shift(-21) - c) / c * 100.0
    fwd_ret_21 = (c.shift(-21) - c) / c * 100.0
    fwd_min_21 = (l.rolling(21).min().shift(-21) - c) / c * 100.0

    # Indicators on Day 0
    vol_sma20 = v.rolling(20).mean()
    rvol = v / (vol_sma20 + 1e-6)
    sma_50 = c.rolling(50).mean()
    sma_200 = c.rolling(min(200, len(c))).mean()
    ema_20 = c.ewm(span=20).mean()
    
    # 52-week High
    high_52w = h.rolling(250).max().shift(1)
    pct_from_52w = ((c - high_52w) / high_52w) * 100.0

    # 20-day High Breakout
    high_20 = h.rolling(20).max().shift(1)
    is_breakout_20d = c >= high_20

    # Day Bar Anatomy
    day_range = (h - l).replace(0, np.nan)
    close_loc = (c - l) / day_range
    candle_body = (c - o) / day_range
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr_14 = tr.rolling(14).mean()
    range_vs_atr = (h - l) / (atr_14 + 1e-6)

    # VCP Contraction: 5-day range vs 20-day range
    high_5d = h.rolling(5).max().shift(1)
    low_5d = l.rolling(5).min().shift(1)
    high_20d = h.rolling(20).max().shift(1)
    low_20d = l.rolling(20).min().shift(1)
    vcp_ratio = (high_5d - low_5d) / ((high_20d - low_20d) + 1e-6)

    # Relative Strength vs NIFTY
    n_aligned = n_close.reindex(df.index, method='ffill')
    rs_21d = (c.pct_change(21) - n_aligned.pct_change(21)) * 100.0

    for i in range(250, len(df) - 22):
        dt = df.index[i]
        m_ret = fwd_max_21.iloc[i]
        c_ret = fwd_ret_21.iloc[i]
        min_ret = fwd_min_21.iloc[i]
        if np.isnan(m_ret) or np.isnan(c_ret):
            continue

        n_ok = False
        if dt in n_close.index:
            n_px = n_close.loc[dt]
            n_sm = n_sma50.loc[dt]
            n_ok = (n_px >= n_sm)

        episodes.append({
            'ticker': t,
            'date': dt,
            'fwd_max_21': m_ret,
            'fwd_ret_21': c_ret,
            'fwd_min_21': min_ret,
            'hit_20': (m_ret >= 20.0),
            'hit_15': (m_ret >= 15.0),
            'stopped_7': (min_ret <= -7.0),
            'rvol': rvol.iloc[i],
            'pct_from_52w': pct_from_52w.iloc[i],
            'is_breakout_20d': is_breakout_20d.iloc[i],
            'close_loc': close_loc.iloc[i],
            'range_vs_atr': range_vs_atr.iloc[i],
            'vcp_ratio': vcp_ratio.iloc[i],
            'rs_21d': rs_21d.iloc[i],
            'stage2': (sma_50.iloc[i] > sma_200.iloc[i] and c.iloc[i] > ema_20.iloc[i]),
            'nifty_bull': n_ok,
        })

df_ep = pd.DataFrame(episodes)
print(f"Total historical episodes collected: {len(df_ep):,}\n")

# Baseline across all
base_hit20 = df_ep['hit_20'].mean() * 100
base_hit15 = df_ep['hit_15'].mean() * 100
print(f"BASELINE RANDOM PICK: Hit +20% in 21d = {base_hit20:.1f}% | Hit +15% = {base_hit15:.1f}%\n")

# Test Filter Combinations
filters = {
    "1. High RVOL alone (>= 2.0x)": (df_ep['rvol'] >= 2.0),
    "2. 20-Day Breakout alone": (df_ep['is_breakout_20d'] == True),
    "3. Within 5% of 52W High alone": (df_ep['pct_from_52w'] >= -5.0),
    "4. Stage 2 + Nifty Bull": (df_ep['stage2'] == True) & (df_ep['nifty_bull'] == True),
    "5. Stage 2 + RVOL >= 2.0x + 20D Breakout": (df_ep['stage2'] == True) & (df_ep['rvol'] >= 2.0) & (df_ep['is_breakout_20d'] == True),
    "6. Stage 2 + 52W High (<5%) + RVOL >= 2.0x": (df_ep['stage2'] == True) & (df_ep['pct_from_52w'] >= -5.0) & (df_ep['rvol'] >= 2.0),
    "7. All-Time High / 52W Breakout (Close >= 98% 52W) + RVOL >= 2.0x + Close Loc >= 0.75": 
        (df_ep['pct_from_52w'] >= -2.0) & (df_ep['rvol'] >= 2.0) & (df_ep['close_loc'] >= 0.75) & (df_ep['nifty_bull'] == True),
    "8. SUPER-SNIPER DNA: 52W High (<=3%) + RVOL >= 2.2x + VCP Coil (<=0.65) + Close Loc >= 0.75 + Stage 2":
        (df_ep['pct_from_52w'] >= -3.0) & (df_ep['rvol'] >= 2.2) & (df_ep['vcp_ratio'] <= 0.65) & 
        (df_ep['close_loc'] >= 0.75) & (df_ep['stage2'] == True) & (df_ep['nifty_bull'] == True),
    "9. EXPLOSIVE EXPANSION: Range >= 1.8x ATR + RVOL >= 2.5x + 52W High + Close Loc >= 0.80":
        (df_ep['range_vs_atr'] >= 1.8) & (df_ep['rvol'] >= 2.5) & (df_ep['pct_from_52w'] >= -5.0) & 
        (df_ep['close_loc'] >= 0.80) & (df_ep['nifty_bull'] == True),
}

print(f"{'Strategy / Filter Blueprint':<70} | {'Count':<6} | {'Hit +15%':<9} | {'Hit +20%':<9} | {'Hit +25%':<9} | {'Avg Ret 21d':<12}")
print("-" * 125)

for name, mask in filters.items():
    sub = df_ep[mask]
    if len(sub) == 0:
        continue
    hit15 = sub['hit_15'].mean() * 100
    hit20 = sub['hit_20'].mean() * 100
    hit25 = (sub['fwd_max_21'] >= 25.0).mean() * 100
    avg_ret = sub['fwd_ret_21'].mean()
    print(f"{name:<70} | {len(sub):<6} | {hit15:>7.1f}% | {hit20:>7.1f}% | {hit25:>7.1f}% | {avg_ret:>+10.2f}%")

