"""
TraderAI - Elite Apex Sniper: Static +25% Exit vs Dynamic Trailing Runner
Tests whether letting the Elite Apex leaders ride yields significantly higher compounding.
"""
import pickle
import pandas as pd
import numpy as np

# Load universes
hb_cache = pickle.load(open('data/cache/high_beta_universe.pkl', 'rb'))
broad_cache = pickle.load(open('data/cache/universe_5y.pkl', 'rb'))
benchmarks = pickle.load(open('data/cache/benchmarks_5y.pkl', 'rb'))

all_cache = {**broad_cache, **hb_cache}
tickers = [k for k in all_cache.keys() if k.endswith('.NS')]

ndf = benchmarks['^NSEI'].copy()
if isinstance(ndf.columns, pd.MultiIndex):
    ndf.columns = [c[0] if isinstance(c, tuple) else c for c in ndf.columns]
ndf.index = pd.to_datetime(ndf.index)
n_close = ndf['Close'].astype(float)
n_sma50 = n_close.rolling(50).mean()

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

# Precompute bars
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
    ema_10 = c.ewm(span=10).mean()
    ema_20 = c.ewm(span=20).mean()

    high_52w = h.rolling(250).max().shift(1)
    pct_from_52w = ((c - high_52w) / high_52w) * 100.0
    high_20 = h.rolling(20).max().shift(1)

    n_aligned = n_close.reindex(df.index, method='ffill')
    rs_21 = (c.pct_change(21) - n_aligned.pct_change(21)) * 100.0

    df_quick = pd.DataFrame({
        'open': o, 'high': h, 'low': l, 'close': c, 'volume': v,
        'rvol': rvol, 'high_20': high_20, 'pct_52w': pct_from_52w,
        'sma_50': sma_50, 'sma_200': sma_200, 'ema_10': ema_10, 'ema_20': ema_20,
        'rs_21': rs_21
    }, index=[d.strftime('%Y-%m-%d') for d in df.index])
    date_to_bars[t] = df_quick

def run_simulation(mode="STATIC_25", slots=3, initial_cap=100000.0):
    capital = initial_cap
    open_trades = []
    closed_trades = []
    monthly_pnl = {}
    daily_equity = []
    SLIPPAGE = 0.002

    for i, d_str in enumerate(date_strs):
        # 1. Manage open trades
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
            ema10 = bar['ema_10']
            trade['days_held'] += 1

            exit_reason = None
            exit_fill = cur_c

            if mode == "STATIC_25":
                if cur_h >= trade['target_px']:
                    exit_reason = "TARGET_25_HIT"
                    exit_fill = trade['target_px']
                elif cur_c < trade['stop_px']:
                    exit_reason = "STOP_LOSS_CLOSE"
                    exit_fill = cur_c
                elif trade['days_held'] >= 21:
                    exit_reason = "TIME_EXPIRY_21D"
                    exit_fill = cur_c

            elif mode == "DYNAMIC_RUNNER":
                # If gained >= 20%, activate runner mode: lock +8% profit floor and trail with EMA 10
                if cur_h >= trade['entry_px'] * 1.20:
                    trade['is_runner'] = True
                    trade['stop_px'] = max(trade['stop_px'], trade['entry_px'] * 1.08)

                if trade.get('is_runner', False):
                    # In runner mode: trail with 10 EMA (daily close basis)
                    trade['stop_px'] = max(trade['stop_px'], round(ema10, 2))
                    # Allow holding up to 42 sessions (~2 months) as long as 10 EMA holds
                    if cur_c < trade['stop_px']:
                        exit_reason = "RUNNER_EMA10_TRAIL_EXIT"
                        exit_fill = cur_c
                    elif trade['days_held'] >= 42:
                        exit_reason = "MAX_RUNNER_EXPIRY_42D"
                        exit_fill = cur_c
                else:
                    # Normal trade exit
                    if cur_c < trade['stop_px']:
                        exit_reason = "STOP_LOSS_CLOSE"
                        exit_fill = cur_c
                    elif trade['days_held'] >= 21:
                        exit_reason = "TIME_EXPIRY_21D"
                        exit_fill = cur_c

            if exit_reason:
                pnl = (exit_fill - trade['entry_px']) * trade['shares']
                friction = (trade['entry_px'] * trade['shares'] * 0.002) + (exit_fill * trade['shares'] * 0.003) + 15.93
                net_pnl = pnl - friction
                capital += (trade['entry_px'] * trade['shares']) + net_pnl
                closed_trades.append({
                    'ticker': t, 'pnl': net_pnl, 'ret_pct': net_pnl / (trade['entry_px'] * trade['shares']) * 100,
                    'reason': exit_reason, 'days': trade['days_held'], 'date': d_str
                })
                mo = d_str[:7]
                monthly_pnl[mo] = monthly_pnl.get(mo, 0.0) + net_pnl
            else:
                remaining.append(trade)

        open_trades = remaining

        # Calculate equity
        holdings_val = sum(date_to_bars[tr['ticker']].loc[d_str]['close'] * tr['shares']
                           for tr in open_trades if tr['ticker'] in date_to_bars and d_str in date_to_bars[tr['ticker']].index)
        total_equity = capital + holdings_val
        daily_equity.append({'date': d_str, 'equity': total_equity})

        # 2. Entries: Elite Sniper Filter (RS >= 15%, 52W < 3%, RVOL >= 2.0x, Stage 2)
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
                
                is_stage2 = (b['sma_50'] > b['sma_200'] and b['close'] >= b['ema_20'])
                is_breakout = (b['close'] >= b['high_20'])
                has_rvol = (b['rvol'] >= 2.0)
                is_near_52w = (b['pct_52w'] >= -3.0)
                has_rs = (b['rs_21'] >= 15.0)

                if is_stage2 and is_breakout and has_rvol and is_near_52w and has_rs:
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
                        'stop_px': fill_px * 0.93, # 7% stop
                        'target_px': fill_px * 1.25, # 25% target
                        'is_runner': False,
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
        'mode': mode,
        'final_val': total_val,
        'ret_pct': (total_val - initial_cap) / initial_cap * 100.0,
        'cagr': cagr,
        'win_pct': win_pct,
        'trades': len(df_tr),
        'profit_factor': profit_factor,
        'max_dd': max_dd,
        'mo_avg_inr': mo_s.mean(),
        'best_mo_inr': mo_s.max(),
        'pos_months_pct': (mo_s > 0).mean() * 100.0,
        'trades_df': df_tr,
    }

print("Running Comparison: Static +25% Target vs Dynamic Runner...")
res_static = run_simulation("STATIC_25", slots=3)
res_runner = run_simulation("DYNAMIC_RUNNER", slots=3)

print("\n" + "=" * 115)
print(f"{'Strategy Mode':<30} | {'Final Capital':<13} | {'Return %':<9} | {'CAGR %':<7} | {'Win %':<6} | {'PF':<5} | {'MaxDD':<7} | {'Best Month':<12}")
print("=" * 115)
for r in [res_static, res_runner]:
    print(f"{r['mode']:<30} | ₹{r['final_val']:>11,.0f} | {r['ret_pct']:>7.1f}% | {r['cagr']:>5.1f}% | {r['win_pct']:>5.1f}% | {r['profit_factor']:>4.2f} | {r['max_dd']:>6.1f}% | ₹{r['best_mo_inr']:>+10,.0f}")
print("=" * 115)

# Inspect top 10 winning trades from Dynamic Runner
runner_wins = res_runner['trades_df'].sort_values('ret_pct', ascending=False).head(10)
print("\nTop 10 Winning Trades under Dynamic Runner Mode:")
for _, tr in runner_wins.iterrows():
    print(f"  {tr['ticker']:<14} | Gain: {tr['ret_pct']:>+6.1f}% | PnL: ₹{tr['pnl']:>+8,.0f} | Days: {tr['days']:>2} | Date: {tr['date']} | Exit: {tr['reason']}")

