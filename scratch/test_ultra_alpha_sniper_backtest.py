"""
TraderAI - Ultra-Alpha Precision Sniper Backtest
Compares:
1. Baseline Breakout Engine (RVOL >= 1.4x, 20D Breakout)
2. Ultra-Alpha Precision Sniper (RS vs Nifty >= +10%, <= 3% of 52W High, RVOL >= 1.8x, Stage 2)
3. Ultra-Alpha Elite Sniper (RS vs Nifty >= +15%, <= 2% of 52W High, RVOL >= 2.0x, Stage 2)

Tested across 5 Years of Indian Daily Market Data (2021-2026) with:
- 3 Concentrated Slots (33.3% Capital per trade)
- Daily Close Stop Loss (-7.0%)
- Target (+20% and +25%)
- Max 21 Market Sessions Holding Ceiling
- Full Indian Statutory Friction (STT, DP Charges, GST, Stamp Duty, 0.20% Slippage)
"""
import pickle
import math
import pandas as pd
import numpy as np

# Load universes
hb_cache = pickle.load(open('data/cache/high_beta_universe.pkl', 'rb'))
broad_cache = pickle.load(open('data/cache/universe_5y.pkl', 'rb'))
benchmarks = pickle.load(open('data/cache/benchmarks_5y.pkl', 'rb'))

# Merge universes
all_cache = {**broad_cache, **hb_cache}
tickers = [k for k in all_cache.keys() if k.endswith('.NS')]

ndf = benchmarks['^NSEI'].copy()
if isinstance(ndf.columns, pd.MultiIndex):
    ndf.columns = [c[0] if isinstance(c, tuple) else c for c in ndf.columns]
ndf.index = pd.to_datetime(ndf.index)
ndf = ndf[~ndf.index.duplicated(keep='last')].sort_index()
n_close = ndf['Close'].astype(float)
n_sma50 = n_close.rolling(50).mean()
n_ema20 = n_close.ewm(span=20).mean()

# Clean and prepare stock data
clean_dfs = {}
for t in tickers:
    df = all_cache[t].copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df.columns = [str(c).capitalize() for c in df.columns]
    if not all(c in df.columns for c in ['Open', 'High', 'Low', 'Close', 'Volume']):
        continue
    df.index = pd.to_datetime(df.index)
    df = df[~df.index.duplicated(keep='last')].sort_index()
    if len(df) >= 150:
        clean_dfs[t] = df

all_dates = sorted(list(set.union(*[set(df.index) for df in clean_dfs.values()])))
date_strs = [d.strftime('%Y-%m-%d') for d in all_dates]

# Precompute indicators and index by date string
date_to_bars = {}
for t, df in clean_dfs.items():
    c = df['Close'].astype(float)
    h = df['High'].astype(float)
    l = df['Low'].astype(float)
    o = df['Open'].astype(float)
    v = df['Volume'].astype(float)

    vol_sma20 = v.rolling(20).mean()
    rvol = v / (vol_sma20 + 1e-6)
    sma_50 = c.rolling(50).mean()
    sma_200 = c.rolling(min(200, len(c))).mean()
    ema_20 = c.ewm(span=20).mean()

    high_52w = h.rolling(250).max().shift(1)
    pct_from_52w = ((c - high_52w) / high_52w) * 100.0
    high_20 = h.rolling(20).max().shift(1)

    n_aligned = n_close.reindex(df.index, method='ffill')
    rs_21 = (c.pct_change(21) - n_aligned.pct_change(21)) * 100.0

    df_quick = pd.DataFrame({
        'open': o, 'high': h, 'low': l, 'close': c, 'volume': v,
        'rvol': rvol, 'high_20': high_20, 'pct_52w': pct_from_52w,
        'sma_50': sma_50, 'sma_200': sma_200, 'ema_20': ema_20,
        'rs_21': rs_21
    }, index=[d.strftime('%Y-%m-%d') for d in df.index])
    date_to_bars[t] = df_quick

def run_backtest(
    strategy_name: str,
    rs_min: float = 0.0,
    pct_52w_min: float = -15.0,
    rvol_min: float = 1.4,
    target_pct: float = 0.20,
    stop_pct: float = 0.07,
    slots: int = 3,
    initial_cap: float = 100000.0,
):
    capital = initial_cap
    open_trades = []
    closed_trades = []
    monthly_pnl = {}
    daily_equity = []
    SLIPPAGE = 0.002

    for i, d_str in enumerate(date_strs):
        # 1. Evaluate open trades
        remaining = []
        for trade in open_trades:
            t = trade['ticker']
            if t not in date_to_bars or d_str not in date_to_bars[t].index:
                trade['days_held'] += 1
                remaining.append(trade)
                continue

            bar = date_to_bars[t].loc[d_str]
            cur_c = bar['close']
            cur_h = bar['high']
            trade['days_held'] += 1

            # Target Check
            if cur_h >= trade['target_px']:
                exit_fill = trade['target_px']
                pnl = (exit_fill - trade['entry_px']) * trade['shares']
                friction = (trade['entry_px'] * trade['shares'] * 0.002) + (exit_fill * trade['shares'] * 0.003) + 15.93
                net_pnl = pnl - friction
                capital += (trade['entry_px'] * trade['shares']) + net_pnl
                closed_trades.append({
                    'ticker': t, 'pnl': net_pnl, 'ret_pct': net_pnl / (trade['entry_px'] * trade['shares']) * 100,
                    'reason': 'TARGET_HIT', 'days': trade['days_held'], 'date': d_str
                })
                mo = d_str[:7]
                monthly_pnl[mo] = monthly_pnl.get(mo, 0.0) + net_pnl
                continue

            # Daily Close Stop Loss Check
            if cur_c < trade['stop_px']:
                exit_fill = cur_c
                pnl = (exit_fill - trade['entry_px']) * trade['shares']
                friction = (trade['entry_px'] * trade['shares'] * 0.002) + (exit_fill * trade['shares'] * 0.003) + 15.93
                net_pnl = pnl - friction
                capital += (trade['entry_px'] * trade['shares']) + net_pnl
                closed_trades.append({
                    'ticker': t, 'pnl': net_pnl, 'ret_pct': net_pnl / (trade['entry_px'] * trade['shares']) * 100,
                    'reason': 'STOP_LOSS_CLOSE', 'days': trade['days_held'], 'date': d_str
                })
                mo = d_str[:7]
                monthly_pnl[mo] = monthly_pnl.get(mo, 0.0) + net_pnl
                continue

            # Time Expiry Check (21 sessions)
            if trade['days_held'] >= 21:
                exit_fill = cur_c
                pnl = (exit_fill - trade['entry_px']) * trade['shares']
                friction = (trade['entry_px'] * trade['shares'] * 0.002) + (exit_fill * trade['shares'] * 0.003) + 15.93
                net_pnl = pnl - friction
                capital += (trade['entry_px'] * trade['shares']) + net_pnl
                closed_trades.append({
                    'ticker': t, 'pnl': net_pnl, 'ret_pct': net_pnl / (trade['entry_px'] * trade['shares']) * 100,
                    'reason': 'TIME_EXPIRY', 'days': trade['days_held'], 'date': d_str
                })
                mo = d_str[:7]
                monthly_pnl[mo] = monthly_pnl.get(mo, 0.0) + net_pnl
                continue

            remaining.append(trade)
        open_trades = remaining

        # Calculate equity
        holdings_val = sum(date_to_bars[tr['ticker']].loc[d_str]['close'] * tr['shares']
                           for tr in open_trades if tr['ticker'] in date_to_bars and d_str in date_to_bars[tr['ticker']].index)
        total_equity = capital + holdings_val
        daily_equity.append({'date': d_str, 'equity': total_equity})

        # 2. Entries if slots available
        avail_slots = slots - len(open_trades)
        dt = pd.to_datetime(d_str)
        n_ok = (n_close.loc[dt] >= n_sma50.loc[dt]) if dt in n_close.index else True

        if avail_slots > 0 and n_ok and i + 1 < len(date_strs):
            next_d = date_strs[i + 1]
            cands = []
            for t in clean_dfs.keys():
                if any(tr['ticker'] == t for tr in open_trades):
                    continue
                if t not in date_to_bars or d_str not in date_to_bars[t].index:
                    continue
                b = date_to_bars[t].loc[d_str]
                
                # Check Filters
                is_stage2 = (b['sma_50'] > b['sma_200'] and b['close'] >= b['ema_20'])
                is_breakout = (b['close'] >= b['high_20'])
                has_rvol = (b['rvol'] >= rvol_min)
                is_near_52w = (b['pct_52w'] >= pct_52w_min)
                has_rs = (b['rs_21'] >= rs_min)

                if is_stage2 and is_breakout and has_rvol and is_near_52w and has_rs:
                    # Ranking score: prioritizes higher RS and higher RVOL
                    score = b['rs_21'] * 2.0 + b['rvol'] * 10.0 + (100.0 + b['pct_52w'])
                    cands.append((t, score, b['rvol'], b['rs_21']))

            cands.sort(key=lambda x: x[1], reverse=True)
            slot_alloc = total_equity / slots

            for cand in cands[:avail_slots]:
                t = cand[0]
                if next_d not in date_to_bars[t].index:
                    continue
                next_bar = date_to_bars[t].loc[next_d]
                fill_px = next_bar['open'] * (1.0 + SLIPPAGE)
                if fill_px <= 0:
                    continue
                shares = int(min(capital, slot_alloc) // fill_px)
                cost = shares * fill_px
                if shares > 0 and capital >= cost:
                    capital -= cost
                    open_trades.append({
                        'ticker': t,
                        'entry_px': fill_px,
                        'shares': shares,
                        'stop_px': fill_px * (1.0 - stop_pct),
                        'target_px': fill_px * (1.0 + target_pct),
                        'days_held': 0,
                    })

    df_tr = pd.DataFrame(closed_trades)
    mo_s = pd.Series(monthly_pnl)
    total_val = capital + sum(t['shares'] * t['entry_px'] for t in open_trades)
    win_pct = (df_tr['pnl'] > 0).mean() * 100 if not df_tr.empty else 0.0
    wins = df_tr[df_tr['pnl'] > 0]
    losses = df_tr[df_tr['pnl'] <= 0]
    total_gain = wins['pnl'].sum() if not wins.empty else 0.0
    total_loss = abs(losses['pnl'].sum()) if not losses.empty else 1.0
    profit_factor = total_gain / total_loss if total_loss > 0 else 0.0

    eq_df = pd.DataFrame(daily_equity)
    eq_df['peak'] = eq_df['equity'].cummax()
    eq_df['dd'] = (eq_df['equity'] - eq_df['peak']) / eq_df['peak'] * 100.0
    max_dd = eq_df['dd'].min()

    num_months = len(mo_s)
    cagr = ((total_val / initial_cap) ** (12.0 / max(12, num_months)) - 1.0) * 100.0

    return {
        'strategy': strategy_name,
        'final_val': total_val,
        'ret_pct': (total_val - initial_cap) / initial_cap * 100.0,
        'cagr': cagr,
        'win_pct': win_pct,
        'trades': len(df_tr),
        'profit_factor': profit_factor,
        'max_dd': max_dd,
        'mo_avg_inr': mo_s.mean(),
        'mo_avg_pct': mo_s.mean() / (initial_cap) * 100.0,
        'best_mo_inr': mo_s.max(),
        'pos_months_pct': (mo_s > 0).mean() * 100.0,
    }

print("Running Backtest Suite across 5 Years of Indian Daily Market Data...")

configs = [
    ("1. Baseline Breakout (RVOL>=1.4, Broad)", 0.0, -15.0, 1.4, 0.20),
    ("2. High-Beta Apex Core (RVOL>=1.6, 52W<12%)", 0.0, -12.0, 1.6, 0.20),
    ("3. Ultra-Alpha Sniper (RS>=+10%, 52W<5%, RVOL>=1.8)", 10.0, -5.0, 1.8, 0.20),
    ("4. Ultra-Alpha Sniper + 25% Target", 10.0, -5.0, 1.8, 0.25),
    ("5. Elite Apex Sniper (RS>=+15%, 52W<3%, RVOL>=2.0, +25% Target)", 15.0, -3.0, 2.0, 0.25),
]

results = []
for name, rs, p52, rv, tp in configs:
    res = run_backtest(name, rs_min=rs, pct_52w_min=p52, rvol_min=rv, target_pct=tp, slots=3)
    results.append(res)

print("\n" + "=" * 125)
print(f"{'Strategy Configuration':<48} | {'Final Capital':<13} | {'Return %':<9} | {'CAGR %':<7} | {'Win %':<6} | {'Trades':<6} | {'PF':<5} | {'MaxDD':<7} | {'Avg Mo INR':<10}")
print("=" * 125)

for r in results:
    print(f"{r['strategy']:<48} | ₹{r['final_val']:>11,.0f} | {r['ret_pct']:>7.1f}% | {r['cagr']:>5.1f}% | {r['win_pct']:>5.1f}% | {r['trades']:>6} | {r['profit_factor']:>4.2f} | {r['max_dd']:>6.1f}% | ₹{r['mo_avg_inr']:>+8,.0f}")
print("=" * 125)

