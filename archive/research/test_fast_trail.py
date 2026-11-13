"""
Test Fast Swing (3-7 Days) vs Standard Swing (7-20 Days) with dynamic trailing exits.
"""
import sys
import os
import pickle
import pandas as pd
import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "cache", "crypto_5y.pkl")
with open(CACHE_FILE, "rb") as f:
    crypto_data = pickle.load(f)

btc_df = crypto_data["BTC-USD"]

def compute_indicators(df, btc_df):
    d = df.copy()
    c = d['close']
    d['ema5'] = c.ewm(span=5, adjust=False).mean()
    d['ema10'] = c.ewm(span=10, adjust=False).mean()
    d['ema20'] = c.ewm(span=20, adjust=False).mean()
    d['ema50'] = c.ewm(span=50, adjust=False).mean()
    d['sma20_vol'] = d['volume'].rolling(20).mean()
    d['rvol'] = d['volume'] / (d['sma20_vol'] + 1e-8)
    
    d['high10'] = d['high'].rolling(10).max().shift(1)
    d['high20'] = d['high'].rolling(20).max().shift(1)
    
    aligned_btc = btc_df['close'].reindex(d.index).ffill()
    base_ratio = c / (aligned_btc + 1e-8)
    sma_base = base_ratio.rolling(min(50, len(base_ratio))).mean()
    d['mansfield_rs'] = ((base_ratio / (sma_base + 1e-8)) - 1.0) * 100.0
    return d

processed = {sym: compute_indicators(df, btc_df) for sym, df in crypto_data.items()}
all_dates = sorted(btc_df.index)

def test_fast_trail(name, entry_lookback=10, trail_ema='ema5', stop_pct=0.05, min_rvol=1.5, capital=3000.0):
    active_pos = {}
    closed_trades = []
    daily_equity = []
    curr_cap = capital
    max_slots = 2
    
    for dt in all_dates:
        btc_bar = processed["BTC-USD"].loc[dt] if dt in processed["BTC-USD"].index else None
        if btc_bar is None or pd.isna(btc_bar['ema50']):
            continue
        btc_bull = (btc_bar['close'] > btc_bar['ema50']) and (btc_bar['ema20'] > btc_bar['ema50'])
        
        exits = []
        for sym, pos in list(active_pos.items()):
            if dt not in processed[sym].index:
                continue
            bar = processed[sym].loc[dt]
            curr_c = bar['close']
            curr_l = bar['low']
            entry_p = pos['entry_price']
            days_held = (dt - pos['entry_date']).days
            
            gain = (curr_c - entry_p) / entry_p
            loss = (curr_l - entry_p) / entry_p
            
            ex_p = None
            reason = None
            
            if loss <= -stop_pct:
                ex_p = entry_p * (1.0 - stop_pct)
                reason = f"Stop Loss (-{stop_pct*100:.1f}%)"
            elif gain >= 0.12 and curr_c < bar[trail_ema]:
                ex_p = curr_c
                reason = f"Fast {trail_ema.upper()} Trail Exit"
            elif not btc_bull and curr_c < bar['ema20']:
                ex_p = curr_c
                reason = "BTC Bear Exit"
                
            if ex_p is not None:
                exits.append((sym, ex_p, reason, days_held))
                
        for sym, ex_p, reason, days_held in exits:
            pos = active_pos.pop(sym)
            gross = pos['shares'] * ex_p
            fee = gross * 0.0020
            slip = gross * 0.0010
            tds = gross * 0.0100
            net = gross - fee - slip - tds
            pnl = net - pos['cost_basis']
            ret = (pnl / pos['cost_basis']) * 100.0
            curr_cap += net
            closed_trades.append({'sym': sym, 'pnl': pnl, 'ret': ret, 'days': days_held, 'reason': reason})
            
        open_slots = max_slots - len(active_pos)
        if open_slots > 0 and btc_bull:
            cands = []
            for sym, df in processed.items():
                if sym in active_pos or dt not in df.index:
                    continue
                bar = df.loc[dt]
                if pd.isna(bar['rvol']):
                    continue
                c = bar['close']
                h_col = 'high10' if entry_lookback == 10 else 'high20'
                if c > bar[h_col] and bar['rvol'] >= min_rvol and c > bar['ema20']:
                    cands.append((sym, bar['mansfield_rs'] + bar['rvol']*5, c))
                    
            cands.sort(key=lambda x: x[1], reverse=True)
            for sym, score, c in cands[:open_slots]:
                cur_eq = curr_cap + sum(p['shares'] * processed[s].loc[dt]['close'] for s, p in active_pos.items() if dt in processed[s].index)
                alloc = min(cur_eq / max_slots, curr_cap)
                if alloc < 150:
                    continue
                eff_p = c * 1.0010
                fee = alloc * 0.0020
                shares = (alloc - fee) / eff_p
                curr_cap -= alloc
                active_pos[sym] = {
                    'entry_price': eff_p, 'entry_date': dt, 'shares': shares,
                    'cost_basis': alloc
                }
                
        hold_val = sum(p['shares'] * processed[s].loc[dt]['close'] for s, p in active_pos.items() if dt in processed[s].index)
        daily_equity.append(curr_cap + hold_val)
        
    s = pd.Series(daily_equity)
    fin_eq = s.iloc[-1]
    net_p = fin_eq - capital
    net_r = (net_p / capital) * 100.0
    pk = s.cummax()
    dd = ((s - pk) / pk).min() * 100.0
    
    tdf = pd.DataFrame(closed_trades)
    if len(tdf) > 0:
        wins = tdf[tdf['pnl'] > 0]
        losses = tdf[tdf['pnl'] <= 0]
        wr = (len(wins) / len(tdf)) * 100.0
        pf = (wins['pnl'].sum() if len(wins) > 0 else 0) / (abs(losses['pnl'].sum()) if len(losses) > 0 else 1e-8)
        avg_w = wins['ret'].mean() if len(wins) > 0 else 0
        avg_l = losses['ret'].mean() if len(losses) > 0 else 0
        avg_d = tdf['days'].mean()
        best_t = tdf['ret'].max()
    else:
        wr = pf = avg_w = avg_l = avg_d = best_t = 0
        
    print(f"\n[{name}]")
    print(f"  Final: Rs {fin_eq:8.2f} ({net_r:+.1f}%) | Net P&L: Rs {net_p:+.2f} | Max DD: {dd:.1f}%")
    print(f"  Trades: {len(tdf)} | Avg Hold: {avg_d:.1f} days | Win Rate: {wr:.1f}% | Profit Factor: {pf:.2f}")
    print(f"  Avg Win: {avg_w:+.1f}% | Avg Loss: {avg_l:.1f}% | Best: {best_t:+.1f}%")

print("Testing Fast Swing variants...")
test_fast_trail("Fast Swing 5 EMA Trail (Avg 5-7 Days)", entry_lookback=10, trail_ema='ema5', stop_pct=0.05, min_rvol=1.5)
test_fast_trail("Standard Swing 10 EMA Trail (Avg 10-14 Days)", entry_lookback=20, trail_ema='ema10', stop_pct=0.06, min_rvol=1.5)
