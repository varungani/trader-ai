"""
TraderAI - Turnover Reduction & Profit Maximization Test
======================================================
Tests the hypothesis:
Cutting trade count by 40-50% using higher conviction filters (RVOL >= 1.8x, Minervini RS Leader)
saves Rs 10,000+ in CDSL DP charges and friction, directly increasing net expectancy.
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
    
    # 6-month Relative Strength momentum vs index
    res["ret_6m"] = (c - c.shift(125)) / c.shift(125)
    return res

indicators = {s: enrich_stock(df) for s, df in univ.items()}

def test_conviction(rvol_cut=1.8, target_pct=0.14, stop_pct=0.045, max_pos=3, init_capital=30000.0):
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
                    'gross_pnl': costs.gross_pnl_rupees, 'friction': costs.total_friction_rupees
                })
                cash += (pos['qty'] * exit_px) - costs.total_friction_rupees
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        invested = sum(pos['qty'] * (float(indicators[sym].loc[date_idx, 'Close']) if date_idx in indicators[sym].index else pos['entry_price']) for sym, pos in open_positions.items())
        daily_equity.append({'date': date_idx, 'year_month': date_str[:7], 'equity': cash + invested})
        
        if nifty_c < nifty_sma50:
            continue
            
        if len(open_positions) < max_pos:
            candidates = []
            for sym, ind in indicators.items():
                if sym in open_positions or date_idx not in ind.index:
                    continue
                bar = ind.loc[date_idx]
                c_px, o_px, h_px, l_px = float(bar['Close']), float(bar['Open']), float(bar['High']), float(bar['Low'])
                sma50 = float(bar['sma50']) if not np.isnan(bar['sma50']) else 0.0
                sma200 = float(bar['sma200']) if not np.isnan(bar['sma200']) else 0.0
                rvol = float(bar['rvol']) if not np.isnan(bar['rvol']) else 1.0
                vcp = float(bar['vcp_ratio']) if not np.isnan(bar['vcp_ratio']) else 1.0
                high20 = float(bar['high20']) if not np.isnan(bar['high20']) else 0.0
                ret_6m = float(bar['ret_6m']) if not np.isnan(bar['ret_6m']) else 0.0
                
                # Minervini Stage 2 + Leader Momentum
                if c_px <= sma50 or sma50 <= sma200 or ret_6m <= 0.10:
                    continue
                # Elite Volume VCP Breakout
                if vcp <= 0.65 and rvol >= rvol_cut and c_px >= high20 * 0.995:
                    score = (1.0 - vcp) * 10.0 + rvol + (ret_6m * 2.0)
                    candidates.append((sym, score, c_px))
                    
            candidates.sort(key=lambda x: x[1], reverse=True)
            slots_free = max_pos - len(open_positions)
            for sym, score, entry_px in candidates[:slots_free]:
                pos_alloc = min(cash, init_capital / max_pos)
                qty = int(pos_alloc // entry_px)
                if qty > 0 and cash >= (qty * entry_px):
                    cash -= (qty * entry_px)
                    stop_px = round(entry_px * (1.0 - stop_pct), 2)
                    tp_px = round(entry_px * (1.0 + target_pct), 2)
                    open_positions[sym] = {
                        'entry_price': entry_px, 'qty': qty, 'stop_loss': stop_px,
                        'target': tp_px, 'days_held': 0, 'entry_date': date_str
                    }
                    
    df_tr = pd.DataFrame(closed_trades)
    df_eq = pd.DataFrame(daily_equity)
    if df_tr.empty:
        return None
        
    wins = df_tr[df_tr['net_pnl'] > 0]
    wr = len(wins) / len(df_tr) * 100.0
    tot_pnl = df_tr['net_pnl'].sum()
    gross_pnl = df_tr['gross_pnl'].sum()
    friction = df_tr['friction'].sum()
    pf = wins['net_pnl'].sum() / abs(df_tr[df_tr['net_pnl'] <= 0]['net_pnl'].sum())
    
    df_eq['peak'] = df_eq['equity'].cummax()
    df_eq['dd'] = (df_eq['equity'] - df_eq['peak']) / df_eq['peak'] * 100.0
    max_dd = df_eq['dd'].min()
    
    # Monthly
    m_snaps = df_eq.groupby('year_month').last()
    m_pnl = m_snaps['equity'] - m_snaps['equity'].shift(1).fillna(init_capital)
    
    return {
        'trades': len(df_tr), 'wr': wr, 'gross_pnl': gross_pnl, 'friction': friction,
        'net_pnl': tot_pnl, 'ret_pct': (tot_pnl / init_capital) * 100.0,
        'pf': pf, 'dd': max_dd, 'exp': tot_pnl / len(df_tr),
        'avg_mo': m_pnl.mean(), 'best_mo': m_pnl.max(), 'worst_mo': m_pnl.min()
    }

print("="*90)
print("TESTING TURNOVER REDUCTION & CONVICTION SIZING ON 10-YEAR DATA (2016-2026)")
print("="*90)

for rvol in [1.3, 1.5, 1.8, 2.0]:
    for tp in [0.12, 0.14]:
        res = test_conviction(rvol_cut=rvol, target_pct=tp)
        if res:
            print(f"RVOL >={rvol:3.1f}x | TP={tp*100:4.1f}%: {res['trades']:3d} trd | WR: {res['wr']:4.1f}% | Net P&L: Rs {res['net_pnl']:+8.1f} ({res['ret_pct']:+5.1f}%) | Fees: Rs {res['friction']:7.1f} | PF: {res['pf']:4.2f} | Exp: Rs {res['exp']:+6.1f} | DD: {res['dd']:5.1f}% | Avg Mo: Rs {res['avg_mo']:+6.1f}")
