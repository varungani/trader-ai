"""
Optimize 10-Year Indian Stock Strategy:
Combine Minervini VCP <= 0.65 + RVOL >= 1.8x + Stage 2 Uptrend + Uncapped 10 EMA Trailing Runner.
Test on 10-Year Dataset (2016-2026).
"""
import os, sys, pickle, numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.costs import compute_indian_delivery_costs

with open("data/cache/universe_10y.pkl", "rb") as f:
    univ = pickle.load(f)
with open("data/cache/benchmarks_10y.pkl", "rb") as f:
    bm = pickle.load(f)

nifty_df = bm['^NSEI'].copy()
if isinstance(nifty_df.columns, pd.MultiIndex):
    nifty_df.columns = nifty_df.columns.get_level_values(0)
nifty_df['sma50'] = nifty_df['Close'].rolling(50).mean()

def enrich_stock(df):
    res = df.copy()
    if isinstance(res.columns, pd.MultiIndex):
        res.columns = res.columns.get_level_values(0)
    c, h, l, v, o = res["Close"], res["High"], res["Low"], res["Volume"], res["Open"]
    res["ema10"] = c.ewm(span=10, adjust=False).mean()
    res["ema20"] = c.ewm(span=20, adjust=False).mean()
    res["sma50"] = c.rolling(50).mean()
    res["sma200"] = c.rolling(200).mean()
    res["vol_sma20"] = v.rolling(20).mean()
    res["rvol"] = v / res["vol_sma20"].replace(0, np.nan)
    res["high20"] = h.rolling(20).max().shift(1)
    
    range_5d = h.rolling(5).max() - l.rolling(5).min()
    range_20d = h.rolling(20).max() - l.rolling(20).min()
    res["vcp_ratio"] = range_5d / range_20d.replace(0, np.nan)
    res["ret_6m"] = (c - c.shift(125)) / c.shift(125)
    return res

indicators = {s: enrich_stock(df) for s, df in univ.items()}

def run_runner_simulation(name, trail_ema=True, pt1_pct=0.15, max_pos=3, compound=True):
    init_capital = 30000.0
    dates = nifty_df.loc["2016-10-24":"2026-10-16"].index
    cash = init_capital
    open_positions = {}
    closed_trades = []
    daily_equity = []
    
    for i in range(len(dates)):
        date_idx = dates[i]
        date_str = str(date_idx.date())
        nifty_bar = nifty_df.loc[date_idx]
        nifty_c = float(nifty_bar['Close'])
        nifty_sma50 = float(nifty_bar['sma50']) if not np.isnan(nifty_bar['sma50']) else 0.0
        
        # Exits
        to_close = []
        for sym, pos in open_positions.items():
            ind = indicators[sym]
            if date_idx not in ind.index:
                pos['days_held'] += 1
                continue
            bar = ind.loc[date_idx]
            o_px, h_px, l_px, c_px = float(bar['Open']), float(bar['High']), float(bar['Low']), float(bar['Close'])
            pos['days_held'] += 1
            
            exit_reason = None
            exit_px = 0.0
            
            # Hard stop -4.5%
            if l_px <= pos['stop_loss']:
                exit_reason = 'STOP_LOSS'
                exit_px = min(pos['stop_loss'], o_px)
            # Scale out 35% at pt1_pct (+15%)
            elif not pos['partial_booked'] and h_px >= pos['entry_price'] * (1.0 + pt1_pct):
                pos['partial_booked'] = True
                booked_qty = int(pos['qty'] * 0.35)
                if booked_qty > 0:
                    booked_px = pos['entry_price'] * (1.0 + pt1_pct)
                    costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=booked_px, quantity=booked_qty)
                    cash += (booked_qty * booked_px) - costs.total_friction_rupees
                    pos['qty'] -= booked_qty
                    pos['realized_partial_pnl'] = costs.net_pnl_rupees
                pos['stop_loss'] = pos['entry_price'] * 1.01  # Move stop to breakeven +1%
            # Trailing 10 EMA exit for runner
            elif trail_ema and pos['partial_booked'] and c_px < float(bar['ema10']):
                exit_reason = '10_EMA_TRAIL'
                exit_px = c_px
            # Fixed target if no trail
            elif not trail_ema and h_px >= pos['target']:
                exit_reason = 'TARGET_HIT'
                exit_px = pos['target']
            elif pos['days_held'] >= 10 and abs((c_px - pos['entry_price']) / pos['entry_price']) <= 0.02:
                exit_reason = 'STAGNATION_10D'
                exit_px = c_px
            elif pos['days_held'] >= 25:
                exit_reason = 'TIME_STOP_25D'
                exit_px = c_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=exit_px, quantity=pos['qty'])
                total_trade_pnl = costs.net_pnl_rupees + pos.get('realized_partial_pnl', 0.0)
                closed_trades.append({
                    'ticker': sym, 'year': date_idx.year, 'net_pnl': total_trade_pnl,
                    'ret_pct': (total_trade_pnl / (pos['entry_price'] * (pos['qty'] + int(pos['qty']*0.35 if pos['partial_booked'] else 0)))) * 100.0,
                    'reason': exit_reason, 'days': pos['days_held']
                })
                cash += (pos['qty'] * exit_px) - costs.total_friction_rupees
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        invested = sum(pos['qty'] * (float(indicators[sym].loc[date_idx, 'Close']) if date_idx in indicators[sym].index else pos['entry_price']) for sym, pos in open_positions.items())
        total_equity = cash + invested
        daily_equity.append({'date': date_idx, 'equity': total_equity})
        
        # Macro Gate
        if nifty_c < nifty_sma50:
            continue
            
        if len(open_positions) < max_pos:
            candidates = []
            for sym, ind in indicators.items():
                if sym in open_positions or date_idx not in ind.index:
                    continue
                bar = ind.loc[date_idx]
                c_px, sma50, sma200, rvol, vcp, high20, ret_6m = (
                    float(bar['Close']), float(bar['sma50']), float(bar['sma200']),
                    float(bar['rvol']), float(bar['vcp_ratio']), float(bar['high20']), float(bar['ret_6m'])
                )
                if c_px <= sma50 or sma50 <= sma200 or ret_6m <= 0.10:
                    continue
                if vcp <= 0.65 and rvol >= 1.8 and c_px >= high20 * 0.995:
                    score = (1.0 - vcp) * 10.0 + rvol + (ret_6m * 2.0)
                    candidates.append((sym, score, c_px))
                    
            candidates.sort(key=lambda x: x[1], reverse=True)
            slots_free = max_pos - len(open_positions)
            slot_budget = (total_equity / max_pos) if compound else (init_capital / max_pos)
            
            for sym, score, entry_px in candidates[:slots_free]:
                alloc = min(cash, slot_budget)
                qty = int(alloc // entry_px)
                if qty > 0 and cash >= (qty * entry_px):
                    cash -= (qty * entry_px)
                    open_positions[sym] = {
                        'entry_price': entry_px, 'qty': qty,
                        'stop_loss': round(entry_px * 0.955, 2),
                        'target': round(entry_px * 1.14, 2),
                        'days_held': 0, 'entry_date': date_str,
                        'partial_booked': False, 'realized_partial_pnl': 0.0
                    }
                    
    df_tr = pd.DataFrame(closed_trades)
    df_eq = pd.DataFrame(daily_equity)
    df_eq['peak'] = df_eq['equity'].cummax()
    df_eq['dd'] = (df_eq['equity'] - df_eq['peak']) / df_eq['peak'] * 100.0
    
    final_eq = df_eq['equity'].iloc[-1]
    net_p = final_eq - init_capital
    net_r = (net_p / init_capital) * 100.0
    cagr = ((final_eq / init_capital) ** (1.0 / 10.0) - 1.0) * 100.0
    max_dd = df_eq['dd'].min()
    wr = len(df_tr[df_tr['net_pnl'] > 0]) / len(df_tr) * 100.0
    pf = df_tr[df_tr['net_pnl'] > 0]['net_pnl'].sum() / abs(df_tr[df_tr['net_pnl'] <= 0]['net_pnl'].sum())
    avg_w = df_tr[df_tr['net_pnl'] > 0]['ret_pct'].mean()
    avg_l = df_tr[df_tr['net_pnl'] <= 0]['ret_pct'].mean()
    best_t = df_tr['ret_pct'].max()
    
    print(f"\n[{name}]")
    print(f"  Final Equity: Rs {final_eq:10,.2f} ({net_r:+.1f}% | CAGR: {cagr:.1f}%) | Net P&L: Rs {net_p:+,.2f}")
    print(f"  Trades: {len(df_tr)} | Win Rate: {wr:.1f}% | Profit Factor: {pf:.2f} | Max DD: {max_dd:.1f}%")
    print(f"  Avg Win: {avg_w:+.1f}% | Avg Loss: {avg_l:.1f}% | Best Trade: {best_t:+.1f}%")
    return {'final': final_eq, 'net_p': net_p, 'cagr': cagr, 'dd': max_dd, 'pf': pf, 'wr': wr, 'best': best_t}

print("="*85)
print("10-YEAR INDIAN STOCK STRATEGY OPTIMIZATION (2016-2026)")
print("Initial Capital: Rs 30,000 | CNC Cash Delivery with Exact Statutory Indian Costs")
print("="*85)

run_runner_simulation("1. Baseline: Fixed 14% Target (No Trailing Runner)", trail_ema=False, max_pos=3, compound=True)
run_runner_simulation("2. IMPROVED: Uncapped 10 EMA Trailing Runner (Scale 35% @ +15%)", trail_ema=True, pt1_pct=0.15, max_pos=3, compound=True)
run_runner_simulation("3. MONSTER CONCENTRATION: 2-Stock Bullet (50% each | 10 EMA Runner)", trail_ema=True, pt1_pct=0.15, max_pos=2, compound=True)
