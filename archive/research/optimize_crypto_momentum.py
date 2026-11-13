"""
Optimize Crypto Momentum & Breakout Rules for Rs 3,000 capital.
Find the optimal parameters for win rate, profit factor, and maximum capital preservation.
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

def compute_crypto_indicators(df, btc_df):
    d = df.copy()
    close = d['close']
    d['ema10'] = close.ewm(span=10, adjust=False).mean()
    d['ema20'] = close.ewm(span=20, adjust=False).mean()
    d['ema50'] = close.ewm(span=50, adjust=False).mean()
    d['ema200'] = close.ewm(span=200, adjust=False).mean()
    d['sma20_vol'] = d['volume'].rolling(20).mean()
    d['rvol'] = d['volume'] / (d['sma20_vol'] + 1e-8)
    
    tr1 = d['high'] - d['low']
    tr2 = (d['high'] - close.shift(1)).abs()
    tr3 = (d['low'] - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    d['atr5'] = tr.rolling(5).mean()
    d['atr20'] = tr.rolling(20).mean()
    d['vcp_ratio'] = d['atr5'] / (d['atr20'] + 1e-8)
    
    d['high20'] = d['high'].rolling(20).max().shift(1)
    d['high10'] = d['high'].rolling(10).max().shift(1)
    
    aligned_btc = btc_df['close'].reindex(d.index).ffill()
    base_ratio = close / (aligned_btc + 1e-8)
    sma_base = base_ratio.rolling(50).mean()
    d['mansfield_rs'] = ((base_ratio / (sma_base + 1e-8)) - 1.0) * 100.0
    
    return d

processed_data = {sym: compute_crypto_indicators(df, btc_df) for sym, df in crypto_data.items()}
all_dates = sorted(btc_df.index)

def test_variant(name, lookback_high=20, rvol_min=1.5, stop_pct=0.07, pt_scale=0.20, trail_ema=True, max_slots=2, require_btc_bull=True, capital=3000.0):
    active_positions = {}
    closed_trades = []
    daily_equity = []
    curr_cap = capital
    
    for dt in all_dates:
        btc_bar = processed_data["BTC-USD"].loc[dt] if dt in processed_data["BTC-USD"].index else None
        if btc_bar is None or pd.isna(btc_bar['ema50']):
            continue
            
        btc_bull = (btc_bar['close'] > btc_bar['ema50']) and (btc_bar['ema20'] > btc_bar['ema50'])
        if require_btc_bull and not btc_bull:
            market_allowed = False
        else:
            market_allowed = True
            
        # Manage exits
        exits_to_make = []
        for sym, pos in list(active_positions.items()):
            if dt not in processed_data[sym].index:
                continue
            bar = processed_data[sym].loc[dt]
            curr_close = bar['close']
            curr_low = bar['low']
            curr_high = bar['high']
            
            if curr_high > pos['highest_price']:
                pos['highest_price'] = curr_high
                
            entry_p = pos['entry_price']
            gain_pct = (curr_close - entry_p) / entry_p
            low_pct = (curr_low - entry_p) / entry_p
            
            exit_price = None
            exit_reason = None
            
            # Stop loss
            if low_pct <= -stop_pct:
                exit_price = entry_p * (1.0 - stop_pct)
                exit_reason = f"Hard Stop (-{int(stop_pct*100)}%)"
            elif gain_pct >= pt_scale and not pos['partial_booked']:
                pos['partial_booked'] = True
                pos['stop_price'] = entry_p * 1.02 # breakeven+
            elif trail_ema and pos['partial_booked'] and curr_close < bar['ema10']:
                exit_price = curr_close
                exit_reason = "10 EMA Trail Exit"
            elif require_btc_bull and not btc_bull and (curr_close < bar['ema20']):
                exit_price = curr_close
                exit_reason = "BTC Bear Regime Cut"
                
            if exit_price is not None:
                exits_to_make.append((sym, exit_price, exit_reason))
                
        for sym, ex_price, reason in exits_to_make:
            pos = active_positions.pop(sym)
            shares = pos['shares']
            gross_val = shares * ex_price
            
            # 0.20% fee + 0.10% slippage + 1.00% Indian TDS
            fee = gross_val * 0.0020
            slippage = gross_val * 0.0010
            tds = gross_val * 0.0100
            net_proceeds = gross_val - fee - slippage - tds
            
            trade_pnl = net_proceeds - pos['cost_basis']
            trade_ret = (trade_pnl / pos['cost_basis']) * 100.0
            curr_cap += net_proceeds
            
            closed_trades.append({
                'symbol': sym,
                'pnl': trade_pnl,
                'ret_pct': trade_ret,
                'reason': reason,
                'duration': (dt - pos['entry_date']).days
            })
            
        # Entries
        open_slots = max_slots - len(active_positions)
        if open_slots > 0 and market_allowed:
            candidates = []
            for sym, df in processed_data.items():
                if sym in active_positions or dt not in df.index:
                    continue
                bar = df.loc[dt]
                if pd.isna(bar['ema50']) or pd.isna(bar['rvol']):
                    continue
                close = bar['close']
                rvol = bar['rvol']
                m_rs = bar['mansfield_rs']
                
                h_col = 'high20' if lookback_high == 20 else 'high10'
                if close > bar[h_col] and rvol >= rvol_min and close > bar['ema20']:
                    score = m_rs + (rvol * 5)
                    candidates.append((sym, score, close))
                    
            candidates.sort(key=lambda x: x[1], reverse=True)
            for sym, score, close in candidates[:open_slots]:
                current_equity = curr_cap + sum(p['shares'] * processed_data[s].loc[dt]['close'] for s, p in active_positions.items() if dt in processed_data[s].index)
                alloc = (current_equity / max_slots)
                alloc = min(alloc, curr_cap)
                if alloc < 150:
                    continue
                    
                eff_entry_price = close * 1.0010
                fee = alloc * 0.0020
                investable = alloc - fee
                shares = investable / eff_entry_price
                curr_cap -= alloc
                
                active_positions[sym] = {
                    'entry_price': eff_entry_price,
                    'entry_date': dt,
                    'shares': shares,
                    'cost_basis': alloc,
                    'highest_price': close,
                    'partial_booked': False,
                    'stop_price': eff_entry_price * (1.0 - stop_pct)
                }
                
        holdings_val = sum(p['shares'] * processed_data[s].loc[dt]['close'] for s, p in active_positions.items() if dt in processed_data[s].index)
        daily_equity.append({'date': dt, 'equity': curr_cap + holdings_val})
        
    eq_df = pd.DataFrame(daily_equity)
    eq_df['peak'] = eq_df['equity'].cummax()
    eq_df['dd'] = (eq_df['equity'] - eq_df['peak']) / eq_df['peak']
    max_dd = eq_df['dd'].min() * 100.0
    
    final_eq = eq_df['equity'].iloc[-1]
    net_pnl = final_eq - capital
    net_ret = (net_pnl / capital) * 100.0
    
    tdf = pd.DataFrame(closed_trades)
    if not tdf.empty:
        n_t = len(tdf)
        wins = tdf[tdf['pnl'] > 0]
        losses = tdf[tdf['pnl'] <= 0]
        wr = (len(wins) / n_t) * 100.0
        pf = (wins['pnl'].sum() if len(wins) > 0 else 0) / (abs(losses['pnl'].sum()) if len(losses) > 0 else 1e-8)
        avg_w = wins['ret_pct'].mean() if len(wins) > 0 else 0
        avg_l = losses['ret_pct'].mean() if len(losses) > 0 else 0
        best_t = tdf['ret_pct'].max()
    else:
        n_t = wr = pf = avg_w = avg_l = best_t = 0
        
    print(f"\n[{name}]")
    print(f"  Final: Rs {final_eq:.2f} ({net_ret:+.1f}%) | Net: Rs {net_pnl:+.2f} | Max DD: {max_dd:.1f}%")
    print(f"  Trades: {n_t} | Win Rate: {wr:.1f}% | Profit Factor: {pf:.2f}")
    print(f"  Avg Win: {avg_w:+.1f}% | Avg Loss: {avg_l:.1f}% | Best: {best_t:+.1f}%")
    return {
        'name': name, 'final_eq': final_eq, 'net_ret': net_ret, 'max_dd': max_dd,
        'trades': n_t, 'wr': wr, 'pf': pf, 'avg_w': avg_w, 'avg_l': avg_l, 'best_t': best_t
    }

print("Running parameter optimization sweeps...")
test_variant("20D Breakout + 7% Stop + 20% Target (2 Slots)", lookback_high=20, rvol_min=1.5, stop_pct=0.07, pt_scale=0.20, max_slots=2)
test_variant("20D Breakout + 5% Stop + 15% Target (2 Slots)", lookback_high=20, rvol_min=1.5, stop_pct=0.05, pt_scale=0.15, max_slots=2)
test_variant("10D Fast Breakout + 7% Stop + 20% Target (2 Slots)", lookback_high=10, rvol_min=1.5, stop_pct=0.07, pt_scale=0.20, max_slots=2)
test_variant("20D Breakout + 8% Stop + 25% Target (1 Slot - Rs 3,000 Full)", lookback_high=20, rvol_min=1.5, stop_pct=0.08, pt_scale=0.25, max_slots=1)
test_variant("20D Breakout + NO BTC Macro Gate (Control)", lookback_high=20, rvol_min=1.5, stop_pct=0.07, pt_scale=0.20, require_btc_bull=False, max_slots=2)
