import pickle
import os
import pandas as pd
import numpy as np

def scan_recent_rvol_ignitions():
    universe = {}
    for p in ['data/cache/universe_10y.pkl', 'data/cache/high_beta_universe.pkl']:
        if os.path.exists(p):
            with open(p, 'rb') as f:
                d = pickle.load(f)
                universe.update(d)
                
    print(f"Loaded {len(universe)} tickers. Scanning for recent high RVOL (>= 2.0x) ignitions (past 5 sessions)...")
    
    recent_ignitions = []
    
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
        
        # Check last 5 rows
        last_5 = df.tail(5)
        for date_idx, row in last_5.iterrows():
            if row['rvol'] >= 2.0 and row['ret_1d'] >= 2.0:
                recent_ignitions.append({
                    'ticker': ticker,
                    'date': date_idx,
                    'close': row['close'],
                    'rvol': row['rvol'],
                    'day_ret': row['ret_1d'],
                    'vol_shares': row['volume']
                })
                
    df_recent = pd.DataFrame(recent_ignitions)
    if len(df_recent) > 0:
        df_recent = df_recent.sort_values(by='date', ascending=False)
        print(f"\nFound {len(df_recent)} high-RVOL ignition events in the past 5 sessions:")
        print(df_recent.to_string())
    else:
        print("\nNo high RVOL ignitions found in the past 5 sessions.")
        
if __name__ == '__main__':
    scan_recent_rvol_ignitions()
