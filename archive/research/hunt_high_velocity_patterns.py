"""
TraderAI - High-Velocity Short-Term Pattern Discovery & Compounding Engine
========================================================================
Explores new high-thrust patterns designed for pure short-term swing trading:
1. Pattern A: 52-Week High Base Breakout (Multi-month base, RVOL >= 2.0x)
2. Pattern B: Stage 2 Oversold Snapback (RSI14 <= 38 bouncing off 50 SMA)
3. Pattern C: Power Play / High Tight Flag (Strong momentum followed by 3-5D contraction)
4. Dynamic Compounding: Reinvesting profits instead of static Rs 10k allocation.
"""
import os, sys, pickle, numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.costs import compute_indian_delivery_costs

with open("data/cache/universe_10y.pkl", "rb") as f:
    univ = pickle.load(f)
with open("data/cache/benchmarks_10y.pkl", "rb") as f:
    bm = pickle.load(f)

nifty_df = bm['^NSEI'].copy()
nifty_df['sma50'] = nifty_df['Close'].rolling(50).mean()

def enrich_stock(df):
    res = df.copy()
    c, h, l, v, o = res["Close"], res["High"], res["Low"], res["Volume"], res["Open"]
    res["ema10"] = c.ewm(span=10, adjust=False).mean()
    res["ema20"] = c.ewm(span=20, adjust=False).mean()
    res["sma50"] = c.rolling(50).mean()
    res["sma200"] = c.rolling(200).mean()
    
    tr1 = h - l
    tr2 = (h - c.shift(1)).abs()
    tr3 = (l - c.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    res["atr14"] = tr.rolling(14).mean()
    
    res["vol_sma20"] = v.rolling(20).mean()
    res["rvol"] = v / res["vol_sma20"].replace(0, np.nan)
    
    # 52-Week High (250 sessions)
    res["high52w"] = h.rolling(250).max().shift(1)
    res["dist_52w_pct"] = ((c - res["high52w"]) / res["high52w"]) * 100.0
    
    # Base tight range (15-day range / 50-day range)
    range_15d = h.rolling(15).max() - l.rolling(15).min()
    range_50d = h.rolling(50).max() - l.rolling(50).min()
    res["base_tightness"] = range_15d / range_50d.replace(0, np.nan)
    
    # RSI 14
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    res["rsi14"] = 100 - (100 / (1 + rs))
    
    # Trailing 15-day return
    res["ret_15d"] = (c - c.shift(15)) / c.shift(15) * 100.0
    # 3-day contraction range
    res["range_3d_pct"] = (h.rolling(3).max() - l.rolling(3).min()) / c * 100.0
    return res

indicators = {s: enrich_stock(df) for s, df in univ.items()}

def test_pattern(pattern_name="52W_BREAKOUT", compound=True, target_pct=0.15, stop_pct=0.045, max_pos=3, init_capital=30000.0):
    dates = nifty_df.loc["2016-10-24":"2026-10-16"].index
    cash = init_capital
    portfolio_equity = init_capital
    open_positions = {}
    closed_trades = []
    daily_equity = []
    
    for i in range(len(dates)):
        date_idx = dates[i]
        date_str = str(date_idx.date())
        nifty_bar = nifty_df.loc[date_idx]
        nifty_c = float(nifty_bar['Close'])
        nifty_sma50 = float(nifty_bar['sma50']) if not np.isnan(nifty_bar['sma50']) else 0.0
        
        # Exits
        to_close = []
        for sym, pos in open_positions.items():
            ind = indicators[sym]
            if date_idx not in ind.index:
                pos['days_held'] += 1
                continue
            bar = ind.loc[date_idx]
            o_px, h_px, l_px, c_px = float(bar['Open']), float(bar['High']), float(bar['Low']), float(bar['Close'])
            pos['days_held'] += 1
            
            exit_reason = None
            exit_px = 0.0
            
            if l_px <= pos['stop_loss']:
                exit_reason = 'STOP_LOSS'
                exit_px = min(pos['stop_loss'], o_px)
            elif h_px >= pos['target']:
                exit_reason = 'TARGET_HIT'
                exit_px = pos['target']
            elif pos['days_held'] >= 8 and abs((c_px - pos['entry_price']) / pos['entry_price']) <= 0.015:
                # 8-day tight stagnation exit to recycle capital fast
                exit_reason = 'STAGNATION_8D'
                exit_px = c_px
            elif pos['days_held'] >= 15:
                # 15-day swing limit
                exit_reason = 'TIME_STOP_15D'
                exit_px = c_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=exit_px, quantity=pos['qty'])
                closed_trades.append({
                    'ticker': sym, 'year': date_idx.year, 'entry_px': pos['entry_price'], 'exit_px': exit_px,
                    'qty': pos['qty'], 'days_held': pos['days_held'], 'reason': exit_reason,
                    'net_pnl': costs.net_pnl_rupees, 'friction': costs.total_friction_rupees,
                    'ret_pct': costs.net_pnl_pct
                })
                cash += (pos['qty'] * exit_px) - costs.total_friction_rupees
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        invested = sum(pos['qty'] * (float(indicators[sym].loc[date_idx, 'Close']) if date_idx in indicators[sym].index else pos['entry_price']) for sym, pos in open_positions.items())
        portfolio_equity = cash + invested
        daily_equity.append({'date': date_idx, 'year_month': date_str[:7], 'equity': portfolio_equity, 'invested': invested})
        
        # Macro Gate
        if nifty_c < nifty_sma50:
            continue
            
        if len(open_positions) < max_pos:
            candidates = []
            for sym, ind in indicators.items():
                if sym in open_positions or date_idx not in ind.index:
                    continue
                bar = ind.loc[date_idx]
                c_px, o_px, h_px, l_px = float(bar['Close']), float(bar['Open']), float(bar['High']), float(bar['Low'])
                sma50 = float(bar['sma50']) if not np.isnan(bar['sma50']) else 0.0
                sma200 = float(bar['sma200']) if not np.isnan(bar['sma200']) else 0.0
                ema10 = float(bar['ema10']) if not np.isnan(bar['ema10']) else 0.0
                ema20 = float(bar['ema20']) if not np.isnan(bar['ema20']) else 0.0
                rvol = float(bar['rvol']) if not np.isnan(bar['rvol']) else 1.0
                high52w = float(bar['high52w']) if not np.isnan(bar['high52w']) else 0.0
                dist_52w = float(bar['dist_52w_pct']) if not np.isnan(bar['dist_52w_pct']) else -99.0
                tightness = float(bar['base_tightness']) if not np.isnan(bar['base_tightness']) else 1.0
                rsi = float(bar['rsi14']) if not np.isnan(bar['rsi14']) else 50.0
                ret_15d = float(bar['ret_15d']) if not np.isnan(bar['ret_15d']) else 0.0
                range_3d = float(bar['range_3d_pct']) if not np.isnan(bar['range_3d_pct']) else 10.0
                
                if pattern_name == "52W_BREAKOUT":
                    # Pattern 1: 52-Week High Base Breakout
                    # Price within 2% of 52W high, base is tight (<= 0.55), explosion volume >= 1.8x
                    if c_px > sma50 > sma200 and dist_52w >= -2.0 and tightness <= 0.60 and rvol >= 1.8 and c_px > o_px:
                        score = rvol * 3.0 + (1.0 - tightness) * 10.0
                        candidates.append((sym, score, c_px))
                        
                elif pattern_name == "STAGE2_PULLBACK_SNAPBACK":
                    # Pattern 2: Deep Oversold Pullback Snapback
                    # In strong Stage 2 (50 SMA > 200 SMA), stock pulls back deeply to 50 SMA with RSI <= 42,
                    # prints a bullish hammer/engulfing candle (Close > Open)
                    if sma50 > sma200 and l_px <= sma50 * 1.02 and c_px >= sma50 * 0.98 and rsi <= 45 and c_px > o_px and rvol >= 1.2:
                        score = (50.0 - rsi) * 2.0 + rvol
                        candidates.append((sym, score, c_px))
                        
                elif pattern_name == "POWER_PLAY_FLAG":
                    # Pattern 3: High Tight Flag / Power Play
                    # Stock moved +15% to +35% over last 15 days, consolidated tightly (3D range <= 4.0%),
                    # now breaking out above 10 EMA with volume >= 1.5x
                    if ret_15d >= 12.0 and range_3d <= 4.5 and c_px > ema10 and c_px > o_px and rvol >= 1.5:
                        score = ret_15d + rvol * 2.0
                        candidates.append((sym, score, c_px))
                        
            candidates.sort(key=lambda x: x[1], reverse=True)
            slots_free = max_pos - len(open_positions)
            
            # Sizing: Compounding vs Static
            current_total_equity = cash + sum(pos['qty'] * pos['entry_price'] for pos in open_positions.values())
            slot_budget = (current_total_equity / max_pos) if compound else (init_capital / max_pos)
            
            for sym, score, entry_px in candidates[:slots_free]:
                alloc = min(cash, slot_budget)
                qty = int(alloc // entry_px)
                if qty > 0 and cash >= (qty * entry_px):
                    cash -= (qty * entry_px)
                    open_positions[sym] = {
                        'entry_price': entry_px, 'qty': qty,
                        'stop_loss': round(entry_px * (1.0 - stop_pct), 2),
                        'target': round(entry_px * (1.0 + target_pct), 2),
                        'days_held': 0, 'entry_date': date_str
                    }
                    
    df_tr = pd.DataFrame(closed_trades)
    df_eq = pd.DataFrame(daily_equity)
    if df_tr.empty:
        return None
        
    wins = df_tr[df_tr['net_pnl'] > 0]
    wr = len(wins) / len(df_tr) * 100.0
    tot_pnl = df_tr['net_pnl'].sum()
    gross_pnl = (df_tr['exit_px'] * df_tr['qty'] - df_tr['entry_px'] * df_tr['qty']).sum()
    friction = df_tr['friction'].sum()
    pf = wins['net_pnl'].sum() / abs(df_tr[df_tr['net_pnl'] <= 0]['net_pnl'].sum())
    
    df_eq['peak'] = df_eq['equity'].cummax()
    df_eq['dd'] = (df_eq['equity'] - df_eq['peak']) / df_eq['peak'] * 100.0
    max_dd = df_eq['dd'].min()
    final_eq = df_eq['equity'].iloc[-1]
    
    # Monthly P&L
    df_eq['year_month'] = df_eq['date'].apply(lambda d: str(d.date())[:7])
    m_snaps = df_eq.groupby('year_month').last()
    m_ret = (m_snaps['equity'] - m_snaps['equity'].shift(1).fillna(init_capital)) / m_snaps['equity'].shift(1).fillna(init_capital) * 100.0
    m_pnl = m_snaps['equity'] - m_snaps['equity'].shift(1).fillna(init_capital)
    
    avg_hold = df_tr['days_held'].mean()
    
    return {
        'pattern': pattern_name, 'compound': compound, 'trades': len(df_tr), 'wr': wr,
        'final_equity': final_eq, 'tot_pnl': tot_pnl, 'ret_pct': ((final_eq - init_capital) / init_capital) * 100.0,
        'pf': pf, 'dd': max_dd, 'avg_hold': avg_hold, 'friction': friction,
        'avg_mo_pct': m_ret.mean(), 'best_mo_pct': m_ret.max(), 'worst_mo_pct': m_ret.min(),
        'win_months': (m_pnl > 0).sum(), 'tot_months': len(m_pnl)
    }

print("="*95)
print("EXPLORING HIGH-VELOCITY SHORT-TERM SWING PATTERNS & DYNAMIC COMPOUNDING (10 YEARS | 111 STOCKS)")
print("="*95)

patterns = [
    ("52W_BREAKOUT", "52-Week High Tight Base Breakout (Multi-month base, RVOL >= 1.8x)"),
    ("STAGE2_PULLBACK_SNAPBACK", "Deep Oversold Snapback in Stage 2 (RSI <= 45 near 50 SMA)"),
    ("POWER_PLAY_FLAG", "High Tight Flag Power Play (+15% surge, 3D tight flag <= 4%)")
]

for pat_id, pat_desc in patterns:
    print(f"\n>>> Pattern: {pat_desc}")
    # Static allocation (fixed Rs 10k)
    r_static = test_pattern(pattern_name=pat_id, compound=False, target_pct=0.14, stop_pct=0.045)
    if r_static:
        print(f"    [Static Rs 10k Sizing] Trades: {r_static['trades']:3d} | WR: {r_static['wr']:4.1f}% | Avg Hold: {r_static['avg_hold']:4.1f}d | Net P&L: Rs {r_static['tot_pnl']:+8.1f} ({r_static['ret_pct']:+5.1f}%) | PF: {r_static['pf']:4.2f} | DD: {r_static['dd']:5.1f}% | Avg Mo: {r_static['avg_mo_pct']:+.2f}%")
        
    # Dynamic Compounded allocation (reinvesting profits)
    r_comp = test_pattern(pattern_name=pat_id, compound=True, target_pct=0.14, stop_pct=0.045)
    if r_comp:
        print(f"    [Dynamic Compounding ] Trades: {r_comp['trades']:3d} | WR: {r_comp['wr']:4.1f}% | Avg Hold: {r_comp['avg_hold']:4.1f}d | Final Eq: Rs {r_comp['final_equity']:8.1f} ({r_comp['ret_pct']:+5.1f}%) | PF: {r_comp['pf']:4.2f} | DD: {r_comp['dd']:5.1f}% | Avg Mo: {r_comp['avg_mo_pct']:+.2f}% | Best Mo: {r_comp['best_mo_pct']:+.1f}% | Worst Mo: {r_comp['worst_mo_pct']:+.1f}%")
