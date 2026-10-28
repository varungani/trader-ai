"""
TraderAI - Institutional Pullback-Reversal (IPR) Calibration & Test
==================================================================
Generalizes Pattern 4 (75% WR / 3.98 PF) into an active, high-expectancy swing engine:
1. Stage 2 Uptrend (Close > 50 SMA > 200 SMA)
2. 2-to-4 session pullback to dynamic 20 EMA support (distance -1% to +2.5%)
3. Bullish Reversal Candle (Close > Open and Close > Yesterday's Close or High)
4. Volume expansion on reversal (RVOL >= 1.3x - 1.8x)
5. Tests both static and dynamic compounding across 10 years (2016-2026).
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
    
    # Distance to 20 EMA
    res["dist_ema20_pct"] = ((c - res["ema20"]) / res["ema20"]) * 100.0
    
    # Red days count in last 4 days
    res["red_day"] = (c < o).astype(int)
    res["red_days_prior_3"] = res["red_day"].shift(1) + res["red_day"].shift(2) + res["red_day"].shift(3)
    
    # Bullish reversal: Close > Open, Close > prior Close, low tested EMA20
    res["tested_ema20"] = (l <= res["ema20"] * 1.015) & (c >= res["ema20"] * 0.985)
    res["bullish_reversal"] = (c > o) & (c > c.shift(1)) & res["tested_ema20"]
    return res

indicators = {s: enrich_stock(df) for s, df in univ.items()}

def run_ipr(rvol_cut=1.4, target_pct=0.12, stop_pct=0.045, compound=True, init_capital=30000.0, max_pos=3):
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
            elif pos['days_held'] >= 8 and abs((c_px - pos['entry_price']) / pos['entry_price']) <= 0.015:
                exit_reason = 'STAGNATION_8D'
                exit_px = c_px
            elif pos['days_held'] >= 15:
                exit_reason = 'TIME_STOP_15D'
                exit_px = c_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=exit_px, quantity=pos['qty'])
                closed_trades.append({
                    'ticker': sym, 'year': date_idx.year, 'net_pnl': costs.net_pnl_rupees,
                    'friction': costs.total_friction_rupees, 'days_held': pos['days_held']
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
                c_px, sma50, sma200, rvol, rev, red_count = (
                    float(bar['Close']), float(bar['sma50']), float(bar['sma200']),
                    float(bar['rvol']), bool(bar['bullish_reversal']), float(bar['red_days_prior_3'])
                )
                
                # Stage 2 uptrend
                if c_px <= sma50 or sma50 <= sma200:
                    continue
                # Pullback of at least 1-3 red days, followed by confirmed reversal + volume
                if rev and red_count >= 1.0 and rvol >= rvol_cut:
                    score = rvol * 2.0 + red_count
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
                        'stop_loss': round(entry_px * (1.0 - stop_pct), 2),
                        'target': round(entry_px * (1.0 + target_pct), 2),
                        'days_held': 0, 'entry_date': date_str
                    }
                    
    df_tr = pd.DataFrame(closed_trades)
    df_eq = pd.DataFrame(daily_equity)
    if df_tr.empty:
        return None
        
    wins = df_tr[df_tr['net_pnl'] > 0]
    wr = len(wins) / len(df_tr) * 100.0
    tot_pnl = df_tr['net_pnl'].sum()
    gross_w = wins['net_pnl'].sum() if not wins.empty else 0.0
    gross_l = abs(df_tr[df_tr['net_pnl'] <= 0]['net_pnl'].sum()) if not df_tr[df_tr['net_pnl'] <= 0].empty else 1.0
    pf = gross_w / gross_l
    
    df_eq['peak'] = df_eq['equity'].cummax()
    df_eq['dd'] = (df_eq['equity'] - df_eq['peak']) / df_eq['peak'] * 100.0
    max_dd = df_eq['dd'].min()
    final_eq = df_eq['equity'].iloc[-1]
    ret_pct = ((final_eq - init_capital) / init_capital) * 100.0
    avg_hold = df_tr['days_held'].mean()
    
    # Monthly
    df_eq['year_month'] = df_eq['date'].apply(lambda d: str(d.date())[:7])
    m_snaps = df_eq.groupby('year_month').last()
    m_ret = (m_snaps['equity'] - m_snaps['equity'].shift(1).fillna(init_capital)) / m_snaps['equity'].shift(1).fillna(init_capital) * 100.0
    
    return {
        'rvol': rvol_cut, 'target': target_pct, 'compound': compound,
        'trades': len(df_tr), 'wr': wr, 'final_equity': final_eq, 'tot_pnl': tot_pnl,
        'ret_pct': ret_pct, 'pf': pf, 'dd': max_dd, 'avg_hold': avg_hold,
        'avg_mo': m_ret.mean(), 'best_mo': m_ret.max(), 'worst_mo': m_ret.min()
    }

print("="*95)
print("TESTING INSTITUTIONAL PULLBACK-REVERSAL (IPR) ENGINE (10 YEARS | 111 STOCKS)")
print("="*95)

for rvol in [1.2, 1.4, 1.6]:
    for tp in [0.10, 0.12, 0.14]:
        res = run_ipr(rvol_cut=rvol, target_pct=tp, compound=True)
        if res:
            print(f"RVOL >={rvol:3.1f}x | TP={tp*100:4.1f}%: {res['trades']:3d} trd | WR: {res['wr']:4.1f}% | Avg Hold: {res['avg_hold']:4.1f}d | Final Eq: Rs {res['final_equity']:8.1f} ({res['ret_pct']:+5.1f}%) | PF: {res['pf']:4.2f} | DD: {res['dd']:5.1f}% | Avg Mo: {res['avg_mo']:+.2f}%")
