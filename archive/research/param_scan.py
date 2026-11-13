import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pickle, pandas as pd, numpy as np
from backtesting.swing_midcap_backtest import load_cached_universe, compute_indicators
from data.costs import compute_indian_delivery_costs

univ, bm = load_cached_universe()
nifty_df = bm['^NSEI']
indicators = {sym: compute_indicators(df) for sym, df in univ.items()}
all_dates = nifty_df.index

def run_param_scan(max_hold, target_r_mult, stop_floor, rsi_min, rsi_max):
    cash = 100000.0
    open_positions = {}
    trades = []
    
    for i in range(200, len(all_dates)):
        date_idx = all_dates[i]
        date_str = str(date_idx.date())
        
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
            
            exit_reason = None
            exit_px = 0.0
            if low_px <= pos['stop_loss']:
                exit_reason = 'STOP_LOSS'
                exit_px = min(pos['stop_loss'], open_px)
            elif high_px >= pos['target']:
                exit_reason = 'TARGET_HIT'
                exit_px = pos['target']
            elif pos['days_held'] >= max_hold:
                exit_reason = f'TIME_EXPIRY_{max_hold}D'
                exit_px = close_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=exit_px, quantity=pos['qty'], apply_stcg=False)
                cash += (exit_px * pos['qty']) - costs.total_friction_rupees
                trades.append({
                    'net_pnl': costs.net_pnl_rupees,
                    'gross_pnl': costs.gross_pnl_rupees,
                    'reason': exit_reason
                })
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        nifty_loc = nifty_df.index.get_loc(date_idx)
        regime_bullish = True
        if nifty_loc >= 50:
            n_close = float(nifty_df['Close'].iloc[nifty_loc])
            n_sma50 = float(nifty_df['Close'].iloc[nifty_loc-49:nifty_loc+1].mean())
            if n_close < n_sma50:
                regime_bullish = False
                
        if len(open_positions) < 5 and regime_bullish:
            available = [s for s in univ.keys() if s not in open_positions]
            candidates = []
            for sym in available:
                ind = indicators[sym]
                if date_idx not in ind.index: continue
                loc = ind.index.get_loc(date_idx)
                if loc < 50: continue
                bar = ind.iloc[loc]
                close = float(bar['Close'])
                open_p = float(bar['Open'])
                ema20 = float(bar['ema20'])
                sma50 = float(bar['sma50'])
                sma200 = float(bar['sma200'])
                rsi = float(bar['rsi14'])
                mom60 = float(bar['mom60'])
                adtv = float(bar['adtv_cr'])
                if adtv < 5.0 or close <= 10.0: continue
                
                is_uptrend = close > sma50 and (sma50 > sma200 or mom60 > 5.0)
                low_3d = float(ind['Low'].iloc[loc-2:loc+1].min())
                tested_ema20 = low_3d <= (ema20 * 1.015) and close >= (ema20 * 0.97)
                rsi_ok = rsi_min <= rsi <= rsi_max
                green_reversal = close > open_p and close >= ema20
                if is_uptrend and tested_ema20 and rsi_ok and green_reversal:
                    candidates.append((sym, mom60, close, ema20))
                    
            candidates.sort(key=lambda x: x[1], reverse=True)
            for sym, mom60, close_px, ema20 in candidates[:5-len(open_positions)]:
                alloc = min(cash, 20000.0)
                qty = int(alloc // close_px)
                if qty > 0 and cash >= (qty * close_px):
                    stop_dist = max(stop_floor, min(0.06, (close_px - (ema20 * 0.985)) / close_px))
                    stop_px = round(close_px * (1.0 - stop_dist), 2)
                    target_px = round(close_px * (1.0 + (stop_dist * target_r_mult)), 2)
                    cash -= (qty * close_px)
                    open_positions[sym] = {
                        'entry_price': close_px, 'qty': qty, 'stop_loss': stop_px,
                        'target': target_px, 'days_held': 0
                    }
                    
    tot_trades = len(trades)
    if not tot_trades: return None
    wins = [t for t in trades if t['net_pnl'] > 0]
    losses = [t for t in trades if t['net_pnl'] <= 0]
    tot_net = sum(t['net_pnl'] for t in trades)
    wr = len(wins) / tot_trades * 100.0
    avg_win = np.mean([t['net_pnl'] for t in wins]) if wins else 0
    avg_loss = np.mean([abs(t['net_pnl']) for t in losses]) if losses else 0
    w_l_ratio = avg_win / avg_loss if avg_loss else 0
    exp_rs = tot_net / tot_trades
    
    return {
        'hold': max_hold, 'r_mult': target_r_mult, 'stop_fl': stop_floor,
        'rsi_band': f'{rsi_min}-{rsi_max}', 'trades': tot_trades,
        'win_rate': round(wr, 1), 'net_ret': round(tot_net / 1000.0, 1),
        'net_pnl': round(tot_net, 0), 'avg_win': round(avg_win, 0),
        'avg_loss': round(avg_loss, 0), 'wl_ratio': round(w_l_ratio, 2),
        'expectancy': round(exp_rs, 1)
    }

grid = [
    (15, 2.5, 0.035, 40, 65),
    (20, 2.5, 0.035, 40, 65),
    (25, 2.5, 0.035, 40, 65),
    (20, 3.0, 0.035, 40, 65),
    (25, 3.0, 0.035, 40, 65),
    (25, 3.0, 0.040, 40, 65),
    (20, 2.5, 0.040, 45, 65),
    (25, 3.0, 0.035, 45, 65),
]

results = []
for p in grid:
    res = run_param_scan(*p)
    if res: results.append(res)

df_res = pd.DataFrame(results)
print(df_res.to_string(index=False))
