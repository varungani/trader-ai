import pandas as pd

df = pd.read_csv('data/cache/fast_surges_census.csv')
print(f'Total surges with >= 15% gain in 5 days: {len(df)}')

print('\n--- Filter: Day 0 RVOL >= 2.0x ---')
r2 = df[df['rvol'] >= 2.0]
print(f'Count: {len(r2)} | Median 3d gain: +{r2["max_gain_3d"].median():.1f}% | Median 5d gain: +{r2["max_gain_5d"].median():.1f}%')

print('\n--- Filter: Day 0 RVOL >= 3.0x (Extreme Institutional Buying) ---')
r3 = df[df['rvol'] >= 3.0]
print(f'Count: {len(r3)} | Median 3d gain: +{r3["max_gain_3d"].median():.1f}% | Median 5d gain: +{r3["max_gain_5d"].median():.1f}%')

print('\nTop 15 Explosive Short-Term Surges with RVOL >= 3.0x:')
cols = ['ticker', 'date', 'price', 'rvol', 'day_ret', 'max_gain_3d', 'max_gain_5d']
print(r3.sort_values(by='max_gain_3d', ascending=False)[cols].head(15).to_string())
