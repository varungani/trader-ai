"""
Backtest 1 to 4 Week (7 to 28 Days) Crypto Swing Momentum on 5-Year Dataset.
Starting Capital: Rs 3,000 | Indian Statutory Drag: 1% TDS + 0.20% fee + 0.10% slippage.
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
    d['ema10'] = c.ewm(span=10, adjust=False).mean()
    d['ema20'] = c.ewm(span=20, adjust=False).mean()
    d['ema50'] = c.ewm(span=50, adjust=False).mean()
    d['sma20_vol'] = d['volume'].rolling(20).mean()
    d['rvol'] = d['volume'] / (d['sma20_vol'] + 1e-8)
    d['high20'] = d['high'].rolling(20).max().shift(1)
    
    aligned_btc = btc_df['close'].reindex(d.index).ffill()
    base_ratio = c / (aligned_btc + 1e-8)
    sma_base = base_ratio.rolling(min(50, len(base_ratio))).mean()
    d['mansfield_rs'] = ((base_ratio / (sma_base + 1e-8)) - 1.0) * 100.0
    return d

processed = {sym: compute_indicators(df, btc_df) for sym, df in crypto_data.items()}
all_dates = sorted(btc_df.index)

def test_multi_week_swing(name, stop_pct=0.065, pt1_pct=0.20, pt1_scale=0.35, trail_ema='ema10', max_days=28, capital=3000.0, max_slots=2):
    active_pos = {}
    closed_trades = []
    daily_equity = []
    curr_cap = capital
    
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
            
            # Hard stop
            if loss <= -stop_pct:
                ex_p = entry_p * (1.0 - stop_pct)
                reason = f"Hard Stop (-{stop_pct*100:.1f}%)"
            # Partial profit scale-out at +20%
            elif gain >= pt1_pct and not pos['partial_booked']:
                pos['partial_booked'] = True
                # Partial booking of pt1_scale (35%)
                booked_shares = pos['shares'] * pt1_scale
                gross_partial = booked_shares * curr_c
                fee = gross_partial * 0.0020
                slip = gross_partial * 0.0010
                tds = gross_partial * 0.0100
                net_partial = gross_partial - fee - slip - tds
                curr_cap += net_partial
                pos['shares'] -= booked_shares
                pos['cost_basis'] -= (pos['cost_basis'] * pt1_scale)
                pos['realized_partial_pnl'] = net_partial - (pos['cost_basis'] * pt1_scale / (1.0 - pt1_scale))
                pos['stop_price'] = entry_p * 1.02  # Breakeven + 2%
            # Trailing exit after partial booking
            elif pos['partial_booked'] and curr_c < bar[trail_ema]:
                ex_p = curr_c
                reason = f"{trail_ema.upper()} Trailing Exit ({days_held}d)"
            # 4-week maximum hold limit (session 28)
            elif days_held >= max_days:
                ex_p = curr_c
                reason = f"4-Week Time Limit ({days_held}d)"
            # BTC Bear Exit
            elif not btc_bull and curr_c < bar['ema20']:
                ex_p = curr_c
                reason = f"BTC Bear Regime Cut ({days_held}d)"
                
            if ex_p is not None:
                exits.append((sym, ex_p, reason, days_held))
                
        for sym, ex_p, reason, days_held in exits:
            pos = active_pos.pop(sym)
            gross = pos['shares'] * ex_p
            fee = gross * 0.0020
            slip = gross * 0.0010
            tds = gross * 0.0100
            net = gross - fee - slip - tds
            trade_pnl = (net - pos['cost_basis']) + pos.get('realized_partial_pnl', 0.0)
            trade_ret = (trade_pnl / (pos['orig_cost'])) * 100.0
            curr_cap += net
            closed_trades.append({'sym': sym, 'pnl': trade_pnl, 'ret': trade_ret, 'days': days_held, 'reason': reason})
            
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
                if c > bar['high20'] and bar['rvol'] >= 1.4 and c > bar['ema20']:
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
                    'cost_basis': alloc, 'orig_cost': alloc, 'partial_booked': False,
                    'realized_partial_pnl': 0.0
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
    print(f"  Final Equity: Rs {fin_eq:8.2f} ({net_r:+.1f}%) | Net P&L: Rs {net_p:+.2f}")
    print(f"  Trades: {len(tdf)} | Avg Hold: {avg_d:.1f} days | Win Rate: {wr:.1f}%")
    print(f"  Profit Factor: {pf:.2f} | Max Drawdown: {dd:.1f}%")
    print(f"  Avg Win: {avg_w:+.1f}% | Avg Loss: {avg_l:.1f}% | Best Trade: {best_t:+.1f}%")

print("="*80)
print("TESTING 1-TO-4 WEEK CRYPTO SWING ARCHITECTURES (7-28 DAYS)")
print("Starting Capital: Rs 3,000 | Friction: 1% TDS + 0.2% Fee + 0.1% Slippage")
print("="*80)

test_multi_week_swing("1. 1-4 Week Swing (10 EMA Trail | 4-Week Max)", trail_ema='ema10', max_days=28, stop_pct=0.065, pt1_pct=0.20)
test_multi_week_swing("2. 1-4 Week Swing (20 EMA Trail | 4-Week Max)", trail_ema='ema20', max_days=28, stop_pct=0.070, pt1_pct=0.25)
test_multi_week_swing("3. Pure 2-4 Week Runner (10 EMA Trail | No Fixed Target)", trail_ema='ema10', max_days=28, stop_pct=0.065, pt1_pct=99.0)
test_multi_week_swing("4. 1-4 Week Swing (Tighter 5.5% Stop | 10 EMA Trail)", trail_ema='ema10', max_days=28, stop_pct=0.055, pt1_pct=0.18)
