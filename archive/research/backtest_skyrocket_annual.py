import pickle
import os
import pandas as pd
import numpy as np

def run_chronological_skyrocket_backtest():
    universe = {}
    for p in ['data/cache/universe_10y.pkl', 'data/cache/high_beta_universe.pkl']:
        if os.path.exists(p):
            with open(p, 'rb') as f:
                d = pickle.load(f)
                universe.update(d)
                
    print(f"Loaded {len(universe)} tickers. Running chronological compounding simulation...")
    
    # We want to identify every high-velocity setup:
    # 1. RVOL >= 2.5x
    # 2. Daily return >= +2.5%
    # 3. 3-day tightness < 6.0%
    # 4. Close in top 25% of candle
    # 5. Above 20 EMA
    
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
            
            # Forward test 5 sessions
            stop_px = entry_px * 0.965 # -3.5% stop
            hit_tp = False
            exit_px = entry_px
            bars = 0
            
            for f in range(1, 6):
                c_idx = idx + f
                b_low = df['low'].iloc[c_idx]
                b_high = df['high'].iloc[c_idx]
                b_close = df['close'].iloc[c_idx]
                
                # Check stop
                if b_low <= stop_px:
                    exit_px = stop_px
                    bars = f
                    break
                # Quick take-profit at +12.0%
                elif (b_high - entry_px) / entry_px >= 0.12:
                    exit_px = entry_px * 1.12
                    bars = f
                    hit_tp = True
                    break
                elif f == 5:
                    exit_px = b_close
                    bars = 5
                    
            ret = (exit_px - entry_px) / entry_px * 100
            candidates.append({
                'ticker': ticker,
                'entry_date': pd.to_datetime(entry_date),
                'entry_price': entry_px,
                'exit_price': exit_px,
                'ret_pct': ret,
                'bars': bars,
                'rvol': df['rvol'].iloc[idx]
            })
            
    df_all = pd.DataFrame(candidates)
    df_all = df_all.sort_values(by='entry_date').reset_index(drop=True)
    print(f"Total historical velocity triggers found: {len(df_all)}")
    
    # Chronological Portfolio Simulation:
    # Let's test 2 Portfolio Models from 2019 to 2026:
    # Model A: 50% Sizing (Max 2 concurrent slots)
    # Model B: 100% Sniper Sizing (1 trade at a time, full cash compounding!)
    
    # Let's run Model B (100% full compounding sniper):
    start_capital = 100000.0 # 1 Lakh
    capital = start_capital
    trade_log = []
    
    last_exit_date = pd.Timestamp('2019-01-01')
    
    for _, t in df_all[df_all['entry_date'] >= '2019-01-01'].iterrows():
        # If no active trade, take this trade
        if t['entry_date'] >= last_exit_date:
            pnl_pct = t['ret_pct']
            gain_rs = capital * (pnl_pct / 100.0)
            capital += gain_rs
            last_exit_date = t['entry_date'] + pd.to_timedelta(t['bars'] * 1.45, unit='D')
            trade_log.append({
                'ticker': t['ticker'],
                'entry_date': t['entry_date'],
                'exit_date': last_exit_date,
                'ret_pct': pnl_pct,
                'bars': t['bars'],
                'equity_after': capital
            })
            
    df_snip = pd.DataFrame(trade_log)
    print("\n" + "="*85)
    print("CHRONOLOGICAL 100% COMPOUNDING SNIPER SIMULATION (2019–2026)")
    print("="*85)
    print(f"Total Sequential Trades Executed: {len(df_snip)}")
    win_cnt = (df_snip['ret_pct'] > 0).sum()
    print(f"Win Rate                       : {win_cnt / len(df_snip) * 100:.1f}%")
    print(f"Average Holding Time           : {df_snip['bars'].mean():.1f} sessions (~4 days)")
    print(f"Starting Capital               : Rs. {start_capital:,.2f}")
    print(f"Ending Capital                 : Rs. {capital:,.2f}")
    
    # Calculate Year-by-Year Compounded Returns:
    df_snip['year'] = df_snip['entry_date'].dt.year
    print("\nYear-by-Year Actual Compounded Performance:")
    print(f"{'Year':<8} | {'Trades':<8} | {'Wins':<6} | {'Year Net Gain':<15} | {'Year-End Capital':<20}")
    print("-" * 65)
    
    prev_eq = start_capital
    for yr, group in df_snip.groupby('year'):
        yr_end_eq = group['equity_after'].iloc[-1]
        yr_gain = (yr_end_eq - prev_eq) / prev_eq * 100
        yr_wins = (group['ret_pct'] > 0).sum()
        print(f"{yr:<8} | {len(group):<8} | {yr_wins:<6} | {yr_gain:>+7.1f}%        | Rs. {yr_end_eq:>12,.0f}")
        prev_eq = yr_end_eq

if __name__ == '__main__':
    run_chronological_skyrocket_backtest()
