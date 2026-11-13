"""
TraderAI - Deep-Dive Pattern Mining for >10% Monthly Return Engines
===================================================================
Tests 5 advanced, non-standard pattern architectures:
1. Mansfield Relative Strength 52W High Breakout (RS line hits 52W high before price)
2. TTM Volatility Squeeze (Bollinger Bands inside Keltner Channel + Momentum Histogram firing)
3. Volume Acceleration Ladder (3 consecutive days of expanding volume + green closes)
4. Undercut & Rally (U&R Shakeout Pivot: undercut prior swing low, reclaim, 3D tight coil)
5. Super-Momentum Hybrid (TTM Squeeze + RS High + Volume Surge >= 2.2x)

Evaluates:
- % of months delivering >= +10.0% net return
- Average monthly return during bull/momentum regimes
- Compounded equity growth, Profit Factor, and Max Drawdown
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

def enrich_stock(df, nifty_close):
    res = df.copy()
    c, h, l, v, o = res["Close"], res["High"], res["Low"], res["Volume"], res["Open"]
    res["ema10"] = c.ewm(span=10, adjust=False).mean()
    res["ema20"] = c.ewm(span=20, adjust=False).mean()
    res["sma50"] = c.rolling(50).mean()
    res["sma200"] = c.rolling(200).mean()
    
    # 20-day volume & RVOL
    res["vol_sma20"] = v.rolling(20).mean()
    res["rvol"] = v / res["vol_sma20"].replace(0, np.nan)
    
    # 20-day High / Low
    res["high20"] = h.rolling(20).max().shift(1)
    res["low20"] = l.rolling(20).min().shift(1)
    res["high50"] = h.rolling(50).max().shift(1)
    
    # ATR 14
    tr1 = h - l
    tr2 = (h - c.shift(1)).abs()
    tr3 = (l - c.shift(1)).abs()
    res["atr14"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()
    
    # 1. Mansfield Relative Strength vs NIFTY 50
    # Align dates with nifty
    aligned_nifty = nifty_close.reindex(res.index).ffill()
    res["rs_line"] = c / aligned_nifty.replace(0, np.nan)
    res["rs_sma50"] = res["rs_line"].rolling(50).mean()
    res["mansfield_rs"] = ((res["rs_line"] / res["rs_sma50"]) - 1.0) * 100.0
    res["rs_high_52w"] = res["rs_line"].rolling(250).max().shift(1)
    res["is_rs_52w_high"] = res["rs_line"] >= res["rs_high_52w"] * 0.99
    
    # 2. TTM Squeeze (Bollinger Bands inside Keltner Channel)
    bb_mid = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    bb_up = bb_mid + (2.0 * bb_std)
    bb_low = bb_mid - (2.0 * bb_std)
    
    kc_up = bb_mid + (1.5 * res["atr14"])
    kc_low = bb_mid - (1.5 * res["atr14"])
    # Squeeze is ON when BB is inside KC
    res["ttm_squeeze_on"] = (bb_up < kc_up) & (bb_low > kc_low)
    # Momentum oscillator (linear regression of price - average of donchian midline and 20 SMA)
    donchian_mid = (h.rolling(20).max() + l.rolling(20).min()) / 2.0
    delta = c - ((donchian_mid + bb_mid) / 2.0)
    res["ttm_mom"] = delta.rolling(12).mean()
    res["ttm_fire"] = (res["ttm_squeeze_on"].shift(1)) & (~res["ttm_squeeze_on"]) & (res["ttm_mom"] > 0)
    
    # 3. Volume Acceleration Ladder (3 green days with increasing volume: V3 > V2 > V1)
    green_1 = c > o
    green_2 = c.shift(1) > o.shift(1)
    green_3 = c.shift(2) > o.shift(2)
    vol_accel = (v > v.shift(1)) & (v.shift(1) > v.shift(2)) & (v >= res["vol_sma20"] * 1.5)
    res["is_vol_ladder"] = green_1 & green_2 & green_3 & vol_accel
    
    # 4. Undercut & Rally (U&R) Shakeout Pivot
    # Stock dipped below 20-day low within last 5 days, but rallied back above 20 EMA with Close > Open
    low_under_prior = (l.shift(1) < res["low20"].shift(1)) | (l.shift(2) < res["low20"].shift(2))
    res["is_undercut_rally"] = low_under_prior & (c > res["ema20"]) & (c > o) & (res["rvol"] >= 1.4)
    
    # 5. Range Coiling (VCP proxy)
    r_5d = h.rolling(5).max() - l.rolling(5).min()
    r_20d = h.rolling(20).max() - l.rolling(20).min()
    res["vcp"] = r_5d / r_20d.replace(0, np.nan)
    return res

print(f"Calculating advanced momentum & volatility squeeze indicators for {len(univ)} stocks...")
indicators = {s: enrich_stock(df, nifty_df['Close']) for s, df in univ.items()}

def simulate_pattern(pattern_id, target_pct=0.15, stop_pct=0.045, init_capital=30000.0, max_pos=3):
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
            
            # Partial profit scale-out at +12%
            if not pos.get('tp1_hit', False) and h_px >= pos['entry_price'] * 1.12:
                pos['tp1_hit'] = True
                sell_qty = int(pos['qty'] * 0.40)
                if sell_qty > 0:
                    costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=pos['entry_price'] * 1.12, quantity=sell_qty)
                    closed_trades.append({
                        'ticker': sym, 'year': date_idx.year, 'days_held': pos['days_held'],
                        'reason': 'PARTIAL_TP1_SCALE', 'net_pnl': costs.net_pnl_rupees,
                        'gain_pct': 12.0
                    })
                    cash += (sell_qty * pos['entry_price'] * 1.12) - costs.total_friction_rupees
                    pos['qty'] -= sell_qty
                    pos['stop_loss'] = max(pos['stop_loss'], pos['entry_price'] * 1.015)
                    
            exit_reason = None
            exit_px = 0.0
            
            if l_px <= pos['stop_loss']:
                exit_reason = 'STOP_LOSS'
                exit_px = min(pos['stop_loss'], o_px)
            # Runner leg trails by 10 EMA
            elif pos.get('tp1_hit', False) and c_px < ema10:
                exit_reason = 'RUNNER_EMA10_CROSS'
                exit_px = c_px
            # Stagnation exit (recycle after 5 days if flat)
            elif not pos.get('tp1_hit', False) and pos['days_held'] >= 5 and abs((c_px - pos['entry_price']) / pos['entry_price']) <= 0.015:
                exit_reason = 'STAGNATION_5D'
                exit_px = c_px
            elif pos['days_held'] >= 25:
                exit_reason = 'TIME_STOP_25D'
                exit_px = c_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=exit_px, quantity=pos['qty'])
                closed_trades.append({
                    'ticker': sym, 'year': date_idx.year, 'days_held': pos['days_held'],
                    'reason': exit_reason, 'net_pnl': costs.net_pnl_rupees,
                    'gain_pct': ((exit_px - pos['entry_price'])/pos['entry_price'])*100.0
                })
                cash += (pos['qty'] * exit_px) - costs.total_friction_rupees
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        invested = sum(pos['qty'] * (float(indicators[sym].loc[date_idx, 'Close']) if date_idx in indicators[sym].index else pos['entry_price']) for sym, pos in open_positions.items())
        total_equity = cash + invested
        daily_equity.append({'date': date_idx, 'year_month': date_str[:7], 'equity': total_equity})
        
        # Macro Regime Protection
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
                rvol = float(bar['rvol']) if not np.isnan(bar['rvol']) else 1.0
                high20 = float(bar['high20']) if not np.isnan(bar['high20']) else 0.0
                
                # Base uptrend
                if c_px <= sma50 or sma50 <= sma200:
                    continue
                    
                match = False
                score = 0.0
                
                if pattern_id == "MANSFIELD_RS_52W":
                    # 1. Mansfield RS 52-Week High Breakout
                    is_rs_high = bool(bar['is_rs_52w_high'])
                    m_rs = float(bar['mansfield_rs']) if not np.isnan(bar['mansfield_rs']) else 0.0
                    if is_rs_high and m_rs >= 5.0 and rvol >= 1.6 and c_px >= high20 * 0.995:
                        match = True
                        score = m_rs + (rvol * 3.0)
                        
                elif pattern_id == "TTM_SQUEEZE_FIRE":
                    # 2. TTM Squeeze Fire + Volume
                    ttm_fire = bool(bar['ttm_fire'])
                    if ttm_fire and rvol >= 1.6 and c_px > o_px:
                        match = True
                        score = rvol * 3.0
                        
                elif pattern_id == "VOL_ACCEL_LADDER":
                    # 3. Volume Acceleration Ladder (3 consecutive volume increases)
                    is_ladder = bool(bar['is_vol_ladder'])
                    if is_ladder and c_px >= high20 * 0.99:
                        match = True
                        score = rvol * 3.0
                        
                elif pattern_id == "UNDERCUT_RALLY":
                    # 4. Undercut & Rally (U&R) Shakeout Pivot
                    is_ur = bool(bar['is_undercut_rally'])
                    if is_ur and rvol >= 1.5:
                        match = True
                        score = rvol * 2.5
                        
                elif pattern_id == "SUPER_CONFLUENCE_HYBRID":
                    # 5. Hybrid: RS Outperformer + Volatility Contraction (VCP <= 0.65) + RVOL >= 2.0x
                    vcp = float(bar['vcp']) if not np.isnan(bar['vcp']) else 1.0
                    m_rs = float(bar['mansfield_rs']) if not np.isnan(bar['mansfield_rs']) else 0.0
                    if vcp <= 0.65 and m_rs >= 5.0 and rvol >= 2.0 and c_px >= high20 * 0.995:
                        match = True
                        score = m_rs * 2.0 + (rvol * 4.0) + (1.0 - vcp) * 10.0
                        
                if match:
                    candidates.append((sym, score, c_px))
                    
            candidates.sort(key=lambda x: x[1], reverse=True)
            slots_free = max_pos - len(open_positions)
            slot_budget = total_equity / max_pos
            
            for sym, score, entry_px in candidates[:slots_free]:
                alloc = min(cash, slot_budget)
                qty = int(alloc // entry_px)
                if qty > 0 and cash >= (qty * entry_px):
                    cash -= (qty * entry_px)
                    open_positions[sym] = {
                        'entry_price': entry_px, 'qty': qty,
                        'stop_loss': round(entry_px * (1.0 - stop_pct), 2),
                        'days_held': 0, 'entry_date': date_str, 'tp1_hit': False
                    }
                    
    df_tr = pd.DataFrame(closed_trades)
    df_eq = pd.DataFrame(daily_equity)
    if df_tr.empty:
        return None
        
    wins = df_tr[df_tr['net_pnl'] > 0]
    wr = len(wins) / len(df_tr) * 100.0
    tot_pnl = df_tr['net_pnl'].sum()
    gross_w = wins['net_pnl'].sum() if not wins.empty else 0.0
    gross_l = abs(df_tr[df_tr['net_pnl'] <= 0]['net_pnl'].sum()) if not df_tr[df_tr['net_pnl'] <= 0].empty else 1.0
    pf = gross_w / gross_l
    
    df_eq['peak'] = df_eq['equity'].cummax()
    df_eq['dd'] = (df_eq['equity'] - df_eq['peak']) / df_eq['peak'] * 100.0
    max_dd = df_eq['dd'].min()
    final_eq = df_eq['equity'].iloc[-1]
    ret_pct = ((final_eq - init_capital) / init_capital) * 100.0
    
    # Monthly analysis: Count months with >= +10.0% return
    df_eq['year_month'] = df_eq['date'].apply(lambda d: str(d.date())[:7])
    m_snaps = df_eq.groupby('year_month').last()
    m_ret = (m_snaps['equity'] - m_snaps['equity'].shift(1).fillna(init_capital)) / m_snaps['equity'].shift(1).fillna(init_capital) * 100.0
    
    months_over_10pct = (m_ret >= 10.0).sum()
    months_over_5pct = (m_ret >= 5.0).sum()
    tot_months = len(m_ret)
    avg_mo = m_ret.mean()
    best_mo = m_ret.max()
    worst_mo = m_ret.min()
    
    monster_trades_20pct = len(df_tr[df_tr['gain_pct'] >= 20.0])
    max_trade_gain = df_tr['gain_pct'].max()
    
    return {
        'pattern': pattern_id, 'trades': len(df_tr), 'wr': wr, 'final_equity': final_eq,
        'ret_pct': ret_pct, 'pf': pf, 'max_dd': max_dd,
        'avg_mo': avg_mo, 'best_mo': best_mo, 'worst_mo': worst_mo,
        'm_over_10pct': months_over_10pct, 'm_over_5pct': months_over_5pct,
        'tot_months': tot_months, 'monster_trades': monster_trades_20pct,
        'max_gain': max_trade_gain
    }

print("\n" + "="*95)
print("DEEP-DIVE 10-YEAR SCAN: 5 ADVANCED PATTERNS HUNTING FOR >10% MONTHLY CLUSTERS")
print("="*95)

patterns = [
    ("MANSFIELD_RS_52W", "1. Mansfield RS 52W High Breakout (RS line leads price to 1-year high)"),
    ("TTM_SQUEEZE_FIRE", "2. TTM Squeeze Fire (BB inside Keltner Channel compression explosion)"),
    ("VOL_ACCEL_LADDER", "3. Volume Acceleration Ladder (3 consecutive higher-vol green closes)"),
    ("UNDERCUT_RALLY", "4. Undercut & Rally (U&R Shakeout Pivot: undercut low20 then reclaim)"),
    ("SUPER_CONFLUENCE_HYBRID", "5. Super-Confluence Hybrid (Mansfield RS >= 5% + VCP <= 0.65 + RVOL >= 2.0x)")
]

for pid, pdesc in patterns:
    res = simulate_pattern(pid)
    if res:
        print(f"\n>>> Pattern: {pdesc}")
        print(f"    Trades: {res['trades']:3d} | Win Rate: {res['wr']:4.1f}% | Profit Factor: {res['pf']:4.2f}")
        print(f"    Final Equity: Rs {res['final_equity']:,.2f} on Rs 30,000 start ({res['ret_pct']:+.1f}% Total Net Return)")
        print(f"    Max Drawdown: {res['max_dd']:5.1f}% | Avg Month: {res['avg_mo']:+.2f}% | Best Month: {res['best_mo']:+.1f}% | Worst Month: {res['worst_mo']:+.1f}%")
        print(f"    Months >= +10.0%: {res['m_over_10pct']}/{res['tot_months']} months ({res['m_over_10pct']/res['tot_months']*100:.1f}%) | Months >= +5.0%: {res['m_over_5pct']}/{res['tot_months']}")
        print(f"    Monster Trades (>20%): {res['monster_trades']} trades | Max Single Trade Gain: {res['max_gain']:+.1f}%")
