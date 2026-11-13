import pickle
import pandas as pd
import numpy as np

# Load high-beta universe
hb_cache = pickle.load(open('data/cache/high_beta_universe.pkl', 'rb'))
broad_cache = pickle.load(open('data/cache/universe_5y.pkl', 'rb'))

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

# Test 1: What is the distribution of 21-day forward returns across all high-beta stocks?
all_21d_returns = []
for t, df in clean_dfs.items():
    c = df['Close'].astype(float)
    ret_21d = (c.shift(-21) - c) / c * 100.0
    max_21d = (df['High'].rolling(21).max().shift(-21) - c) / c * 100.0
    for dt, r, m in zip(df.index[:-21], ret_21d[:-21], max_21d[:-21]):
        if not np.isnan(r):
            all_21d_returns.append({
                'ticker': t, 'date': dt.strftime('%Y-%m-%d'),
                'ret_21d': r, 'max_21d': m
            })

df_all = pd.DataFrame(all_21d_returns)
print(f"Total 21-day episodes analyzed: {len(df_all):,}")
print(f"Episodes gaining >= +15%: {(df_all['ret_21d'] >= 15).mean()*100:.1f}%")
print(f"Episodes gaining >= +20%: {(df_all['ret_21d'] >= 20).mean()*100:.1f}%")
print(f"Episodes gaining >= +30%: {(df_all['ret_21d'] >= 30).mean()*100:.1f}%")
print(f"Episodes with peak >= +20% intraday: {(df_all['max_21d'] >= 20).mean()*100:.1f}%\n")

# Test 2: If an oracle picked the top 2 momentum stocks each month, what was the return?
# Let's inspect by calendar month:
df_all['month'] = df_all['date'].str[:7]
monthly_groups = df_all.groupby('month')

monthly_top2_oracle = []
for mo, g in monthly_groups:
    top2 = g.sort_values('ret_21d', ascending=False).drop_duplicates('ticker').head(2)
    top3 = g.sort_values('ret_21d', ascending=False).drop_duplicates('ticker').head(3)
    monthly_top2_oracle.append({
        'month': mo,
        'oracle_top2_avg': top2['ret_21d'].mean(),
        'oracle_top3_avg': top3['ret_21d'].mean()
    })

df_oracle = pd.DataFrame(monthly_top2_oracle)
print(f"THEORETICAL MAXIMUM CEILING (Hindsight Oracle picking top 2 stocks each month):")
print(f"  Average Monthly Return: {df_oracle['oracle_top2_avg'].mean():.1f}% / month")
print(f"  Top 3 Stocks Average:   {df_oracle['oracle_top3_avg'].mean():.1f}% / month\n")

# Test 3: What if we rank purely by prior momentum + RVOL without peeking forward?
# At the start of each month, pick the top 2 or 3 stocks by (1-month return * RVOL)
# and hold for that month:
months = sorted(list(set(d.strftime('%Y-%m') for df in clean_dfs.values() for d in df.index)))
real_top2_returns = []
real_top3_returns = []

for mo in months[:-1]:
    # find first trading day of this month
    cands = []
    for t, df in clean_dfs.items():
        sub = df[df.index.strftime('%Y-%m') == mo]
        if sub.empty:
            continue
        first_dt = sub.index[0]
        idx = df.index.get_loc(first_dt)
        if idx < 22 or idx + 21 >= len(df):
            continue
        
        c = df['Close'].astype(float)
        v = df['Volume'].astype(float)
        # prior 21-day momentum
        mom = (c.iloc[idx] - c.iloc[idx-21]) / c.iloc[idx-21] * 100.0
        rvol = v.iloc[idx] / (v.iloc[idx-20:idx].mean() + 1e-6)
        
        # forward return over the month
        fwd_ret = (c.iloc[idx+21] - c.iloc[idx]) / c.iloc[idx] * 100.0
        cands.append({'ticker': t, 'mom': mom, 'rvol': rvol, 'fwd_ret': fwd_ret, 'score': mom * rvol})
    
    if len(cands) >= 5:
        cands_df = pd.DataFrame(cands)
        # pick top 2 by momentum
        top2 = cands_df.sort_values('mom', ascending=False).head(2)
        top3 = cands_df.sort_values('mom', ascending=False).head(3)
        real_top2_returns.append(top2['fwd_ret'].mean())
        real_top3_returns.append(top3['fwd_ret'].mean())

print("REALISTIC SYSTEMATIC MOMENTUM ROTATION (No Forward Peeking):")
print(f"  Top 2 Concentrated (50% each): Average = {np.mean(real_top2_returns):.2f}% / month | Win Months = {(pd.Series(real_top2_returns)>0).mean()*100:.1f}%")
print(f"  Top 3 Concentrated (33% each): Average = {np.mean(real_top3_returns):.2f}% / month | Win Months = {(pd.Series(real_top3_returns)>0).mean()*100:.1f}%")
print(f"  Best Month: {np.max(real_top2_returns):.1f}% | Worst Month: {np.min(real_top2_returns):.1f}%")

