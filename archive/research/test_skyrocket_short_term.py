import pickle
import os
import pandas as pd
import numpy as np

def test_skyrocket_short_term():
    universe = {}
    for p in ['data/cache/universe_10y.pkl', 'data/cache/high_beta_universe.pkl']:
        if os.path.exists(p):
            with open(p, 'rb') as f:
                d = pickle.load(f)
                universe.update(d)
                
    print(f"Testing the High-Asymmetry Short-Term Engine on {len(universe)} tickers...")
    
    # STRATEGY RULES:
    # 1. Selection: High Beta / Momentum Leaders only (RVOL >= 2.5x, Day Gain >= 2.5%, Close near high >= 0.75)
    # 2. Strict Tight Stop: Max -2.5% to -3.0% (Zero tolerance for fake breakouts)
    # 3. Asymmetric Profit Capture:
    #    - Do NOT sell at +3% or +4%!
    #    - Aim for +10% to +16% short-term thrust (1-5 days)
    #    - Trail stop to breakeven once stock hits +5%
    # 4. Position Sizing:
    #    - 50% capital per trade (2 sniper slots) or 33% capital (3 slots)
    
    trades = []
    
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
        df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        
        # 3-day tightness
        roll_max = df['high'].shift(1).rolling(3).max()
        roll_min = df['low'].shift(1).rolling(3).min()
        df['tightness_3d'] = (roll_max - roll_min) / (df['close'].shift(1) + 1e-6) * 100
        
        # High-octane ignition condition:
        # Stock above 20 EMA, RVOL >= 2.5x, day return >= 2.5%, close in top 25% of candle, tightness < 6%
        cond = (df['close'] > df['ema20']) & (df['rvol'] >= 2.5) & (df['ret_1d'] >= 2.5) & (df['close_loc'] >= 0.75) & (df['tightness_3d'] < 6.0)
        
        indices = np.where(cond.values)[0]
        
        last_exit = -1
        for idx in indices:
            if idx < 20 or idx >= len(df) - 7:
                continue
            if idx <= last_exit:
                continue
                
            entry_px = df['close'].iloc[idx]
            entry_date = df.index[idx]
            
            # Hard -2.8% stop
            stop_px = entry_px * 0.972
            breakeven_set = False
            exit_px = entry_px
            bars = 0
            
            for f in range(1, 8): # up to 7 sessions max
                c_idx = idx + f
                b_low = df['low'].iloc[c_idx]
                b_high = df['high'].iloc[c_idx]
                b_close = df['close'].iloc[c_idx]
                prev_low = df['low'].iloc[c_idx - 1]
                
                # If gains >= +5%, set stop to breakeven (+0.5%)
                if not breakeven_set and (b_high - entry_px) / entry_px >= 0.05:
                    breakeven_set = True
                    stop_px = max(stop_px, entry_px * 1.005)
                    
                # Check stop
                if b_low <= stop_px:
                    exit_px = stop_px
                    bars = f
                    break
                    
                # Target hit: +14% (Fast explosion target)
                if (b_high - entry_px) / entry_px >= 0.14:
                    exit_px = entry_px * 1.14
                    bars = f
                    break
                    
                # If breakeven set and past session 3, trail on previous day's low
                if breakeven_set and f >= 3:
                    if b_low <= prev_low:
                        exit_px = prev_low
                        bars = f
                        break
                        
                # End of short term window (session 7)
                if f == 7:
                    exit_px = b_close
                    bars = 7
                    break
                    
            ret = (exit_px - entry_px) / entry_px * 100
            trades.append({
                'ticker': ticker,
                'date': entry_date,
                'ret': ret,
                'bars': bars
            })
            last_exit = idx + bars
            
    df_t = pd.DataFrame(trades)
    print("\n" + "="*85)
    print("HIGH-ASYMMETRY SHORT-TERM ENGINE RESULTS (2018–2026)")
    print("="*85)
    
    tot = len(df_t)
    win_rate = (df_t['ret'] > 0).mean() * 100
    avg_ret = df_t['ret'] * 1.0
    avg_ret_mean = avg_ret.mean()
    avg_win = df_t[df_t['ret'] > 0]['ret'].mean()
    avg_loss = df_t[df_t['ret'] <= 0]['ret'].mean()
    pf = abs(df_t[df_t['ret'] > 0]['ret'].sum() / (df_t[df_t['ret'] <= 0]['ret'].sum() + 1e-6))
    avg_bars = df_t['bars'].mean()
    
    print(f"Total Quality Trades : {tot}")
    print(f"Win Rate             : {win_rate:.1f}%")
    print(f"Average Return/Trade : {avg_ret_mean:+.2f}%")
    print(f"Average Winner       : {avg_win:+.2f}% (High Asymmetry!)")
    print(f"Average Loser        : {avg_loss:+.2f}% (Strictly cut at -2.8%)")
    print(f"Payoff Ratio (Win/Loss): {abs(avg_win/avg_loss):.2f} : 1")
    print(f"Profit Factor        : {pf:.2f}")
    print(f"Average Duration     : {avg_bars:.1f} sessions (under 1 week!)")
    
    # Compounding calculations:
    # Say we take 40 quality trades a year:
    trades_per_year = 40
    
    # 1. 10% sizing (Retail style):
    comp_10 = ((1 + (avg_ret_mean * 0.10) / 100) ** trades_per_year - 1.0) * 100
    # 2. 33% sizing (3 concurrent slots):
    comp_33 = ((1 + (avg_ret_mean * 0.33) / 100) ** trades_per_year - 1.0) * 100
    # 3. 50% sizing (2 sniper bullets):
    comp_50 = ((1 + (avg_ret_mean * 0.50) / 100) ** trades_per_year - 1.0) * 100
    # 4. 100% full sequential compounding:
    comp_100 = ((1 + (avg_ret_mean * 1.0) / 100) ** min(trades_per_year, int(240/avg_bars)) - 1.0) * 100
    
    print("\n--- ANNUAL COMPOUNDED PORTFOLIO VELOCITY (40 Trades/Year) ---")
    print(f"  * 10% Position Size (10 tiny slots) : {comp_10:+.1f}% / year")
    print(f"  * 33% Position Size (3 slots)       : {comp_33:+.1f}% / year")
    print(f"  * 50% Position Size (2 slots)       : {comp_50:+.1f}% / year")
    print(f"  * 100% Sequential Sizing (1 slot)   : {comp_100:+.1f}% / year")

if __name__ == '__main__':
    test_skyrocket_short_term()
