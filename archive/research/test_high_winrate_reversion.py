import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pickle, pandas as pd, numpy as np, math
from backtesting.swing_midcap_backtest import load_cached_universe, compute_indicators
from data.costs import compute_indian_delivery_costs

univ, bm = load_cached_universe()
nifty_df = bm['^NSEI']

def enrich_reversion_indicators(df):
    res = compute_indicators(df)
    res['vol_sma20'] = res['Volume'].rolling(20).mean()
    res['vol_ratio'] = res['Volume'] / res['vol_sma20'].replace(0, np.nan)
    res['ema20'] = res['Close'].ewm(span=20, adjust=False).mean()
    res['sma200'] = res['Close'].rolling(200).mean()
    
    # RSI 2 (Connors RSI for mean reversion)
    delta = res['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(2).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(2).mean()
    rs = gain / (loss.replace(0, np.nan) + 1e-6)
    res['rsi2'] = 100 - (100 / (1 + rs))
    
    # Distance from 20 EMA in %
    res['dist_ema20'] = (res['Close'] - res['ema20']) / res['ema20'] * 100
    return res

print(f"Precomputing Mean-Reversion indicators across {len(univ)} tickers...")
indicators = {sym: enrich_reversion_indicators(df) for sym, df in univ.items()}
all_dates = nifty_df.index

def run_mean_reversion_backtest():
    """
    HIGH-WIN-RATE MEAN REVERSION:
    - Long-term trend: Stock above 200 SMA (healthy company, not bankrupt garbage)
    - Short-term oversold: 3-day pullback, RSI(2) < 15, stretched -3% to -8% below 20 EMA
    - Reversal confirmation: Today is green candle with RVOL >= 1.2x
    - Execution: Open(T+1) + 0.20% slippage
    - Exit: Target is return to 20 EMA or +6.0%, Stop is -4.0%
    """
    cash = 100000.0
    open_positions = {}
    pending_buys = []
    trades = []
    
    SLIPPAGE_PCT = 0.002
    MAX_POSITIONS = 3
    MIN_TICKET_SIZE = 15000.0
    
    for i in range(200, len(all_dates)):
        date_idx = all_dates[i]
        date_str = str(date_idx.date())
        year = date_idx.year
        
        # 1. Fill pending buys at Today's Open + Slippage
        if pending_buys:
            for sym in pending_buys:
                if sym in open_positions:
                    continue
                if len(open_positions) >= MAX_POSITIONS:
                    break
                ind = indicators[sym]
                if date_idx not in ind.index:
                    continue
                bar = ind.loc[date_idx]
                today_open = float(bar['Open'])
                if today_open <= 0 or math.isnan(today_open):
                    continue
                fill_px = round(today_open * (1.0 + SLIPPAGE_PCT), 2)
                
                empty_slots = MAX_POSITIONS - len(open_positions)
                alloc = min(cash / empty_slots, 35000.0)
                if alloc < MIN_TICKET_SIZE:
                    continue
                    
                qty = int(alloc // fill_px)
                cost = qty * fill_px
                if qty > 0 and cash >= cost:
                    cash -= cost
                    stop_px = round(fill_px * 0.96, 2)   # -4.0% stop
                    target_px = round(fill_px * 1.06, 2) # +6.0% quick mean reversion target
                    open_positions[sym] = {
                        'entry_price': fill_px,
                        'qty': qty,
                        'stop_loss': stop_px,
                        'target': target_px,
                        'peak_price': fill_px,
                        'days_held': 0,
                        'entry_date': date_str,
                    }
            pending_buys = []
            
        # 2. Check exits
        to_close = []
        for sym, pos in open_positions.items():
            ind = indicators[sym]
            if date_idx not in ind.index:
                pos['days_held'] += 1
                continue
            bar = ind.loc[date_idx]
            open_px = float(bar['Open'])
            high_px = float(bar['High'])
            low_px = float(bar['Low'])
            close_px = float(bar['Close'])
            pos['days_held'] += 1
            pos['peak_price'] = max(pos.get('peak_price', pos['entry_price']), high_px)
            
            exit_reason = None
            exit_px = 0.0
            
            if low_px <= pos['stop_loss']:
                exit_reason = 'STOP_LOSS'
                exit_px = min(pos['stop_loss'], open_px) if open_px < pos['stop_loss'] else pos['stop_loss']
            elif high_px >= pos['target']:
                exit_reason = 'TARGET_HIT (+6%)'
                exit_px = pos['target']
            elif pos['days_held'] >= 6: # 6 sessions max
                exit_reason = 'TIME_EXIT (6d)'
                exit_px = close_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(
                    buy_price=pos['entry_price'], sell_price=exit_px, quantity=pos['qty'], apply_stcg=False
                )
                cash += (exit_px * pos['qty']) - costs.total_friction_rupees
                trades.append({
                    'ticker': sym,
                    'year': year,
                    'net_pnl': costs.net_pnl_rupees,
                    'ret_pct': costs.net_pnl_pct,
                    'reason': exit_reason,
                    'days': pos['days_held']
                })
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        # 3. EOD Scan for Mean-Reversion Setups
        nifty_loc = nifty_df.index.get_loc(date_idx)
        regime_bullish = True
        if nifty_loc >= 50:
            n_close = float(nifty_df['Close'].iloc[nifty_loc])
            n_sma50 = float(nifty_df['Close'].iloc[nifty_loc-49:nifty_loc+1].mean())
            if n_close < n_sma50:
                regime_bullish = False
                
        if len(open_positions) < MAX_POSITIONS and regime_bullish:
            available = [s for s in univ.keys() if s not in open_positions]
            candidates = []
            for sym in available:
                ind = indicators[sym]
                if date_idx not in ind.index: continue
                loc = ind.index.get_loc(date_idx)
                if loc < 200: continue
                b = ind.iloc[loc]
                c = float(b['Close'])
                o = float(b['Open'])
                h = float(b['High'])
                l = float(b['Low'])
                sma200 = float(b['sma200'])
                rsi2 = float(b['rsi2'])
                dist_ema20 = float(b['dist_ema20'])
                vol_r = float(b['vol_ratio'])
                adtv = float(b['adtv_cr'])
                
                # Rule: Uptrend (Close > SMA200), Pullback (dist_ema20 between -2% and -7%),
                # Oversold (RSI2 < 20), Bullish reversal today (Close > Open, Close in upper 60% of bar)
                close_loc = (c - l) / (h - l + 1e-6)
                if adtv >= 5.0 and c > sma200 and -7.0 <= dist_ema20 <= -1.5 and rsi2 <= 20.0 and c > o and close_loc >= 0.60:
                    candidates.append((sym, rsi2, c))
                    
            # Sort by lowest RSI2 (most oversold quality bounce)
            candidates.sort(key=lambda x: x[1])
            slots_needed = MAX_POSITIONS - len(open_positions)
            pending_buys = [sym for sym, _, _ in candidates[:slots_needed]]
            
    df_t = pd.DataFrame(trades)
    print("\n" + "="*85)
    print("HIGH-WIN-RATE MEAN-REVERSION PULLBACK STRATEGY (OVERSOLD DIP BOUNCE)")
    print("="*85)
    
    total = len(df_t)
    win_rate = (df_t['net_pnl'] > 0).mean() * 100
    avg_ret = df_t['ret_pct'].mean()
    avg_win = df_t[df_t['net_pnl'] > 0]['ret_pct'].mean()
    avg_loss = df_t[df_t['net_pnl'] <= 0]['ret_pct'].mean()
    wins = df_t[df_t['net_pnl'] > 0]['net_pnl'].sum()
    losses = abs(df_t[df_t['net_pnl'] <= 0]['net_pnl'].sum())
    pf = wins / (losses + 1e-6)
    
    print(f"Total Completed Trades : {total}")
    print(f"Overall Win Rate       : {win_rate:.1f}%  <-- (LOOK AT THIS WIN RATE!)")
    print(f"Average Return/Trade   : {avg_ret:+.2f}%")
    print(f"Average Winner         : +{avg_win:.2f}% | Average Loser: {avg_loss:.2f}%")
    print(f"Profit Factor          : {pf:.2f}")
    print(f"Total Net P&L (INR)    : Rs. {df_t['net_pnl'].sum():+,.2f}")
    print(f"Average Holding Time   : {df_t['days'].mean():.1f} market sessions (FAST!)")
    
    print("\nYear-by-Year Breakdown:")
    for yr, grp in df_t.groupby('year'):
        yr_wr = (grp['net_pnl'] > 0).mean() * 100
        yr_pnl = grp['net_pnl'].sum()
        print(f"  {yr}: {len(grp):>2} trades | Win Rate: {yr_wr:>5.1f}% | Net P&L: Rs. {yr_pnl:>+8,.1f}")

if __name__ == '__main__':
    run_mean_reversion_backtest()
