"""
TraderAI - Aggressive Compounding & Capital Turnover Analysis
============================================================
Examines what happens when short-term trading profits ARE compounded
and capital is fully deployed (reinvesting gains into larger positions).
"""
import os, sys, math, pickle
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backtesting.swing_midcap_backtest import load_cached_universe
from data.costs import compute_indian_delivery_costs

if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

univ, bm = load_cached_universe()
nifty_df = bm['^NSEI']

def enrich_data(df: pd.DataFrame, nifty: pd.DataFrame) -> pd.DataFrame:
    res = df.copy()
    c, h, l, v, o = res["Close"], res["High"], res["Low"], res["Volume"], res["Open"]
    res["ema20"] = c.ewm(span=20, adjust=False).mean()
    res["sma50"] = c.rolling(50).mean()
    res["sma200"] = c.rolling(200).mean()
    
    tr1 = h - l
    tr2 = (h - c.shift(1)).abs()
    tr3 = (l - c.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    res["atr14"] = tr.rolling(14).mean()
    
    res["vol_sma20"] = v.rolling(20).mean()
    res["rvol"] = v / res["vol_sma20"].replace(0, np.nan)
    res["high20"] = h.rolling(20).max().shift(1)
    
    range_5d = h.rolling(5).max() - l.rolling(5).min()
    range_20d = h.rolling(20).max() - l.rolling(20).min()
    res["vcp_ratio"] = range_5d / range_20d.replace(0, np.nan)
    
    res["dist_ema20_pct"] = ((c - res["ema20"]) / res["ema20"]) * 100.0
    res["adtv_cr"] = (c * v).rolling(20).mean() / 1e7
    return res

indicators = {sym: enrich_data(df, nifty_df) for sym, df in univ.items()}
all_dates = nifty_df.index

def run_compounded_swing():
    init_capital = 30000.0
    cash = init_capital
    open_positions = {}
    trades = []
    daily_equity = []
    
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
            pos['days_held'] += 1
            pos['peak_price'] = max(pos['peak_price'], float(bar['High']))
            
            low_px = float(bar['Low'])
            high_px = float(bar['High'])
            open_px = float(bar['Open'])
            close_px = float(bar['Close'])
            
            exit_reason = None
            exit_px = 0.0
            
            current_stop = pos['stop_loss']
            if pos['peak_price'] >= pos['entry_price'] * 1.06:
                current_stop = max(current_stop, pos['entry_price'] * 1.01) # Breakeven ratchet
                
            if low_px <= current_stop:
                exit_reason = 'STOP_LOSS'
                exit_px = min(current_stop, open_px)
            elif high_px >= pos['target']:
                exit_reason = 'TARGET_HIT'
                exit_px = pos['target']
            elif pos['days_held'] >= 15:
                exit_reason = 'TIME_EXPIRY_15D'
                exit_px = close_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(
                    buy_price=pos['entry_price'], sell_price=exit_px,
                    quantity=pos['qty'], apply_stcg=False
                )
                cash += (exit_px * pos['qty']) - costs.total_friction_rupees
                trades.append({
                    'ticker': sym, 'year': year, 'entry_price': pos['entry_price'],
                    'exit_price': exit_px, 'days_held': pos['days_held'],
                    'net_pnl': costs.net_pnl_rupees, 'return_pct': costs.net_pnl_pct,
                    'reason': exit_reason
                })
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        holdings_val = sum(float(indicators[s].loc[date_idx]['Close']) * p['qty'] 
                           for s, p in open_positions.items() if date_idx in indicators[s].index)
        current_equity = cash + holdings_val
        daily_equity.append({
            'date': date_idx, 'year': year,
            'portfolio_val': current_equity, 'cash': cash
        })
        
        # Macro Regime (Nifty >= 50 SMA)
        nifty_loc = nifty_df.index.get_loc(date_idx)
        regime_bullish = True
        if nifty_loc >= 50:
            n_close = float(nifty_df['Close'].iloc[nifty_loc])
            n_sma50 = float(nifty_df['Close'].iloc[nifty_loc-49:nifty_loc+1].mean())
            if n_close < n_sma50:
                regime_bullish = False
                
        # Entries (Compounding: 1/3 of ACTIVE equity per trade!)
        if len(open_positions) < 3 and regime_bullish:
            available = [s for s in univ.keys() if s not in open_positions]
            candidates = []
            for sym in available:
                ind = indicators[sym]
                if date_idx not in ind.index: continue
                loc = ind.index.get_loc(date_idx)
                if loc < 50: continue
                bar = ind.iloc[loc]
                
                c = float(bar['Close'])
                l = float(bar['Low'])
                o = float(bar['Open'])
                h20 = float(bar['high20'])
                ema20 = float(bar['ema20'])
                sma50 = float(bar['sma50'])
                sma200 = float(bar['sma200'])
                vcp = float(bar['vcp_ratio'])
                rvol = float(bar['rvol'])
                dist = float(bar['dist_ema20_pct'])
                adtv = float(bar['adtv_cr'])
                
                if adtv < 5.0 or c < 15.0: continue
                
                # Setup: Stage 2 + (VCP Breakout OR Sweet Spot)
                if c > ema20 > sma50 > sma200:
                    if c >= h20 and vcp <= 0.65 and rvol >= 1.4:
                        candidates.append((sym, 10.0 + rvol, c, bar))
                    elif 0.0 <= dist <= 2.2 and l <= ema20 * 1.015 and c > o and rvol >= 0.9:
                        candidates.append((sym, 5.0 + (3.0 - dist), c, bar))
                        
            candidates.sort(key=lambda x: x[1], reverse=True)
            slots_free = 3 - len(open_positions)
            
            for sym, score, close_px, bar in candidates[:slots_free]:
                # COMPOUNDING: Allocate 1/3 of CURRENT portfolio equity!
                pos_alloc = min(cash, current_equity / 3.0)
                qty = int(pos_alloc // close_px)
                if qty > 0 and cash >= (qty * close_px):
                    cash -= (qty * close_px)
                    atr = float(bar['atr14']) if not np.isnan(bar['atr14']) else close_px * 0.025
                    stop_px = round(max(close_px - (1.8 * atr), close_px * 0.955), 2)
                    tp_px = round(close_px * 1.14, 2)
                    open_positions[sym] = {
                        'entry_price': close_px, 'qty': qty, 'stop_loss': stop_px,
                        'target': tp_px, 'peak_price': close_px, 'days_held': 0,
                        'entry_date': date_str
                    }
                    
    df_daily = pd.DataFrame(daily_equity)
    df_trades = pd.DataFrame(trades)
    
    print("="*80)
    print("YEAR-BY-YEAR COMPOUNDED PERFORMANCE ON RS 30,000 SHORT-TERM TRADING:")
    print("="*80)
    yearly = df_daily.groupby('year').last()
    yearly['prev_val'] = yearly['portfolio_val'].shift(1).fillna(init_capital)
    yearly['annual_return_pct'] = (yearly['portfolio_val'] - yearly['prev_val']) / yearly['prev_val'] * 100.0
    yearly['trades_count'] = df_trades.groupby('year')['ticker'].count()
    yearly['win_rate'] = df_trades.groupby('year').apply(lambda g: (g['net_pnl'] > 0).mean() * 100.0)
    
    for yr, r in yearly.iterrows():
        print(f"Year {yr}: Ending Equity: Rs {r['portfolio_val']:8,.1f} | Annual Return: {r['annual_return_pct']:+6.1f}% | Trades: {int(r['trades_count'] or 0):2d} | Win Rate: {r['win_rate']:4.1f}%")
        
    final_eq = df_daily['portfolio_val'].iloc[-1]
    total_gain = final_eq - init_capital
    print("-"*80)
    print(f"Initial Capital: Rs {init_capital:,.0f}")
    print(f"Final Equity:    Rs {final_eq:,.0f} (+{total_gain/init_capital*100:,.1f}% total gain)")
    print(f"Average Hold:    {df_trades['days_held'].mean():.1f} trading sessions (2 to 3 weeks max per trade)")
    print("="*80)

run_compounded_swing()
