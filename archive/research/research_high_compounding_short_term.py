import pickle
import os
import pandas as pd
import numpy as np

def run_high_compounding_research():
    universe = {}
    for p in ['data/cache/universe_10y.pkl', 'data/cache/high_beta_universe.pkl']:
        if os.path.exists(p):
            with open(p, 'rb') as f:
                d = pickle.load(f)
                universe.update(d)
                
    print(f"Loaded {len(universe)} tickers. Researching why compounding stalls at 68% and how to reach 150%-300%+...")
    
    # Let's inspect the benchmark (NIFTY 50 or SPY/QQQ if available)
    # We will use RELIANCE.NS / Nifty proxy or general market trend
    # Let's compute a market regime indicator from all stocks: % of stocks above 50 SMA
    
    all_dates = set()
    for t, df in universe.items():
        if df is not None:
            all_dates.update(df.index)
    sorted_dates = sorted(list(all_dates))
    
    # Build market breadth: % of stocks above 50 SMA on each date
    print("Building market breadth index...")
    breadth_dict = {}
    
    # Sample 30 major liquid stocks for breadth
    liquid_tickers = [t for t in universe.keys() if 'NS' in t][:40]
    
    daily_above_50 = {d: [] for d in sorted_dates}
    for t in liquid_tickers:
        df = universe[t]
        if df is None or len(df) < 60:
            continue
        c = df['Close'] if 'Close' in df.columns else df['close']
        c = c.astype(float)
        sma50 = c.rolling(50).mean()
        above = (c > sma50).astype(int)
        for dt, val in above.dropna().items():
            if dt in daily_above_50:
                daily_above_50[dt].append(val)
                
    market_bullish_dates = set()
    for dt, lst in daily_above_50.items():
        if len(lst) >= 15:
            # Bullish regime if > 50% of stocks are above 50 SMA
            if np.mean(lst) >= 0.50:
                market_bullish_dates.add(dt)
                
    print(f"Total dates: {len(sorted_dates)}, Bullish Market Regime Dates: {len(market_bullish_dates)} ({len(market_bullish_dates)/len(sorted_dates)*100:.1f}%)")
    
    # Now let's compare:
    # Model 1: Raw Unfiltered Short-Term Trading (takes all 1600+ setups, in bull & bear markets, small sizing)
    # Model 2: Market Regime Filtered (ONLY trade when Market Breadth > 50% Bullish)
    # Model 3: A+ Pristine Filter (Market Bullish + Tight Pre-Breakout Range < 4.5% + RVOL >= 2.5x + High Beta stock)
    # Model 4: Concentrated Sniper Sizing (33% position size = 3 concurrent slots)
    
    models = {
        '1_Unfiltered_All': [],
        '2_Regime_Filtered': [],
        '3_A_Plus_Pristine': []
    }
    
    for ticker, df in universe.items():
        if df is None or len(df) < 100:
            continue
        df = df.copy()
        df.columns = [col.lower() for col in df.columns]
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
        
        # 3-day tightness prior
        roll_max = df['high'].shift(1).rolling(3).max()
        roll_min = df['low'].shift(1).rolling(3).min()
        df['tightness_3d'] = (roll_max - roll_min) / (df['close'].shift(1) + 1e-6) * 100
        
        # Signal basic: RVOL >= 2.2x, day_ret >= 2.5%, close_loc >= 0.70
        basic_sig = (df['rvol'] >= 2.2) & (df['ret_1d'] >= 2.5) & (df['close_loc'] >= 0.70) & (df['close'] > df['ema20'])
        
        indices = np.where(basic_sig.values)[0]
        for idx in indices:
            if idx < 20 or idx >= len(df) - 6:
                continue
                
            entry_date = df.index[idx]
            entry_px = df['close'].iloc[idx]
            tightness = df['tightness_3d'].iloc[idx]
            rvol = df['rvol'].iloc[idx]
            
            is_regime_bull = entry_date in market_bullish_dates
            is_a_plus = is_regime_bull and (tightness < 5.0) and (rvol >= 2.5)
            
            # Short-Term Exit (Hold strictly 3 to 6 sessions):
            # Stop: -3.2%
            # Partial profit: +8.0% (take 50%), trail rest on prior low up to day 6
            stop_px = entry_px * 0.968 # -3.2% stop
            hit_partial = False
            realized_ret = 0.0
            bars = 0
            
            for f in range(1, 7):
                c_idx = idx + f
                b_low = df['low'].iloc[c_idx]
                b_high = df['high'].iloc[c_idx]
                b_close = df['close'].iloc[c_idx]
                prev_low = df['low'].iloc[c_idx - 1]
                
                # Check partial at +8%
                if not hit_partial and (b_high - entry_px) / entry_px >= 0.08:
                    hit_partial = True
                    realized_ret += 0.50 * 8.0
                    stop_px = max(stop_px, entry_px * 1.005) # breakeven on rest
                    
                if b_low <= stop_px:
                    if not hit_partial:
                        realized_ret = (stop_px - entry_px) / entry_px * 100
                    else:
                        realized_ret += 0.50 * ((stop_px - entry_px) / entry_px * 100)
                    bars = f
                    break
                    
                # If partial hit and past day 3, trail rest on previous low
                if hit_partial and f >= 3:
                    if b_low <= prev_low:
                        realized_ret += 0.50 * ((prev_low - entry_px) / entry_px * 100)
                        bars = f
                        break
                        
                if f == 6:
                    rem_ret = (b_close - entry_px) / entry_px * 100
                    if not hit_partial:
                        realized_ret = rem_ret
                    else:
                        realized_ret += 0.50 * rem_ret
                    bars = 6
                    break
                    
            trade_obj = {
                'ticker': ticker,
                'date': entry_date,
                'ret': realized_ret,
                'bars': bars,
                'hit_partial': hit_partial
            }
            
            models['1_Unfiltered_All'].append(trade_obj)
            if is_regime_bull:
                models['2_Regime_Filtered'].append(trade_obj)
            if is_a_plus:
                models['3_A_Plus_Pristine'].append(trade_obj)
                
    print("\n" + "="*85)
    print("SHORT-TERM COMPOUNDING FORENSIC COMPARISON (2018–2026)")
    print("="*85)
    
    for m_name, t_list in models.items():
        df_m = pd.DataFrame(t_list)
        if len(df_m) == 0:
            continue
        tot = len(df_m)
        win_rate = (df_m['ret'] > 0).mean() * 100
        avg_ret = df_m['ret'].mean()
        avg_win = df_m[df_m['ret'] > 0]['ret'].mean() if len(df_m[df_m['ret'] > 0]) > 0 else 0
        avg_loss = df_m[df_m['ret'] <= 0]['ret'].mean() if len(df_m[df_m['ret'] <= 0]) > 0 else 0
        pf = abs(df_m[df_m['ret'] > 0]['ret'].sum() / (df_m[df_m['ret'] <= 0]['ret'].sum() + 1e-6))
        avg_bars = df_m['bars'].mean()
        
        # Sizing models:
        # If diversified across 10 stocks (10% size): portfolio gain per trade = avg_ret * 0.10
        # If concentrated in 3 stocks (33% size): portfolio gain per trade = avg_ret * 0.33
        # If sniper 2 stocks (50% size): portfolio gain per trade = avg_ret * 0.50
        
        # Let's calculate annual trades and annual compounded return
        years = 8.0
        trades_per_year = tot / years
        
        # Compounding with 33% position size (3 concurrent slots):
        # Effective portfolio trade return:
        port_ret_33 = avg_ret * 0.333
        # Number of sequential compounding turns per year = 240 / avg_bars
        # Max concurrent slots = 3, so total portfolio turns = (240 / avg_bars)
        # Annualized Portfolio Compounding:
        annual_compounded_10 = ((1 + (avg_ret * 0.10)/100) ** (trades_per_year) - 1.0) * 100
        annual_compounded_33 = ((1 + (avg_ret * 0.333)/100) ** (min(trades_per_year, 240/avg_bars * 3)) - 1.0) * 100
        annual_compounded_50 = ((1 + (avg_ret * 0.50)/100) ** (min(trades_per_year, 240/avg_bars * 2)) - 1.0) * 100
        
        print(f"\n>>> MODEL: {m_name} <<<")
        print(f"Total Trades         : {tot} ({trades_per_year:.1f} trades/year)")
        print(f"Win Rate             : {win_rate:.1f}%")
        print(f"Average Return/Trade : {avg_ret:+.2f}%")
        print(f"Avg Winner           : {avg_win:+.2f}% | Avg Loser: {avg_loss:.2f}%")
        print(f"Profit Factor        : {pf:.2f}")
        print(f"Avg Duration         : {avg_bars:.1f} sessions")
        print(f"--- Compounded Portfolio Annual Return ---")
        print(f"  * Diversified (10 stocks, 10% each)  : {annual_compounded_10:+.1f}% / year")
        print(f"  * Concentrated (3 stocks, 33% each)  : {annual_compounded_33:+.1f}% / year")
        print(f"  * Sniper (2 stocks, 50% each)        : {annual_compounded_50:+.1f}% / year")

if __name__ == '__main__':
    run_high_compounding_research()
