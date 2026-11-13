"""
TraderAI - The Free-Roll Velocity Strategy
Testing:
- T1 Quick Profit at +8% (locks profit, moves stop to entry/breakeven)
- T2 Runner at +20%
- Stop loss: -6% (Daily Close)
- Holding period: Max 21 sessions
- Slot concentration: 3 slots (33.3% each)
"""
import pickle
import pandas as pd
import numpy as np

# Load universes
hb_cache = pickle.load(open('data/cache/high_beta_universe.pkl', 'rb'))
benchmarks = pickle.load(open('data/cache/benchmarks_5y.pkl', 'rb'))

ndf = benchmarks['^NSEI'].copy()
if isinstance(ndf.columns, pd.MultiIndex):
    ndf.columns = [c[0] if isinstance(c, tuple) else c for c in ndf.columns]
ndf.index = pd.to_datetime(ndf.index)
n_close = ndf['Close'].astype(float)
n_sma50 = n_close.rolling(50).mean()

tickers = [k for k in hb_cache.keys() if k.endswith('.NS')]
clean_dfs = {}
for t in tickers:
    df = hb_cache[t].copy()
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

# Pre-index
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
    high_52w = h.rolling(250).max().shift(1)
    pct_from_52w = ((c - high_52w) / high_52w) * 100.0
    high_20 = h.rolling(20).max().shift(1)
    
    df_quick = pd.DataFrame({
        'open': o, 'high': h, 'low': l, 'close': c, 'volume': v,
        'rvol': rvol, 'high_20': high_20, 'pct_52w': pct_from_52w,
        'sma_50': sma_50, 'sma_200': sma_200
    }, index=[d.strftime('%Y-%m-%d') for d in df.index])
    date_to_bars[t] = df_quick

def simulate_strategy(quick_target=0.08, final_target=0.20, stop_pct=0.06, slots=3):
    initial_cap = 100000.0
    capital = initial_cap
    open_trades = []
    closed_trades = []
    monthly_pnl = {}

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

            # Check T1 Partial Lock (+8%)
            if not trade['partial_booked'] and cur_h >= trade['t1_px']:
                trade['partial_booked'] = True
                trade['stop_px'] = max(trade['stop_px'], trade['entry_px'] * 1.01) # move stop to breakeven +1%
                # Book 50% shares
                booked_shares = trade['shares'] // 2
                trade['shares'] -= booked_shares
                gain = (trade['t1_px'] - trade['entry_px']) * booked_shares
                friction = (trade['t1_px'] * booked_shares * 0.003) + 15.93
                net_gain = gain - friction
                capital += (trade['entry_px'] * booked_shares) + net_gain
                mo = d_str[:7]
                monthly_pnl[mo] = monthly_pnl.get(mo, 0.0) + net_gain

            # Check T2 Full Target (+20%)
            if cur_h >= trade['t2_px']:
                gain = (trade['t2_px'] - trade['entry_px']) * trade['shares']
                friction = (trade['t2_px'] * trade['shares'] * 0.003) + 15.93
                net_gain = gain - friction
                capital += (trade['entry_px'] * trade['shares']) + net_gain
                closed_trades.append({'ticker': t, 'pnl': net_gain, 'reason': 'TARGET_T2_HIT', 'date': d_str})
                mo = d_str[:7]
                monthly_pnl[mo] = monthly_pnl.get(mo, 0.0) + net_gain
                continue

            # Check Stop Loss (Daily Close)
            if cur_c < trade['stop_px']:
                pnl = (cur_c - trade['entry_px']) * trade['shares']
                friction = (cur_c * trade['shares'] * 0.003) + 15.93
                net_pnl = pnl - friction
                capital += (trade['entry_px'] * trade['shares']) + net_pnl
                reason = 'BREAKEVEN_EXIT' if trade['partial_booked'] else 'STOP_LOSS_CLOSE'
                closed_trades.append({'ticker': t, 'pnl': net_pnl, 'reason': reason, 'date': d_str})
                mo = d_str[:7]
                monthly_pnl[mo] = monthly_pnl.get(mo, 0.0) + net_pnl
                continue

            # Check Time Expiry (21 sessions)
            if trade['days_held'] >= 21:
                pnl = (cur_c - trade['entry_px']) * trade['shares']
                friction = (cur_c * trade['shares'] * 0.003) + 15.93
                net_pnl = pnl - friction
                capital += (trade['entry_px'] * trade['shares']) + net_pnl
                closed_trades.append({'ticker': t, 'pnl': net_pnl, 'reason': 'TIME_EXPIRY', 'date': d_str})
                mo = d_str[:7]
                monthly_pnl[mo] = monthly_pnl.get(mo, 0.0) + net_pnl
                continue

            remaining.append(trade)
        open_trades = remaining

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
                if b['close'] >= b['high_20'] and b['rvol'] >= 1.6 and b['pct_52w'] >= -12.0 and b['sma_50'] > b['sma_200']:
                    cands.append((t, b['rvol'], b['pct_52w']))

            cands.sort(key=lambda x: (x[1] >= 2.0, x[2]), reverse=True)
            total_equity = capital + sum(tr['entry_px'] * tr['shares'] for tr in open_trades)
            slot_alloc = total_equity / slots

            for cand in cands[:avail_slots]:
                t = cand[0]
                if next_d not in date_to_bars[t].index:
                    continue
                fill_px = date_to_bars[t].loc[next_d]['open'] * 1.002
                if fill_px <= 0:
                    continue
                shares = int(min(capital, slot_alloc) // fill_px)
                cost = shares * fill_px
                if shares >= 2 and capital >= cost:
                    capital -= cost
                    open_trades.append({
                        'ticker': t,
                        'entry_px': fill_px,
                        'shares': shares,
                        'stop_px': fill_px * (1.0 - stop_pct),
                        't1_px': fill_px * (1.0 + quick_target),
                        't2_px': fill_px * (1.0 + final_target),
                        'partial_booked': False,
                        'days_held': 0,
                    })

    df_tr = pd.DataFrame(closed_trades)
    mo_s = pd.Series(monthly_pnl)
    total_val = capital + sum(t['shares'] * t['entry_px'] for t in open_trades)
    win_pct = (df_tr['pnl'] > 0).mean() * 100 if not df_tr.empty else 0
    return {
        'final_val': total_val,
        'ret_pct': (total_val - initial_cap) / initial_cap * 100,
        'win_pct': win_pct,
        'trades': len(df_tr),
        'mo_avg': mo_s.mean(),
        'best_mo': mo_s.max(),
        'positive_months': (mo_s > 0).mean() * 100
    }

print("=== FREE-ROLL VELOCITY SIMULATION ===")
res_freeroll = simulate_strategy(quick_target=0.08, final_target=0.20, stop_pct=0.06, slots=3)
print(f"Final Capital: ₹{res_freeroll['final_val']:,.2f} (+{res_freeroll['ret_pct']:.1f}%)")
print(f"Total Trades: {res_freeroll['trades']}")
print(f"Win Rate: {res_freeroll['win_pct']:.1f}%")
print(f"Avg Monthly Profit: ₹{res_freeroll['mo_avg']:+,.2f}/mo")
print(f"Profitable Months: {res_freeroll['positive_months']:.1f}%")
print(f"Best Single Month: ₹{res_freeroll['best_mo']:+,.2f}")

