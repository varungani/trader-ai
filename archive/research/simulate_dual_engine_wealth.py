import pickle
import os
import pandas as pd
import numpy as np

def run_wealth_engine():
    # Load universe
    universe = {}
    for p in ['data/cache/universe_10y.pkl', 'data/cache/high_beta_universe.pkl']:
        if os.path.exists(p):
            with open(p, 'rb') as f:
                d = pickle.load(f)
                universe.update(d)
                
    print(f"Loaded {len(universe)} tickers for Deep Wealth Engine exploration.")
    
    # We want to test a TRUE "Wealth Algorithm":
    # The "Asymmetric Free-Roll Monster Engine"
    # Core Thesis:
    # 1. 90% of trades are ordinary (either small loss -5%, small scratch 0%, or nice +15%).
    # 2. But 10% of trades become MONSTERS (AppLovin, Mazdock, Trent, Dixon, Coinbase, Nvidia, ARM) that gain +80% to +250%.
    # 3. Traditional trading KILLS the monsters by capping profits at +8% or +10%.
    # 4. Long-term buy-and-hold gets KILLED when losers drop -70%.
    # 5. The Solution: "Free-Roll Pyramiding & Trend-Riding":
    #    - Enter on Coiled VDU Base or Pocket Pivot
    #    - Strict -6.5% Stop (Zero tolerance for bad entries)
    #    - Stage 1: At +10% gain, sell 25% of position (locks in +2.5% on portfolio, moves stop on remaining 75% to Breakeven). Risk on trade is now NEGATIVE (guaranteed profit).
    #    - Stage 2: Trail remaining 75% position on Daily 50 EMA (or Weekly 10 EMA).
    #    - DO NOT EXIT until the stock closes below the 50 EMA on above-average volume.
    #    - Let runners ride for up to 300 trading days (14 months).
    
    results = []
    
    for ticker, df in universe.items():
        if df is None or len(df) < 300:
            continue
            
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = df[col].astype(float)
                
        if 'close' not in df.columns or 'volume' not in df.columns:
            continue
            
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['sma200'] = df['close'].rolling(200).mean()
        
        # Volume metrics
        df['vol_ma50'] = df['volume'].rolling(50).mean()
        df['rvol'] = df['volume'] / (df['vol_ma50'].replace(0, np.nan) + 1e-6)
        df['pre_v_ratio'] = df['volume'].shift(1).rolling(10).mean() / (df['vol_ma50'].shift(1).replace(0, np.nan) + 1e-6)
        
        # 4-day close tightness
        roll_max = df['close'].shift(1).rolling(4).max()
        roll_min = df['close'].shift(1).rolling(4).min()
        df['tightness_4d'] = (roll_max - roll_min) / (roll_min + 1e-6) * 100
        
        # Relative Strength (120-day return)
        df['rs_120'] = df['close'] / df['close'].shift(120) - 1.0
        
        # Signal:
        # A: Coiled Spring (Tightness < 6.0%, Pre-Volume < 0.90x, RVOL > 1.35x, Close > Open, Close > EMA20)
        # B: Stage 2 Breakout/Pocket Pivot (RS > 15%, Close > EMA20, yesterday <= EMA20*1.01, RVOL > 1.5x)
        cond_a = (df['tightness_4d'] < 6.0) & (df['pre_v_ratio'] < 0.90) & (df['rvol'] > 1.35) & (df['close'] > df['open']) & (df['close'] > df['ema20'])
        cond_b = (df['rs_120'] > 0.15) & (df['close'] > df['ema20']) & (df['close'].shift(1) <= df['ema20'].shift(1) * 1.01) & (df['rvol'] > 1.5) & (df['close'] > df['open'])
        
        df['signal'] = cond_a | cond_b
        indices = np.where(df['signal'].values)[0]
        
        last_exit = -1
        for idx in indices:
            if idx <= 200 or idx >= len(df) - 250:
                continue
            if idx <= last_exit:
                continue
                
            entry_price = df['close'].iloc[idx]
            entry_date = df.index[idx]
            
            stop_price = entry_price * 0.935 # -6.5% initial stop
            partial_taken = False
            total_realized_pct = 0
            exit_price_final = entry_price
            holding_bars = 0
            
            # Simulate forward up to 300 bars
            for f in range(1, min(301, len(df) - idx)):
                c_idx = idx + f
                b_low = df['low'].iloc[c_idx]
                b_high = df['high'].iloc[c_idx]
                b_close = df['close'].iloc[c_idx]
                b_ema50 = df['ema50'].iloc[c_idx]
                
                # Check partial take profit at +10%
                if not partial_taken and (b_high - entry_price) / entry_price >= 0.10:
                    partial_taken = True
                    # Sell 25% at +10%
                    total_realized_pct += 0.25 * 10.0
                    # Move stop on remaining 75% to Breakeven (+0.5%)
                    stop_price = max(stop_price, entry_price * 1.005)
                    
                # Check Stop Loss
                if b_low <= stop_price:
                    if not partial_taken:
                        total_realized_pct = (stop_price - entry_price) / entry_price * 100
                    else:
                        remaining_ret = (stop_price - entry_price) / entry_price * 100
                        total_realized_pct += 0.75 * remaining_ret
                    holding_bars = f
                    exit_price_final = stop_price
                    break
                    
                # If partial taken and after 15 bars, trail remaining 75% on 50 EMA
                if partial_taken and f >= 15:
                    if b_close < b_ema50:
                        remaining_ret = (b_close - entry_price) / entry_price * 100
                        total_realized_pct += 0.75 * remaining_ret
                        holding_bars = f
                        exit_price_final = b_close
                        break
                        
                if f == 300 or c_idx == len(df) - 1:
                    remaining_ret = (b_close - entry_price) / entry_price * 100
                    if not partial_taken:
                        total_realized_pct = remaining_ret
                    else:
                        total_realized_pct += 0.75 * remaining_ret
                    holding_bars = f
                    exit_price_final = b_close
                    break
                    
            results.append({
                'ticker': ticker,
                'entry_date': entry_date,
                'entry_price': entry_price,
                'exit_price': exit_price_final,
                'ret_pct': total_realized_pct,
                'bars': holding_bars,
                'partial_taken': partial_taken
            })
            
            last_exit = idx + max(holding_bars, 10)
            
    df_res = pd.DataFrame(results)
    print("\n" + "="*85)
    print("RESULTS: ASYMMETRIC FREE-ROLL MONSTER ENGINE (2018-2026)")
    print("="*85)
    
    total = len(df_res)
    win_rate = (df_res['ret_pct'] > 0).mean() * 100
    avg_ret = df_res['ret_pct'].mean()
    median_ret = df_res['ret_pct'].median()
    avg_winner = df_res[df_res['ret_pct'] > 0]['ret_pct'].mean()
    avg_loser = df_res[df_res['ret_pct'] <= 0]['ret_pct'].mean()
    wins = df_res[df_res['ret_pct'] > 0]['ret_pct'].sum()
    losses = abs(df_res[df_res['ret_pct'] <= 0]['ret_pct'].sum())
    profit_factor = wins / (losses + 1e-6)
    
    gains_30 = (df_res['ret_pct'] >= 30.0).sum()
    gains_50 = (df_res['ret_pct'] >= 50.0).sum()
    gains_75 = (df_res['ret_pct'] >= 75.0).sum()
    gains_100 = (df_res['ret_pct'] >= 100.0).sum()
    
    print(f"Total Completed Trades: {total}")
    print(f"Win Rate              : {win_rate:.1f}%")
    print(f"Average Return/Trade  : {avg_ret:+.2f}%")
    print(f"Median Return         : {median_ret:+.2f}%")
    print(f"Avg Winner            : {avg_winner:+.2f}% | Avg Loser: {avg_loser:+.2f}%")
    print(f"Profit Factor         : {profit_factor:.2f}")
    print(f"Average Hold Time     : {df_res['bars'].mean():.1f} trading days ({df_res['bars'].mean()/21:.1f} months)")
    print(f"Trades >= +30% Net    : {gains_30} ({gains_30/total*100:.1f}%)")
    print(f"Trades >= +50% Net    : {gains_50} ({gains_50/total*100:.1f}%)")
    print(f"Trades >= +75% Net    : {gains_75} ({gains_75/total*100:.1f}%) [Like Brother's Trade!]")
    print(f"Trades >= +100% Net   : {gains_100} ({gains_100/total*100:.1f}%)")
    
    print("\nTop 15 Monster Free-Roll Winners:")
    top15 = df_res.sort_values(by='ret_pct', ascending=False).head(15)
    for i, r in top15.iterrows():
        print(f"  {r['ticker']:<12} | Entry: {str(r['entry_date'])[:10]} | Exit: Rs.{r['exit_price']:.2f} | Net Return: +{r['ret_pct']:.1f}% | Held: {r['bars']} bars ({r['bars']/21:.1f} mos)")
        
    df_res.to_csv('data/cache/freeroll_engine_results.csv', index=False)
    print("\nSaved full simulation results to data/cache/freeroll_engine_results.csv")

if __name__ == '__main__':
    run_wealth_engine()
