"""
TraderAI - Scan 6 Distinct New Price-Action & Volume Patterns (10 Years | 111 Stocks)
===================================================================================
Tests 6 institutional & classic technical patterns:
1. Pocket Pivot Breakout (Dr. Chris Kacher)
2. NR7 Volatility Squeeze Breakout (Toby Crabel)
3. Bollinger Band Squeeze & Walk (John Bollinger)
4. 3-Day Pullback Bullish Engulfing Reversal
5. Gap & Go Momentum Thrust (Gap up > 1.5% on 2x RVOL)
6. 50-Day SMA Volume Dry-Up (VDU) Bounce
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
    
    # 20-day Volume SMA & RVOL
    res["vol_sma20"] = v.rolling(20).mean()
    res["rvol"] = v / res["vol_sma20"].replace(0, np.nan)
    
    # 20-day High / Low
    res["high20"] = h.rolling(20).max().shift(1)
    
    # Range
    res["daily_range"] = h - l
    
    # NR7 (Narrowest Range in 7 days)
    res["min_range_7d"] = res["daily_range"].rolling(7).min()
    res["is_nr7"] = res["daily_range"] == res["min_range_7d"]
    
    # Bollinger Bands (20, 2)
    bb_mid = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    res["bb_upper"] = bb_mid + (2.0 * bb_std)
    res["bb_lower"] = bb_mid - (2.0 * bb_std)
    res["bb_width"] = (res["bb_upper"] - res["bb_lower"]) / bb_mid
    res["bb_width_min6m"] = res["bb_width"].rolling(125).min()
    res["bb_squeeze"] = res["bb_width"] <= (res["bb_width_min6m"] * 1.15)
    
    # Down-day volume over past 10 days (for Pocket Pivot)
    is_down = c < c.shift(1)
    down_vol = v.where(is_down, 0)
    res["max_down_vol_10d"] = down_vol.rolling(10).max().shift(1)
    res["is_pocket_pivot"] = (v > res["max_down_vol_10d"]) & (c > o)
    
    # Consecutive down days
    res["down_day"] = (c < c.shift(1)).astype(int)
    res["down_3d"] = (res["down_day"].shift(1) == 1) & (res["down_day"].shift(2) == 1) & (res["down_day"].shift(3) == 1)
    # Bullish engulfing
    res["bullish_engulfing"] = (c > o) & (c > h.shift(1)) & (o < l.shift(1))
    
    # Gap up
    res["gap_up_pct"] = ((o - h.shift(1)) / h.shift(1)) * 100.0
    
    # 50 SMA Distance
    res["dist_sma50_pct"] = ((c - res["sma50"]) / res["sma50"]) * 100.0
    return res

print(f"Enriching technical indicators for {len(univ)} stocks...")
indicators = {s: enrich_stock(df) for s, df in univ.items()}

def simulate_pattern(pattern_id, target_pct=0.12, stop_pct=0.045, init_capital=30000.0, max_pos=3, compound=True):
    dates = nifty_df.loc["2016-10-24":"2026-10-16"].index
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
        
        # 1. Process Exits
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
            elif pos['days_held'] >= 10 and abs((c_px - pos['entry_price']) / pos['entry_price']) <= 0.02:
                exit_reason = 'STAGNATION_10D'
                exit_px = c_px
            elif pos['days_held'] >= 15:
                exit_reason = 'TIME_STOP_15D'
                exit_px = c_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=exit_px, quantity=pos['qty'])
                closed_trades.append({
                    'ticker': sym, 'net_pnl': costs.net_pnl_rupees, 'friction': costs.total_friction_rupees,
                    'days_held': pos['days_held'], 'reason': exit_reason
                })
                cash += (pos['qty'] * exit_px) - costs.total_friction_rupees
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        invested = sum(pos['qty'] * (float(indicators[sym].loc[date_idx, 'Close']) if date_idx in indicators[sym].index else pos['entry_price']) for sym, pos in open_positions.items())
        total_equity = cash + invested
        daily_equity.append({'date': date_idx, 'year_month': date_str[:7], 'equity': total_equity})
        
        # Macro Regime Gate
        if nifty_c < nifty_sma50:
            continue
            
        if len(open_positions) < max_pos:
            candidates = []
            for sym, ind in indicators.items():
                if sym in open_positions or date_idx not in ind.index:
                    continue
                bar = ind.loc[date_idx]
                c_px, o_px, h_px, l_px, v_px = float(bar['Close']), float(bar['Open']), float(bar['High']), float(bar['Low']), float(bar['Volume'])
                sma50 = float(bar['sma50']) if not np.isnan(bar['sma50']) else 0.0
                sma200 = float(bar['sma200']) if not np.isnan(bar['sma200']) else 0.0
                ema20 = float(bar['ema20']) if not np.isnan(bar['ema20']) else 0.0
                rvol = float(bar['rvol']) if not np.isnan(bar['rvol']) else 1.0
                high20 = float(bar['high20']) if not np.isnan(bar['high20']) else 0.0
                
                # Base Stage 2 uptrend requirement
                if c_px <= sma50 or sma50 <= sma200:
                    continue
                    
                match = False
                score = 0.0
                
                if pattern_id == "POCKET_PIVOT":
                    # Pattern 1: Pocket Pivot (Volume > 10D max down volume, near 10 EMA/50 SMA)
                    is_pp = bool(bar['is_pocket_pivot'])
                    if is_pp and c_px >= ema20 * 0.98 and c_px <= ema20 * 1.03 and rvol >= 1.4:
                        match = True
                        score = rvol * 3.0
                        
                elif pattern_id == "NR7_BREAKOUT":
                    # Pattern 2: NR7 Volatility Squeeze Breakout (Yesterday was NR7, today breaks above high with vol)
                    prev_idx = ind.index.get_loc(date_idx) - 1
                    if prev_idx >= 0:
                        prev_bar = ind.iloc[prev_idx]
                        if bool(prev_bar['is_nr7']) and c_px > float(prev_bar['High']) and rvol >= 1.5:
                            match = True
                            score = rvol * 2.5
                            
                elif pattern_id == "BB_SQUEEZE_WALK":
                    # Pattern 3: Bollinger Band Squeeze & Walk (Squeeze + Close > Upper Band + RVOL >= 1.5x)
                    bb_up = float(bar['bb_upper'])
                    is_sq = bool(bar['bb_squeeze'])
                    if is_sq and c_px >= bb_up and rvol >= 1.5:
                        match = True
                        score = rvol * 2.0
                        
                elif pattern_id == "3D_PULLBACK_ENGULF":
                    # Pattern 4: 3-Day Pullback followed by Bullish Engulfing Reversal
                    down_3d = bool(bar['down_3d'])
                    engulf = bool(bar['bullish_engulfing'])
                    if down_3d and engulf and rvol >= 1.3:
                        match = True
                        score = rvol * 2.0
                        
                elif pattern_id == "GAP_AND_GO":
                    # Pattern 5: Gap & Go (Gap up >= 1.5% on >= 2.0x RVOL, closing near high)
                    gap_pct = float(bar['gap_up_pct']) if not np.isnan(bar['gap_up_pct']) else 0.0
                    day_rng = h_px - l_px
                    if gap_pct >= 1.5 and rvol >= 2.0 and day_rng > 0 and (c_px - l_px) / day_rng >= 0.70:
                        match = True
                        score = gap_pct + (rvol * 2.0)
                        
                elif pattern_id == "SMA50_VDU_BOUNCE":
                    # Pattern 6: 50-Day SMA Volume Dry-Up (VDU) Bounce
                    dist_sma = float(bar['dist_sma50_pct'])
                    if 0.0 <= dist_sma <= 2.5 and l_px <= sma50 * 1.01 and c_px > o_px and rvol >= 1.4:
                        match = True
                        score = (3.0 - dist_sma) * 3.0 + rvol
                        
                if match:
                    candidates.append((sym, score, c_px))
                    
            candidates.sort(key=lambda x: x[1], reverse=True)
            slots_free = max_pos - len(open_positions)
            slot_budget = (total_equity / max_pos) if compound else (init_capital / max_pos)
            
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
        return {'pattern': pattern_id, 'trades': 0, 'wr': 0.0, 'net_pnl': 0.0, 'ret_pct': 0.0, 'pf': 0.0, 'dd': 0.0, 'avg_hold': 0.0}
        
    wins = df_tr[df_tr['net_pnl'] > 0]
    wr = len(wins) / len(df_tr) * 100.0
    tot_pnl = df_tr['net_pnl'].sum()
    friction = df_tr['friction'].sum()
    gross_w = wins['net_pnl'].sum() if not wins.empty else 0.0
    gross_l = abs(df_tr[df_tr['net_pnl'] <= 0]['net_pnl'].sum()) if not df_tr[df_tr['net_pnl'] <= 0].empty else 1.0
    pf = gross_w / gross_l
    
    df_eq['peak'] = df_eq['equity'].cummax()
    df_eq['dd'] = (df_eq['equity'] - df_eq['peak']) / df_eq['peak'] * 100.0
    max_dd = df_eq['dd'].min()
    final_eq = df_eq['equity'].iloc[-1]
    ret_pct = ((final_eq - init_capital) / init_capital) * 100.0
    avg_hold = df_tr['days_held'].mean()
    
    return {
        'pattern': pattern_id, 'trades': len(df_tr), 'wr': wr, 'final_equity': final_eq,
        'net_pnl': tot_pnl, 'ret_pct': ret_pct, 'pf': pf, 'dd': max_dd,
        'avg_hold': avg_hold, 'friction': friction
    }

print("\n" + "="*95)
print("COMPREHENSIVE 10-YEAR SCAN: 6 NEW PATTERNS (2016-2026 | 111 STOCKS | COMPOUNDED)")
print("="*95)

pattern_definitions = [
    ("POCKET_PIVOT", "1. Pocket Pivot Breakout (Vol > 10D max down-vol)"),
    ("NR7_BREAKOUT", "2. NR7 Volatility Coiling Breakout (7D range low + vol)"),
    ("BB_SQUEEZE_WALK", "3. Bollinger Band Squeeze & Walk (6M squeeze + band walk)"),
    ("3D_PULLBACK_ENGULF", "4. 3-Day Pullback + Bullish Engulfing Reversal"),
    ("GAP_AND_GO", "5. Gap & Go Thrust (Gap up >= 1.5% on 2x RVOL)"),
    ("SMA50_VDU_BOUNCE", "6. 50-Day SMA Support Bounce (Stage 2 trend retest)")
]

for pid, pdesc in pattern_definitions:
    res = simulate_pattern(pid, target_pct=0.12, stop_pct=0.045, compound=True)
    print(f"\n>>> Pattern: {pdesc}")
    print(f"    Trades: {res['trades']:3d} | WR: {res['wr']:4.1f}% | Avg Hold: {res['avg_hold']:4.1f}d | Final Equity: Rs {res['final_equity']:8.1f} ({res['ret_pct']:+5.1f}%) | Net P&L: Rs {res['net_pnl']:+8.1f} | Fees: Rs {res['friction']:7.1f} | PF: {res['pf']:4.2f} | DD: {res['dd']:5.1f}%")
