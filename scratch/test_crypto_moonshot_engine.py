"""
Test Parabolic High-Beta Crypto Moonshot Engine on 5-Year Data (2021-2026).
Focuses on High-Beta Altcoin Leaders (SOL, AVAX, NEAR, DOGE, LINK) outperforming BTC.
Captures Parabolic 50% to 200%+ Waves with Tight Risk (-6.0% Stop) on Rs 3,000 Capital.
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

# Filter high-beta rocket coins (SOL, AVAX, NEAR, DOGE, LINK, BNB, ADA)
HIGH_BETA_COINS = ["SOL-USD", "AVAX-USD", "NEAR-USD", "DOGE-USD", "LINK-USD", "BNB-USD", "ADA-USD", "XRP-USD"]

def run_parabolic_moonshot(name, high_beta_only=True, stop_pct=0.060, scale_target=0.25, trail_ema='ema10', max_days=30, capital=3000.0, max_slots=2):
    curr_cap = capital
    active_pos = {}
    closed_trades = []
    daily_equity = []
    
    for dt in all_dates:
        btc_bar = processed["BTC-USD"].loc[dt] if dt in processed["BTC-USD"].index else None
        if btc_bar is None or pd.isna(btc_bar['ema50']):
            continue
        btc_bull = (btc_bar['close'] > btc_bar['ema50']) and (btc_bar['ema20'] > btc_bar['ema50'])
        
        # 1. Manage Exits
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
                reason = f"Hard Stop (-{stop_pct*100:.1f}%)"
            elif gain >= scale_target and not pos['partial_booked']:
                pos['partial_booked'] = True
                booked_shares = pos['shares'] * 0.30  # Book 30% to lock cost
                gross_partial = booked_shares * curr_c
                fee = gross_partial * 0.0020
                slip = gross_partial * 0.0010
                tds = gross_partial * 0.0100
                net_partial = gross_partial - fee - slip - tds
                curr_cap += net_partial
                pos['shares'] -= booked_shares
                pos['cost_basis'] -= (pos['cost_basis'] * 0.30)
                pos['realized_partial_pnl'] = net_partial - (pos['orig_cost'] * 0.30)
                pos['stop_price'] = entry_p * 1.02 # Breakeven+
            elif pos['partial_booked'] and curr_c < bar[trail_ema]:
                ex_p = curr_c
                reason = f"{trail_ema.upper()} Parabolic Trail Exit ({days_held}d)"
            elif days_held >= max_days:
                ex_p = curr_c
                reason = f"30-Day Window Expiry ({days_held}d)"
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
            final_pnl = (net - pos['cost_basis']) + pos.get('realized_partial_pnl', 0.0)
            ret_pct = (final_pnl / pos['orig_cost']) * 100.0
            curr_cap += net
            closed_trades.append({
                'symbol': sym, 'pnl': final_pnl, 'ret': ret_pct,
                'days': days_held, 'reason': reason, 'cost': pos['orig_cost']
            })
            
        # 2. Manage Entries
        open_slots = max_slots - len(active_pos)
        if open_slots > 0 and btc_bull:
            cands = []
            target_universe = HIGH_BETA_COINS if high_beta_only else list(processed.keys())
            for sym in target_universe:
                if sym in active_pos or dt not in processed[sym].index:
                    continue
                bar = processed[sym].loc[dt]
                if pd.isna(bar['rvol']):
                    continue
                c = bar['close']
                # Parabolic Trigger: 20D High breakout + RVOL >= 1.5 + Outperforming BTC (Mansfield RS >= 5%)
                if c > bar['high20'] and bar['rvol'] >= 1.5 and c > bar['ema20'] and bar['mansfield_rs'] >= 5.0:
                    score = bar['mansfield_rs'] * 2.0 + (bar['rvol'] * 10.0)
                    cands.append((sym, score, c))
                    
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
    n_t = len(tdf)
    if n_t > 0:
        wins = tdf[tdf['pnl'] > 0]
        losses = tdf[tdf['pnl'] <= 0]
        wr = (len(wins) / n_t) * 100.0
        pf = (wins['pnl'].sum() if len(wins) > 0 else 0) / (abs(losses['pnl'].sum()) if len(losses) > 0 else 1e-8)
        avg_w = wins['ret'].mean() if len(wins) > 0 else 0
        avg_l = losses['ret'].mean() if len(losses) > 0 else 0
        best_t = tdf['ret'].max()
        avg_d = tdf['days'].mean()
    else:
        wr = pf = avg_w = avg_l = best_t = avg_d = 0
        
    print(f"\n[{name}]")
    print(f"  Final Equity: Rs {fin_eq:8.2f} ({net_r:+.1f}%) | Net Profit: Rs {net_p:+8.2f}")
    print(f"  Trades: {n_t} | Win Rate: {wr:.1f}% | Profit Factor: {pf:.2f} | Max DD: {dd:.1f}%")
    print(f"  Avg Win: {avg_w:+.1f}% | Avg Loss: {avg_l:.1f}% | Best Trade: {best_t:+.1f}% | Avg Hold: {avg_d:.1f}d")
    return {'final': fin_eq, 'net_r': net_r, 'pf': pf, 'wr': wr, 'best': best_t, 'dd': dd}

print("="*85)
print("TESTING PARABOLIC HIGH-BETA CRYPTO MOONSHOT ARCHITECTURES")
print("Starting Capital: Rs 3,000 | Indian 1% TDS + 0.2% Fee + 0.1% Slippage")
print("="*85)

run_parabolic_moonshot("1. High-Beta Altcoins Only (SOL, AVAX, NEAR, DOGE) | 2 Slots | 10 EMA Trail", high_beta_only=True, stop_pct=0.060, scale_target=0.25, trail_ema='ema10')
run_parabolic_moonshot("2. High-Beta Altcoins | 1 High-Conviction Slot (Rs 3,000) | 10 EMA Trail", high_beta_only=True, stop_pct=0.060, scale_target=0.25, trail_ema='ema10', max_slots=1)
run_parabolic_moonshot("3. High-Beta Altcoins | 2 Slots | 15 EMA Trail (Wider Parabolic Runner)", high_beta_only=True, stop_pct=0.065, scale_target=0.30, trail_ema='ema20')
