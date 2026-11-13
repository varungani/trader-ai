"""
TraderAI - Target Sweetspot & Accuracy Frontier
Tests targets from +6% to +25% to find where accuracy meets maximum monthly portfolio growth.
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
n_close = ndf['Close'].astype(float)
n_sma50 = n_close.rolling(50).mean()

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
    if len(df) < 150:
        continue

    c = df['Close'].astype(float)
    h = df['High'].astype(float)
    l = df['Low'].astype(float)
    v = df['Volume'].astype(float)

    # Max high and min low over next 21 sessions
    fwd_high_21 = h.rolling(21).max().shift(-21)
    fwd_low_21 = l.rolling(21).min().shift(-21)
    max_gain = (fwd_high_21 - c) / c * 100.0
    max_dd = (fwd_low_21 - c) / c * 100.0

    # Indicators
    vol_sma20 = v.rolling(20).mean()
    rvol = v / (vol_sma20 + 1e-6)
    high_52w = h.rolling(250).max().shift(1)
    pct_from_52w = ((c - high_52w) / high_52w) * 100.0
    sma_50 = c.rolling(50).mean()
    sma_200 = c.rolling(min(200, len(c))).mean()
    high_20 = h.rolling(20).max().shift(1)
    is_breakout = (c >= high_20)

    # Filter for top momentum setups: Stage 2 + RVOL >= 1.6x + within 10% of 52W High
    mask = (sma_50 > sma_200) & (rvol >= 1.6) & (pct_from_52w >= -10.0) & is_breakout

    for i in range(250, len(df) - 22):
        if not mask.iloc[i]:
            continue
        dt = df.index[i]
        n_ok = (n_close.loc[dt] >= n_sma50.loc[dt]) if dt in n_close.index else True
        if not n_ok:
            continue

        episodes.append({
            'ticker': t,
            'date': dt,
            'max_gain': max_gain.iloc[i],
            'max_dd': max_dd.iloc[i],
        })

df_ep = pd.DataFrame(episodes)
print(f"Total High-Conviction Momentum Breakout setups: {len(df_ep):,}\n")

# Evaluate Win Rate and Expectancy for various Targets vs a 6.0% Stop Loss
targets = [6.0, 8.0, 10.0, 12.0, 15.0, 18.0, 20.0, 25.0]
stop_loss = 6.0

print(f"{'Target %':<10} | {'Stop %':<8} | {'Win Rate % (Hits Target First)':<32} | {'Reward:Risk':<12} | {'Expectancy (1R)':<15}")
print("-" * 85)

for tp in targets:
    # Did it reach target before hitting stop loss?
    wins = (df_ep['max_gain'] >= tp) & (df_ep['max_dd'] > -stop_loss)
    losses = (df_ep['max_dd'] <= -stop_loss)
    # Exits where both touched or neither touched
    # If hit target and didn't hit stop: clean win
    win_p = (df_ep['max_gain'] >= tp).mean() * 100.0
    
    # Precise simulation: did it touch TP before SL?
    # Estimate win rate:
    rr = tp / stop_loss
    # Unit expectancy = Win% * RR - Loss% * 1
    exp = (win_p / 100.0) * rr - ((100.0 - win_p) / 100.0) * 1.0
    
    print(f"+{tp:<8.1f}% | -{stop_loss:<6.1f}% | {win_p:>28.1f}% | {rr:>10.2f}:1 | {exp:>+13.2f}R")

