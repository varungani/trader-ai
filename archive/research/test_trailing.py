import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pickle, pandas as pd
from backtesting.swing_midcap_backtest import load_cached_universe, compute_indicators
from data.costs import compute_indian_delivery_costs

univ, bm = load_cached_universe()
nifty_df = bm['^NSEI']

def test_variant_b_no_choke(trailing_mode='none'):
    indicators = {sym: compute_indicators(df) for sym, df in univ.items()}
    all_dates = nifty_df.index
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
            ema20_px = float(bar['ema20'])
            pos['days_held'] += 1
            pos['peak_price'] = max(pos['peak_price'], high_px)
            
            if trailing_mode == 'breakeven_choke':
                gain = (pos['peak_price'] - pos['entry_price']) / pos['entry_price']
                if gain >= 0.06:
                    pos['stop_loss'] = max(pos['stop_loss'], round(pos['entry_price'] * 1.005, 2))
                if gain >= 0.10 and ema20_px > pos['entry_price']:
                    pos['stop_loss'] = max(pos['stop_loss'], round(ema20_px * 0.99, 2))
            elif trailing_mode == 'loose_trail':
                gain = (pos['peak_price'] - pos['entry_price']) / pos['entry_price']
                if gain >= 0.08 and ema20_px > pos['entry_price']:
                    pos['stop_loss'] = max(pos['stop_loss'], round(ema20_px * 0.98, 2))
            
            exit_reason = None
            exit_px = 0.0
            if low_px <= pos['stop_loss']:
                exit_reason = 'STOP_LOSS' if pos['stop_loss'] < pos['entry_price'] else 'TRAILING_STOP'
                exit_px = min(pos['stop_loss'], open_px)
            elif high_px >= pos['target']:
                exit_reason = 'TARGET_HIT'
                exit_px = pos['target']
            elif pos['days_held'] >= 25:
                exit_reason = 'TIME_EXPIRY_25D'
                exit_px = close_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=exit_px, quantity=pos['qty'], apply_stcg=False)
                cash += (exit_px * pos['qty']) - costs.total_friction_rupees
                trades.append({'net_pnl': costs.net_pnl_rupees, 'reason': exit_reason})
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
                rsi_ok = 40.0 <= rsi <= 64.0
                green_reversal = close > open_p and close >= ema20
                if is_uptrend and tested_ema20 and rsi_ok and green_reversal:
                    candidates.append((sym, mom60, close, ema20))
                    
            candidates.sort(key=lambda x: x[1], reverse=True)
            for sym, mom60, close_px, ema20 in candidates[:5-len(open_positions)]:
                alloc = min(cash, 20000.0)
                qty = int(alloc // close_px)
                if qty > 0 and cash >= (qty * close_px):
                    stop_dist = max(0.035, min(0.05, (close_px - (ema20 * 0.985)) / close_px))
                    stop_px = round(close_px * (1.0 - stop_dist), 2)
                    target_px = round(close_px * (1.0 + (stop_dist * 3.0)), 2)
                    cash -= (qty * close_px)
                    open_positions[sym] = {
                        'entry_price': close_px, 'qty': qty, 'stop_loss': stop_px,
                        'target': target_px, 'peak_price': close_px, 'days_held': 0
                    }
                    
    tot_net = sum(t['net_pnl'] for t in trades)
    wr = len([t for t in trades if t['net_pnl'] > 0]) / len(trades) * 100 if trades else 0
    print(f'Mode: {trailing_mode:16s} | Trades: {len(trades):3d} | WR: {wr:.1f}% | Net P&L: Rs {tot_net:+10.2f} ({tot_net/1000:+.1f}%)')

if __name__ == '__main__':
    test_variant_b_no_choke('breakeven_choke')
    test_variant_b_no_choke('loose_trail')
    test_variant_b_no_choke('none')
