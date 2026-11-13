import pickle
import pandas as pd
import numpy as np

# Load data
hb_cache = pickle.load(open('data/cache/high_beta_universe.pkl', 'rb'))
benchmarks = pickle.load(open('data/cache/benchmarks_5y.pkl', 'rb'))

ndf = benchmarks['^NSEI'].copy()
if isinstance(ndf.columns, pd.MultiIndex):
    ndf.columns = [c[0] if isinstance(c, tuple) else c for c in ndf.columns]
ndf.index = pd.to_datetime(ndf.index)
n_close = ndf['Close'].astype(float)
n_sma50 = n_close.rolling(50).mean()
n_ema20 = n_close.ewm(span=20).mean()

tickers = [k for k in hb_cache.keys() if k.endswith('.NS')]
clean_dfs = {}
for t in tickers:
    df = hb_cache[t].copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df.columns = [str(c).capitalize() for c in df.columns]
    if not all(c in df.columns for c in ['Open', 'High', 'Low', 'Close', 'Volume']):
        continue
    df.index = pd.to_datetime(df.index)
    df = df[~df.index.duplicated(keep='last')].sort_index()
    if len(df) >= 150:
        clean_dfs[t] = df

episodes = []
for t, df in clean_dfs.items():
    c = df['Close'].astype(float)
    h = df['High'].astype(float)
    l = df['Low'].astype(float)
    v = df['Volume'].astype(float)
    
    fwd_max_21 = (h.rolling(21).max().shift(-21) - c) / c * 100.0
    fwd_min_21 = (l.rolling(21).min().shift(-21) - c) / c * 100.0
    fwd_close_21 = (c.shift(-21) - c) / c * 100.0
    
    vol_sma20 = v.rolling(20).mean()
    rvol = v / (vol_sma20 + 1e-6)
    high_52w = h.rolling(250).max().shift(1)
    pct_from_52w = ((c - high_52w) / high_52w) * 100.0
    sma_50 = c.rolling(50).mean()
    sma_200 = c.rolling(min(200, len(c))).mean()
    
    n_aligned = n_close.reindex(df.index, method='ffill')
    rs_21 = (c.pct_change(21) - n_aligned.pct_change(21)) * 100.0
    rs_63 = (c.pct_change(63) - n_aligned.pct_change(63)) * 100.0
    
    for i in range(250, len(df) - 22):
        dt = df.index[i]
        n_ok = (n_close.loc[dt] > n_ema20.loc[dt] and n_ema20.loc[dt] > n_sma50.loc[dt]) if dt in n_close.index else False
        if not n_ok:
            continue
            
        m = fwd_max_21.iloc[i]
        cl = fwd_close_21.iloc[i]
        if np.isnan(m) or np.isnan(cl):
            continue
            
        episodes.append({
            'ticker': t,
            'date': dt,
            'fwd_max_21': m,
            'fwd_close_21': cl,
            'rvol': rvol.iloc[i],
            'pct_from_52w': pct_from_52w.iloc[i],
            'rs_21': rs_21.iloc[i],
            'rs_63': rs_63.iloc[i],
            'stage2': (sma_50.iloc[i] > sma_200.iloc[i]),
        })

df_ep = pd.DataFrame(episodes)
print(f"Total episodes during Confirmed Nifty Super-Bull Regime: {len(df_ep):,}")

# Test the effect of Relative Strength Leadership (True Alpha)
print(f"\n{'RS vs Nifty Threshold':<35} | {'Count':<6} | {'Hit +15%':<9} | {'Hit +20%':<9} | {'Hit +25%':<9} | {'Avg Ret':<10}")
print("-" * 85)
for rs_thresh in [0, 5, 10, 15, 20]:
    mask = (df_ep['stage2']) & (df_ep['rvol'] >= 1.8) & (df_ep['pct_from_52w'] >= -5.0) & (df_ep['rs_21'] >= rs_thresh)
    sub = df_ep[mask]
    if len(sub) == 0:
        continue
    h15 = (sub['fwd_max_21'] >= 15).mean() * 100
    h20 = (sub['fwd_max_21'] >= 20).mean() * 100
    h25 = (sub['fwd_max_21'] >= 25).mean() * 100
    avg = sub['fwd_close_21'].mean()
    print(f"RS 21d >= +{rs_thresh:<2} % + RVOL>=1.8 + 52wHigh  | {len(sub):<6} | {h15:>7.1f}% | {h20:>7.1f}% | {h25:>7.1f}% | {avg:>+8.2f}%")

