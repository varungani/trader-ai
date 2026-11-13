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

print(f"Loaded {len(univ)} tickers. Precomputing indicators...")
indicators = {sym: enrich_indicators(df) for sym, df in univ.items()}
all_dates = nifty_df.index

def run_realistic_execution_backtest():
    """
    REALISTIC INSTITUTIONAL BACKTEST:
    1. Zero Lookahead: Scan happens at End-of-Day (EOD) on bar T.
    2. Fill Execution: Strictly filled on Bar T+1 at Open(T+1) + 0.20% Slippage.
    3. Minimum Ticket Size: Enforce >= Rs. 15,000 per position (negates Rs. 15.93 CDSL DP fee).
    4. Concentrated Sizing: Max 3 concurrent positions (approx 33% capital per slot).
    5. Statutory Costs: Full STT, DP, SEBI, GST, Stamp Duty applied via costs.py.
    """
    cash = 100000.0
    open_positions = {}
    pending_buys = []  # list of (sym, signal_date)
    trades = []
    daily_records = []
    
    SLIPPAGE_PCT = 0.002  # 0.20% realistic execution slippage on open
    MIN_TICKET_SIZE = 15000.0
    MAX_POSITIONS = 3
    
    for i in range(200, len(all_dates)):
        date_idx = all_dates[i]
        date_str = str(date_idx.date())
        year = date_idx.year
        
        # ─── 1. EXECUTE PENDING ORDERS FROM YESTERDAY AT TODAY'S OPEN + SLIPPAGE ───
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
                    
                # Fill at Open with slippage
                fill_px = round(today_open * (1.0 + SLIPPAGE_PCT), 2)
                
                # Sizing: Divide available cash across empty slots
                empty_slots = MAX_POSITIONS - len(open_positions)
                alloc = min(cash / empty_slots, 35000.0)
                if alloc < MIN_TICKET_SIZE:
                    continue
                    
                qty = int(alloc // fill_px)
                cost = qty * fill_px
                if qty > 0 and cash >= cost:
                    cash -= cost
                    stop_px = round(fill_px * 0.955, 2)  # -4.5% planned stop
                    target_px = round(fill_px * 1.12, 2) # +12.0% planned target
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
            
        # ─── 2. EVALUATE EXITS ON ACTIVE POSITIONS ───
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
            
            # Stop loss / gap-down check
            if low_px <= pos['stop_loss']:
                exit_reason = 'STOP_LOSS'
                # Fill at open if gapped below stop, else stop price
                exit_px = min(pos['stop_loss'], open_px) if open_px < pos['stop_loss'] else pos['stop_loss']
            # Target check
            elif high_px >= pos['target']:
                exit_reason = 'TARGET_HIT'
                exit_px = pos['target']
            # Time exit (20 market sessions)
            elif pos['days_held'] >= 20:
                exit_reason = 'TIME_EXPIRY_20D'
                exit_px = close_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(
                    buy_price=pos['entry_price'],
                    sell_price=exit_px,
                    quantity=pos['qty'],
                    apply_stcg=False
                )
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
        
        # ─── 3. EOD SCAN FOR NEW SIGNALS (QUEUED FOR TOMORROW'S OPEN) ───
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
                if loc < 50: continue
                bar = ind.iloc[loc]
                close = float(bar['Close'])
                high50 = float(bar['high50'])
                rsi = float(bar['rsi14'])
                mom60 = float(bar['mom60'])
                adtv = float(bar['adtv_cr'])
                vol_r = float(bar['vol_ratio'])
                
                # Signal: 50-day breakout + RVOL >= 1.5x (Institutional volume) + RSI > 60
                if adtv >= 5.0 and close > 10.0 and close >= high50 and vol_r >= 1.5 and rsi > 60.0:
                    candidates.append((sym, mom60, close))
                    
            candidates.sort(key=lambda x: x[1], reverse=True)
            # Queue top candidates for tomorrow morning execution
            slots_needed = MAX_POSITIONS - len(open_positions)
            pending_buys = [sym for sym, _, _ in candidates[:slots_needed]]
            
    df_trades = pd.DataFrame(trades)
    df_daily = pd.DataFrame(daily_records)
    
    print("\n" + "="*85)
    print("REALISTIC BACKTEST AUDIT (NEXT-DAY OPEN FILL + SLIPPAGE + STATUTORY FRICTION)")
    print("="*85)
    
    if len(df_trades) == 0:
        print("No trades executed.")
        return
        
    pnl_series = df_trades['net_pnl']
    mean_pnl = pnl_series.mean()
    se_pnl = pnl_series.sem()
    t_stat = mean_pnl / se_pnl if se_pnl > 0 else 0
    # Normal approximation for p-value without external scipy dependency
    p_val = 0.5 * math.erfc(t_stat / math.sqrt(2)) if t_stat != 0 else 0.5
    
    print(f"Total Completed Trades  : {len(df_trades)}")
    print(f"Overall Win Rate        : {(df_trades['net_pnl'] > 0).mean()*100:.1f}%")
    print(f"Mean Net Trade P&L      : Rs. {mean_pnl:+.2f} (SE = Rs. {se_pnl:.2f})")
    print(f"t-statistic             : {t_stat:+.2f} | p-value: {p_val:.5f}")
    print(f"Total Net P&L Generated : Rs. {df_trades['net_pnl'].sum():+,.2f}")
    print(f"Total Friction Deducted : Rs. {df_trades['friction'].sum():,.2f}")
    
    print("\nYear-by-Year Breakdown (Realistic Fills):")
    print(f"{'Year':<8} | {'Trades':<8} | {'Win Rate':<10} | {'Net P&L (INR)':<16} | {'Avg P&L/Trade':<15}")
    print("-" * 65)
    for yr, grp in df_trades.groupby('year'):
        yr_pnl = grp['net_pnl'].sum()
        yr_wr = (grp['net_pnl'] > 0).mean() * 100
        yr_avg = grp['net_pnl'].mean()
        print(f"{yr:<8} | {len(grp):<8} | {yr_wr:>5.1f}%    | Rs. {yr_pnl:>10,.1f}  | Rs. {yr_avg:>+8.1f}")
        
    print("="*85)

if __name__ == '__main__':
    run_realistic_execution_backtest()
