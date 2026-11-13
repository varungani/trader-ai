"""
TraderAI - Compounded 10-Year Simulation of the 1.8x RVOL VCP Engine
==================================================================
Simulates the exact winning setup (VCP <= 0.65, RVOL >= 1.8x, TP=14%, SL=4.5%, Stagnation=10D)
under two modes:
1. Static Sizing (Fixed Rs 10k per trade forever)
2. Compounded Sizing (1/3 of dynamic account equity per trade)
"""
import os, sys, pickle, numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.costs import compute_indian_delivery_costs

with open("data/cache/universe_10y.pkl", "rb") as f:
    univ = pickle.load(f)
with open("data/cache/benchmarks_10y.pkl", "rb") as f:
    bm = pickle.load(f)

nifty_df = bm['^NSEI'].copy()
nifty_df['sma50'] = nifty_df['Close'].rolling(50).mean()

def enrich_stock(df):
    res = df.copy()
    c, h, l, v, o = res["Close"], res["High"], res["Low"], res["Volume"], res["Open"]
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

def run_simulation(compound=False, init_capital=30000.0, max_pos=3):
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
            
            if l_px <= pos['stop_loss']:
                exit_reason = 'STOP_LOSS'
                exit_px = min(pos['stop_loss'], o_px)
            elif h_px >= pos['target']:
                exit_reason = 'TARGET_HIT'
                exit_px = pos['target']
            elif pos['days_held'] >= 10 and abs((c_px - pos['entry_price']) / pos['entry_price']) <= 0.02:
                exit_reason = 'STAGNATION_10D'
                exit_px = c_px
            elif pos['days_held'] >= 20:
                exit_reason = 'TIME_STOP_20D'
                exit_px = c_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=exit_px, quantity=pos['qty'])
                closed_trades.append({
                    'ticker': sym, 'year': date_idx.year, 'net_pnl': costs.net_pnl_rupees,
                    'gross_pnl': costs.gross_pnl_rupees, 'friction': costs.total_friction_rupees,
                    'ret_pct': costs.net_pnl_pct
                })
                cash += (pos['qty'] * exit_px) - costs.total_friction_rupees
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        invested = sum(pos['qty'] * (float(indicators[sym].loc[date_idx, 'Close']) if date_idx in indicators[sym].index else pos['entry_price']) for sym, pos in open_positions.items())
        total_equity = cash + invested
        daily_equity.append({'date': date_idx, 'year_month': date_str[:7], 'equity': total_equity})
        
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
            
            # Position sizing
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
                        'days_held': 0, 'entry_date': date_str
                    }
                    
    df_tr = pd.DataFrame(closed_trades)
    df_eq = pd.DataFrame(daily_equity)
    df_eq['peak'] = df_eq['equity'].cummax()
    df_eq['dd'] = (df_eq['equity'] - df_eq['peak']) / df_eq['peak'] * 100.0
    
    final_equity = df_eq['equity'].iloc[-1]
    net_profit = final_equity - init_capital
    max_dd = df_eq['dd'].min()
    wr = len(df_tr[df_tr['net_pnl'] > 0]) / len(df_tr) * 100.0
    pf = df_tr[df_tr['net_pnl'] > 0]['net_pnl'].sum() / abs(df_tr[df_tr['net_pnl'] <= 0]['net_pnl'].sum())
    
    # Monthly CAGR & returns
    cagr = ((final_equity / init_capital) ** (1.0 / 10.0) - 1.0) * 100.0
    
    # Yearly breakdown
    yearly = df_tr.groupby('year')['net_pnl'].sum()
    
    return {
        'compound': compound, 'trades': len(df_tr), 'wr': wr, 'final_equity': final_equity,
        'net_profit': net_profit, 'ret_pct': (net_profit / init_capital) * 100.0,
        'cagr': cagr, 'pf': pf, 'max_dd': max_dd, 'yearly': yearly
    }

print("="*80)
print("COMPARING STATIC RS 10k SIZING VS DYNAMIC COMPOUNDING (10 YEARS | 2016-2026)")
print("="*80)

r_static = run_simulation(compound=False)
r_comp = run_simulation(compound=True)

print(f"\n[Static Rs 10k Sizing]:")
print(f"  Trades:        {r_static['trades']}")
print(f"  Win Rate:      {r_static['wr']:.1f}%")
print(f"  Final Equity:  Rs {r_static['final_equity']:,.2f} on Rs 30k start (+{r_static['ret_pct']:.1f}%)")
print(f"  Net Profit:    Rs {r_static['net_profit']:+,.2f}")
print(f"  10-Year CAGR:  {r_static['cagr']:.1f}%")
print(f"  Profit Factor: {r_static['pf']:.2f}")
print(f"  Max Drawdown:  {r_static['max_dd']:.1f}%")

print(f"\n[Dynamic Compounded Sizing (Reinvesting Gains)]:")
print(f"  Trades:        {r_comp['trades']}")
print(f"  Win Rate:      {r_comp['wr']:.1f}%")
print(f"  Final Equity:  Rs {r_comp['final_equity']:,.2f} on Rs 30k start (+{r_comp['ret_pct']:.1f}%)")
print(f"  Net Profit:    Rs {r_comp['net_profit']:+,.2f}")
print(f"  10-Year CAGR:  {r_comp['cagr']:.1f}%")
print(f"  Profit Factor: {r_comp['pf']:.2f}")
print(f"  Max Drawdown:  {r_comp['max_dd']:.1f}%")
