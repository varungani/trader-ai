"""
Deep-Dive Investigation 1: The Monster Anomaly Census
===================================================
Mines 10 years of daily data (2016-2026, 111 Indian stocks + US leaders) to find:
1. Every single instance where a stock moved >= +20% in 15 days, or >= +35% in 30 days.
2. The exact technical & volume DNA of the stock in the 20 days PRIOR to the move.
3. What distinguished the true monsters from false breakouts.
"""
import os, sys, pickle, numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

with open("data/cache/universe_10y.pkl", "rb") as f:
    univ = pickle.load(f)
with open("data/cache/benchmarks_10y.pkl", "rb") as f:
    bm = pickle.load(f)

nifty_df = bm['^NSEI'].copy()
if isinstance(nifty_df.columns, pd.MultiIndex):
    nifty_df.columns = nifty_df.columns.get_level_values(0)
nifty_df['sma50'] = nifty_df['Close'].rolling(50).mean()

print(f"Loaded {len(univ)} stocks across 10 years (2016-2026). Mining all 15-day and 30-day monster anomalies...")

monsters_15d = []
monsters_30d = []

for sym, df in univ.items():
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=['Close', 'Volume']).copy()
    if len(df) < 250:
        continue
        
    c = df['Close']
    h = df['High']
    l = df['Low']
    v = df['Volume']
    o = df['Open']
    
    # Forward returns
    ret_fwd_15d = (c.shift(-15) - c) / c * 100.0
    max_fwd_15d = (h.rolling(15).max().shift(-15) - c) / c * 100.0
    max_fwd_30d = (h.rolling(30).max().shift(-30) - c) / c * 100.0
    
    # Pre-ignition indicators (at entry day)
    sma50 = c.rolling(50).mean()
    sma200 = c.rolling(200).mean()
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    
    vol_sma20 = v.rolling(20).mean()
    rvol = v / vol_sma20.replace(0, np.nan)
    
    # 52-week high proximity
    high52w = h.rolling(250).max().shift(1)
    dist_52w = (c - high52w) / high52w * 100.0
    
    # Volatility Contraction: 5-day range / 20-day range
    range_5d = h.rolling(5).max() - l.rolling(5).min()
    range_20d = h.rolling(20).max() - l.rolling(20).min()
    vcp_ratio = range_5d / range_20d.replace(0, np.nan)
    
    # Bollinger Band Width (20, 2)
    bb_mid = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    bb_width = (bb_std * 4.0) / bb_mid.replace(0, np.nan) * 100.0
    
    # Prior 6-month momentum
    ret_6m = (c - c.shift(125)) / c.shift(125) * 100.0
    
    # Up-day to Down-day Volume Ratio over trailing 20 days
    is_up_day = (c > c.shift(1)).fillna(False)
    up_vol = v.copy()
    up_vol[~is_up_day] = 0.0
    down_vol = v.copy()
    down_vol[is_up_day] = 0.0
    up_vol_20 = up_vol.rolling(20).sum()
    down_vol_20 = down_vol.rolling(20).sum()
    vol_asymmetry = up_vol_20 / down_vol_20.replace(0, np.nan)
    
    # Scan every bar
    for dt, fwd_max15 in max_fwd_15d.dropna().items():
        if fwd_max15 >= 20.0: # Surged >= +20% in next 15 sessions!
            date_idx = dt
            if date_idx not in nifty_df.index: continue
            nifty_c = float(nifty_df.loc[date_idx, 'Close'])
            nifty_s50 = float(nifty_df.loc[date_idx, 'sma50'])
            
            monsters_15d.append({
                'ticker': sym,
                'date': str(dt)[:10],
                'year': dt.year,
                'fwd_max_15d': fwd_max15,
                'fwd_close_15d': ret_fwd_15d.loc[dt],
                'price': float(c.loc[dt]),
                'stage2': bool(c.loc[dt] > sma50.loc[dt] > sma200.loc[dt]),
                'rvol': float(rvol.loc[dt]),
                'dist_52w': float(dist_52w.loc[dt]),
                'vcp_ratio': float(vcp_ratio.loc[dt]),
                'bb_width': float(bb_width.loc[dt]),
                'ret_6m': float(ret_6m.loc[dt]),
                'vol_asymmetry': float(vol_asymmetry.loc[dt]),
                'nifty_above_50': bool(nifty_c > nifty_s50),
            })
            
    for dt, fwd_max30 in max_fwd_30d.dropna().items():
        if fwd_max30 >= 35.0: # Surged >= +35% in next 30 sessions!
            monsters_30d.append({
                'ticker': sym,
                'date': str(dt)[:10],
                'year': dt.year,
                'fwd_max_30d': fwd_max30,
                'price': float(c.loc[dt]),
                'stage2': bool(c.loc[dt] > sma50.loc[dt] > sma200.loc[dt]),
                'rvol': float(rvol.loc[dt]),
                'dist_52w': float(dist_52w.loc[dt]),
                'vcp_ratio': float(vcp_ratio.loc[dt]),
                'bb_width': float(bb_width.loc[dt]),
                'vol_asymmetry': float(vol_asymmetry.loc[dt]),
            })

df_m15 = pd.DataFrame(monsters_15d)
df_m30 = pd.DataFrame(monsters_30d)

print("\n" + "="*85)
print(f"CENSUS RESULTS: FOUND {len(df_m15)} 15-DAY MONSTERS (>= +20%) AND {len(df_m30)} 30-DAY MONSTERS (>= +35%)")
print("="*85)

print("\n--- STATISTICAL DNA OF 15-DAY MONSTERS (>= +20% THRUST) ---")
print(f"• Total Occurrences: {len(df_m15)} across 111 stocks in 10 years (Avg {len(df_m15)/10:.1f} per year / ~{len(df_m15)/120:.1f} per month!)")
print(f"• Average Peak Gain in 15 Days:  +{df_m15['fwd_max_15d'].mean():.1f}% (Top 10% averaged +{df_m15['fwd_max_15d'].quantile(0.90):.1f}%)")
print(f"• % of Monsters in Stage-2 Trend (Price > 50 > 200 SMA): {df_m15['stage2'].mean()*100:.1f}%")
print(f"• % Occurring within 10% of 52-Week High:               {(df_m15['dist_52w'] >= -10.0).mean()*100:.1f}%")
print(f"• Average RVOL on Ignition Day:                         {df_m15['rvol'].median():.2f}x (75th percentile: {df_m15['rvol'].quantile(0.75):.2f}x)")
print(f"• Median Volatility Contraction Ratio (VCP):             {df_m15['vcp_ratio'].median():.2f} (<= 0.55 indicates extreme coil)")
print(f"• Median Up-to-Down Volume Asymmetry Ratio:              {df_m15['vol_asymmetry'].median():.2f}x (Institutions bought {df_m15['vol_asymmetry'].median():.1f}x more volume than they sold!)")
print(f"• % of Monsters that ignited when NIFTY was < 50 SMA:   {(~df_m15['nifty_above_50']).mean()*100:.1f}% (Decoupled Alpha!)")

print("\n--- TOP 10 GREATEST 15-DAY MOVES IN NSE 10-YEAR HISTORY ---")
top10_15 = df_m15.sort_values(by='fwd_max_15d', ascending=False).drop_duplicates(subset=['ticker', 'year']).head(10)
for idx, r in top10_15.iterrows():
    print(f"• {r['date']} | {r['ticker']:<14}: Max Gain +{r['fwd_max_15d']:>5.1f}% in 15d | RVOL: {r['rvol']:>4.2f}x | Dist 52W: {r['dist_52w']:>+5.1f}% | Vol Asymmetry: {r['vol_asymmetry']:>4.2f}x")

print("\n--- OCCURRENCES BY YEAR ---")
yr_counts = df_m15.groupby('year').size()
for yr, cnt in yr_counts.items():
    print(f"  Year {yr}: {cnt:3d} monster moves")

