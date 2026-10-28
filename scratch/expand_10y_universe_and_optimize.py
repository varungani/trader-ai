"""
TraderAI - Expand 10Y Universe to Liquid Midcaps & Run Profit Optimization
==========================================================================
1. Appends liquid high-momentum midcaps with 10Y data to universe_10y.pkl.
2. Evaluates Profit Improvement Levers across OOS (2016-2021) and IS (2021-2026):
   - Lever 1: Target / Stop Geometry (4% stop, 10% vs 12% vs 15% target)
   - Lever 2: Dynamic Trailing Runner (50% scale-out at +8%, 50% trails 20 EMA)
   - Lever 3: Fast Stagnation Recycling (6-day vs 10-day dead money exit)
   - Lever 4: Volatility/RVOL Entry Thresholds (RVOL >= 1.2x vs 1.5x)
"""
import os, sys, pickle, time, numpy as np, pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.costs import compute_indian_delivery_costs

CACHE_10Y_FILE = "data/cache/universe_10y.pkl"
CACHE_BM_FILE = "data/cache/benchmarks_10y.pkl"

with open(CACHE_10Y_FILE, "rb") as f:
    univ = pickle.load(f)
with open(CACHE_BM_FILE, "rb") as f:
    bm = pickle.load(f)

with open("data/cache/universe_5y.pkl", "rb") as f:
    u5 = pickle.load(f)

all_syms = list(u5.keys())
missing_syms = [s for s in all_syms[60:120] if s not in univ]

print(f"Current 10Y universe has {len(univ)} stocks. Checking {len(missing_syms)} midcaps...")

if missing_syms:
    chunk_size = 20
    added = 0
    for i in range(0, len(missing_syms), chunk_size):
        chunk = missing_syms[i:i+chunk_size]
        print(f"Fetching midcap chunk {i//chunk_size + 1}: {len(chunk)} tickers...")
        try:
            df = yf.download(chunk, period="10y", group_by="ticker", progress=False)
            for s in chunk:
                try:
                    if s in df.columns.levels[0]:
                        sub = df[s].dropna(subset=['Close'])
                        if len(sub) >= 2000 and sub.index[0].year <= 2017:
                            sub.index = pd.to_datetime(sub.index).tz_localize(None)
                            univ[s] = sub[['Open', 'High', 'Low', 'Close', 'Volume']]
                            print(f"  + Added midcap {s}: {len(sub)} bars ({sub.index[0].date()} to {sub.index[-1].date()})")
                            added += 1
                except Exception as ex:
                    pass
        except Exception as e:
            print(f"Chunk error: {e}")
        time.sleep(0.5)
        
    print(f"Added {added} new midcaps. Total 10Y universe: {len(univ)} stocks.")
    with open(CACHE_10Y_FILE, "wb") as f:
        pickle.dump(univ, f)

nifty_df = bm['^NSEI'].copy()
nifty_df['sma50'] = nifty_df['Close'].rolling(50).mean()

def enrich_stock(df):
    res = df.copy()
    c, h, l, v, o = res["Close"], res["High"], res["Low"], res["Volume"], res["Open"]
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
    res["high20"] = h.rolling(20).max().shift(1)
    res["high50"] = h.rolling(50).max().shift(1)
    
    range_5d = h.rolling(5).max() - l.rolling(5).min()
    range_20d = h.rolling(20).max() - l.rolling(20).min()
    res["vcp_ratio"] = range_5d / range_20d.replace(0, np.nan)
    res["dist_ema20_pct"] = ((c - res["ema20"]) / res["ema20"]) * 100.0
    
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    res["rsi14"] = 100 - (100 / (1 + rs))
    return res

indicators = {s: enrich_stock(df) for s, df in univ.items()}

def run_profit_engine(
    pattern="VCP",
    start_date="2016-10-24",
    end_date="2021-10-01",
    target_pct=0.12,
    stop_pct=0.045,
    use_trailing_runner=False,
    runner_tp1=0.08,
    stagnation_days=10,
    max_hold=20,
    rvol_thresh=1.3,
    init_capital=30000.0,
    max_pos=3
):
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
        
        # Exits
        to_close = []
        for sym, pos in open_positions.items():
            ind = indicators[sym]
            if date_idx not in ind.index:
                pos['days_held'] += 1
                continue
            bar = ind.loc[date_idx]
            o_px, h_px, l_px, c_px = float(bar['Open']), float(bar['High']), float(bar['Low']), float(bar['Close'])
            ema20 = float(bar['ema20'])
            pos['days_held'] += 1
            
            # Trailing runner logic
            if use_trailing_runner and not pos.get('tp1_hit', False):
                if h_px >= pos['entry_price'] * (1.0 + runner_tp1):
                    # Scale out half at TP1
                    pos['tp1_hit'] = True
                    half_qty = pos['qty'] // 2
                    if half_qty > 0:
                        costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=pos['entry_price'] * (1.0 + runner_tp1), quantity=half_qty)
                        closed_trades.append({
                            'ticker': sym, 'net_pnl': costs.net_pnl_rupees, 'days_held': pos['days_held'],
                            'reason': 'RUNNER_TP1_HALF', 'ret_pct': costs.net_pnl_pct
                        })
                        cash += (half_qty * pos['entry_price'] * (1.0 + runner_tp1)) - costs.total_friction_rupees
                        pos['qty'] -= half_qty
                        # Raise stop to breakeven + 1%
                        pos['stop_loss'] = max(pos['stop_loss'], pos['entry_price'] * 1.01)
                        
            exit_reason = None
            exit_px = 0.0
            
            if l_px <= pos['stop_loss']:
                exit_reason = 'STOP_LOSS'
                exit_px = min(pos['stop_loss'], o_px)
            elif use_trailing_runner and pos.get('tp1_hit', False):
                # Runner leg exits on break below 20 EMA or 30 days
                if c_px < ema20:
                    exit_reason = 'RUNNER_EMA20_CROSS'
                    exit_px = c_px
                elif pos['days_held'] >= 30:
                    exit_reason = 'RUNNER_30D_EXPIRY'
                    exit_px = c_px
            elif not use_trailing_runner and h_px >= pos['target']:
                exit_reason = 'TARGET_HIT'
                exit_px = pos['target']
            elif stagnation_days > 0 and pos['days_held'] >= stagnation_days and abs((c_px - pos['entry_price']) / pos['entry_price']) <= 0.02:
                exit_reason = f'STAGNATION_{stagnation_days}D'
                exit_px = c_px
            elif pos['days_held'] >= max_hold:
                exit_reason = f'TIME_STOP_{max_hold}D'
                exit_px = c_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=exit_px, quantity=pos['qty'])
                closed_trades.append({
                    'ticker': sym, 'net_pnl': costs.net_pnl_rupees, 'days_held': pos['days_held'],
                    'reason': exit_reason, 'ret_pct': costs.net_pnl_pct
                })
                cash += (pos['qty'] * exit_px) - costs.total_friction_rupees
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        invested = sum(pos['qty'] * (float(indicators[sym].loc[date_idx, 'Close']) if date_idx in indicators[sym].index else pos['entry_price']) for sym, pos in open_positions.items())
        daily_equity.append({'date': date_idx, 'equity': cash + invested, 'cash': cash, 'invested': invested})
        
        # Absolute Macro Regime Gate: Nifty > 50 SMA
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
                ema20 = float(bar['ema20']) if not np.isnan(bar['ema20']) else 0.0
                rvol = float(bar['rvol']) if not np.isnan(bar['rvol']) else 1.0
                vcp = float(bar['vcp_ratio']) if not np.isnan(bar['vcp_ratio']) else 1.0
                dist = float(bar['dist_ema20_pct']) if not np.isnan(bar['dist_ema20_pct']) else 0.0
                rsi = float(bar['rsi14']) if not np.isnan(bar['rsi14']) else 50.0
                
                if c_px <= sma50 or sma50 <= sma200:
                    continue
                    
                if pattern == "VCP":
                    high20 = float(bar['high20']) if not np.isnan(bar['high20']) else 0.0
                    if vcp <= 0.65 and rvol >= rvol_thresh and c_px >= high20 * 0.995:
                        score = (1.0 - vcp) * 10.0 + rvol
                        candidates.append((sym, score, c_px))
                elif pattern == "SWEET_SPOT":
                    if 0.0 <= dist <= 2.2 and l_px <= ema20 * 1.015 and c_px > o_px and rvol >= rvol_thresh:
                        score = 10.0 - dist + (rvol * 0.5)
                        candidates.append((sym, score, c_px))
                elif pattern == "BREAKOUT_50D":
                    high50 = float(bar['high50']) if not np.isnan(bar['high50']) else 0.0
                    if c_px >= high50 and rvol >= rvol_thresh and rsi >= 60.0:
                        score = rvol * 2.0 + (rsi / 10.0)
                        candidates.append((sym, score, c_px))
                        
            candidates.sort(key=lambda x: x[1], reverse=True)
            slots_free = max_pos - len(open_positions)
            for sym, score, entry_px in candidates[:slots_free]:
                pos_alloc = min(cash, init_capital / max_pos)
                qty = int(pos_alloc // entry_px)
                if qty > 0 and cash >= (qty * entry_px):
                    cash -= (qty * entry_px)
                    stop_px = round(entry_px * (1.0 - stop_pct), 2)
                    tp_px = round(entry_px * (1.0 + target_pct), 2)
                    open_positions[sym] = {
                        'entry_price': entry_px, 'qty': qty, 'stop_loss': stop_px,
                        'target': tp_px, 'days_held': 0, 'entry_date': date_str,
                        'tp1_hit': False
                    }
                    
    df_tr = pd.DataFrame(closed_trades)
    df_eq = pd.DataFrame(daily_equity)
    if df_tr.empty:
        return {'trades': 0, 'pnl': 0.0, 'wr': 0.0, 'pf': 0.0, 'dd': 0.0, 'avg_mo': 0.0}
        
    wins = df_tr[df_tr['net_pnl'] > 0]
    losses = df_tr[df_tr['net_pnl'] <= 0]
    wr = len(wins) / len(df_tr) * 100.0
    tot_pnl = df_tr['net_pnl'].sum()
    gross_w = wins['net_pnl'].sum() if not wins.empty else 0.0
    gross_l = abs(losses['net_pnl'].sum()) if not losses.empty else 1.0
    pf = gross_w / gross_l
    
    df_eq['peak'] = df_eq['equity'].cummax()
    df_eq['dd'] = (df_eq['equity'] - df_eq['peak']) / df_eq['peak'] * 100.0
    max_dd = df_eq['dd'].min()
    
    # Calculate monthly average profit
    df_eq['year_month'] = df_eq['date'].apply(lambda d: str(d.date())[:7])
    m_snaps = df_eq.groupby('year_month').last()
    m_pnl = m_snaps['equity'] - m_snaps['equity'].shift(1).fillna(init_capital)
    avg_mo = m_pnl.mean()
    best_mo = m_pnl.max()
    worst_mo = m_pnl.min()
    
    return {
        'pattern': pattern, 'trades': len(df_tr), 'wr': wr, 'pnl': tot_pnl,
        'ret_pct': (tot_pnl / init_capital) * 100.0, 'pf': pf, 'dd': max_dd,
        'avg_mo': avg_mo, 'best_mo': best_mo, 'worst_mo': worst_mo
    }

print("\n" + "="*95)
print("SYSTEMATIC PROFIT IMPROVEMENT EXPERIMENT (EXPANDED UNIVERSE WITH LIQUID MIDCAPS)")
print("="*95)

experiments = [
    {"name": "Baseline (Fixed 12% TP, 4.5% SL, 10D Stagnation)", "target_pct": 0.12, "stop_pct": 0.045, "use_runner": False, "stag": 10},
    {"name": "Dynamic Trailing Runner (50% at +8%, 50% trails 20 EMA)", "target_pct": 0.12, "stop_pct": 0.045, "use_runner": True, "stag": 10},
    {"name": "Fast Capital Recycling (6D Stagnation Exit)", "target_pct": 0.12, "stop_pct": 0.045, "use_runner": False, "stag": 6},
    {"name": "Asymmetric R:R (15% Target, 4.0% Stop)", "target_pct": 0.15, "stop_pct": 0.040, "use_runner": False, "stag": 10},
    {"name": "High-Conviction Volume (RVOL >= 1.5x, 12% Target)", "target_pct": 0.12, "stop_pct": 0.045, "use_runner": False, "stag": 10, "rvol": 1.5},
]

for exp in experiments:
    print(f"\n>>> Configuration: {exp['name']}")
    for period_name, s_d, e_d in [("OOS (2016-2021)", "2016-10-24", "2021-10-01"), ("IS (2021-2026)", "2021-10-18", "2026-10-16")]:
        r = run_profit_engine(
            pattern="VCP", start_date=s_d, end_date=e_d,
            target_pct=exp['target_pct'], stop_pct=exp['stop_pct'],
            use_trailing_runner=exp.get('use_runner', False),
            stagnation_days=exp.get('stag', 10),
            rvol_thresh=exp.get('rvol', 1.3)
        )
        print(f"    [{period_name}] Trades: {r['trades']:3d} | WR: {r['wr']:4.1f}% | Net P&L: Rs {r['pnl']:+8.1f} ({r['ret_pct']:+5.1f}%) | PF: {r['pf']:4.2f} | DD: {r['dd']:5.1f}% | Avg Mo: Rs {r['avg_mo']:+6.1f} | Best: Rs {r['best_mo']:+6.1f} | Worst: Rs {r['worst_mo']:+6.1f}")
