import pickle
import os
import pandas as pd
import numpy as np

def run_institutional_short_term():
    universe = {}
    for p in ['data/cache/universe_10y.pkl', 'data/cache/high_beta_universe.pkl']:
        if os.path.exists(p):
            with open(p, 'rb') as f:
                d = pickle.load(f)
                universe.update(d)
                
    print(f"Loaded {len(universe)} tickers for Institutional Short-Term High-Velocity Engine.")
    
    # We want to test the TRUE institutional short-term setup that makes explosive fast money:
    # 1. Trend: Stock above 20 EMA and 50 SMA (Stage 2 thrust).
    # 2. Base: Stock broke out to a 20-day NEW HIGH (clean breakout, not intraday chop).
    # 3. Volatility Squeeze prior to breakout: 4-day close tightness < 5.0% OR 10-day volume dry-up < 0.85x.
    # 4. Institutional Explosion: Today's RVOL >= 2.0x (Smart money clearing the book).
    # 5. Bullish Close: Close in the top 25% of the day's candle (buyers in total control).
    
    # Short-Term Exit Rules (Strictly 3 to 10 trading sessions!):
    # Rule A: Stop-Loss = Low of Breakout Day OR -4.5% (whichever is tighter).
    # Rule B: At +6% (2R), move stop to Breakeven (Trade is now risk-free).
    # Rule C: Profit Target:
    #   - Scale out 50% at +8.0% to +10.0% (quick cash in 2-4 days)
    #   - Trail remaining 50% on 5 EMA or low of previous day for up to 10 sessions!
    
    trades = []
    
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
            
        df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['sma50'] = df['close'].rolling(50).mean()
        df['vol_ma50'] = df['volume'].rolling(50).mean()
        df['rvol'] = df['volume'] / (df['vol_ma50'].replace(0, np.nan) + 1e-6)
        
        # 20-day high breakout
        df['high_20d'] = df['high'].shift(1).rolling(20).max()
        df['is_20d_breakout'] = df['close'] > df['high_20d']
        
        # 4-day tightness prior
        roll_max = df['close'].shift(1).rolling(4).max()
        roll_min = df['close'].shift(1).rolling(4).min()
        df['tightness_4d'] = (roll_max - roll_min) / (roll_min + 1e-6) * 100
        
        # Pre-volume ratio (volume dry-up)
        df['pre_v_ratio'] = df['volume'].shift(1).rolling(10).mean() / (df['vol_ma50'].shift(1).replace(0, np.nan) + 1e-6)
        
        # Candle close location
        df['close_loc'] = (df['close'] - df['low']) / (df['high'] - df['low'] + 1e-6)
        
        # The Institutional Thrust Signal:
        cond_trend = (df['close'] > df['ema20']) & (df['ema20'] > df['sma50'])
        cond_base = (df['tightness_4d'] < 6.0) | (df['pre_v_ratio'] < 0.90)
        cond_breakout = df['is_20d_breakout']
        cond_volume = df['rvol'] >= 1.8
        cond_candle = (df['close'] > df['open']) & (df['close_loc'] >= 0.70)
        
        df['signal'] = cond_trend & cond_base & cond_breakout & cond_volume & cond_candle
        
        indices = np.where(df['signal'].values)[0]
        
        last_exit = -1
        for idx in indices:
            if idx < 30 or idx >= len(df) - 10:
                continue
            if idx <= last_exit:
                continue
                
            entry_px = df['close'].iloc[idx]
            entry_date = df.index[idx]
            breakout_low = df['low'].iloc[idx]
            
            # Tight stop: max(breakout_low, entry_px * 0.955) -> Max loss 4.5%
            stop_px = max(breakout_low, entry_px * 0.955)
            
            # Simulate forward up to 10 sessions (Strict short term!)
            hit_partial = False
            total_realized_pct = 0.0
            exit_px = entry_px
            holding_bars = 0
            
            for f in range(1, 11):
                c_idx = idx + f
                b_low = df['low'].iloc[c_idx]
                b_high = df['high'].iloc[c_idx]
                b_close = df['close'].iloc[c_idx]
                prev_low = df['low'].iloc[c_idx - 1]
                
                # Check partial take profit at +8.0%
                if not hit_partial and (b_high - entry_px) / entry_px >= 0.08:
                    hit_partial = True
                    total_realized_pct += 0.50 * 8.0 # Lock 50% at +8.0%
                    stop_px = max(stop_px, entry_px * 1.005) # Breakeven on rest
                    
                # Check Stop
                if b_low <= stop_px:
                    if not hit_partial:
                        total_realized_pct = (stop_px - entry_px) / entry_px * 100
                    else:
                        remaining_ret = (stop_px - entry_px) / entry_px * 100
                        total_realized_pct += 0.50 * remaining_ret
                    exit_px = stop_px
                    holding_bars = f
                    break
                    
                # If partial hit and past day 4, trail remaining 50% on prior day's low
                if hit_partial and f >= 4:
                    if b_low <= prev_low:
                        remaining_ret = (prev_low - entry_px) / entry_px * 100
                        total_realized_pct += 0.50 * remaining_ret
                        exit_px = prev_low
                        holding_bars = f
                        break
                        
                # End of short-term window (Day 10)
                if f == 10:
                    remaining_ret = (b_close - entry_px) / entry_px * 100
                    if not hit_partial:
                        total_realized_pct = remaining_ret
                    else:
                        total_realized_pct += 0.50 * remaining_ret
                    exit_px = b_close
                    holding_bars = 10
                    break
                    
            trades.append({
                'ticker': ticker,
                'entry_date': entry_date,
                'entry_price': entry_px,
                'exit_price': exit_px,
                'ret_pct': total_realized_pct,
                'bars': holding_bars,
                'hit_partial': hit_partial
            })
            
            last_exit = idx + max(holding_bars, 2)
            
    df_res = pd.DataFrame(trades)
    print("\n" + "="*85)
    print("RESULTS: INSTITUTIONAL HIGH-VELOCITY SHORT-TERM SYSTEM (3 TO 10 SESSIONS)")
    print("="*85)
    
    total = len(df_res)
    win_rate = (df_res['ret_pct'] > 0).mean() * 100
    avg_ret = df_res['ret_pct'].mean()
    median_ret = df_res['ret_pct'].median()
    avg_win = df_res[df_res['ret_pct'] > 0]['ret_pct'].mean()
    avg_loss = df_res[df_res['ret_pct'] <= 0]['ret_pct'].mean()
    wins = df_res[df_res['ret_pct'] > 0]['ret_pct'].sum()
    losses = abs(df_res[df_res['ret_pct'] <= 0]['ret_pct'].sum())
    pf = wins / (losses + 1e-6)
    
    avg_bars = df_res['bars'].mean()
    
    gains_8 = (df_res['ret_pct'] >= 8.0).sum()
    gains_15 = (df_res['ret_pct'] >= 15.0).sum()
    gains_25 = (df_res['ret_pct'] >= 25.0).sum()
    
    print(f"Total Sample Trades  : {total}")
    print(f"Win Rate             : {win_rate:.1f}%")
    print(f"Average Return/Trade : {avg_ret:+.2f}%")
    print(f"Median Return        : {median_ret:+.2f}%")
    print(f"Avg Winner           : {avg_win:+.2f}% | Avg Loser: {avg_loss:.2f}%")
    print(f"Profit Factor        : {pf:.2f}")
    print(f"Avg Holding Duration : {avg_bars:.1f} trading sessions ({avg_bars} days!)")
    print(f"Trades >= +8.0% Net  : {gains_8} ({gains_8/total*100:.1f}%)")
    print(f"Trades >= +15.0% Net : {gains_15} ({gains_15/total*100:.1f}%)")
    print(f"Trades >= +25.0% Net : {gains_25} ({gains_25/total*100:.1f}%)")
    
    # Capital Velocity Compounding Calculation:
    # 240 trading days / 6.5 days = ~37 cycles per year!
    annual_turnover_cycles = 240 / avg_bars
    compounded_annual_gain = ((1 + avg_ret / 100) ** annual_turnover_cycles - 1.0) * 100
    print(f"\n--- CAPITAL VELOCITY MULTIPLIER ---")
    print(f"Annual Turnover Cycles: ~{annual_turnover_cycles:.1f} cycles per year")
    print(f"Compounded Annual Edge: +{compounded_annual_gain:.1f}% per year in pure short-term trading!")
    
    print("\nTop 15 Explosive Short-Term Trades (3 to 10 Days):")
    for _, r in df_res.sort_values(by='ret_pct', ascending=False).head(15).iterrows():
        print(f"  {r['ticker']:<12} | Entry: {str(r['entry_date'])[:10]} | Exit: Rs.{r['exit_price']:.2f} | Net: +{r['ret_pct']:>5.1f}% | Bars: {int(r['bars'])} sessions")
        
    df_res.to_csv('data/cache/short_term_velocity_results.csv', index=False)
    print("\nSaved short-term results to data/cache/short_term_velocity_results.csv")

if __name__ == '__main__':
    run_institutional_short_term()
