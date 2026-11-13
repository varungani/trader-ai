"""
Exact Exposure & Matched Alpha Calculation for Option 1B
"""
import os, sys, pickle, numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backtesting.swing_midcap_backtest import load_cached_universe, compute_indicators
from data.costs import compute_indian_delivery_costs

univ, bm = load_cached_universe()
nifty_df = bm['^NSEI']

def enrich_indicators(df):
    res = compute_indicators(df)
    res['vol_sma20'] = res['Volume'].rolling(20).mean()
    res['vol_ratio'] = res['Volume'] / res['vol_sma20'].replace(0, np.nan)
    res['high50'] = res['High'].rolling(50).max().shift(1)
    return res

indicators = {sym: enrich_indicators(df) for sym, df in univ.items()}
all_dates = nifty_df.index

def run_calc():
    cash = 100000.0
    open_positions = {}
    trades = []
    daily_records = []
    
    for i in range(200, len(all_dates)):
        date_idx = all_dates[i]
        date_str = str(date_idx.date())
        year = date_idx.year
        
        # Exits
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
            elif pos['days_held'] >= 20:
                exit_reason = 'TIME_EXPIRY_20D'
                exit_px = close_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=exit_px, quantity=pos['qty'], apply_stcg=False)
                cash += (exit_px * pos['qty']) - costs.total_friction_rupees
                trades.append({
                    'ticker': sym, 'net_pnl': costs.net_pnl_rupees, 'days_held': pos['days_held']
                })
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        holdings_val = sum(float(indicators[s].loc[date_idx]['Close']) * p['qty'] 
                           for s, p in open_positions.items() if date_idx in indicators[s].index)
        daily_records.append({
            'date': date_idx, 'portfolio_val': cash + holdings_val,
            'cash': cash, 'invested_val': holdings_val, 'positions': len(open_positions)
        })
        
        # Regime Filter
        nifty_loc = nifty_df.index.get_loc(date_idx)
        regime_bullish = True
        if nifty_loc >= 50:
            n_close = float(nifty_df['Close'].iloc[nifty_loc])
            n_sma50 = float(nifty_df['Close'].iloc[nifty_loc-49:nifty_loc+1].mean())
            if n_close < n_sma50:
                regime_bullish = False
                
        # Entries
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
                high50 = float(bar['high50'])
                rsi = float(bar['rsi14'])
                mom60 = float(bar['mom60'])
                adtv = float(bar['adtv_cr'])
                vol_r = float(bar['vol_ratio'])
                
                if adtv >= 5.0 and close > 10.0 and close >= high50 and vol_r >= 1.2 and rsi > 60.0:
                    candidates.append((sym, mom60, close))
                    
            candidates.sort(key=lambda x: x[1], reverse=True)
            for sym, mom60, close_px in candidates[:5-len(open_positions)]:
                alloc = min(cash, 20000.0)
                qty = int(alloc // close_px)
                if qty > 0 and cash >= (qty * close_px):
                    stop_px = round(close_px * 0.955, 2)
                    target_px = round(close_px * 1.12, 2)
                    cash -= (qty * close_px)
                    open_positions[sym] = {
                        'entry_price': close_px, 'qty': qty, 'stop_loss': stop_px,
                        'target': target_px, 'peak_price': close_px, 'days_held': 0,
                        'entry_date': date_str
                    }
                    
    df_daily = pd.DataFrame(daily_records)
    df_trades = pd.DataFrame(trades)
    
    avg_invested_pct = (df_daily['invested_val'] / df_daily['portfolio_val']).mean() * 100.0
    total_net_return = (df_daily['portfolio_val'].iloc[-1] - 100000.0) / 100000.0 * 100.0
    
    # Calculate Equal-Weight 136 benchmark over same period
    bm_returns = []
    start_date = df_daily['date'].iloc[0]
    end_date = df_daily['date'].iloc[-1]
    
    # Universe return
    u_gains = []
    for s, ind in indicators.items():
        if start_date in ind.index and end_date in ind.index:
            p0 = float(ind.loc[start_date]['Close'])
            p1 = float(ind.loc[end_date]['Close'])
            if p0 > 0:
                u_gains.append((p1 - p0) / p0)
    avg_u_return = np.mean(u_gains) * 100.0
    
    # Nifty return
    n0 = float(nifty_df.loc[start_date]['Close'])
    n1 = float(nifty_df.loc[end_date]['Close'])
    nifty_return = (n1 - n0) / n0 * 100.0
    
    # Exposure-matched benchmark return
    matched_universe_bm = avg_u_return * (avg_invested_pct / 100.0)
    matched_nifty_bm = nifty_return * (avg_invested_pct / 100.0)
    
    alpha_vs_matched_univ = total_net_return - matched_universe_bm
    alpha_vs_matched_nifty = total_net_return - matched_nifty_bm
    
    print(f"Option 1B Total Net Return:      +{total_net_return:.2f}%")
    print(f"Average % Invested:              {avg_invested_pct:.2f}%")
    print(f"Equal-Weight Universe 136 Gain:  +{avg_u_return:.2f}%")
    print(f"NIFTY 50 Benchmark Gain:         +{nifty_return:.2f}%")
    print(f"Exposure-Matched Universe Return: +{matched_universe_bm:.2f}%")
    print(f"Exposure-Matched Nifty Return:    +{matched_nifty_bm:.2f}%")
    print(f"Exposure-Matched Alpha (Universe): {alpha_vs_matched_univ:+.2f}%")
    print(f"Exposure-Matched Alpha (Nifty):    {alpha_vs_matched_nifty:+.2f}%")

run_calc()
