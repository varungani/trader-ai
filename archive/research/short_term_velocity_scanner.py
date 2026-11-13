import pickle
import os
import pandas as pd
import numpy as np

def run_short_term_velocity_analysis():
    # Load universe
    universe = {}
    for p in ['data/cache/universe_10y.pkl', 'data/cache/high_beta_universe.pkl']:
        if os.path.exists(p):
            with open(p, 'rb') as f:
                d = pickle.load(f)
                universe.update(d)
                
    print(f"Loaded {len(universe)} tickers for Short-Term High-Velocity Exploration.")
    
    # We want to identify FAST CASH patterns:
    # Explosions of >= +15% to +40% in just 3 to 10 TRADING SESSIONS!
    fast_surges = []
    
    for ticker, df in universe.items():
        if df is None or len(df) < 100:
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
        
        # True range and ATR
        h_l = df['high'] - df['low']
        h_pc = (df['high'] - df['close'].shift(1)).abs()
        l_pc = (df['low'] - df['close'].shift(1)).abs()
        tr = pd.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)
        df['atr14'] = tr.rolling(14).mean()
        df['atr_pct'] = df['atr14'] / df['close'] * 100
        
        # Daily return and gap
        df['ret_1d'] = df['close'].pct_change() * 100
        df['gap_pct'] = (df['open'] - df['close'].shift(1)) / df['close'].shift(1) * 100
        
        # Moving averages
        df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
        
        # 3-day and 5-day and 10-day forward returns and max forward gain
        for f in [3, 5, 10]:
            df[f'fwd_ret_{f}d'] = (df['close'].shift(-f) - df['close']) / df['close'] * 100
            
        # Max high in next 5 and 10 days
        roll_high_5 = df['high'].iloc[::-1].rolling(5).max().iloc[::-1].shift(-1)
        df['max_gain_5d'] = (roll_high_5 - df['close']) / df['close'] * 100
        
        roll_high_10 = df['high'].iloc[::-1].rolling(10).max().iloc[::-1].shift(-1)
        df['max_gain_10d'] = (roll_high_10 - df['close']) / df['close'] * 100
        
        # Scan for fast surges >= +15% in 5 days or >= +20% in 10 days
        surges = df[df['max_gain_5d'] >= 15.0].copy()
        
        for idx_row, row in surges.iterrows():
            loc = df.index.get_loc(idx_row)
            if loc < 30 or loc >= len(df) - 10:
                continue
                
            prev_close = df['close'].iloc[loc - 1]
            prev_vol = df['volume'].iloc[loc - 1]
            prev_rvol = df['rvol'].iloc[loc - 1]
            
            # Pre-surge tightness (range over past 3 days)
            recent_3d_range = (df['high'].iloc[loc-3:loc].max() - df['low'].iloc[loc-3:loc].min()) / prev_close * 100
            
            # Did it gap?
            gap = row['gap_pct']
            ignition_rvol = row['rvol']
            candle_body = (row['close'] - row['open']) / (row['high'] - row['low'] + 1e-6) * 100
            
            fast_surges.append({
                'ticker': ticker,
                'date': idx_row,
                'price': row['close'],
                'max_gain_3d': (df['high'].iloc[loc+1:loc+4].max() - row['close']) / row['close'] * 100 if loc+4 <= len(df) else 0,
                'max_gain_5d': row['max_gain_5d'],
                'max_gain_10d': row['max_gain_10d'],
                'fwd_ret_5d': row['fwd_ret_5d'],
                'fwd_ret_10d': row['fwd_ret_10d'],
                'rvol': ignition_rvol,
                'gap_pct': gap,
                'day_ret': row['ret_1d'],
                'candle_body': candle_body,
                'recent_3d_range': recent_3d_range,
                'atr_pct': row['atr_pct']
            })
            
    df_fast = pd.DataFrame(fast_surges)
    print(f"\nFound {len(df_fast)} FAST SHORT-TERM VELOCITY SURGES (>= +15% in 5 days)!")
    
    print("\n" + "="*85)
    print("SHORT-TERM HIGH-VELOCITY CENSUS (3 TO 10 SESSIONS)")
    print("="*85)
    print(f"Median Gain in 5 Days : +{df_fast['max_gain_5d'].median():.1f}%")
    print(f"Median Gain in 10 Days: +{df_fast['max_gain_10d'].median():.1f}%")
    print(f"Median Day 0 RVOL     : {df_fast['rvol'].median():.2f}x")
    print(f"Median Day 0 Return   : +{df_fast['day_ret'].median():.1f}%")
    print(f"Median 3-Day Pre-Range: {df_fast['recent_3d_range'].median():.1f}%")
    
    # Let's see the most extreme 3-day and 5-day gains
    print("\nTop 15 Fast 5-Day Explosions:")
    top15 = df_fast.sort_values(by='max_gain_5d', ascending=False).head(15)
    for _, r in top15.iterrows():
        print(f"  {r['ticker']:<12} | Date: {str(r['date'])[:10]} | Day 0 Gain: {r['day_ret']:+5.1f}% | RVOL: {r['rvol']:4.1f}x | 3-Day Peak: +{r['max_gain_3d']:4.1f}% | 5-Day Peak: +{r['max_gain_5d']:4.1f}%")
        
    df_fast.to_csv('data/cache/fast_surges_census.csv', index=False)
    print("\nSaved fast surges to data/cache/fast_surges_census.csv")

if __name__ == '__main__':
    run_short_term_velocity_analysis()
