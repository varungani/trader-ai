"""
TraderAI - Dual-Pattern Optimization Engine (VCP Breakout + 20 EMA Sweet Spot)
==============================================================================
Empirical data proved:
- Pattern 2 (Minervini VCP): Rs +18,854 Net | PF 1.56 | Max DD -11.3%
- Pattern 4 (20 EMA Pullback): Rs +20,153 Net | PF 1.55 | Max DD -10.5%
- Blind 50D Breakout & Raw RS failed (high drawdowns, -22% to -32%)

Now testing:
1. Dual-Pattern Synergy (Both VCP Breakout and 20 EMA Pullback working together)
2. Compounded Capital on Rs 30,000 initial capital
3. Monthly P&L Distribution: How many months hit +5%, +8%, +10%+?
4. Target Scan: 10% vs 12% vs 15% vs 20%
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

print("Enriching universe...")
indicators = {sym: enrich_data(df, nifty_df) for sym, df in univ.items()}
all_dates = nifty_df.index

def run_dual_engine(target_pct=15.0, compound=True, allow_runner=False):
    init_capital = 30000.0
    cash = init_capital
    open_positions = {}
    trades = []
    daily_equity = []
    monthly_pnl = {}
    
    for i in range(200, len(all_dates)):
        date_idx = all_dates[i]
        date_str = str(date_idx.date())
        year_month = date_str[:7]
        
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
            if allow_runner and pos['peak_price'] >= pos['entry_price'] * 1.08:
                # Ratchet to breakeven + 1%
                current_stop = max(current_stop, pos['entry_price'] * 1.01)
                
            if low_px <= current_stop:
                exit_reason = 'STOP_LOSS'
                exit_px = min(current_stop, open_px)
            elif high_px >= pos['target']:
                exit_reason = 'TARGET_HIT'
                exit_px = pos['target']
            elif pos['days_held'] >= 20:
                exit_reason = 'TIME_EXPIRY_20D'
                exit_px = close_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(
                    buy_price=pos['entry_price'], sell_price=exit_px,
                    quantity=pos['qty'], apply_stcg=False
                )
                cash += (exit_px * pos['qty']) - costs.total_friction_rupees
                net_rupees = costs.net_pnl_rupees
                trades.append({
                    'ticker': sym, 'month': year_month, 'entry_price': pos['entry_price'],
                    'exit_price': exit_px, 'days_held': pos['days_held'],
                    'net_pnl': net_rupees, 'return_pct': costs.net_pnl_pct,
                    'reason': exit_reason, 'setup': pos['setup']
                })
                monthly_pnl[year_month] = monthly_pnl.get(year_month, 0.0) + net_rupees
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        # Daily Mark-to-Market
        holdings_val = sum(float(indicators[s].loc[date_idx]['Close']) * p['qty'] 
                           for s, p in open_positions.items() if date_idx in indicators[s].index)
        current_portfolio_val = cash + holdings_val
        daily_equity.append({
            'date': date_idx, 'portfolio_val': current_portfolio_val, 'cash': cash
        })
        
        # Macro Regime (Nifty >= 50 SMA)
        nifty_loc = nifty_df.index.get_loc(date_idx)
        regime_bullish = True
        if nifty_loc >= 50:
            n_close = float(nifty_df['Close'].iloc[nifty_loc])
            n_sma50 = float(nifty_df['Close'].iloc[nifty_loc-49:nifty_loc+1].mean())
            if n_close < n_sma50:
                regime_bullish = False
                
        # Entries (Dual Engine: VCP Breakout OR 20 EMA Pullback)
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
                
                # Setup A: Minervini VCP Breakout
                is_vcp = (c > ema20 > sma50 > sma200 and c >= h20 and vcp <= 0.65 and rvol >= 1.4)
                # Setup B: 20 EMA Sweet-Spot Rebound
                is_pullback = (c > sma50 > sma200 and 0.0 <= dist <= 2.2 and l <= ema20 * 1.015 and c > o and rvol >= 0.9)
                
                if is_vcp:
                    candidates.append((sym, 10.0 + rvol, c, bar, 'VCP_BREAKOUT'))
                elif is_pullback:
                    candidates.append((sym, 5.0 + (3.0 - dist), c, bar, '20EMA_PULLBACK'))
                    
            candidates.sort(key=lambda x: x[1], reverse=True)
            slots_free = 3 - len(open_positions)
            
            for sym, score, close_px, bar, setup_type in candidates[:slots_free]:
                total_equity = current_portfolio_val if compound else init_capital
                pos_alloc = min(cash, total_equity / 3.0)
                qty = int(pos_alloc // close_px)
                if qty > 0 and cash >= (qty * close_px):
                    cash -= (qty * close_px)
                    
                    atr = float(bar['atr14']) if not np.isnan(bar['atr14']) else close_px * 0.025
                    # Stop: 1.8 ATR bounded max 4.5%
                    stop_px = round(max(close_px - (1.8 * atr), close_px * 0.955), 2)
                    tp_px = round(close_px * (1.0 + (target_pct / 100.0)), 2)
                    
                    open_positions[sym] = {
                        'entry_price': close_px, 'qty': qty, 'stop_loss': stop_px,
                        'target': tp_px, 'peak_price': close_px, 'days_held': 0,
                        'entry_date': date_str, 'atr': atr, 'setup': setup_type
                    }
                    
    df_trades = pd.DataFrame(trades)
    df_daily = pd.DataFrame(daily_equity)
    df_daily['peak'] = df_daily['portfolio_val'].cummax()
    df_daily['dd'] = (df_daily['portfolio_val'] - df_daily['peak']) / df_daily['peak'] * 100.0
    
    total_trades = len(df_trades)
    wins = df_trades[df_trades['net_pnl'] > 0]
    losses = df_trades[df_trades['net_pnl'] <= 0]
    wr = len(wins) / total_trades * 100.0
    final_equity = df_daily['portfolio_val'].iloc[-1]
    net_profit = final_equity - init_capital
    total_return_pct = (net_profit / init_capital) * 100.0
    max_dd = df_daily['dd'].min()
    
    # Monthly stats
    s_monthly = pd.Series(monthly_pnl)
    # Convert monthly pnl to approx % of initial or avg equity
    months_over_5pct = (s_monthly >= (init_capital * 0.05)).sum()
    months_over_8pct = (s_monthly >= (init_capital * 0.08)).sum()
    months_over_10pct = (s_monthly >= (init_capital * 0.10)).sum()
    max_monthly_rupees = s_monthly.max()
    
    pf = round(wins['net_pnl'].sum() / abs(losses['net_pnl'].sum()), 2)
    payoff = round(wins['net_pnl'].mean() / abs(losses['net_pnl'].mean()), 2)
    
    return {
        'target_pct': target_pct,
        'compound': compound,
        'runner': allow_runner,
        'trades': total_trades,
        'win_rate': round(wr, 1),
        'final_equity': round(final_equity, 1),
        'net_profit_rs': round(net_profit, 1),
        'total_return_pct': round(total_return_pct, 1),
        'profit_factor': pf,
        'payoff_ratio': payoff,
        'max_dd_pct': round(max_dd, 1),
        'months_over_5pct': months_over_5pct,
        'months_over_8pct': months_over_8pct,
        'months_over_10pct': months_over_10pct,
        'best_month_rs': round(max_monthly_rupees, 1)
    }

print("Running parameter grid on Dual Engine...")
tests = [
    (10.0, False, False),
    (12.0, False, False),
    (15.0, False, False),
    (20.0, False, False),
    (12.0, True, False),
    (15.0, True, False),
    (15.0, True, True),
    (20.0, True, True),
]

out = []
for t_pct, comp, run in tests:
    res = run_dual_engine(target_pct=t_pct, compound=comp, allow_runner=run)
    out.append(res)
    print(f"Target: {t_pct:4.1f}% | Comp: {str(comp):5s} | Runner: {str(run):5s} -> Net: Rs {res['net_profit_rs']:+10,.1f} ({res['total_return_pct']:+6.1f}%) | WR: {res['win_rate']:4.1f}% | PF: {res['profit_factor']:4.2f} | MaxDD: {res['max_dd_pct']:5.1f}% | BestMo: Rs {res['best_month_rs']:+6,.1f}")

df_out = pd.DataFrame(out)
print("\n" + "="*110)
print("DUAL ENGINE OPTIMIZATION RESULTS (VCP BREAKOUT + 20 EMA PULLBACK ON RS 30,000 CAPITAL):")
print("="*110)
print(df_out.to_string(index=False))
print("="*110)
