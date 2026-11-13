import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pickle, pandas as pd, numpy as np, math
from backtesting.swing_midcap_backtest import load_cached_universe, compute_indicators
from data.costs import compute_indian_delivery_costs

univ, bm = load_cached_universe()
nifty_df = bm['^NSEI']

def enrich_indicators(df):
    res = compute_indicators(df)
    res['vol_sma20'] = res['Volume'].rolling(20).mean()
    res['vol_ratio'] = res['Volume'] / res['vol_sma20'].replace(0, np.nan)
    res['high50'] = res['High'].rolling(50).max().shift(1)
    res['ema20'] = res['Close'].ewm(span=20, adjust=False).mean()
    res['ema10'] = res['Close'].ewm(span=10, adjust=False).mean()
    
    # 4-day close tightness
    roll_max = res['Close'].shift(1).rolling(4).max()
    roll_min = res['Close'].shift(1).rolling(4).min()
    res['tightness_4d'] = (roll_max - roll_min) / (roll_min + 1e-6) * 100
    
    # Distance from 20 EMA
    res['dist_ema20'] = (res['Close'] - res['ema20']) / res['ema20'] * 100
    return res

print(f"Precomputing indicators across {len(univ)} tickers for High Win-Rate Research...")
indicators = {sym: enrich_indicators(df) for sym, df in univ.items()}
all_dates = nifty_df.index

def test_strategy_variant(variant_name, setup_type, take_profit_pct, breakeven_trigger_pct):
    """
    Simulates a strategy with zero lookahead (Next-day Open + 0.20% slippage):
    - setup_type: 'RAW_BREAKOUT' vs 'PULLBACK_REBOUND' vs 'COILED_VCP'
    - take_profit_pct: e.g. 7.0%, 8.0%, 12.0%
    - breakeven_trigger_pct: e.g. 4.0%, 5.0%, None
    """
    cash = 100000.0
    open_positions = {}
    pending_buys = []
    trades = []
    
    SLIPPAGE_PCT = 0.002
    MAX_POSITIONS = 3
    MIN_TICKET_SIZE = 15000.0
    
    for i in range(200, len(all_dates)):
        date_idx = all_dates[i]
        date_str = str(date_idx.date())
        year = date_idx.year
        
        # 1. Fill pending buys at Today's Open + Slippage
        if pending_buys:
            for sym in pending_buys:
                if sym in open_positions:
                    continue
                if len(open_positions) >= MAX_POSITIONS:
                    break
                ind = indicators[sym]
                if date_idx not in ind.index:
                    continue
                bar = ind.loc[date_idx]
                today_open = float(bar['Open'])
                if today_open <= 0 or math.isnan(today_open):
                    continue
                fill_px = round(today_open * (1.0 + SLIPPAGE_PCT), 2)
                
                empty_slots = MAX_POSITIONS - len(open_positions)
                alloc = min(cash / empty_slots, 35000.0)
                if alloc < MIN_TICKET_SIZE:
                    continue
                    
                qty = int(alloc // fill_px)
                cost = qty * fill_px
                if qty > 0 and cash >= cost:
                    cash -= cost
                    stop_px = round(fill_px * 0.965, 2) # -3.5% initial stop
                    target_px = round(fill_px * (1.0 + take_profit_pct / 100.0), 2)
                    open_positions[sym] = {
                        'entry_price': fill_px,
                        'qty': qty,
                        'stop_loss': stop_px,
                        'target': target_px,
                        'peak_price': fill_px,
                        'days_held': 0,
                        'entry_date': date_str,
                        'breakeven_locked': False
                    }
            pending_buys = []
            
        # 2. Check exits
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
            pos['peak_price'] = max(pos.get('peak_price', pos['entry_price']), high_px)
            
            # Breakeven ratchet: If trade was up by breakeven_trigger_pct, protect entry!
            if breakeven_trigger_pct is not None and not pos['breakeven_locked']:
                if (pos['peak_price'] - pos['entry_price']) / pos['entry_price'] >= (breakeven_trigger_pct / 100.0):
                    pos['breakeven_locked'] = True
                    pos['stop_loss'] = max(pos['stop_loss'], pos['entry_price'] * 1.002) # protect breakeven
                    
            exit_reason = None
            exit_px = 0.0
            
            # Check stop
            if low_px <= pos['stop_loss']:
                exit_reason = 'BREAKEVEN_HIT' if pos['stop_loss'] >= pos['entry_price'] else 'STOP_LOSS'
                exit_px = min(pos['stop_loss'], open_px) if open_px < pos['stop_loss'] else pos['stop_loss']
            # Check target
            elif high_px >= pos['target']:
                exit_reason = 'TARGET_HIT'
                exit_px = pos['target']
            # Time exit (8 sessions fast recycling)
            elif pos['days_held'] >= 8:
                exit_reason = 'TIME_EXIT (8d)'
                exit_px = close_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(
                    buy_price=pos['entry_price'], sell_price=exit_px, quantity=pos['qty'], apply_stcg=False
                )
                cash += (exit_px * pos['qty']) - costs.total_friction_rupees
                trades.append({
                    'ticker': sym,
                    'year': year,
                    'net_pnl': costs.net_pnl_rupees,
                    'ret_pct': costs.net_pnl_pct,
                    'reason': exit_reason,
                    'days': pos['days_held']
                })
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        # 3. Scan for signals at EOD
        nifty_loc = nifty_df.index.get_loc(date_idx)
        regime_bullish = True
        if nifty_loc >= 50:
            n_close = float(nifty_df['Close'].iloc[nifty_loc])
            n_sma50 = float(nifty_df['Close'].iloc[nifty_loc-49:nifty_loc+1].mean())
            if n_close < n_sma50:
                regime_bullish = False
                
        if len(open_positions) < MAX_POSITIONS and regime_bullish:
            available = [s for s in univ.keys() if s not in open_positions]
            candidates = []
            for sym in available:
                ind = indicators[sym]
                if date_idx not in ind.index: continue
                loc = ind.index.get_loc(date_idx)
                if loc < 50: continue
                b = ind.iloc[loc]
                c = float(b['Close'])
                o = float(b['Open'])
                h = float(b['High'])
                l = float(b['Low'])
                high50 = float(b['high50'])
                rsi = float(b['rsi14'])
                mom60 = float(b['mom60'])
                adtv = float(b['adtv_cr'])
                vol_r = float(b['vol_ratio'])
                ema20 = float(b['ema20'])
                dist_ema = float(b['dist_ema20'])
                tightness = float(b['tightness_4d'])
                close_loc = (c - l) / (h - l + 1e-6)
                
                if adtv < 5.0 or c < 20.0:
                    continue
                    
                match = False
                if setup_type == 'RAW_BREAKOUT':
                    # The naive strategy: 50-day high breakout
                    if c >= high50 and vol_r >= 1.5 and rsi > 60:
                        match = True
                elif setup_type == 'COILED_VCP':
                    # Coiled spring breakout (Tightness < 5.0% + Volume Surge + Not over-extended)
                    if tightness < 5.0 and vol_r >= 1.8 and c > o and close_loc >= 0.70 and 0 <= dist_ema <= 4.0:
                        match = True
                elif setup_type == 'PULLBACK_REBOUND':
                    # Sweet-spot 20 EMA Rebound in strong uptrend
                    # Stock pulled back near 20 EMA (-1.5% to +2.0%), today green reversal with RVOL >= 1.4x
                    if -1.5 <= dist_ema <= 2.5 and c > o and vol_r >= 1.4 and rsi >= 50 and close_loc >= 0.65:
                        match = True
                        
                if match:
                    candidates.append((sym, mom60, c))
                    
            candidates.sort(key=lambda x: x[1], reverse=True)
            slots_needed = MAX_POSITIONS - len(open_positions)
            pending_buys = [sym for sym, _, _ in candidates[:slots_needed]]
            
    df_t = pd.DataFrame(trades)
    if len(df_t) == 0:
        return {"name": variant_name, "trades": 0, "win_rate": 0, "avg_ret": 0, "pf": 0}
        
    win_rate = (df_t['net_pnl'] > 0).mean() * 100
    avg_ret = df_t['ret_pct'].mean()
    avg_win = df_t[df_t['net_pnl'] > 0]['ret_pct'].mean() if len(df_t[df_t['net_pnl'] > 0]) > 0 else 0
    avg_loss = df_t[df_t['net_pnl'] <= 0]['ret_pct'].mean() if len(df_t[df_t['net_pnl'] <= 0]) > 0 else 0
    wins = df_t[df_t['net_pnl'] > 0]['net_pnl'].sum()
    losses = abs(df_t[df_t['net_pnl'] <= 0]['net_pnl'].sum())
    pf = wins / (losses + 1e-6)
    
    return {
        "name": variant_name,
        "trades": len(df_t),
        "win_rate": win_rate,
        "avg_ret": avg_ret,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "pf": pf,
        "net_pnl": df_t['net_pnl'].sum(),
        "avg_days": df_t['days'].mean()
    }

print("\n" + "="*85)
print("WIN-RATE EXPERIMENTAL SHOWDOWN: RAW BREAKOUT vs COILED VCP vs 20 EMA PULLBACK")
print("="*85)

results = []
# 1. Naive Breakout (Baseline from verify_stats)
results.append(test_strategy_variant("1. Naive 50d Breakout (+12% Tgt, No BE)", 'RAW_BREAKOUT', 12.0, None))

# 2. Breakout with Breakeven Ratchet at +4.5%
results.append(test_strategy_variant("2. 50d Breakout + Breakeven at +4.5%", 'RAW_BREAKOUT', 10.0, 4.5))

# 3. Coiled VCP Springboard (Tightness < 5% + RVOL) with +8% Quick Target
results.append(test_strategy_variant("3. Coiled VCP (+8% Target, BE at +4.0%)", 'COILED_VCP', 8.0, 4.0))

# 4. 20 EMA Sweet-Spot Rebound (+7% Target, BE at +3.5%)
results.append(test_strategy_variant("4. 20 EMA Pullback (+7% Target, BE at +3.5%)", 'PULLBACK_REBOUND', 7.0, 3.5))

# 5. 20 EMA Pullback (+10% Target, BE at +4.0%)
results.append(test_strategy_variant("5. 20 EMA Pullback (+10% Target, BE at +4.0%)", 'PULLBACK_REBOUND', 10.0, 4.0))

print(f"{'Strategy Architecture':<40} | {'Trades':<8} | {'Win Rate':<10} | {'Avg Win':<8} | {'Avg Loss':<9} | {'PF':<6} | {'Total Net P&L':<15}")
print("-" * 105)
for r in results:
    print(f"{r['name']:<40} | {r['trades']:<8} | {r['win_rate']:>5.1f}%    | +{r['avg_win']:>5.2f}% | {r['avg_loss']:>6.2f}%  | {r['pf']:>4.2f} | Rs. {r['net_pnl']:>10,.0f}")
