import pickle
import os
import pandas as pd
import numpy as np

def run_simulation():
    # Load all universe data
    universe = {}
    for p in ['data/cache/universe_10y.pkl', 'data/cache/high_beta_universe.pkl']:
        if os.path.exists(p):
            with open(p, 'rb') as f:
                d = pickle.load(f)
                universe.update(d)
                
    print(f"Loaded total {len(universe)} unique tickers.")
    
    results_swing = []
    results_bnh = []
    results_rider_ema20 = []
    results_rider_ema50 = []
    
    for ticker, df in universe.items():
        if df is None or len(df) < 250:
            continue
            
        df = df.copy()
        # Standardize column names to lower
        df.columns = [c.lower() for c in df.columns]
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col not in df.columns:
                continue
            df[col] = df[col].astype(float)
            
        if 'close' not in df.columns or 'volume' not in df.columns:
            continue
            
        # Moving averages
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['sma50'] = df['close'].rolling(50).mean()
        df['sma200'] = df['close'].rolling(200).mean()
        
        # Volume metrics
        df['vol_ma50'] = df['volume'].rolling(50).mean()
        df['rvol'] = df['volume'] / (df['vol_ma50'].replace(0, np.nan) + 1e-6)
        df['pre_v_ratio'] = df['volume'].shift(1).rolling(10).mean() / (df['vol_ma50'].shift(1).replace(0, np.nan) + 1e-6)
        
        # 4-day close tightness
        roll_max = df['close'].shift(1).rolling(4).max()
        roll_min = df['close'].shift(1).rolling(4).min()
        df['tightness_4d'] = (roll_max - roll_min) / (roll_min + 1e-6) * 100
        
        # 52w high
        df['high_52w'] = df['high'].rolling(252).max()
        df['pct_from_52w'] = (df['close'] - df['high_52w']) / df['high_52w'] * 100
        
        # Entry Signals:
        # 1. Coiled Springboard: tightness < 6.5%, pre_v < 0.95, RVOL today > 1.3, close > open, close > ema20
        # 2. Stage 2 Pocket Pivot: close > ema20, yesterday close <= ema20*1.01, rvol > 1.4, close > open
        signal_coil = (df['tightness_4d'] < 6.5) & (df['pre_v_ratio'] < 0.95) & (df['rvol'] > 1.3) & (df['close'] > df['open']) & (df['close'] > df['ema20'])
        signal_pivot = (df['close'] > df['ema20']) & (df['close'].shift(1) <= df['ema20'].shift(1) * 1.01) & (df['rvol'] > 1.4) & (df['close'] > df['open'])
        
        df['entry_signal'] = signal_coil | signal_pivot
        
        indices = np.where(df['entry_signal'].values)[0]
        
        last_exit_idx = -1
        for idx in indices:
            if idx <= 200 or idx >= len(df) - 250:
                continue
            if idx <= last_exit_idx:
                continue
                
            entry_price = df['close'].iloc[idx]
            entry_date = df.index[idx]
            
            # --- 1. RETAIL SWING SIMULATION (+8% target, -5% stop, max 20 bars) ---
            sw_exit_price = entry_price
            sw_bars = 0
            for f in range(1, 21):
                cur_idx = idx + f
                bar_high = df['high'].iloc[cur_idx]
                bar_low = df['low'].iloc[cur_idx]
                bar_close = df['close'].iloc[cur_idx]
                
                if (bar_low - entry_price) / entry_price <= -0.05:
                    sw_exit_price = entry_price * 0.95
                    sw_bars = f
                    break
                elif (bar_high - entry_price) / entry_price >= 0.08:
                    sw_exit_price = entry_price * 1.08
                    sw_bars = f
                    break
                elif f == 20:
                    sw_exit_price = bar_close
                    sw_bars = 20
            sw_ret = (sw_exit_price - entry_price) / entry_price * 100
            results_swing.append({
                'ticker': ticker, 'date': entry_date, 'ret': sw_ret, 'bars': sw_bars
            })
            
            # --- 2. NAIVE BUY AND HOLD (Hold 250 bars / 1 year) ---
            bnh_close = df['close'].iloc[idx + 250]
            bnh_max_dd = 0
            peak = entry_price
            for f in range(1, 251):
                p = df['close'].iloc[idx + f]
                if p > peak:
                    peak = p
                dd = (p - peak) / peak * 100
                if dd < bnh_max_dd:
                    bnh_max_dd = dd
            bnh_ret = (bnh_close - entry_price) / entry_price * 100
            results_bnh.append({
                'ticker': ticker, 'date': entry_date, 'ret': bnh_ret, 'max_dd': bnh_max_dd
            })
            
            # --- 3. ASYMMETRIC POSITION TREND RIDER (EMA 20) ---
            rider_stop = entry_price * 0.93
            breakeven_locked = False
            r_exit_price = entry_price
            r_bars = 0
            
            for f in range(1, 251):
                cur_idx = idx + f
                bar_low = df['low'].iloc[cur_idx]
                bar_high = df['high'].iloc[cur_idx]
                bar_close = df['close'].iloc[cur_idx]
                cur_ema20 = df['ema20'].iloc[cur_idx]
                
                if not breakeven_locked and (bar_high - entry_price) / entry_price >= 0.06:
                    breakeven_locked = True
                    rider_stop = max(rider_stop, entry_price)
                    
                if bar_low <= rider_stop:
                    r_exit_price = rider_stop
                    r_bars = f
                    break
                    
                if breakeven_locked and f >= 10:
                    if bar_close < cur_ema20:
                        r_exit_price = bar_close
                        r_bars = f
                        break
                        
                if f == 250:
                    r_exit_price = bar_close
                    r_bars = 250
                    
            r_ret = (r_exit_price - entry_price) / entry_price * 100
            results_rider_ema20.append({
                'ticker': ticker, 'date': entry_date, 'ret': r_ret, 'bars': r_bars
            })
            
            # --- 4. ASYMMETRIC MONSTER RIDER (EMA 50 Deep Trail) ---
            rider50_stop = entry_price * 0.93
            be_locked50 = False
            r50_exit_price = entry_price
            r50_bars = 0
            
            for f in range(1, 251):
                cur_idx = idx + f
                bar_low = df['low'].iloc[cur_idx]
                bar_high = df['high'].iloc[cur_idx]
                bar_close = df['close'].iloc[cur_idx]
                cur_ema50 = df['ema50'].iloc[cur_idx]
                
                if not be_locked50 and (bar_high - entry_price) / entry_price >= 0.08:
                    be_locked50 = True
                    rider50_stop = max(rider50_stop, entry_price)
                    
                if bar_low <= rider50_stop:
                    r50_exit_price = rider50_stop
                    r50_bars = f
                    break
                    
                if be_locked50 and f >= 15:
                    if bar_close < cur_ema50:
                        r50_exit_price = bar_close
                        r50_bars = f
                        break
                        
                if f == 250:
                    r50_exit_price = bar_close
                    r50_bars = 250
                    
            r50_ret = (r50_exit_price - entry_price) / entry_price * 100
            results_rider_ema50.append({
                'ticker': ticker, 'date': entry_date, 'ret': r50_ret, 'bars': r50_bars
            })
            
            last_exit_idx = idx + max(r_bars, 10)
            
    df_sw = pd.DataFrame(results_swing)
    df_bnh = pd.DataFrame(results_bnh)
    df_r20 = pd.DataFrame(results_rider_ema20)
    df_r50 = pd.DataFrame(results_rider_ema50)
    
    print("\n" + "="*85)
    print("EMPIRICAL COMPARISON: RETAIL SWING vs BUY-AND-HOLD vs ASYMMETRIC TREND RIDERS")
    print("="*85)
    
    def summarize(df, name):
        total_trades = len(df)
        if total_trades == 0:
            print(f"No trades for {name}")
            return
        win_rate = (df['ret'] > 0).mean() * 100
        avg_ret = df['ret'].mean()
        median_ret = df['ret'].median()
        avg_win = df[df['ret'] > 0]['ret'].mean() if len(df[df['ret'] > 0]) > 0 else 0
        avg_loser = df[df['ret'] <= 0]['ret'].mean() if len(df[df['ret'] <= 0]) > 0 else 0
        win_sum = df[df['ret'] > 0]['ret'].sum()
        loss_sum = abs(df[df['ret'] <= 0]['ret'].sum())
        profit_factor = win_sum / (loss_sum + 1e-6)
        multi_baggers_30 = (df['ret'] >= 30.0).sum()
        multi_baggers_50 = (df['ret'] >= 50.0).sum()
        multi_baggers_100 = (df['ret'] >= 100.0).sum()
        avg_holding = df['bars'].mean() if 'bars' in df.columns else 250
        
        print(f"\n>>> {name} <<<")
        print(f"Total Sample Trades  : {total_trades}")
        print(f"Win Rate             : {win_rate:.1f}%")
        print(f"Average Return/Trade : {avg_ret:+.2f}%")
        print(f"Median Return        : {median_ret:+.2f}%")
        print(f"Avg Winner           : {avg_win:+.2f}% | Avg Loser: {avg_loser:+.2f}%")
        print(f"Profit Factor        : {profit_factor:.2f}")
        print(f"Avg Holding Duration : {avg_holding:.1f} trading days ({avg_holding/21:.1f} months)")
        print(f"Gains >= +30%        : {multi_baggers_30} ({multi_baggers_30/total_trades*100:.1f}%)")
        print(f"Gains >= +50%        : {multi_baggers_50} ({multi_baggers_50/total_trades*100:.1f}%)")
        print(f"Gains >= +100%       : {multi_baggers_100} ({multi_baggers_100/total_trades*100:.1f}%)")
        if 'max_dd' in df.columns:
            print(f"Avg Max Drawdown     : {df['max_dd'].mean():.2f}%")
            print(f"Worst Max Drawdown   : {df['max_dd'].min():.2f}%")

    summarize(df_sw, "1. RETAIL SWING (+8% Fixed Target, -5% Stop)")
    summarize(df_bnh, "2. NAIVE 1-YEAR BUY AND HOLD (Brother's Style, No Stops)")
    summarize(df_r20, "3. ASYMMETRIC TREND RIDER (Daily EMA 20 Trail)")
    summarize(df_r50, "4. ASYMMETRIC MONSTER RIDER (Daily EMA 50 Deep Trail)")
    
    # Save results
    df_r50.to_csv('data/cache/simulation_rider_ema50.csv', index=False)
    print("\nSaved detailed simulation results to data/cache/simulation_rider_ema50.csv")

if __name__ == '__main__':
    run_simulation()
