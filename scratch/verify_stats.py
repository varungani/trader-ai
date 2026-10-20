import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pickle, pandas as pd, numpy as np, math
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

def run_detailed_breakout_swing():
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
                    'ticker': sym,
                    'year': year,
                    'entry_date': pos['entry_date'],
                    'exit_date': date_str,
                    'entry_price': pos['entry_price'],
                    'exit_price': exit_px,
                    'days_held': pos['days_held'],
                    'net_pnl': costs.net_pnl_rupees,
                    'gross_pnl': costs.gross_pnl_rupees,
                    'friction': costs.total_friction_rupees,
                    'return_pct': costs.net_pnl_pct,
                    'reason': exit_reason
                })
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        holdings_val = sum(float(indicators[s].loc[date_idx]['Close']) * p['qty'] 
                           for s, p in open_positions.items() if date_idx in indicators[s].index)
        daily_records.append({
            'date': date_idx, 'year': year, 'portfolio_val': cash + holdings_val,
            'cash': cash, 'positions': len(open_positions)
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
                    stop_px = round(close_px * 0.955, 2) # 4.5% risk
                    target_px = round(close_px * 1.12, 2) # 12% target
                    cash -= (qty * close_px)
                    open_positions[sym] = {
                        'entry_price': close_px, 'qty': qty, 'stop_loss': stop_px,
                        'target': target_px, 'peak_price': close_px, 'days_held': 0,
                        'entry_date': date_str
                    }
                    
    df_trades = pd.DataFrame(trades)
    df_daily = pd.DataFrame(daily_records)
    
    # Statistical t-test on net P&L
    pnl_series = df_trades['net_pnl']
    mean_pnl = pnl_series.mean()
    se_pnl = pnl_series.sem()
    t_stat = mean_pnl / se_pnl
    # Large sample (N=331) approximation using normal CDF
    p_val = 0.5 * (1.0 - math.erf(t_stat / math.sqrt(2)))
    
    print("="*80)
    print("STATISTICAL EDGE VERIFICATION (OPTION 1B SWING ENGINE)")
    print("="*80)
    print(f"Total Trades:           {len(df_trades)}")
    print(f"Mean Net Trade P&L:     Rs {mean_pnl:+.2f} (SE = Rs {se_pnl:.2f})")
    print(f"t-statistic:            {t_stat:+.2f}")
    print(f"p-value (one-sided):    {p_val:.5f}  {'*** HIGHLY SIGNIFICANT (p < 0.001) ***' if p_val < 0.001 else 'NOT SIGNIFICANT'}")
    
    print("\n" + "="*80)
    print("YEAR-BY-YEAR P&L BREAKDOWN (NET OF ALL STATUTORY COSTS):")
    print("="*80)
    for yr, group in df_trades.groupby('year'):
        yr_net = group['net_pnl'].sum()
        yr_wr = (group['net_pnl'] > 0).mean() * 100
        yr_count = len(group)
        print(f"Year {yr}: {yr_count:3d} trades | Win Rate: {yr_wr:4.1f}% | Net P&L: Rs {yr_net:+8.1f} | Avg Net/Trade: Rs {yr_net/yr_count:+6.1f}")
        
    print("\n" + "="*80)
    print("EXIT REASON DISTRIBUTION:")
    print("="*80)
    for r, group in df_trades.groupby('reason'):
        print(f"  {r:16s} : {len(group):3d} trades ({len(group)/len(df_trades)*100:4.1f}%) | Total Net: Rs {group['net_pnl'].sum():+9.1f} | Mean Net: Rs {group['net_pnl'].mean():+6.1f}")
    print("="*80)

run_detailed_breakout_swing()
