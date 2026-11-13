import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pickle, pandas as pd, numpy as np
from backtesting.swing_midcap_backtest import load_cached_universe, compute_indicators
from data.costs import compute_indian_delivery_costs

univ, bm = load_cached_universe()
nifty_df = bm['^NSEI']

# Precompute indicators with volume ratio
def enrich_indicators(df):
    res = compute_indicators(df)
    res['vol_sma20'] = res['Volume'].rolling(20).mean()
    res['vol_ratio'] = res['Volume'] / res['vol_sma20'].replace(0, np.nan)
    res['high50'] = res['High'].rolling(50).max().shift(1)
    return res

indicators = {sym: enrich_indicators(df) for sym, df in univ.items()}
all_dates = nifty_df.index

def simulate_strategy(name, entry_fn, exit_fn, max_hold_days=20):
    cash = 100000.0
    open_positions = {}
    trades = []
    daily_equity = []
    
    for i in range(200, len(all_dates)):
        date_idx = all_dates[i]
        date_str = str(date_idx.date())
        
        # 1. Exits
        to_close = []
        for sym, pos in open_positions.items():
            ind = indicators[sym]
            if date_idx not in ind.index:
                pos['days_held'] += 1
                continue
            bar = ind.loc[date_idx]
            open_px = float(bar['Open'])
            high_px = float(bar['High'])
            low_px = float(bar['Low'])
            close_px = float(bar['Close'])
            pos['days_held'] += 1
            pos['peak_price'] = max(pos['peak_price'], high_px)
            
            exit_reason, exit_px = exit_fn(pos, bar, max_hold_days)
            if exit_reason:
                costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=exit_px, quantity=pos['qty'], apply_stcg=False)
                cash += (exit_px * pos['qty']) - costs.total_friction_rupees
                trades.append({
                    'ticker': sym,
                    'entry_price': pos['entry_price'],
                    'exit_price': exit_px,
                    'days_held': pos['days_held'],
                    'net_pnl': costs.net_pnl_rupees,
                    'gross_pnl': costs.gross_pnl_rupees,
                    'friction': costs.total_friction_rupees,
                    'reason': exit_reason
                })
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        # Daily Equity
        holdings_val = sum(float(indicators[s].loc[date_idx]['Close']) * p['qty'] 
                           for s, p in open_positions.items() if date_idx in indicators[s].index)
        daily_equity.append(cash + holdings_val)
        
        # 2. Market Regime Filter
        nifty_loc = nifty_df.index.get_loc(date_idx)
        regime_bullish = True
        if nifty_loc >= 50:
            n_close = float(nifty_df['Close'].iloc[nifty_loc])
            n_sma50 = float(nifty_df['Close'].iloc[nifty_loc-49:nifty_loc+1].mean())
            if n_close < n_sma50:
                regime_bullish = False
                
        # 3. Entries
        if len(open_positions) < 5 and regime_bullish:
            available = [s for s in univ.keys() if s not in open_positions]
            candidates = []
            for sym in available:
                ind = indicators[sym]
                if date_idx not in ind.index: continue
                loc = ind.index.get_loc(date_idx)
                if loc < 50: continue
                bar = ind.iloc[loc]
                passed, rank_val, stop_pct, target_pct = entry_fn(sym, ind, loc, bar)
                if passed:
                    candidates.append((sym, rank_val, float(bar['Close']), stop_pct, target_pct))
                    
            candidates.sort(key=lambda x: x[1], reverse=True)
            for sym, rank_val, close_px, stop_pct, target_pct in candidates[:5-len(open_positions)]:
                alloc = min(cash, 20000.0)
                qty = int(alloc // close_px)
                if qty > 0 and cash >= (qty * close_px):
                    stop_px = round(close_px * (1.0 - stop_pct), 2)
                    target_px = round(close_px * (1.0 + target_pct), 2)
                    cash -= (qty * close_px)
                    open_positions[sym] = {
                        'entry_price': close_px, 'qty': qty, 'stop_loss': stop_px,
                        'target': target_px, 'peak_price': close_px, 'days_held': 0,
                        'stop_pct': stop_pct, 'target_pct': target_pct
                    }
                    
    # Metrics
    tot_trades = len(trades)
    wins = [t for t in trades if t['net_pnl'] > 0]
    losses = [t for t in trades if t['net_pnl'] <= 0]
    tot_net = sum(t['net_pnl'] for t in trades)
    tot_friction = sum(t['friction'] for t in trades)
    wr = len(wins) / tot_trades * 100 if tot_trades else 0
    avg_win = np.mean([t['net_pnl'] for t in wins]) if wins else 0
    avg_loss = np.mean([abs(t['net_pnl']) for t in losses]) if losses else 0
    wl_ratio = avg_win / avg_loss if avg_loss else 0
    exp_rs = tot_net / tot_trades if tot_trades else 0
    
    eq = pd.Series(daily_equity)
    peaks = eq.cummax()
    max_dd = abs(float(((eq - peaks) / peaks).min())) * 100 if len(eq) else 0
    daily_rets = eq.pct_change().dropna()
    sharpe = float((daily_rets.mean() * 252) / (daily_rets.std() * np.sqrt(252))) if len(daily_rets) and daily_rets.std() > 0 else 0
    
    return {
        'name': name, 'trades': tot_trades, 'win_rate': round(wr, 1),
        'net_ret': round(tot_net / 1000.0, 1), 'net_pnl': round(tot_net, 0),
        'friction': round(tot_friction, 0), 'avg_win': round(avg_win, 0),
        'avg_loss': round(avg_loss, 0), 'wl_ratio': round(wl_ratio, 2),
        'expectancy': round(exp_rs, 1), 'max_dd': round(max_dd, 1), 'sharpe': round(sharpe, 2),
        'trades_list': trades
    }

# Standard Swing Exit: Stop-loss first, Target hit second, Time expiry third
def standard_exit(pos, bar, max_hold):
    open_px = float(bar['Open'])
    high_px = float(bar['High'])
    low_px = float(bar['Low'])
    close_px = float(bar['Close'])
    
    if low_px <= pos['stop_loss']:
        return 'STOP_LOSS', min(pos['stop_loss'], open_px)
    elif high_px >= pos['target']:
        return 'TARGET_HIT', pos['target']
    elif pos['days_held'] >= max_hold:
        return f'TIME_EXPIRY_{max_hold}D', close_px
    return None, 0.0

# 1. Pure Pullback Swing Setup
def entry_pullback(sym, ind, loc, bar):
    close = float(bar['Close'])
    open_p = float(bar['Open'])
    ema20 = float(bar['ema20'])
    sma50 = float(bar['sma50'])
    sma200 = float(bar['sma200'])
    rsi = float(bar['rsi14'])
    mom60 = float(bar['mom60'])
    adtv = float(bar['adtv_cr'])
    
    if adtv < 5.0 or close <= 10.0: return False, 0, 0, 0
    is_uptrend = close > sma50 and (sma50 > sma200 or mom60 > 5.0)
    low_3d = float(ind['Low'].iloc[loc-2:loc+1].min())
    tested_ema20 = low_3d <= (ema20 * 1.015) and close >= (ema20 * 0.97)
    rsi_ok = 42.0 <= rsi <= 65.0
    green_reversal = close > open_p and close >= ema20
    
    if is_uptrend and tested_ema20 and rsi_ok and green_reversal:
        stop_pct = max(0.035, min(0.05, (close - (ema20 * 0.985)) / close))
        target_pct = stop_pct * 3.0  # 3:1 R:R (10.5% - 15%)
        return True, mom60, stop_pct, target_pct
    return False, 0, 0, 0

# 2. Pure Volume Breakout Swing Setup
def entry_breakout(sym, ind, loc, bar):
    close = float(bar['Close'])
    high50 = float(bar['high50'])
    rsi = float(bar['rsi14'])
    mom60 = float(bar['mom60'])
    adtv = float(bar['adtv_cr'])
    vol_r = float(bar['vol_ratio'])
    
    if adtv < 5.0 or close <= 10.0: return False, 0, 0, 0
    is_breakout = close >= high50 and vol_r >= 1.2 and rsi > 60.0
    if is_breakout:
        stop_pct = 0.045 # 4.5% risk
        target_pct = 0.12 # 12% target
        return True, mom60, stop_pct, target_pct
    return False, 0, 0, 0

# 3. Dual-Engine Swing Setup (Best of Both: Takes Top Pullback OR Breakout by 60D Momentum)
def entry_dual(sym, ind, loc, bar):
    pb_ok, pb_rank, pb_stop, pb_tgt = entry_pullback(sym, ind, loc, bar)
    if pb_ok:
        return True, pb_rank, pb_stop, pb_tgt
    bo_ok, bo_rank, bo_stop, bo_tgt = entry_breakout(sym, ind, loc, bar)
    if bo_ok:
        return True, bo_rank, bo_stop, bo_tgt
    return False, 0, 0, 0

print("Testing Option 1A (Pullback Swing 20D hold)...")
res_1a = simulate_strategy("Option 1A: 20 EMA Pullback Swing (20D hold, 3:1 R:R)", entry_pullback, standard_exit, 20)

print("Testing Option 1B (Volume Breakout Swing 20D hold)...")
res_1b = simulate_strategy("Option 1B: High-Volume 50D Breakout (20D hold, 12% Tgt)", entry_breakout, standard_exit, 20)

print("Testing Option 1C (Dual-Engine Swing 20D hold)...")
res_1c = simulate_strategy("Option 1C: Dual-Engine Swing (Pullback + Breakout)", entry_dual, standard_exit, 20)

summary = [res_1a, res_1b, res_1c]
df_sum = pd.DataFrame(summary).drop(columns=['trades_list'])
print("\n" + "="*80)
print("5-YEAR EMPIRICAL COMPARISON OF SWING STRATEGIES ACROSS 136 STOCKS:")
print("="*80)
print(df_sum.to_string(index=False))
print("="*80)
