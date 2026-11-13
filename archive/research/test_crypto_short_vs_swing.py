"""
Compare Crypto Short-Term (1-3 Days) vs Multi-Day Swing (3-15 Days)
Factoring in 1% Indian TDS, 0.20% exchange fee, and 0.10% slippage on Rs 3,000 capital.
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
    close = d['close']
    d['ema10'] = close.ewm(span=10, adjust=False).mean()
    d['ema20'] = close.ewm(span=20, adjust=False).mean()
    d['ema50'] = close.ewm(span=50, adjust=False).mean()
    d['sma20_vol'] = d['volume'].rolling(20).mean()
    d['rvol'] = d['volume'] / (d['sma20_vol'] + 1e-8)
    
    d['high20'] = d['high'].rolling(20).max().shift(1)
    d['high10'] = d['high'].rolling(10).max().shift(1)
    d['high5'] = d['high'].rolling(5).max().shift(1)
    
    aligned_btc = btc_df['close'].reindex(d.index).ffill()
    base_ratio = close / (aligned_btc + 1e-8)
    sma_base = base_ratio.rolling(min(50, len(base_ratio))).mean()
    d['mansfield_rs'] = ((base_ratio / (sma_base + 1e-8)) - 1.0) * 100.0
    return d

processed = {sym: compute_indicators(df, btc_df) for sym, df in crypto_data.items()}
all_dates = sorted(btc_df.index)

def run_mode_simulation(mode_name, lookback=10, stop_pct=0.045, target_pct=0.12, max_days=3, trail_runner=False, capital=3000.0, max_slots=2):
    active_pos = {}
    closed_trades = []
    daily_equity = []
    curr_cap = capital
    
    for dt in all_dates:
        btc_bar = processed["BTC-USD"].loc[dt] if dt in processed["BTC-USD"].index else None
        if btc_bar is None or pd.isna(btc_bar['ema50']):
            continue
        btc_bull = (btc_bar['close'] > btc_bar['ema50']) and (btc_bar['ema20'] > btc_bar['ema50'])
        
        # Exits
        exits = []
        for sym, pos in list(active_pos.items()):
            if dt not in processed[sym].index:
                continue
            bar = processed[sym].loc[dt]
            curr_c = bar['close']
            curr_l = bar['low']
            curr_h = bar['high']
            entry_p = pos['entry_price']
            days_held = (dt - pos['entry_date']).days
            
            gain = (curr_c - entry_p) / entry_p
            loss = (curr_l - entry_p) / entry_p
            
            ex_p = None
            reason = None
            
            if loss <= -stop_pct:
                ex_p = entry_p * (1.0 - stop_pct)
                reason = f"Stop Loss (-{stop_pct*100:.1f}%)"
            elif gain >= target_pct and not trail_runner:
                ex_p = entry_p * (1.0 + target_pct)
                reason = f"Target Hit (+{target_pct*100:.1f}%)"
            elif trail_runner and gain >= target_pct and not pos['partial_booked']:
                pos['partial_booked'] = True
            elif trail_runner and pos['partial_booked'] and curr_c < bar['ema10']:
                ex_p = curr_c
                reason = "10 EMA Trail Exit"
            elif max_days > 0 and days_held >= max_days and gain < 0.02:
                ex_p = curr_c
                reason = f"Time/Stagnation Exit ({days_held}d)"
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
            
        # Entries
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
                h_col = 'high10' if lookback == 10 else ('high5' if lookback == 5 else 'high20')
                if c > bar[h_col] and bar['rvol'] >= 1.4 and c > bar['ema20']:
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
                    'cost_basis': alloc, 'partial_booked': False
                }
                
        hold_val = sum(p['shares'] * processed[s].loc[dt]['close'] for s, p in active_pos.items() if dt in processed[s].index)
        daily_equity.append(curr_cap + hold_val)
        
    s = pd.Series(daily_equity)
    pk = s.cummax()
    dd = ((s - pk) / pk).min() * 100.0
    fin_eq = s.iloc[-1]
    net_p = fin_eq - capital
    net_r = (net_p / capital) * 100.0
    
    tdf = pd.DataFrame(closed_trades)
    n_t = len(tdf)
    if n_t > 0:
        wins = tdf[tdf['pnl'] > 0]
        losses = tdf[tdf['pnl'] <= 0]
        wr = (len(wins) / n_t) * 100.0
        pf = (wins['pnl'].sum() if len(wins) > 0 else 0) / (abs(losses['pnl'].sum()) if len(losses) > 0 else 1e-8)
        avg_w = wins['ret'].mean() if len(wins) > 0 else 0
        avg_l = losses['ret'].mean() if len(losses) > 0 else 0
        avg_days = tdf['days'].mean()
        best_t = tdf['ret'].max()
    else:
        wr = pf = avg_w = avg_l = avg_days = best_t = 0
        
    print(f"\n[{mode_name}]")
    print(f"  Final Equity: Rs {fin_eq:8.2f} ({net_r:+.1f}%) | Net P&L: Rs {net_p:+.2f}")
    print(f"  Trades: {n_t} | Avg Duration: {avg_days:.1f} days | Win Rate: {wr:.1f}%")
    print(f"  Profit Factor: {pf:.2f} | Max Drawdown: {dd:.1f}%")
    print(f"  Avg Win: {avg_w:+.1f}% | Avg Loss: {avg_l:.1f}% | Best Trade: {best_t:+.1f}%")

print("="*80)
print("COMPARING CRYPTO SHORT-TERM (1-3 DAYS) VS SWING (3-15 DAYS)")
print("Starting Capital: Rs 3,000 | Friction: 1% TDS + 0.2% Fee + 0.1% Slippage")
print("="*80)

run_mode_simulation(
    "1. Short-Term Fast Momentum (1-3 Days)",
    lookback=10, stop_pct=0.045, target_pct=0.10, max_days=3, trail_runner=False
)

run_mode_simulation(
    "2. Short-Term Momentum with +12% Target (2-4 Days)",
    lookback=10, stop_pct=0.045, target_pct=0.12, max_days=4, trail_runner=False
)

run_mode_simulation(
    "3. Multi-Day Swing Trend (3-15 Days | 20D High + 10 EMA Runner)",
    lookback=20, stop_pct=0.060, target_pct=0.18, max_days=0, trail_runner=True
)

run_mode_simulation(
    "4. Hybrid Dual-Mode (10D Breakout + 5% Stop + 10 EMA Runner)",
    lookback=10, stop_pct=0.050, target_pct=0.15, max_days=0, trail_runner=True
)
