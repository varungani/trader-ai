"""
TraderAI - Verification of Apex High-Velocity 3-Slot Engine
Runs full backtest across historical market regimes with:
- 3 Slots (33.3% Capital per position)
- Daily Closing Stop at 7.0%
- Target Profit Lock at +20.0%
- Maximum Holding Limit: 21 Market Sessions (1 Month)
- Realistic Statutory Friction (DP Charges, STT, GST, Stamp Duty, Slippage)
"""
import pickle
import pandas as pd
import numpy as np

# Load universes
hb_cache = pickle.load(open('data/cache/high_beta_universe.pkl', 'rb'))
broad_cache = pickle.load(open('data/cache/universe_5y.pkl', 'rb'))

def run_simulation(cache_dict, slots=3, target_pct=0.20, stop_pct=0.07, max_hold=21, initial_cap=100000.0):
    # Normalize data
    tickers = [k for k in cache_dict.keys() if k.endswith('.NS')]
    clean_dfs = {}
    for t in tickers:
        df = cache_dict[t].copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df.columns = [str(c).capitalize() for c in df.columns]
        if not all(c in df.columns for c in ['Open', 'High', 'Low', 'Close', 'Volume']):
            continue
        df.index = pd.to_datetime(df.index)
        df = df[~df.index.duplicated(keep='last')].sort_index()
        if len(df) >= 100:
            clean_dfs[t] = df

    all_dates = sorted(list(set.union(*[set(df.index) for df in clean_dfs.values()])))
    date_strs = [d.strftime('%Y-%m-%d') for d in all_dates]
    
    # Pre-index by date string
    date_to_bars = {}
    for t, df in clean_dfs.items():
        # Precompute indicators
        c = df['Close'].astype(float)
        v = df['Volume'].astype(float)
        h = df['High'].astype(float)
        l = df['Low'].astype(float)
        o = df['Open'].astype(float)
        
        rvol = v / (v.rolling(20).mean() + 1e-6)
        high_20 = h.shift(1).rolling(20).max()
        high_52w = h.shift(1).rolling(252, min_periods=60).max()
        pct_from_52w = (c - high_52w) / high_52w
        
        # Pre-pack daily row info
        df_quick = pd.DataFrame({
            'open': o, 'high': h, 'low': l, 'close': c, 'volume': v,
            'rvol': rvol, 'high_20': high_20, 'pct_52w': pct_from_52w
        }, index=[d.strftime('%Y-%m-%d') for d in df.index])
        date_to_bars[t] = df_quick

    capital = initial_cap
    open_trades = []
    closed_trades = []
    daily_equity = []
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
            
            # Check Target (+20%)
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
            
            # Check Daily Close Stop Loss (-7%)
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
            
            # Check 1-Month Max Hold (21 sessions)
            if trade['days_held'] >= max_hold:
                exit_fill = cur_c
                pnl = (exit_fill - trade['entry_px']) * trade['shares']
                friction = (trade['entry_px'] * trade['shares'] * 0.002) + (exit_fill * trade['shares'] * 0.003) + 15.93
                net_pnl = pnl - friction
                capital += (trade['entry_px'] * trade['shares']) + net_pnl
                closed_trades.append({
                    'ticker': t, 'pnl': net_pnl, 'ret_pct': net_pnl / (trade['entry_px'] * trade['shares']) * 100,
                    'reason': 'MAX_1_MONTH_EXPIRY', 'days': trade['days_held'], 'date': d_str
                })
                mo = d_str[:7]
                monthly_pnl[mo] = monthly_pnl.get(mo, 0.0) + net_pnl
                continue
            
            remaining.append(trade)
        open_trades = remaining
        
        # 2. Open new trades if slots available
        avail_slots = slots - len(open_trades)
        if avail_slots > 0 and i + 1 < len(date_strs):
            next_d = date_strs[i + 1]
            candidates = []
            for t in clean_dfs.keys():
                if any(tr['ticker'] == t for tr in open_trades):
                    continue
                if t not in date_to_bars or d_str not in date_to_bars[t].index:
                    continue
                b = date_to_bars[t].loc[d_str]
                # Breakout signal
                if b['close'] > b['high_20'] and b['rvol'] >= 1.4:
                    candidates.append((t, b['rvol'], b['pct_52w']))
            
            # Sort by RVOL and 52W high proximity
            candidates.sort(key=lambda x: (x[1] >= 1.8, x[2]), reverse=True)
            
            total_equity = capital + sum(tr['entry_px'] * tr['shares'] for tr in open_trades)
            slot_alloc = total_equity / slots
            for cand in candidates[:avail_slots]:
                t = cand[0]
                if next_d not in date_to_bars[t].index:
                    continue
                next_bar = date_to_bars[t].loc[next_d]
                fill_px = next_bar['open'] * 1.002  # Slippage
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

    # Summary metrics
    df_trades = pd.DataFrame(closed_trades)
    total_net_pnl = df_trades['pnl'].sum() if not df_trades.empty else 0.0
    win_rate = (df_trades['pnl'] > 0).mean() * 100 if not df_trades.empty else 0.0
    mo_series = pd.Series(monthly_pnl)
    
    return {
        'final_capital': capital + sum(t['shares'] * t['entry_px'] for t in open_trades),
        'total_pnl': total_net_pnl,
        'trade_count': len(df_trades),
        'win_rate': win_rate,
        'mo_avg_inr': mo_series.mean() if not mo_series.empty else 0.0,
        'mo_win_pct': (mo_series > 0).mean() * 100 if not mo_series.empty else 0.0,
        'best_month': mo_series.max() if not mo_series.empty else 0.0,
    }

print("=== APEX 3-SLOT ENGINE BACKTEST VERIFICATION ===")
hb_res = run_simulation(hb_cache, slots=3, target_pct=0.20, stop_pct=0.07, max_hold=21)
print(f"High-Beta 3-Slot Engine (Starting ₹1 Lakh):")
print(f"  Final Capital:    ₹{hb_res['final_capital']:,.2f} (+{(hb_res['final_capital']-100000)/1000:.1f}%)")
print(f"  Total Trades:     {hb_res['trade_count']}")
print(f"  Win Rate:         {hb_res['win_rate']:.1f}%")
print(f"  Avg Monthly PnL:  ₹{hb_res['mo_avg_inr']:+,.2f}/mo ({hb_res['mo_avg_inr']/1000:+.1f}% on ₹1L initial)")
print(f"  Profitable Months:{hb_res['mo_win_pct']:.1f}%")
print(f"  Best Single Month:₹{hb_res['best_month']:+,.2f}")
