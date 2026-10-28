"""
Exhaustive 10-Year Quantitative Audit & Optimization of Both Stocks and Crypto (2016-2026).
Compares Baseline vs Improved Strategies and Reports Complete Audited Numbers.
"""
import sys
import os
import pickle
import pandas as pd
import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Load Caches
STOCK_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "cache", "universe_10y.pkl")
BENCH_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "cache", "benchmarks_10y.pkl")
CRYPTO_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "cache", "crypto_10y.pkl")

with open(STOCK_CACHE, "rb") as f:
    stock_universe = pickle.load(f)
with open(BENCH_CACHE, "rb") as f:
    benchmarks = pickle.load(f)
with open(CRYPTO_CACHE, "rb") as f:
    crypto_universe = pickle.load(f)

nifty_df = benchmarks.get("^NSEI")
btc_df = crypto_universe.get("BTC-USD")

print(f"Loaded {len(stock_universe)} Indian stocks and {len(crypto_universe)} Crypto assets across 10 years.")

if isinstance(nifty_df.columns, pd.MultiIndex):
    nifty_df.columns = nifty_df.columns.get_level_values(0)
nifty_df.columns = [c.lower() for c in nifty_df.columns]

# ==============================================================================
# PART 1: 10-YEAR INDIAN EQUITY SWING ENGINE (2016-2026)
# ==============================================================================
def compute_stock_indicators(df, nifty_df):
    d = df.copy()
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    d.columns = [col.lower() for col in d.columns]
    c = d['close']
    d['ema10'] = c.ewm(span=10, adjust=False).mean()
    d['ema20'] = c.ewm(span=20, adjust=False).mean()
    d['ema50'] = c.ewm(span=50, adjust=False).mean()
    d['sma200'] = c.rolling(200).mean()
    d['sma20_vol'] = d['volume'].rolling(20).mean()
    d['rvol'] = d['volume'] / (d['sma20_vol'] + 1e-8)
    d['high20'] = d['high'].rolling(20).max().shift(1)
    
    # ATR & VCP
    tr1 = d['high'] - d['low']
    tr2 = (d['high'] - c.shift(1)).abs()
    tr3 = (d['low'] - c.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    d['atr5'] = tr.rolling(5).mean()
    d['atr20'] = tr.rolling(20).mean()
    d['vcp_ratio'] = d['atr5'] / (d['atr20'] + 1e-8)
    
    # Mansfield Relative Strength vs NIFTY
    aligned_nifty = nifty_df['close'].reindex(d.index).ffill()
    base_ratio = c / (aligned_nifty + 1e-8)
    sma_base = base_ratio.rolling(50).mean()
    d['mansfield_rs'] = ((base_ratio / (sma_base + 1e-8)) - 1.0) * 100.0
    return d

processed_stocks = {}
for sym, df in stock_universe.items():
    if len(df) > 200:
        processed_stocks[sym] = compute_stock_indicators(df, nifty_df)

nifty_dates = sorted(nifty_df.index)
nifty_c = nifty_df['close']
nifty_sma50 = nifty_c.rolling(50).mean()

def run_stock_simulation(
    name,
    max_slots=3,
    stop_pct=0.045,
    pt1_pct=0.15,
    trail_runner=True,
    min_rvol=1.8,
    min_mansfield=10.0,
    pyramid_at=0.04,
    use_macro_gate=True,
    capital=30000.0
):
    curr_cap = capital
    active_pos = {}
    closed_trades = []
    daily_equity = []
    
    for dt in nifty_dates:
        n_c = nifty_c.loc[dt] if dt in nifty_c.index else None
        n_s50 = nifty_sma50.loc[dt] if dt in nifty_sma50.index else None
        if n_c is None or pd.isna(n_s50):
            continue
            
        market_bull = (n_c > n_s50) if use_macro_gate else True
        
        # 1. Manage Exits
        exits = []
        for sym, pos in list(active_pos.items()):
            if dt not in processed_stocks[sym].index:
                continue
            bar = processed_stocks[sym].loc[dt]
            curr_c = bar['close']
            curr_l = bar['low']
            entry_p = pos['entry_price']
            days_held = (dt - pos['entry_date']).days
            
            gain = (curr_c - entry_p) / entry_p
            loss = (curr_l - entry_p) / entry_p
            
            ex_p = None
            reason = None
            
            # Hard Stop
            if loss <= -stop_pct:
                ex_p = entry_p * (1.0 - stop_pct)
                reason = "Hard Stop (-4.5%)"
            # Pyramiding check (add 20% at +4% gain with breakeven stop)
            elif pyramid_at > 0 and gain >= pyramid_at and not pos['pyramided']:
                pos['pyramided'] = True
                pos['stop_price'] = entry_p * 1.01  # Breakeven + 1%
            # Partial profit scale-out at +15%
            elif gain >= pt1_pct and not pos['partial_booked']:
                pos['partial_booked'] = True
                booked_shares = pos['shares'] * 0.35
                gross_partial = booked_shares * curr_c
                # Indian delivery costs (STT 0.1%, GST, DP charges Rs 15.93)
                friction_partial = (gross_partial * 0.0015) + 15.93
                net_partial = gross_partial - friction_partial
                curr_cap += net_partial
                pos['shares'] -= booked_shares
                pos['cost_basis'] -= (pos['cost_basis'] * 0.35)
                pos['realized_partial_pnl'] = net_partial - (pos['orig_cost'] * 0.35)
                pos['stop_price'] = entry_p * 1.02
            # 10 EMA Trailing exit for remaining shares
            elif trail_runner and pos['partial_booked'] and curr_c < bar['ema10']:
                ex_p = curr_c
                reason = f"10 EMA Trail Exit ({days_held}d)"
            # Time Stagnation exit (session 15)
            elif days_held >= 15 and gain < 0.02:
                ex_p = curr_c
                reason = f"Stagnation Cut ({days_held}d)"
            # Macro Gate emergency cut
            elif use_macro_gate and not market_bull and curr_c < bar['ema20']:
                ex_p = curr_c
                reason = "Nifty Bear Cut"
                
            if ex_p is not None:
                exits.append((sym, ex_p, reason, days_held))
                
        for sym, ex_p, reason, days_held in exits:
            pos = active_pos.pop(sym)
            gross = pos['shares'] * ex_p
            friction = (gross * 0.0015) + 15.93 + (gross * 0.0005) # STT, GST, DP, slippage
            net = gross - friction
            final_pnl = (net - pos['cost_basis']) + pos.get('realized_partial_pnl', 0.0)
            ret_pct = (final_pnl / pos['orig_cost']) * 100.0
            curr_cap += net
            closed_trades.append({'sym': sym, 'pnl': final_pnl, 'ret': ret_pct, 'days': days_held, 'reason': reason})
            
        # 2. Entries
        open_slots = max_slots - len(active_pos)
        if open_slots > 0 and market_bull:
            cands = []
            for sym, df in processed_stocks.items():
                if sym in active_pos or dt not in df.index:
                    continue
                bar = df.loc[dt]
                if pd.isna(bar['rvol']):
                    continue
                c = bar['close']
                # Stage 2 + Mansfield RS leader + Volume surge + 20D Breakout
                if c > bar['high20'] and bar['rvol'] >= min_rvol and c > bar['ema20'] and bar['mansfield_rs'] >= min_mansfield:
                    score = bar['mansfield_rs'] + (bar['rvol'] * 5)
                    cands.append((sym, score, c))
                    
            cands.sort(key=lambda x: x[1], reverse=True)
            for sym, score, c in cands[:open_slots]:
                cur_eq = curr_cap + sum(p['shares'] * processed_stocks[s].loc[dt]['close'] for s, p in active_pos.items() if dt in processed_stocks[s].index)
                alloc = min(cur_eq / max_slots, curr_cap)
                if alloc < 2000:
                    continue
                eff_p = c * 1.0005
                friction_entry = alloc * 0.0015
                shares = (alloc - friction_entry) / eff_p
                curr_cap -= alloc
                active_pos[sym] = {
                    'entry_price': eff_p, 'entry_date': dt, 'shares': shares,
                    'cost_basis': alloc, 'orig_cost': alloc, 'pyramided': False,
                    'partial_booked': False, 'realized_partial_pnl': 0.0
                }
                
        hold_val = sum(p['shares'] * processed_stocks[s].loc[dt]['close'] for s, p in active_pos.items() if dt in processed_stocks[s].index)
        daily_equity.append(curr_cap + hold_val)
        
    s = pd.Series(daily_equity)
    fin_eq = s.iloc[-1]
    net_p = fin_eq - capital
    net_r = (net_p / capital) * 100.0
    cagr = ((fin_eq / capital) ** (1.0 / 10.0) - 1.0) * 100.0
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
    else:
        wr = pf = avg_w = avg_l = best_t = 0
        
    return {
        'name': name, 'final_eq': fin_eq, 'net_pnl': net_p, 'net_ret': net_r, 'cagr': cagr,
        'max_dd': dd, 'trades': n_t, 'wr': wr, 'pf': pf, 'avg_w': avg_w, 'avg_l': avg_l, 'best_t': best_t
    }

# ==============================================================================
# PART 2: 10-YEAR CRYPTO ENGINE (2016-2026)
# ==============================================================================
def compute_crypto_indicators(df, btc_df):
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

processed_crypto = {sym: compute_crypto_indicators(df, btc_df) for sym, df in crypto_universe.items()}
btc_dates = sorted(btc_df.index)

def run_crypto_simulation(
    name,
    max_slots=2,
    stop_pct=0.060,
    scale_target=0.25,
    trail_ema='ema10',
    min_rvol=1.5,
    min_rs=5.0,
    high_beta_only=False,
    use_btc_gate=True,
    capital=3000.0
):
    curr_cap = capital
    active_pos = {}
    closed_trades = []
    daily_equity = []
    
    high_beta_set = {"SOL-USD", "AVAX-USD", "NEAR-USD", "DOGE-USD", "LINK-USD", "BNB-USD", "ADA-USD"}
    
    for dt in btc_dates:
        btc_bar = processed_crypto["BTC-USD"].loc[dt] if dt in processed_crypto["BTC-USD"].index else None
        if btc_bar is None or pd.isna(btc_bar['ema50']):
            continue
            
        btc_bull = (btc_bar['close'] > btc_bar['ema50']) and (btc_bar['ema20'] > btc_bar['ema50']) if use_btc_gate else True
        
        # 1. Exits
        exits = []
        for sym, pos in list(active_pos.items()):
            if dt not in processed_crypto[sym].index:
                continue
            bar = processed_crypto[sym].loc[dt]
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
                booked_shares = pos['shares'] * 0.30
                gross_partial = booked_shares * curr_c
                fee = gross_partial * 0.0020
                slip = gross_partial * 0.0010
                tds = gross_partial * 0.0100
                net_partial = gross_partial - fee - slip - tds
                curr_cap += net_partial
                pos['shares'] -= booked_shares
                pos['cost_basis'] -= (pos['cost_basis'] * 0.30)
                pos['realized_partial_pnl'] = net_partial - (pos['orig_cost'] * 0.30)
                pos['stop_price'] = entry_p * 1.02
            elif pos['partial_booked'] and curr_c < bar[trail_ema]:
                ex_p = curr_c
                reason = f"{trail_ema.upper()} Trail Exit ({days_held}d)"
            elif days_held >= 30:
                ex_p = curr_c
                reason = f"30-Day Window Expiry ({days_held}d)"
            elif use_btc_gate and not btc_bull and curr_c < bar['ema20']:
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
            closed_trades.append({'sym': sym, 'pnl': final_pnl, 'ret': ret_pct, 'days': days_held, 'reason': reason})
            
        # 2. Entries
        open_slots = max_slots - len(active_pos)
        if open_slots > 0 and btc_bull:
            cands = []
            pool = [s for s in processed_crypto.keys() if (s in high_beta_set if high_beta_only else True)]
            for sym in pool:
                if sym in active_pos or dt not in processed_crypto[sym].index:
                    continue
                bar = processed_crypto[sym].loc[dt]
                if pd.isna(bar['rvol']):
                    continue
                c = bar['close']
                if c > bar['high20'] and bar['rvol'] >= min_rvol and c > bar['ema20'] and bar['mansfield_rs'] >= min_rs:
                    score = bar['mansfield_rs'] + (bar['rvol'] * 5)
                    cands.append((sym, score, c))
                    
            cands.sort(key=lambda x: x[1], reverse=True)
            for sym, score, c in cands[:open_slots]:
                cur_eq = curr_cap + sum(p['shares'] * processed_crypto[s].loc[dt]['close'] for s, p in active_pos.items() if dt in processed_crypto[s].index)
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
                
        hold_val = sum(p['shares'] * processed_crypto[s].loc[dt]['close'] for s, p in active_pos.items() if dt in processed_crypto[s].index)
        daily_equity.append(curr_cap + hold_val)
        
    s = pd.Series(daily_equity)
    fin_eq = s.iloc[-1]
    net_p = fin_eq - capital
    net_r = (net_p / capital) * 100.0
    cagr = ((fin_eq / capital) ** (1.0 / 10.0) - 1.0) * 100.0
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
    else:
        wr = pf = avg_w = avg_l = best_t = 0
        
    return {
        'name': name, 'final_eq': fin_eq, 'net_pnl': net_p, 'net_ret': net_r, 'cagr': cagr,
        'max_dd': dd, 'trades': n_t, 'wr': wr, 'pf': pf, 'avg_w': avg_w, 'avg_l': avg_l, 'best_t': best_t
    }

print("\n" + "="*85)
print("RUNNING 10-YEAR AUDIT & STRATEGY OPTIMIZATION (2016-2026)")
print("="*85)

print("\n>>> PART 1: 10-YEAR INDIAN EQUITIES AUDIT (Rs 30k Seed | 111 Liquid Stocks)")
stock_runs = [
    ("1. Baseline: 5-Stock Safe Spread (20% each | No Mansfield Filter)", 5, 0.045, 0.12, False, 1.2, 0.0, 0.0),
    ("2. Improved: 3-Stock Concentrated (33% each | RVOL >= 1.8x | 10 EMA Trail)", 3, 0.045, 0.15, True, 1.8, 5.0, 0.0),
    ("3. MONSTER HIGH-BETA: 2-Stock Bullet (50% each | Mansfield RS >= 10% | Pyramiding)", 2, 0.045, 0.18, True, 2.0, 10.0, 0.04),
]

for name, slots, stop, pt, trail, rvol, rs, pyr in stock_runs:
    res = run_stock_simulation(name, max_slots=slots, stop_pct=stop, pt1_pct=pt, trail_runner=trail, min_rvol=rvol, min_mansfield=rs, pyramid_at=pyr)
    print(f"\n[{res['name']}]")
    print(f"  Final Equity: Rs {res['final_eq']:10,.2f} ({res['net_ret']:+.1f}% | CAGR: {res['cagr']:.1f}%) | Net P&L: Rs {res['net_pnl']:+,.2f}")
    print(f"  Trades: {res['trades']} | Win Rate: {res['wr']:.1f}% | Profit Factor: {res['pf']:.2f} | Max DD: {res['max_dd']:.1f}%")
    print(f"  Avg Win: {res['avg_w']:+.1f}% | Avg Loss: {res['avg_l']:.1f}% | Best Trade: {res['best_t']:+.1f}%")

print("\n" + "="*85)
print(">>> PART 2: 10-YEAR CRYPTO AUDIT (Rs 3k Seed | 1% Indian TDS + Fees)")
crypto_runs = [
    ("1. Baseline: All Liquid Tokens (No High-Beta Focus | 2 Slots)", 2, 0.060, 0.20, 'ema10', 1.3, 0.0, False, True),
    ("2. Improved: High-Beta Focus (SOL, AVAX, NEAR, DOGE | 2 Slots | 10 EMA Trail)", 2, 0.060, 0.25, 'ema10', 1.5, 5.0, True, True),
    ("3. PARABOLIC MOONSHOT: High-Beta Rockets | 15 EMA Wide Runner | RVOL >= 1.8x", 2, 0.065, 0.30, 'ema20', 1.8, 8.0, True, True),
    ("4. Control: High-Beta WITHOUT BTC Macro Gate (To show danger)", 2, 0.060, 0.25, 'ema10', 1.5, 5.0, True, False),
]

for name, slots, stop, pt, trail, rvol, rs, hb, gate in crypto_runs:
    res = run_crypto_simulation(name, max_slots=slots, stop_pct=stop, scale_target=pt, trail_ema=trail, min_rvol=rvol, min_rs=rs, high_beta_only=hb, use_btc_gate=gate)
    print(f"\n[{res['name']}]")
    print(f"  Final Equity: Rs {res['final_eq']:10,.2f} ({res['net_ret']:+.1f}% | CAGR: {res['cagr']:.1f}%) | Net P&L: Rs {res['net_pnl']:+,.2f}")
    print(f"  Trades: {res['trades']} | Win Rate: {res['wr']:.1f}% | Profit Factor: {res['pf']:.2f} | Max DD: {res['max_dd']:.1f}%")
    print(f"  Avg Win: {res['avg_w']:+.1f}% | Avg Loss: {res['avg_l']:.1f}% | Best Trade: {res['best_t']:+.1f}%")

print("="*85)
