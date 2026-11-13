import pandas as pd
import numpy as np

# Load data and compute monthly returns
import pickle
import os

universe = {}
for p in ['data/cache/universe_10y.pkl', 'data/cache/high_beta_universe.pkl']:
    if os.path.exists(p):
        with open(p, 'rb') as f:
            d = pickle.load(f)
            universe.update(d)

candidates = []
for ticker, df in universe.items():
    if df is None or len(df) < 50:
        continue
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in df.columns:
            df[col] = df[col].astype(float)
    if 'close' not in df.columns or 'volume' not in df.columns:
        continue
    df['vol_ma20'] = df['volume'].rolling(20).mean()
    df['rvol'] = df['volume'] / (df['vol_ma20'].replace(0, np.nan) + 1e-6)
    df['ret_1d'] = df['close'].pct_change() * 100
    df['close_loc'] = (df['close'] - df['low']) / (df['high'] - df['low'] + 1e-6)
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    roll_max = df['high'].shift(1).rolling(3).max()
    roll_min = df['low'].shift(1).rolling(3).min()
    df['tightness_3d'] = (roll_max - roll_min) / (df['close'].shift(1) + 1e-6) * 100
    
    sig = (df['close'] > df['ema20']) & (df['rvol'] >= 2.5) & (df['ret_1d'] >= 2.5) & (df['close_loc'] >= 0.75) & (df['tightness_3d'] < 6.0)
    indices = np.where(sig.values)[0]
    for idx in indices:
        if idx < 20 or idx >= len(df) - 6:
            continue
        entry_date = df.index[idx]
        entry_px = df['close'].iloc[idx]
        stop_px = entry_px * 0.965
        exit_px = entry_px
        bars = 0
        for f in range(1, 6):
            c_idx = idx + f
            b_low = df['low'].iloc[c_idx]
            b_high = df['high'].iloc[c_idx]
            b_close = df['close'].iloc[c_idx]
            if b_low <= stop_px:
                exit_px = stop_px
                bars = f
                break
            elif (b_high - entry_px) / entry_px >= 0.12:
                exit_px = entry_px * 1.12
                bars = f
                break
            elif f == 5:
                exit_px = b_close
                bars = 5
        ret = (exit_px - entry_px) / entry_px * 100
        candidates.append({
            'ticker': ticker,
            'entry_date': pd.to_datetime(entry_date),
            'exit_date': pd.to_datetime(entry_date) + pd.to_timedelta(bars * 1.45, unit='D'),
            'ret_pct': ret,
            'bars': bars
        })

df_all = pd.DataFrame(candidates).sort_values(by='entry_date').reset_index(drop=True)

# Monthly simulation (2 slots, 50% each)
# Starting capital = Rs. 10,000 (realistic for testing) and Rs. 1,00,000
# Let's break down results across calendar months
df_all['month_year'] = df_all['entry_date'].dt.to_period('M')

monthly_results = []
for m, grp in df_all[df_all['entry_date'] >= '2020-01-01'].groupby('month_year'):
    # In a typical month, sample up to 5-6 trades taken
    # Calculate compounded monthly net
    trades = grp.head(6) # max ~5-6 trades in a month
    # With 2 concurrent slots (50% position size):
    monthly_ret = 0.0
    for _, t in trades.iterrows():
        monthly_ret += 0.50 * t['ret_pct']
    monthly_results.append({
        'month': str(m),
        'trades': len(trades),
        'wins': (trades['ret_pct'] > 0).sum(),
        'net_pct': monthly_ret
    })

df_m = pd.DataFrame(monthly_results)
print("="*85)
print("1-MONTH RESULTS DISTRIBUTION ACROSS 80+ HISTORICAL MONTHS (2020–2026)")
print("="*85)
print(f"Average 1-Month Return : {df_m['net_pct'].mean():+.2f}%")
print(f"Median 1-Month Return  : {df_m['net_pct'].median():+.2f}%")
print(f"Best Month Gain        : {df_m['net_pct'].max():+.2f}%")
print(f"Worst Month Drawdown   : {df_m['net_pct'].min():+.2f}%")
print(f"Profitable Months %    : {(df_m['net_pct'] > 0).mean()*100:.1f}%")

print("\nRecent 12 Calendar Months Breakdown:")
print(f"{'Month':<10} | {'Trades':<8} | {'Wins':<6} | {'Monthly Net Return':<20} | {'On Rs. 10,000':<15} | {'On Rs. 1,00,000':<15}")
print("-" * 85)
for _, r in df_m.tail(12).iterrows():
    pnl = r['net_pct']
    val10k = 10000 * (1 + pnl / 100)
    val100k = 100000 * (1 + pnl / 100)
    print(f"{r['month']:<10} | {int(r['trades']):<8} | {int(r['wins']):<6} | {pnl:>+6.1f}%              | Rs. {val10k:>8,.0f}     | Rs. {val100k:>10,.0f}")
