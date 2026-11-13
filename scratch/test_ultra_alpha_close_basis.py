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
            
        # Ultra Alpha Leader filter
        if not (sma_50.iloc[i] > sma_200.iloc[i] and rvol.iloc[i] >= 2.0 and pct_from_52w.iloc[i] >= -3.0 and rs_21.iloc[i] >= 15.0):
            continue

        entry_px = c.iloc[i]
        target_px = entry_px * 1.20
        stop_px = entry_px * 0.93 # 7% stop
        
        # Track session by session over 21 days
        hit_target = False
        hit_stop_close = False
        hit_stop_intraday = False
        final_ret = 0.0
        
        for day in range(1, 22):
            idx = i + day
            day_h = h.iloc[idx]
            day_l = l.iloc[idx]
            day_c = c.iloc[idx]
            
            # Intraday check
            if day_l <= stop_px and not hit_target:
                hit_stop_intraday = True
            
            # Target check
            if day_h >= target_px:
                hit_target = True
                final_ret = 20.0
                break
                
            # Daily Close Stop check
            if day_c < stop_px:
                hit_stop_close = True
                final_ret = (day_c - entry_px) / entry_px * 100.0
                break
                
        if not hit_target and not hit_stop_close:
            final_ret = (c.iloc[i+21] - entry_px) / entry_px * 100.0

        episodes.append({
            'ticker': t,
            'hit_target': hit_target,
            'hit_stop_close': hit_stop_close,
            'hit_stop_intraday': hit_stop_intraday,
            'final_ret': final_ret,
            'is_winner': (final_ret > 0),
        })

df_res = pd.DataFrame(episodes)
print("=== ULTRA ALPHA LEADER: INTRADAY WICK VS DAILY CLOSE STOP ===")
print(f"Total Trades: {len(df_res)}")
print(f"Hit +20% Target: {df_res['hit_target'].mean()*100:.1f}%")
print(f"Wicked out Intraday: {df_res['hit_stop_intraday'].mean()*100:.1f}%")
print(f"Closed Below Stop: {df_res['hit_stop_close'].mean()*100:.1f}%")
print(f"Final Winning Trades % (Daily Close basis): {df_res['is_winner'].mean()*100:.1f}%")
print(f"Average Return per Trade: {df_res['final_ret'].mean():+.2f}%")

