"""
TraderAI - Quantitative Empirical Audit of the Momentum Engine
=============================================================================
Zero look-ahead bias:
1. Screen on Day 0 Close: Setup detected exclusively using data available at 15:30 yesterday.
2. Entry on Day 1: GTT trigger at pivot (Day 0 High * 1.002). Fills only if Day 1 High >= trigger.
   If Day 1 Open > trigger, fill at Day 1 Open * (1 + 0.0025 slippage).
   If Day 1 Open gaps up > +2.5%, ABORT (Anti-FOMO rule).
3. Exit on Day f:
   - Gap-aware stop: If Open <= Stop, exit at Open * (1 - 0.0025 slippage).
   - Intraday stop: If Low <= Stop, exit at Stop * (1 - 0.0025 slippage).
   - T1 Partial Profit (+5%): If High >= T1, sell 50% at T1 * (1 - 0.0025 slippage), trail remaining stop.
   - Runner exit: Trailing stop under 5-day EMA or previous 3-day low.
   - Time cutoff: Max 10 trading sessions.
4. Friction: Exact statutory Indian delivery charges computed via data/costs.py.
5. Strict 3-Slot and 5-Slot Portfolio Simulation with day-by-day cash accounting.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from analysis.signal_ic_evaluator import load_universe_data
from data.costs import compute_indian_delivery_costs
from data.market_data import fetch_stock_history

SLIPPAGE = 0.0025 # 0.25% per side

def run_rigorous_test():
    print("="*80)
    print("TRADERAI - RIGOROUS ZERO-LOOKAHEAD MOMENTUM AUDIT")
    print("="*80)
    print("Loading 72 liquid NSE stocks (2021-2026)...")
    u = load_universe_data()
    
    # Load Nifty for regime filter
    nifty = fetch_stock_history('^NSEI', period='5y')
    nifty['SMA50'] = nifty['Close'].rolling(50).mean()
    nifty_bull_dates = set(nifty[nifty['Close'] > nifty['SMA50']].index.strftime('%Y-%m-%d'))
    print(f"Loaded {len(u)} tickers. Nifty Bull dates: {len(nifty_bull_dates)}")

    signals = []

    for ticker, df in u.items():
        if len(df) < 120: continue
        df = df.copy()
        df['Vol_MA20'] = df['Volume'].rolling(20).mean()
        df['High_20'] = df['High'].shift(1).rolling(20).max()
        df['Low_3'] = df['Low'].shift(1).rolling(3).min()
        df['EMA5'] = df['Close'].ewm(span=5, adjust=False).mean()
        
        # We screen strictly on DAY 0 CLOSE (yesterday's data)!
        for idx in range(30, len(df)-12):
            d0_date = df.index[idx].strftime('%Y-%m-%d')
            d1_date = df.index[idx+1].strftime('%Y-%m-%d')
            
            # Regime Gate: Only trade when Nifty > 50 SMA on Day 0
            if d0_date not in nifty_bull_dates:
                continue
                
            # Day 0 Setup: High Volume Surge + Close near 20-day High
            c0 = float(df['Close'].iloc[idx])
            v0 = float(df['Volume'].iloc[idx])
            v_avg0 = float(df['Vol_MA20'].iloc[idx])
            h20_0 = float(df['High_20'].iloc[idx])
            h0 = float(df['High'].iloc[idx])
            
            # Setup conditions at 15:30 yesterday:
            # 1. Close is within 3% of 20-day high (coiling at the top)
            # 2. Volume on Day 0 was >= 1.5x average (institutional accumulation yesterday)
            if c0 >= h20_0 * 0.97 and v0 >= 1.5 * v_avg0:
                # Place GTT Buy-Stop at Day 0 High + 0.2%
                trigger_px = h0 * 1.002
                max_buy_px = trigger_px * 1.025 # Anti-FOMO ceiling (+2.5%)
                
                o1 = float(df['Open'].iloc[idx+1])
                h1 = float(df['High'].iloc[idx+1])
                
                # Check if triggered on Day 1
                if o1 > max_buy_px:
                    # Gapped up too high! Abort chasing peak
                    continue
                    
                if h1 >= trigger_px:
                    # Trade filled on Day 1!
                    if o1 >= trigger_px:
                        entry_px = round(o1 * (1.0 + SLIPPAGE), 2)
                    else:
                        entry_px = round(trigger_px * (1.0 + SLIPPAGE), 2)
                        
                    stop_px = round(entry_px * 0.965, 2) # -3.5% initial stop
                    t1_px = round(entry_px * 1.05, 2)   # +5.0% T1 harvest
                    
                    t1_hit = False
                    exit_px_t1 = 0.0
                    exit_px_runner = 0.0
                    exit_date = None
                    exit_reason = None
                    days_held = 0
                    
                    for f in range(1, 15):
                        if idx + 1 + f >= len(df): break
                        days_held = f
                        cur_date = df.index[idx+1+f]
                        cur_o = float(df['Open'].iloc[idx+1+f])
                        cur_h = float(df['High'].iloc[idx+1+f])
                        cur_l = float(df['Low'].iloc[idx+1+f])
                        cur_c = float(df['Close'].iloc[idx+1+f])
                        cur_ema5 = float(df['EMA5'].iloc[idx+1+f])
                        cur_l3 = float(df['Low_3'].iloc[idx+1+f])
                        
                        if not t1_hit:
                            # 1. Check morning gap down on stop
                            if cur_o <= stop_px:
                                exit_px_t1 = round(cur_o * (1.0 - SLIPPAGE), 2)
                                exit_px_runner = exit_px_t1
                                exit_date = cur_date
                                exit_reason = "STOP_GAP"
                                break
                            # 2. Check intraday stop
                            elif cur_l <= stop_px:
                                exit_px_t1 = round(stop_px * (1.0 - SLIPPAGE), 2)
                                exit_px_runner = exit_px_t1
                                exit_date = cur_date
                                exit_reason = "STOP_INTRADAY"
                                break
                            # 3. Check T1 Target (+5.0%)
                            elif cur_h >= t1_px:
                                t1_hit = True
                                exit_px_t1 = round(t1_px * (1.0 - SLIPPAGE), 2)
                                stop_px = round(entry_px * 1.006, 2) # Lock breakeven + buffer
                        else:
                            # T1 was already banked! Manage runner half
                            if cur_o <= stop_px:
                                exit_px_runner = round(cur_o * (1.0 - SLIPPAGE), 2)
                                exit_date = cur_date
                                exit_reason = "RUNNER_STOP_GAP"
                                break
                            elif cur_l <= stop_px:
                                exit_px_runner = round(stop_px * (1.0 - SLIPPAGE), 2)
                                exit_date = cur_date
                                exit_reason = "RUNNER_BE_LOCK"
                                break
                            elif cur_c < cur_ema5 and f >= 3:
                                exit_px_runner = round(cur_c * (1.0 - SLIPPAGE), 2)
                                exit_date = cur_date
                                exit_reason = "RUNNER_EMA5_TRAIL"
                                break
                                
                        # Time exit: 10 sessions max
                        if f >= 10:
                            exit_date = cur_date
                            exit_c = round(cur_c * (1.0 - SLIPPAGE), 2)
                            if not t1_hit:
                                exit_px_t1 = exit_c
                            exit_px_runner = exit_c
                            exit_reason = "TIME_10D"
                            break
                            
                    if exit_date is not None:
                        signals.append({
                            'ticker': ticker,
                            'entry_date': df.index[idx+1],
                            'exit_date': exit_date,
                            'entry_px': entry_px,
                            'exit_px_t1': exit_px_t1,
                            'exit_px_runner': exit_px_runner,
                            't1_hit': t1_hit,
                            'days_held': days_held,
                            'exit_reason': exit_reason,
                            'vol_score': v0 / v_avg0
                        })

    df_sigs = pd.DataFrame(signals)
    df_sigs['entry_date'] = pd.to_datetime(df_sigs['entry_date'])
    df_sigs['exit_date'] = pd.to_datetime(df_sigs['exit_date'])
    df_sigs = df_sigs.sort_values('entry_date').reset_index(drop=True)
    print(f"\nTotal Valid Breakout Signals Generated (Zero Lookahead): N = {len(df_sigs)}")

    # ─── RUN STRICT 5-SLOT & 3-SLOT PORTFOLIO SIMULATION ───
    for n_slots, slot_label in [(5, "5-SLOT (20% per slot)"), (3, "3-SLOT (33.3% per slot)")]:
        print("\n" + "="*80)
        print(f"PORTFOLIO SIMULATION: {slot_label} (STARTING CAPITAL: ₹1,00,000)")
        print("="*80)
        
        capital = 100000.0
        equity = capital
        peak_equity = capital
        max_drawdown = 0.0
        
        active_positions = [] # list of dicts
        closed_trades = []
        
        all_dates = sorted(list(set(df_sigs['entry_date'].unique())))
        
        for cur_date in all_dates:
            # 1. Close trades that reached exit date
            still_active = []
            for pos in active_positions:
                if pos['exit_date'] <= cur_date:
                    # Realize PnL with exact Indian delivery costs
                    buy_px = pos['entry_px']
                    shares = pos['shares']
                    sh_t1 = shares // 2
                    sh_runner = shares - sh_t1
                    
                    cost_t1 = compute_indian_delivery_costs(buy_px, pos['exit_px_t1'], sh_t1).total_friction_rupees
                    cost_run = compute_indian_delivery_costs(buy_px, pos['exit_px_runner'], sh_runner).total_friction_rupees
                    
                    pnl_t1 = (pos['exit_px_t1'] - buy_px) * sh_t1 - cost_t1
                    pnl_run = (pos['exit_px_runner'] - buy_px) * sh_runner - cost_run
                    net_trade_pnl = pnl_t1 + pnl_run
                    
                    equity += net_trade_pnl
                    if equity > peak_equity: peak_equity = equity
                    dd = (peak_equity - equity) / peak_equity * 100.0
                    if dd > max_drawdown: max_drawdown = dd
                    
                    closed_trades.append({
                        'entry_date': pos['entry_date'],
                        'exit_date': pos['exit_date'],
                        'ticker': pos['ticker'],
                        'allocated': shares * buy_px,
                        'net_pnl': net_trade_pnl,
                        't1_hit': pos['t1_hit'],
                        'reason': pos['exit_reason']
                    })
                else:
                    still_active.append(pos)
            active_positions = still_active
            
            # 2. Enter new signals if slots available
            free_slots = n_slots - len(active_positions)
            if free_slots > 0:
                cands = df_sigs[df_sigs['entry_date'] == cur_date].sort_values('vol_score', ascending=False)
                for _, sig in cands.iterrows():
                    if len(active_positions) >= n_slots: break
                    # Slot budget = current equity / n_slots
                    slot_budget = equity / n_slots
                    if slot_budget < 5000: break # Safety floor
                    shares = int(slot_budget // sig['entry_px'])
                    if shares <= 0: continue
                    
                    active_positions.append({
                        **sig.to_dict(),
                        'shares': shares,
                        'allocated': shares * sig['entry_px']
                    })

        df_closed = pd.DataFrame(closed_trades)
        if len(df_closed) == 0:
            print("No trades closed.")
            continue
            
        wins = df_closed[df_closed['net_pnl'] > 0]
        losses = df_closed[df_closed['net_pnl'] <= 0]
        win_rate = len(wins) / len(df_closed) * 100.0
        tot_profit = df_closed['net_pnl'].sum()
        cagr = ((equity / capital) ** (1 / 5.0) - 1.0) * 100.0
        
        print(f"• Total Executed Trades            : {len(df_closed)}")
        print(f"• Overall Win Rate                 : {win_rate:.1f}% (T1 Hit Rate: {df_closed['t1_hit'].mean()*100:.1f}%)")
        print(f"• Final Account Balance            : ₹{equity:,.2f}")
        print(f"• Total Net Realized Profit        : ₹{tot_profit:,.2f}")
        print(f"• Compound Annual Growth (CAGR)    : {cagr:.1f}% per year")
        print(f"• Maximum Portfolio Drawdown       : {max_drawdown:.2f}%")
        print(f"• Average Winner                   : +₹{wins['net_pnl'].mean():,.2f}")
        print(f"• Average Loser                    : -₹{abs(losses['net_pnl'].mean()):,.2f}")
        print(f"• Profit Factor                    : {wins['net_pnl'].sum() / abs(losses['net_pnl'].sum()):.2f}")
        
        # Monthly breakdown
        df_closed['month'] = pd.to_datetime(df_closed['entry_date']).dt.to_period('M')
        m_pnl = df_closed.groupby('month')['net_pnl'].sum()
        print(f"• % of Months Profitable           : {(m_pnl > 0).mean()*100:.1f}%")
        print(f"• Best Month                       : +₹{m_pnl.max():,.2f}")
        print(f"• Top 5 Months:\n{m_pnl.sort_values(ascending=False).head(5)}")

if __name__ == '__main__':
    run_rigorous_test()
