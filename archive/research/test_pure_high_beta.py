"""
Test Pure High-Beta Rockets Universe vs Broad 111 Stocks
2 Concentrated Slots (50% each | Rs 15k each)
Uncapped 10 EMA Trailing Runner (Scale 35% @ +18%)
"""
import os, sys, pickle, numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.costs import compute_indian_delivery_costs
from config import HIGH_BETA_ROCKETS

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
    c, h, l, v = res["Close"], res["High"], res["Low"], res["Volume"]
    res["ema10"] = c.ewm(span=10, adjust=False).mean()
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

stock_ind = {s: enrich_stock(df) for s, df in univ.items()}

def test_universe(name, symbols_filter=None, max_slots=2, pt1=0.18):
    dates = nifty_df.loc["2016-10-24":"2026-10-16"].index
    cash = 30000.0
    open_positions = {}
    closed_trades = []
    equity_curve = []
    
    for i in range(len(dates)):
        dt = dates[i]
        nifty_bar = nifty_df.loc[dt]
        nifty_c = float(nifty_bar['Close'])
        nifty_sma50 = float(nifty_bar['sma50']) if not np.isnan(nifty_bar['sma50']) else 0.0
        
        to_close = []
        for sym, pos in open_positions.items():
            ind = stock_ind[sym]
            if dt not in ind.index:
                pos['days_held'] += 1
                continue
            bar = ind.loc[dt]
            o_px, h_px, l_px, c_px = float(bar['Open']), float(bar['High']), float(bar['Low']), float(bar['Close'])
            pos['days_held'] += 1
            
            exit_reason = None
            exit_px = 0.0
            
            if l_px <= pos['stop_loss']:
                exit_reason = 'STOP_LOSS'
                exit_px = min(pos['stop_loss'], o_px)
            elif not pos['partial_booked'] and h_px >= pos['entry_price'] * (1.0 + pt1):
                pos['partial_booked'] = True
                booked_qty = int(pos['qty'] * 0.35)
                if booked_qty > 0:
                    booked_px = pos['entry_price'] * (1.0 + pt1)
                    costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=booked_px, quantity=booked_qty)
                    cash += (booked_qty * booked_px) - costs.total_friction_rupees
                    pos['qty'] -= booked_qty
                    pos['realized_partial_pnl'] = costs.net_pnl_rupees
                pos['stop_loss'] = pos['entry_price'] * 1.01
            elif pos['partial_booked'] and c_px < float(bar['ema10']):
                exit_reason = '10_EMA_TRAIL'
                exit_px = c_px
            elif pos['days_held'] >= 10 and abs((c_px - pos['entry_price']) / pos['entry_price']) <= 0.02:
                exit_reason = 'STAGNATION_10D'
                exit_px = c_px
            elif pos['days_held'] >= 28:
                exit_reason = 'TIME_STOP_28D'
                exit_px = c_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=exit_px, quantity=pos['qty'])
                tot_pnl = costs.net_pnl_rupees + pos.get('realized_partial_pnl', 0.0)
                closed_trades.append({
                    'ticker': sym, 'pnl': tot_pnl, 'ret': (tot_pnl / (pos['entry_price'] * (pos['qty'] + int(pos['qty']*0.35 if pos['partial_booked'] else 0)))) * 100.0,
                    'reason': exit_reason, 'days': pos['days_held']
                })
                cash += (pos['qty'] * exit_px) - costs.total_friction_rupees
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        inv = sum(pos['qty'] * (float(stock_ind[sym].loc[dt, 'Close']) if dt in stock_ind[sym].index else pos['entry_price']) for sym, pos in open_positions.items())
        tot_eq = cash + inv
        equity_curve.append((dt, tot_eq))
        
        if nifty_c >= nifty_sma50 and len(open_positions) < max_slots:
            cands = []
            target_symbols = [s for s in symbols_filter if s in stock_ind] if symbols_filter else list(stock_ind.keys())
            for sym in target_symbols:
                if sym in open_positions or dt not in stock_ind[sym].index:
                    continue
                bar = stock_ind[sym].loc[dt]
                c_px, sma50, sma200, rvol, vcp, high20, ret_6m = (
                    float(bar['Close']), float(bar['sma50']), float(bar['sma200']),
                    float(bar['rvol']), float(bar['vcp_ratio']), float(bar['high20']), float(bar['ret_6m'])
                )
                if c_px <= sma50 or sma50 <= sma200 or ret_6m <= 0.10:
                    continue
                if vcp <= 0.70 and rvol >= 1.6 and c_px >= high20 * 0.995:
                    score = (1.0 - vcp) * 10.0 + rvol + (ret_6m * 2.0)
                    cands.append((sym, score, c_px))
                    
            cands.sort(key=lambda x: x[1], reverse=True)
            slots_free = max_slots - len(open_positions)
            slot_budget = tot_eq / max_slots
            for sym, score, entry_px in cands[:slots_free]:
                alloc = min(cash, slot_budget)
                qty = int(alloc // entry_px)
                if qty > 0 and cash >= (qty * entry_px):
                    cash -= (qty * entry_px)
                    open_positions[sym] = {
                        'entry_price': entry_px, 'qty': qty,
                        'stop_loss': round(entry_px * 0.950, 2),
                        'days_held': 0, 'partial_booked': False, 'realized_partial_pnl': 0.0
                    }
                    
    df_eq = pd.DataFrame(equity_curve, columns=['date', 'equity']).set_index('date')
    fin_eq = df_eq['equity'].iloc[-1]
    net_pnl = fin_eq - 30000.0
    cagr = ((fin_eq / 30000.0)**(1/10) - 1.0) * 100.0
    pk = df_eq['equity'].cummax()
    dd = ((df_eq['equity'] - pk) / pk).min() * 100.0
    
    tdf = pd.DataFrame(closed_trades)
    wr = len(tdf[tdf['pnl'] > 0]) / len(tdf) * 100.0
    pf = tdf[tdf['pnl'] > 0]['pnl'].sum() / abs(tdf[tdf['pnl'] <= 0]['pnl'].sum())
    avg_w = tdf[tdf['pnl'] > 0]['ret'].mean()
    avg_l = tdf[tdf['pnl'] <= 0]['ret'].mean()
    best_t = tdf['ret'].max()
    
    print(f"\n[{name}]")
    print(f"  Final Equity: Rs {fin_eq:10,.2f} (+{(net_pnl/30000)*100:.1f}% | CAGR: {cagr:.1f}%) | Net P&L: Rs {net_pnl:+,.2f}")
    print(f"  Trades: {len(tdf)} | Win Rate: {wr:.1f}% | Profit Factor: {pf:.2f} | Max DD: {dd:.1f}%")
    print(f"  Avg Win: {avg_w:+.1f}% | Avg Loss: {avg_l:.1f}% | Best Trade: {best_t:+.1f}%")

test_universe("1. Broad 111 Universe (3 Slots)", max_slots=3)
test_universe("2. Pure High-Beta Rockets (2 Bullet Slots)", symbols_filter=HIGH_BETA_ROCKETS, max_slots=2, pt1=0.20)
