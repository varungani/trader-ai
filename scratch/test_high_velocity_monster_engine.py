"""
TraderAI - High-Velocity Asymmetric Monster Engine (4-Year Wealth Compounding)
=============================================================================
Tests the ultimate high-compounding swing trading model:
1. Fast Cut Stagnation: Cut trades after 4 sessions if dead (< 1.0% gain)
2. Asymmetric Scaling: Sell 1/3 at +12%, trail remaining 2/3 by 10 EMA (catch +30% to +80% runs)
3. High Capital Deployment: 85-90% invested during confirmed market uptrends (3-4 concentrated slots)
4. Reinvestment of all profits (aggressive dynamic compounding)
5. Simulates 4-Year Super-Cycle (2020-2024) and Full 10-Year History (2016-2026)
"""
import os, sys, pickle, numpy as np, pandas as pd

if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.costs import compute_indian_delivery_costs

with open("data/cache/universe_10y.pkl", "rb") as f:
    univ = pickle.load(f)
with open("data/cache/benchmarks_10y.pkl", "rb") as f:
    bm = pickle.load(f)

nifty_df = bm['^NSEI'].copy()
nifty_df['sma50'] = nifty_df['Close'].rolling(50).mean()
nifty_df['ema20'] = nifty_df['Close'].ewm(span=20, adjust=False).mean()

def enrich_stock(df):
    res = df.copy()
    c, h, l, v, o = res["Close"], res["High"], res["Low"], res["Volume"], res["Open"]
    res["ema10"] = c.ewm(span=10, adjust=False).mean()
    res["ema20"] = c.ewm(span=20, adjust=False).mean()
    res["sma50"] = c.rolling(50).mean()
    res["sma200"] = c.rolling(200).mean()
    
    res["vol_sma20"] = v.rolling(20).mean()
    res["rvol"] = v / res["vol_sma20"].replace(0, np.nan)
    res["high20"] = h.rolling(20).max().shift(1)
    
    # Range tightness
    r_5d = h.rolling(5).max() - l.rolling(5).min()
    r_20d = h.rolling(20).max() - l.rolling(20).min()
    res["vcp_ratio"] = r_5d / r_20d.replace(0, np.nan)
    
    # 6-month and 3-month momentum
    res["ret_6m"] = (c - c.shift(125)) / c.shift(125)
    res["ret_3m"] = (c - c.shift(63)) / c.shift(63)
    
    # Close in top 25% of day range
    day_rng = (h - l).replace(0, np.nan)
    res["close_pctile"] = (c - l) / day_rng
    return res

indicators = {s: enrich_stock(df) for s, df in univ.items()}

def run_wealth_engine(start_date="2020-01-01", end_date="2024-12-31", init_capital=30000.0, max_pos=3):
    dates = nifty_df.loc[start_date:end_date].index
    cash = init_capital
    open_positions = {}
    closed_trades = []
    daily_equity = []
    
    for i in range(len(dates)):
        date_idx = dates[i]
        date_str = str(date_idx.date())
        nifty_bar = nifty_df.loc[date_idx]
        nifty_c = float(nifty_bar['Close'])
        nifty_sma50 = float(nifty_bar['sma50']) if not np.isnan(nifty_bar['sma50']) else 0.0
        nifty_ema20 = float(nifty_bar['ema20']) if not np.isnan(nifty_bar['ema20']) else 0.0
        
        # Exits
        to_close = []
        for sym, pos in open_positions.items():
            ind = indicators[sym]
            if date_idx not in ind.index:
                pos['days_held'] += 1
                continue
            bar = ind.loc[date_idx]
            o_px, h_px, l_px, c_px = float(bar['Open']), float(bar['High']), float(bar['Low']), float(bar['Close'])
            ema10 = float(bar['ema10'])
            pos['days_held'] += 1
            
            # Step 1: Partial Scale-Out at +12% (Sell 35%, lock in profit & move stop to entry + 1%)
            if not pos.get('tp1_hit', False):
                if h_px >= pos['entry_price'] * 1.12:
                    pos['tp1_hit'] = True
                    sell_qty = int(pos['qty'] * 0.35)
                    if sell_qty > 0:
                        costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=pos['entry_price'] * 1.12, quantity=sell_qty)
                        closed_trades.append({
                            'ticker': sym, 'year': date_idx.year, 'reason': 'TP1_SCALE_35PCT',
                            'net_pnl': costs.net_pnl_rupees, 'gain_pct': 12.0, 'days_held': pos['days_held']
                        })
                        cash += (sell_qty * pos['entry_price'] * 1.12) - costs.total_friction_rupees
                        pos['qty'] -= sell_qty
                        # Raise stop to breakeven + 1.5%
                        pos['stop_loss'] = max(pos['stop_loss'], pos['entry_price'] * 1.015)
                        
            exit_reason = None
            exit_px = 0.0
            
            # Hard stop
            if l_px <= pos['stop_loss']:
                exit_reason = 'STOP_LOSS'
                exit_px = min(pos['stop_loss'], o_px)
            # Runner exit: Close below 10 EMA after TP1 has been secured
            elif pos.get('tp1_hit', False) and c_px < ema10:
                exit_reason = 'RUNNER_EMA10_CROSS'
                exit_px = c_px
            # Fast Cut: If trade hasn't gained at least 1.0% by session 4, cut it immediately!
            elif not pos.get('tp1_hit', False) and pos['days_held'] >= 4 and ((c_px - pos['entry_price']) / pos['entry_price']) < 0.01:
                exit_reason = 'FAST_CUT_4D'
                exit_px = c_px
            # Maximum hold 30 days
            elif pos['days_held'] >= 30:
                exit_reason = 'TIME_STOP_30D'
                exit_px = c_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=exit_px, quantity=pos['qty'])
                closed_trades.append({
                    'ticker': sym, 'year': date_idx.year, 'reason': exit_reason,
                    'net_pnl': costs.net_pnl_rupees, 'gain_pct': ((exit_px - pos['entry_price'])/pos['entry_price'])*100.0,
                    'days_held': pos['days_held']
                })
                cash += (pos['qty'] * exit_px) - costs.total_friction_rupees
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        invested = sum(pos['qty'] * (float(indicators[sym].loc[date_idx, 'Close']) if date_idx in indicators[sym].index else pos['entry_price']) for sym, pos in open_positions.items())
        total_equity = cash + invested
        daily_equity.append({'date': date_idx, 'year': date_idx.year, 'year_month': date_str[:7], 'equity': total_equity})
        
        # Absolute Macro Regime Protection: If Nifty < 50 SMA, cash preservation!
        if nifty_c < nifty_sma50:
            continue
            
        # Entry Logic: High-Conviction Breakout on Leaders
        if len(open_positions) < max_pos:
            candidates = []
            for sym, ind in indicators.items():
                if sym in open_positions or date_idx not in ind.index:
                    continue
                bar = ind.loc[date_idx]
                c_px, o_px, h_px, l_px, v_px = float(bar['Close']), float(bar['Open']), float(bar['High']), float(bar['Low']), float(bar['Volume'])
                sma50 = float(bar['sma50']) if not np.isnan(bar['sma50']) else 0.0
                sma200 = float(bar['sma200']) if not np.isnan(bar['sma200']) else 0.0
                rvol = float(bar['rvol']) if not np.isnan(bar['rvol']) else 1.0
                high20 = float(bar['high20']) if not np.isnan(bar['high20']) else 0.0
                vcp = float(bar['vcp_ratio']) if not np.isnan(bar['vcp_ratio']) else 1.0
                ret_6m = float(bar['ret_6m']) if not np.isnan(bar['ret_6m']) else 0.0
                ret_3m = float(bar['ret_3m']) if not np.isnan(bar['ret_3m']) else 0.0
                close_pctile = float(bar['close_pctile']) if not np.isnan(bar['close_pctile']) else 0.5
                
                # Minimum leader trend: Stage 2 + 6M leader + 3M leader
                if c_px <= sma50 or sma50 <= sma200 or ret_6m <= 0.10:
                    continue
                    
                # Setup: VCP contraction (<= 0.65) OR High Volume Thrust breaking 20D high
                if (vcp <= 0.65 or close_pctile >= 0.75) and rvol >= 1.8 and c_px >= high20 * 0.995:
                    score = rvol * 3.0 + (ret_6m * 3.0) + (ret_3m * 2.0)
                    candidates.append((sym, score, c_px))
                    
            candidates.sort(key=lambda x: x[1], reverse=True)
            slots_free = max_pos - len(open_positions)
            
            # High Capital Deployment: 85-90% deployed in top 3 slots (30% per slot)
            slot_budget = total_equity * 0.30
            
            for sym, score, entry_px in candidates[:slots_free]:
                alloc = min(cash, slot_budget)
                qty = int(alloc // entry_px)
                if qty > 0 and cash >= (qty * entry_px):
                    cash -= (qty * entry_px)
                    open_positions[sym] = {
                        'entry_price': entry_px, 'qty': qty,
                        'stop_loss': round(entry_px * 0.955, 2), # strict 4.5% stop
                        'days_held': 0, 'entry_date': date_str, 'tp1_hit': False
                    }
                    
    df_tr = pd.DataFrame(closed_trades)
    df_eq = pd.DataFrame(daily_equity)
    df_eq['peak'] = df_eq['equity'].cummax()
    df_eq['dd'] = (df_eq['equity'] - df_eq['peak']) / df_eq['peak'] * 100.0
    
    final_eq = df_eq['equity'].iloc[-1]
    net_pnl = final_eq - init_capital
    ret_pct = (net_pnl / init_capital) * 100.0
    max_dd = df_eq['dd'].min()
    wr = len(df_tr[df_tr['net_pnl'] > 0]) / len(df_tr) * 100.0
    pf = df_tr[df_tr['net_pnl'] > 0]['net_pnl'].sum() / abs(df_tr[df_tr['net_pnl'] <= 0]['net_pnl'].sum())
    
    # Big runs
    huge_wins = len(df_tr[df_tr['gain_pct'] >= 20.0])
    max_gain = df_tr['gain_pct'].max()
    avg_hold = df_tr['days_held'].mean()
    
    # Monthly returns
    df_eq['year_month'] = df_eq['date'].apply(lambda d: str(d.date())[:7])
    m_snaps = df_eq.groupby('year_month').last()
    m_ret = (m_snaps['equity'] - m_snaps['equity'].shift(1).fillna(init_capital)) / m_snaps['equity'].shift(1).fillna(init_capital) * 100.0
    
    # Yearly P&L
    yearly = df_tr.groupby('year')['net_pnl'].sum()
    
    return {
        'start_date': start_date, 'end_date': end_date, 'trades': len(df_tr),
        'wr': wr, 'final_equity': final_eq, 'net_pnl': net_pnl, 'ret_pct': ret_pct,
        'pf': pf, 'max_dd': max_dd, 'huge_wins': huge_wins, 'max_gain': max_gain,
        'avg_hold': avg_hold, 'avg_mo_pct': m_ret.mean(), 'best_mo_pct': m_ret.max(),
        'worst_mo_pct': m_ret.min(), 'yearly': yearly
    }

print("="*95)
print("TEST 1: THE 4-YEAR WEALTH RUN (2020 TO 2024 SUPER-CYCLE | RS 30,000 START)")
print("="*95)
r_4y = run_wealth_engine(start_date="2020-01-01", end_date="2024-12-31", init_capital=30000.0)
print(f"Total Trades:        {r_4y['trades']}")
print(f"Win Rate:            {r_4y['wr']:.1f}%")
print(f"Average Hold Period: {r_4y['avg_hold']:.1f} trading days (Rapid Turnover)")
print(f"Final Account Value: Rs {r_4y['final_equity']:,.2f} on Rs 30,000 start")
print(f"Total Net Return:    {r_4y['ret_pct']:+.1f}% ({r_4y['final_equity']/30000.0:.2f}x your money in 4 years!)")
print(f"Profit Factor:       {r_4y['pf']:.2f}")
print(f"Max Drawdown:        {r_4y['max_dd']:.1f}%")
print(f"Monster Trades >20%: {r_4y['huge_wins']} trades | Largest Single Win: {r_4y['max_gain']:+.1f}%")
print(f"Average Month:       {r_4y['avg_mo_pct']:+.2f}% per month")
print(f"Best Month:          {r_4y['best_mo_pct']:+.1f}%")
print(f"Worst Month:         {r_4y['worst_mo_pct']:+.1f}%")
print("\nYearly Net Profits:")
for yr, pnl in r_4y['yearly'].items():
    print(f"  Year {yr}: Rs {pnl:+,.2f}")

print("\n" + "="*95)
print("TEST 2: FULL 10-YEAR STRESS TEST (2016 TO 2026 | INCLUDING 2018 BEAR & 2025 CHOP)")
print("="*95)
r_10y = run_wealth_engine(start_date="2016-10-24", end_date="2026-10-16", init_capital=30000.0)
print(f"Total Trades:        {r_10y['trades']}")
print(f"Win Rate:            {r_10y['wr']:.1f}%")
print(f"Final Account Value: Rs {r_10y['final_equity']:,.2f} on Rs 30,000 start")
print(f"Total Net Return:    {r_10y['ret_pct']:+.1f}% ({r_10y['final_equity']/30000.0:.2f}x total growth)")
print(f"Profit Factor:       {r_10y['pf']:.2f}")
print(f"Max Drawdown:        {r_10y['max_dd']:.1f}%")
print(f"Monster Trades >20%: {r_10y['huge_wins']} trades | Largest Single Win: {r_10y['max_gain']:+.1f}%")
