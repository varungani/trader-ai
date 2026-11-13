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
    
    for i in range(250, len(df) - 22):
        dt = df.index[i]
        n_ok = (n_close.loc[dt] > n_ema20.loc[dt] and n_ema20.loc[dt] > n_sma50.loc[dt]) if dt in n_close.index else False
        if not n_ok:
            continue
            
        m = fwd_max_21.iloc[i]
        cl = fwd_close_21.iloc[i]
        mn = fwd_min_21.iloc[i]
        if np.isnan(m) or np.isnan(cl):
            continue
            
        episodes.append({
            'ticker': t,
            'date': dt,
            'fwd_max_21': m,
            'fwd_min_21': mn,
            'fwd_close_21': cl,
            'rvol': rvol.iloc[i],
            'pct_from_52w': pct_from_52w.iloc[i],
            'rs_21': rs_21.iloc[i],
            'stage2': (sma_50.iloc[i] > sma_200.iloc[i]),
        })

df_ep = pd.DataFrame(episodes)

# Filter: Ultra Alpha Leader
ultra_mask = (df_ep['stage2']) & (df_ep['rvol'] >= 2.0) & (df_ep['pct_from_52w'] >= -3.0) & (df_ep['rs_21'] >= 15.0)
ultra_df = df_ep[ultra_mask]

print(f"ULTRA ALPHA LEADER SETUPS: {len(ultra_df)}")
print(f"Hit +15% Target: {(ultra_df['fwd_max_21'] >= 15).mean()*100:.1f}%")
print(f"Hit +20% Target: {(ultra_df['fwd_max_21'] >= 20).mean()*100:.1f}%")
print(f"Hit +25% Target: {(ultra_df['fwd_max_21'] >= 25).mean()*100:.1f}%")
print(f"Hit 7% Stop Loss first: {(ultra_df['fwd_min_21'] <= -7.0).mean()*100:.1f}%")
print(f"Win Rate (Hit +15% before -7% stop): {((ultra_df['fwd_max_21'] >= 15) & (ultra_df['fwd_min_21'] > -7)).mean()*100:.1f}%")
print(f"Average Return at 21 Days: {ultra_df['fwd_close_21'].mean():+.2f}%")

