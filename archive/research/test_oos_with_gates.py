"""
TraderAI - OOS vs IS with Macro Regime Gate & Profit Optimization
================================================================
Tests candidate patterns with:
1. Macro Regime Gate ON (Nifty > 50 SMA) vs OFF
2. Profit Targets (12% vs 15% vs Trailing Runner)
3. Stagnation Exit (6D vs 10D vs None)
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
    res["high50"] = h.rolling(50).max().shift(1)
    
    range_5d = h.rolling(5).max() - l.rolling(5).min()
    range_20d = h.rolling(20).max() - l.rolling(20).min()
    res["vcp_ratio"] = range_5d / range_20d.replace(0, np.nan)
    res["dist_ema20_pct"] = ((c - res["ema20"]) / res["ema20"]) * 100.0
    
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    res["rsi14"] = 100 - (100 / (1 + rs))
    return res

indicators = {s: enrich_stock(df) for s, df in univ.items()}

def run_simulation(pattern="VCP", start_date="2016-10-24", end_date="2021-10-01", 
                   use_regime_gate=True, target_pct=0.12, stop_pct=0.045, 
                   stagnation_days=10, max_hold=20, init_capital=30000.0, max_pos=3):
    dates = nifty_df.loc[start_date:end_date].index
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
            
            # Conservative stop-first
            if l_px <= pos['stop_loss']:
                exit_reason = 'STOP_LOSS'
                exit_px = min(pos['stop_loss'], o_px)
            elif h_px >= pos['target']:
                exit_reason = 'TARGET_HIT'
                exit_px = pos['target']
            elif stagnation_days > 0 and pos['days_held'] >= stagnation_days and abs((c_px - pos['entry_price']) / pos['entry_price']) <= 0.02:
                exit_reason = f'STAGNATION_{stagnation_days}D'
                exit_px = c_px
            elif pos['days_held'] >= max_hold:
                exit_reason = f'TIME_STOP_{max_hold}D'
                exit_px = c_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=exit_px, quantity=pos['qty'])
                closed_trades.append({
                    'ticker': sym, 'net_pnl': costs.net_pnl_rupees, 'days_held': pos['days_held'],
                    'reason': exit_reason, 'ret_pct': costs.net_pnl_pct
                })
                cash += (pos['qty'] * exit_px) - costs.total_friction_rupees
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        # Equity tracking
        invested = sum(pos['qty'] * (float(indicators[sym].loc[date_idx, 'Close']) if date_idx in indicators[sym].index else pos['entry_price']) for sym, pos in open_positions.items())
        daily_equity.append({'date': date_idx, 'equity': cash + invested, 'cash': cash, 'invested': invested})
        
        # Regime check for entries
        if use_regime_gate and nifty_c < nifty_sma50:
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
                ema20 = float(bar['ema20']) if not np.isnan(bar['ema20']) else 0.0
                rvol = float(bar['rvol']) if not np.isnan(bar['rvol']) else 1.0
                vcp = float(bar['vcp_ratio']) if not np.isnan(bar['vcp_ratio']) else 1.0
                dist = float(bar['dist_ema20_pct']) if not np.isnan(bar['dist_ema20_pct']) else 0.0
                rsi = float(bar['rsi14']) if not np.isnan(bar['rsi14']) else 50.0
                
                if c_px <= sma50 or sma50 <= sma200:
                    continue
                    
                if pattern == "VCP":
                    high20 = float(bar['high20']) if not np.isnan(bar['high20']) else 0.0
                    if vcp <= 0.65 and rvol >= 1.3 and c_px >= high20 * 0.995:
                        score = (1.0 - vcp) * 10.0 + rvol
                        candidates.append((sym, score, c_px))
                elif pattern == "SWEET_SPOT":
                    if 0.0 <= dist <= 2.2 and l_px <= ema20 * 1.015 and c_px > o_px:
                        score = 10.0 - dist + (rvol * 0.5)
                        candidates.append((sym, score, c_px))
                elif pattern == "BREAKOUT_50D":
                    high50 = float(bar['high50']) if not np.isnan(bar['high50']) else 0.0
                    if c_px >= high50 and rvol >= 1.2 and rsi >= 60.0:
                        score = rvol * 2.0 + (rsi / 10.0)
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
        return {'trades': 0, 'pnl': 0.0, 'wr': 0.0, 'pf': 0.0, 'dd': 0.0}
        
    wins = df_tr[df_tr['net_pnl'] > 0]
    losses = df_tr[df_tr['net_pnl'] <= 0]
    wr = len(wins) / len(df_tr) * 100.0
    tot_pnl = df_tr['net_pnl'].sum()
    gross_w = wins['net_pnl'].sum() if not wins.empty else 0.0
    gross_l = abs(losses['net_pnl'].sum()) if not losses.empty else 1.0
    pf = gross_w / gross_l
    
    df_eq['peak'] = df_eq['equity'].cummax()
    df_eq['dd'] = (df_eq['equity'] - df_eq['peak']) / df_eq['peak'] * 100.0
    max_dd = df_eq['dd'].min()
    
    return {
        'pattern': pattern, 'trades': len(df_tr), 'wr': wr, 'pnl': tot_pnl,
        'ret_pct': (tot_pnl / init_capital) * 100.0, 'pf': pf, 'dd': max_dd
    }

print("="*90)
print("EXPERIMENT 1: MACRO REGIME GATE IMPACT ON OUT-OF-SAMPLE (2016-2021) & IN-SAMPLE (2021-2026)")
print("="*90)

for period_name, s_date, e_date in [("OOS (2016-2021)", "2016-10-24", "2021-10-01"), 
                                    ("IS  (2021-2026)", "2021-10-18", "2026-10-16")]:
    print(f"\n--- Period: {period_name} ---")
    for pat in ["VCP", "SWEET_SPOT", "BREAKOUT_50D"]:
        r_off = run_simulation(pattern=pat, start_date=s_date, end_date=e_date, use_regime_gate=False)
        r_on  = run_simulation(pattern=pat, start_date=s_date, end_date=e_date, use_regime_gate=True)
        print(f"[{pat:12s}] Gate OFF: {r_off['trades']:3d} trd | WR: {r_off['wr']:4.1f}% | Net: Rs {r_off['pnl']:+8.1f} ({r_off['ret_pct']:+5.1f}%) | PF: {r_off['pf']:4.2f} | DD: {r_off['dd']:5.1f}%")
        print(f"[{pat:12s}] Gate ON : {r_on['trades']:3d} trd | WR: {r_on['wr']:4.1f}% | Net: Rs {r_on['pnl']:+8.1f} ({r_on['ret_pct']:+5.1f}%) | PF: {r_on['pf']:4.2f} | DD: {r_on['dd']:5.1f}%")
