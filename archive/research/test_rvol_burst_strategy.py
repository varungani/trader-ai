import pickle
import os
import pandas as pd
import numpy as np

def run_rvol_burst_strategy():
    universe = {}
    for p in ['data/cache/universe_10y.pkl', 'data/cache/high_beta_universe.pkl']:
        if os.path.exists(p):
            with open(p, 'rb') as f:
                d = pickle.load(f)
                universe.update(d)
                
    print(f"Loaded {len(universe)} tickers. Testing Pure Short-Term RVOL Burst Strategy (3-5 Days)...")
    
    # STRATEGY RULES:
    # 1. Entry Trigger: Day RVOL >= 3.0x AND Day Return >= +3.0% AND Close in top 25% of candle body
    # 2. Holding Period: Strictly 3 to 5 TRADING DAYS
    # 3. Stop-Loss: Low of ignition day or -3.5%
    # 4. Target: Take profit at +10% to +15% or exit at bar 5
    
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
        
        sig = (df['rvol'] >= 3.0) & (df['ret_1d'] >= 3.0) & (df['close_loc'] >= 0.70)
        indices = np.where(sig.values)[0]
        
        last_exit = -1
        for idx in indices:
            if idx < 20 or idx >= len(df) - 5:
                continue
            if idx <= last_exit:
                continue
                
            entry_px = df['close'].iloc[idx]
            entry_date = df.index[idx]
            stop_px = max(df['low'].iloc[idx], entry_px * 0.965) # max -3.5% risk
            
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
                # Quick take profit at +12%
                elif (b_high - entry_px) / entry_px >= 0.12:
                    exit_px = entry_px * 1.12
                    bars = f
                    break
                # Time exit at session 5
                elif f == 5:
                    exit_px = b_close
                    bars = 5
                    
            ret = (exit_px - entry_px) / entry_px * 100
            trades.append({
                'ticker': ticker,
                'entry_date': entry_date,
                'entry_price': entry_px,
                'exit_price': exit_px,
                'ret_pct': ret,
                'bars': bars,
                'rvol': df['rvol'].iloc[idx],
                'day_ret': df['ret_1d'].iloc[idx]
            })
            last_exit = idx + bars
            
    df_t = pd.DataFrame(trades)
    print("\n" + "="*85)
    print("PURE SHORT-TERM RVOL BURST STRATEGY (3 TO 5 TRADING DAYS)")
    print("="*85)
    total = len(df_t)
    win_rate = (df_t['ret_pct'] > 0).mean() * 100
    avg_ret = df_t['ret_pct'].mean()
    median_ret = df_t['ret_pct'].median()
    avg_win = df_t[df_t['ret_pct'] > 0]['ret_pct'].mean()
    avg_loss = df_t[df_t['ret_pct'] <= 0]['ret_pct'].mean()
    wins = df_t[df_t['ret_pct'] > 0]['ret_pct'].sum()
    losses = abs(df_t[df_t['ret_pct'] <= 0]['ret_pct'].sum())
    pf = wins / (losses + 1e-6)
    
    print(f"Total Fast Trades    : {total}")
    print(f"Win Rate             : {win_rate:.1f}%")
    print(f"Average Return/Trade : {avg_ret:+.2f}% in ~3.8 days!")
    print(f"Median Return        : {median_ret:+.2f}%")
    print(f"Avg Winner           : {avg_win:+.2f}% | Avg Loser: {avg_loss:.2f}%")
    print(f"Profit Factor        : {pf:.2f}")
    print(f"Average Duration     : {df_t['bars'].mean():.1f} market sessions (FAST!)")
    
    # Capital Velocity:
    # 240 days / 3.8 days = ~63 trade cycles per year!
    cycles = 240 / df_t['bars'].mean()
    compounded = ((1 + avg_ret / 100) ** cycles - 1.0) * 100
    print(f"Capital Cycles/Year  : ~{cycles:.1f} cycles")
    print(f"Compounded Edge/Year : +{compounded:.1f}% per year!")
    
    print("\nTop 15 Fast Winners (All closed in <= 5 sessions):")
    for _, r in df_t.sort_values(by='ret_pct', ascending=False).head(15).iterrows():
        print(f"  {r['ticker']:<12} | Date: {str(r['entry_date'])[:10]} | Day 0 RVOL: {r['rvol']:4.1f}x | Net Gain: +{r['ret_pct']:>5.1f}% | Closed in: {int(r['bars'])} sessions")

if __name__ == '__main__':
    run_rvol_burst_strategy()
