import pickle
import os
import pandas as pd
import numpy as np

def run_short_term_backtest():
    universe = {}
    for p in ['data/cache/universe_10y.pkl', 'data/cache/high_beta_universe.pkl']:
        if os.path.exists(p):
            with open(p, 'rb') as f:
                d = pickle.load(f)
                universe.update(d)
                
    print(f"Loaded {len(universe)} tickers for Short-Term (3-7 Day) Velocity Testing.")
    
    # We will simulate 3 pure short-term strategies (holding strictly 3 to 7 market days):
    # Strategy 1: EPISODIC PIVOT (Gap >= +3.5%, RVOL >= 2.0x, Close > Open) -> Hold 3-5 days
    # Strategy 2: NR7 VOLATILITY SQUEEZE (Range is smallest of last 7 bars, RVOL today >= 1.8x, Close > High of past 3 days) -> Hold 5 days
    # Strategy 3: CAPITULATION SLINGSHOT (RSI(2) < 10, stretched below EMA20 by > 2.5 ATR, Hammer/Bullish reversal bar with RVOL >= 1.5x) -> Hold 3 days
    
    ep_trades = []
    nr7_trades = []
    slingshot_trades = []
    
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
            
        # Vol metrics
        df['vol_ma20'] = df['volume'].rolling(20).mean()
        df['rvol'] = df['volume'] / (df['vol_ma20'].replace(0, np.nan) + 1e-6)
        
        # ATR 14
        h_l = df['high'] - df['low']
        h_pc = (df['high'] - df['close'].shift(1)).abs()
        l_pc = (df['low'] - df['close'].shift(1)).abs()
        tr = pd.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)
        df['atr14'] = tr.rolling(14).mean()
        
        # Moving averages
        df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        
        # RSI 2 (Connors RSI short-term indicator)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(2).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(2).mean()
        rs = gain / (loss.replace(0, np.nan) + 1e-6)
        df['rsi2'] = 100 - (100 / (1 + rs))
        
        # Daily range
        df['bar_range'] = df['high'] - df['low']
        df['min_range_7'] = df['bar_range'].rolling(7).min()
        df['is_nr7'] = (df['bar_range'] == df['min_range_7'])
        
        # Gap pct
        df['gap_pct'] = (df['open'] - df['close'].shift(1)) / df['close'].shift(1) * 100
        
        # --- 1. EPISODIC PIVOT (EP) ---
        # Gap >= 3.5%, RVOL >= 2.0x, Close in top 35% of bar, Close > Open
        close_pos = (df['close'] - df['low']) / (df['high'] - df['low'] + 1e-6)
        sig_ep = (df['gap_pct'] >= 3.5) & (df['rvol'] >= 2.0) & (df['close'] > df['open']) & (close_pos >= 0.65)
        
        # --- 2. NR7 SQUEEZE BREAKOUT ---
        # Yesterday was NR7, Today breaks above past 3-day high with RVOL >= 1.8x
        high_3d = df['high'].shift(1).rolling(3).max()
        sig_nr7 = (df['is_nr7'].shift(1) == True) & (df['close'] > high_3d) & (df['rvol'] >= 1.8) & (df['close'] > df['open'])
        
        # --- 3. CAPITULATION SLINGSHOT ---
        # RSI(2) < 10, distance from EMA20 < -2.0*ATR, today green hammer/reversal with RVOL >= 1.5x
        dist_ema20 = (df['close'] - df['ema20']) / df['atr14']
        sig_sling = (df['rsi2'].shift(1) < 10) & (dist_ema20.shift(1) < -2.0) & (df['close'] > df['open']) & (df['rvol'] >= 1.5)
        
        # Run forward simulation for EP (Hold 5 sessions, Stop: low of day 0 or -4.5%, Target: +15%)
        ep_indices = np.where(sig_ep.values)[0]
        for idx in ep_indices:
            if idx < 30 or idx >= len(df) - 6:
                continue
            entry_px = df['close'].iloc[idx]
            stop_px = max(df['low'].iloc[idx], entry_px * 0.955) # tight ~4.5% stop
            
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
                elif (b_high - entry_px) / entry_px >= 0.15:
                    exit_px = entry_px * 1.15
                    bars = f
                    break
                elif f == 5:
                    exit_px = b_close
                    bars = 5
            ep_trades.append({
                'ticker': ticker, 'date': df.index[idx], 'ret': (exit_px - entry_px)/entry_px * 100, 'bars': bars
            })
            
        # Run forward simulation for NR7 Squeeze (Hold 5 sessions, Stop: -4.0%, Target: +12%)
        nr7_indices = np.where(sig_nr7.values)[0]
        for idx in nr7_indices:
            if idx < 30 or idx >= len(df) - 6:
                continue
            entry_px = df['close'].iloc[idx]
            stop_px = entry_px * 0.96 # -4.0% tight stop
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
            nr7_trades.append({
                'ticker': ticker, 'date': df.index[idx], 'ret': (exit_px - entry_px)/entry_px * 100, 'bars': bars
            })
            
        # Run forward simulation for Capitulation Slingshot (Hold 3 sessions, Stop: -4.0%, Target: +10%)
        sling_indices = np.where(sig_sling.values)[0]
        for idx in sling_indices:
            if idx < 30 or idx >= len(df) - 4:
                continue
            entry_px = df['close'].iloc[idx]
            stop_px = entry_px * 0.96 # -4.0% stop
            exit_px = entry_px
            bars = 0
            for f in range(1, 4):
                c_idx = idx + f
                b_low = df['low'].iloc[c_idx]
                b_high = df['high'].iloc[c_idx]
                b_close = df['close'].iloc[c_idx]
                
                if b_low <= stop_px:
                    exit_px = stop_px
                    bars = f
                    break
                elif (b_high - entry_px) / entry_px >= 0.10:
                    exit_px = entry_px * 1.10
                    bars = f
                    break
                elif f == 3:
                    exit_px = b_close
                    bars = 3
            slingshot_trades.append({
                'ticker': ticker, 'date': df.index[idx], 'ret': (exit_px - entry_px)/entry_px * 100, 'bars': bars
            })

    print("\n" + "="*85)
    print("SHORT-TERM (3 TO 5 SESSIONS) HIGH-VELOCITY STRATEGY BACKTEST RESULTS")
    print("="*85)
    
    def summarize(trades, name):
        df = pd.DataFrame(trades)
        if len(df) == 0:
            print(f"No trades for {name}")
            return
        total = len(df)
        win_rate = (df['ret'] > 0).mean() * 100
        avg_ret = df['ret'].mean()
        avg_winner = df[df['ret'] > 0]['ret'].mean() if len(df[df['ret'] > 0]) > 0 else 0
        avg_loser = df[df['ret'] <= 0]['ret'].mean() if len(df[df['ret'] <= 0]) > 0 else 0
        pf = abs(df[df['ret'] > 0]['ret'].sum() / (df[df['ret'] <= 0]['ret'].sum() + 1e-6))
        avg_holding = df['bars'].mean()
        
        print(f"\n>>> {name} <<<")
        print(f"Total Trades         : {total}")
        print(f"Win Rate             : {win_rate:.1f}%")
        print(f"Average Return/Trade : {avg_ret:+.2f}%")
        print(f"Avg Winner           : {avg_winner:+.2f}% | Avg Loser: {avg_loser:+.2f}%")
        print(f"Profit Factor        : {pf:.2f}")
        print(f"Avg Holding Duration : {avg_holding:.1f} trading sessions (FAST CAPITAL TURNOVER!)")
        
        # Compounding potential: If you turn capital 30 times a year at avg_ret:
        annual_compounded = ((1 + avg_ret/100) ** (240 / avg_holding) - 1.0) * 100
        print(f"Annualized Compounded Velocity : +{annual_compounded:.1f}% per year!")
        
    summarize(ep_trades, "1. EPISODIC PIVOT / EARNINGS GAP & GO (Hold 3-5 Days, Tgt +15%, Stop -4.5%)")
    summarize(nr7_trades, "2. NR7 VOLATILITY SQUEEZE BREAKOUT (Hold 3-5 Days, Tgt +12%, Stop -4.0%)")
    summarize(slingshot_trades, "3. CAPITULATION OVERSOLD SLINGSHOT (Hold 1-3 Days, Tgt +10%, Stop -4.0%)")

if __name__ == '__main__':
    run_short_term_backtest()
