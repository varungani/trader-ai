"""
TraderAI - Novel Monster Pattern Discovery & High-Velocity Compounding Engine
=============================================================================
Systematically explores non-traditional, novel multi-factor combinations:
1. Candidate 1: Dual-Timeframe Volatility Squeeze (DT-VCS)
2. Candidate 2: Episodic Super-Volume Thrust (SVT - 60D max volume + top 15% close)
3. Candidate 3: Triple Compression Coil (TCC - micro + macro + BB squeeze)
4. Candidate 4: Uncapped Trend-Rider (Trailing 10 EMA, letting winners run to +50%-100%)
5. High-Velocity Aggressive Compounding (90% capital deployed in top leaders)
"""
import os, sys, pickle, numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.costs import compute_indian_delivery_costs

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

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
    
    # Range
    res["tr"] = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    res["atr14"] = res["tr"].rolling(14).mean()
    res["vol_sma20"] = v.rolling(20).mean()
    res["rvol"] = v / res["vol_sma20"].replace(0, np.nan)
    
    # 60-day max volume
    res["max_vol_60d"] = v.rolling(60).max().shift(1)
    res["is_super_volume"] = (v >= res["max_vol_60d"] * 0.95) & (v >= res["vol_sma20"] * 2.5)
    
    # Day range percentile: where did it close within the day's high-low?
    day_rng = (h - l).replace(0, np.nan)
    res["close_percentile"] = (c - l) / day_rng
    
    # Multi-tier compression
    r_3d = h.rolling(3).max() - l.rolling(3).min()
    r_10d = h.rolling(10).max() - l.rolling(10).min()
    r_30d = h.rolling(30).max() - l.rolling(30).min()
    res["comp_3_10"] = r_3d / r_10d.replace(0, np.nan)
    res["comp_10_30"] = r_10d / r_30d.replace(0, np.nan)
    
    # Bollinger Band Squeeze (20, 2)
    bb_mid = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    bb_w = (4.0 * bb_std) / bb_mid
    res["bb_width_percentile"] = bb_w.rolling(125).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1] if len(x)>0 else 0.5, raw=False)
    
    # 20-day high and 6-month momentum
    res["high20"] = h.rolling(20).max().shift(1)
    res["ret_6m"] = (c - c.shift(125)) / c.shift(125)
    return res

print(f"Enriching advanced pattern indicators for {len(univ)} stocks...")
indicators = {s: enrich_stock(df) for s, df in univ.items()}

def run_monster_simulation(
    pattern_mode="SUPER_VOLUME_THRUST",
    trailing_exit_ema="EMA10", # Exit runner when Close < EMA10 or EMA20
    tp1_pct=0.15,               # Scale out 40% at TP1
    scale_out_ratio=0.40,       # 40% sold at TP1, 60% left as runner
    max_hold_days=45,           # Allow runners up to 45 sessions
    stagnation_days=7,          # Cut flat dead trades fast
    stop_loss_pct=0.045,        # 4.5% risk
    max_pos=3,
    init_capital=30000.0,
    compound=True
):
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
            ema_trail = float(bar['ema10']) if trailing_exit_ema == "EMA10" else float(bar['ema20'])
            pos['days_held'] += 1
            
            # 1. Partial TP1 Scale-Out (Bank gains, move stop to entry + 1%)
            if not pos.get('tp1_hit', False) and tp1_pct > 0:
                if h_px >= pos['entry_price'] * (1.0 + tp1_pct):
                    pos['tp1_hit'] = True
                    sell_qty = int(pos['qty'] * scale_out_ratio)
                    if sell_qty > 0:
                        costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=pos['entry_price'] * (1.0 + tp1_pct), quantity=sell_qty)
                        closed_trades.append({
                            'ticker': sym, 'year': date_idx.year, 'days_held': pos['days_held'],
                            'reason': 'PARTIAL_TP1_SCALE', 'net_pnl': costs.net_pnl_rupees,
                            'friction': costs.total_friction_rupees, 'gain_pct': tp1_pct * 100.0
                        })
                        cash += (sell_qty * pos['entry_price'] * (1.0 + tp1_pct)) - costs.total_friction_rupees
                        pos['qty'] -= sell_qty
                        # Raise stop to breakeven + 1.5%
                        pos['stop_loss'] = max(pos['stop_loss'], pos['entry_price'] * 1.015)
                        
            exit_reason = None
            exit_px = 0.0
            
            # Stop loss
            if l_px <= pos['stop_loss']:
                exit_reason = 'STOP_LOSS'
                exit_px = min(pos['stop_loss'], o_px)
            # Runner exit: Close below trailing EMA after TP1
            elif pos.get('tp1_hit', False) and c_px < ema_trail:
                exit_reason = f'RUNNER_{trailing_exit_ema}_CROSS'
                exit_px = c_px
            # Stagnation exit (fast capital recycling)
            elif not pos.get('tp1_hit', False) and stagnation_days > 0 and pos['days_held'] >= stagnation_days and abs((c_px - pos['entry_price']) / pos['entry_price']) <= 0.015:
                exit_reason = f'STAGNATION_{stagnation_days}D'
                exit_px = c_px
            # Maximum hold limit
            elif pos['days_held'] >= max_hold_days:
                exit_reason = f'MAX_HOLD_{max_hold_days}D'
                exit_px = c_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=exit_px, quantity=pos['qty'])
                closed_trades.append({
                    'ticker': sym, 'year': date_idx.year, 'days_held': pos['days_held'],
                    'reason': exit_reason, 'net_pnl': costs.net_pnl_rupees,
                    'friction': costs.total_friction_rupees, 'gain_pct': ((exit_px - pos['entry_price'])/pos['entry_price'])*100.0
                })
                cash += (pos['qty'] * exit_px) - costs.total_friction_rupees
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        invested = sum(pos['qty'] * (float(indicators[sym].loc[date_idx, 'Close']) if date_idx in indicators[sym].index else pos['entry_price']) for sym, pos in open_positions.items())
        total_equity = cash + invested
        daily_equity.append({'date': date_idx, 'year': date_idx.year, 'year_month': date_str[:7], 'equity': total_equity})
        
        # Macro Regime Circuit Breaker
        if nifty_c < nifty_sma50:
            continue
            
        # Entries
        if len(open_positions) < max_pos:
            candidates = []
            for sym, ind in indicators.items():
                if sym in open_positions or date_idx not in ind.index:
                    continue
                bar = ind.loc[date_idx]
                c_px, o_px, h_px, l_px, v_px = float(bar['Close']), float(bar['Open']), float(bar['High']), float(bar['Low']), float(bar['Volume'])
                sma50 = float(bar['sma50']) if not np.isnan(bar['sma50']) else 0.0
                sma200 = float(bar['sma200']) if not np.isnan(bar['sma200']) else 0.0
                ema10 = float(bar['ema10']) if not np.isnan(bar['ema10']) else 0.0
                ema20 = float(bar['ema20']) if not np.isnan(bar['ema20']) else 0.0
                rvol = float(bar['rvol']) if not np.isnan(bar['rvol']) else 1.0
                high20 = float(bar['high20']) if not np.isnan(bar['high20']) else 0.0
                ret_6m = float(bar['ret_6m']) if not np.isnan(bar['ret_6m']) else 0.0
                is_super_vol = bool(bar['is_super_volume']) if not np.isnan(bar['is_super_volume']) else False
                close_pctile = float(bar['close_percentile']) if not np.isnan(bar['close_percentile']) else 0.5
                c_3_10 = float(bar['comp_3_10']) if not np.isnan(bar['comp_3_10']) else 1.0
                c_10_30 = float(bar['comp_10_30']) if not np.isnan(bar['comp_10_30']) else 1.0
                bb_pctile = float(bar['bb_width_percentile']) if not np.isnan(bar['bb_width_percentile']) else 0.5
                
                # Base Filter: Must be in Stage 2 (Accumulation)
                if c_px <= sma50 or sma50 <= sma200 or ret_6m <= 0.05:
                    continue
                    
                match = False
                score = 0.0
                
                if pattern_mode == "SUPER_VOLUME_THRUST":
                    # Pattern 1: Episodic Super-Volume Thrust (SVT)
                    # 60-day volume surge (RVOL >= 2.5x), closing in upper 20% of candle, breaking 20D high
                    if is_super_vol and close_pctile >= 0.75 and c_px >= high20 * 0.995 and (c_px - o_px)/o_px >= 0.025:
                        match = True
                        score = rvol * 3.0 + (ret_6m * 2.0)
                        
                elif pattern_mode == "TRIPLE_COMPRESSION_COIL":
                    # Pattern 2: Triple Compression Coil (TCC)
                    # 3-day in 10-day <= 0.45, 10-day in 30-day <= 0.50, BB width in bottom 15%
                    # Breaking out on RVOL >= 1.8x
                    if c_3_10 <= 0.45 and c_10_30 <= 0.52 and bb_pctile <= 0.20 and c_px >= high20 * 0.995 and rvol >= 1.8:
                        match = True
                        score = (1.0 - c_3_10) * 10.0 + rvol * 2.0 + (ret_6m * 2.0)
                        
                elif pattern_mode == "MOMENTUM_SURGE_RUNNER":
                    # Pattern 3: High-Velocity Momentum Surge Runner
                    # Minervini VCP + Institutional Volume + Uncapped Runner
                    range_5d = float(bar['High']) - float(bar['Low']) # proxy
                    if c_px >= high20 * 0.998 and rvol >= 1.9 and close_pctile >= 0.70 and ret_6m >= 0.15:
                        match = True
                        score = rvol * 2.5 + (ret_6m * 3.0)
                        
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
                        'stop_loss': round(entry_px * (1.0 - stop_loss_pct), 2),
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
    
    # 4-Year Rolling Windows (What is the best and average 4-year return?)
    df_eq['year'] = df_eq['date'].apply(lambda d: d.year)
    start_eq_2020 = df_eq[df_eq['date'] >= '2020-01-01']['equity'].iloc[0] if not df_eq[df_eq['date'] >= '2020-01-01'].empty else init_capital
    end_eq_2024 = df_eq[df_eq['date'] <= '2024-01-01']['equity'].iloc[-1] if not df_eq[df_eq['date'] <= '2024-01-01'].empty else final_eq
    four_yr_mult = end_eq_2024 / start_eq_2020 if start_eq_2020 > 0 else 1.0
    
    # Big wins analysis
    big_wins = len(df_tr[df_tr['gain_pct'] >= 25.0])
    max_single_win = df_tr['gain_pct'].max()
    
    return {
        'pattern': pattern_mode, 'trades': len(df_tr), 'wr': wr,
        'final_equity': final_eq, 'ret_pct': ret_pct, 'pf': pf,
        'max_dd': max_dd, 'big_wins_count': big_wins, 'max_gain': max_single_win,
        '4yr_multiple': four_yr_mult
    }

print("\n" + "="*95)
print("NOVEL MONSTER PATTERNS & UNCAPPED RUNNER EXPERIMENT (10 YEARS | 111 STOCKS)")
print("="*95)

patterns = [
    ("SUPER_VOLUME_THRUST", "1. Episodic Super-Volume Thrust (SVT: 60D Vol Surge + Upper 25% Close + Uncapped EMA10 Runner)"),
    ("TRIPLE_COMPRESSION_COIL", "2. Triple Compression Coil (TCC: Micro-range + Macro-range + BB Squeeze Explosion)"),
    ("MOMENTUM_SURGE_RUNNER", "3. Momentum Surge Uncapped Runner (High-RS 20D Breakout + 1.9x RVOL + EMA10 Trail)")
]

for pid, pdesc in patterns:
    res = run_monster_simulation(pattern_mode=pid, trailing_exit_ema="EMA10", tp1_pct=0.15, scale_out_ratio=0.40, stagnation_days=7)
    if res:
        print(f"\n>>> Pattern: {pdesc}")
        print(f"    Total Trades:       {res['trades']:3d} | Win Rate: {res['wr']:4.1f}% | Profit Factor: {res['pf']:4.2f}")
        print(f"    Final Equity:       Rs {res['final_equity']:,.2f} on Rs 30,000 capital ({res['ret_pct']:+.1f}% Total Return)")
        print(f"    Max Portfolio DD:    {res['max_dd']:5.1f}%")
        print(f"    Big Winners (>25%): {res['big_wins_count']} monster trades | Largest Single Trade: {res['max_gain']:+.1f}%")
        print(f"    4-Year Bull Window: {res['4yr_multiple']:.2f}x capital growth")
