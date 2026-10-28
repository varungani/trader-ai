"""
TraderAI - True Out-of-Sample Empirical Test (2016-2021) & Profit Optimization
=============================================================================
Batch downloads 10Y data for liquid NSE stocks and benchmarks.
Runs Candidate Patterns out-of-sample (2016-2021) vs in-sample (2021-2026).
"""
import os, sys, pickle, time, numpy as np, pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.costs import compute_indian_delivery_costs

CACHE_10Y_FILE = "data/cache/universe_10y.pkl"
CACHE_BM_FILE = "data/cache/benchmarks_10y.pkl"

def get_symbols():
    with open("data/cache/universe_5y.pkl", "rb") as f:
        u5 = pickle.load(f)
    return list(u5.keys())

def download_10y_data(symbols, max_stocks=70):
    os.makedirs("data/cache", exist_ok=True)
    if os.path.exists(CACHE_10Y_FILE) and os.path.exists(CACHE_BM_FILE):
        print(f"Loading cached 10Y data from {CACHE_10Y_FILE}...")
        with open(CACHE_10Y_FILE, "rb") as f:
            univ = pickle.load(f)
        with open(CACHE_BM_FILE, "rb") as f:
            bm = pickle.load(f)
        return univ, bm

    print(f"Downloading 10Y benchmark (^NSEI)...")
    nifty = yf.download("^NSEI", period="10y", progress=False)
    if isinstance(nifty.columns, pd.MultiIndex):
        nifty = nifty.xs('^NSEI', level=1, axis=1) if '^NSEI' in nifty.columns.levels[1] else nifty
    nifty.index = pd.to_datetime(nifty.index).tz_localize(None)
    bm = {"^NSEI": nifty[['Open', 'High', 'Low', 'Close', 'Volume']]}

    target_syms = symbols[:max_stocks]
    print(f"Batch downloading 10Y data for {len(target_syms)} equities in chunks...")
    univ = {}
    chunk_size = 20
    for i in range(0, len(target_syms), chunk_size):
        chunk = target_syms[i:i+chunk_size]
        print(f"Fetching chunk {i//chunk_size + 1}: {len(chunk)} tickers...")
        try:
            df = yf.download(chunk, period="10y", group_by="ticker", progress=False)
            for s in chunk:
                try:
                    if s in df.columns.levels[0]:
                        sub = df[s].dropna(subset=['Close'])
                        if len(sub) >= 2000 and sub.index[0].year <= 2017:
                            sub.index = pd.to_datetime(sub.index).tz_localize(None)
                            univ[s] = sub[['Open', 'High', 'Low', 'Close', 'Volume']]
                            print(f"  + {s}: {len(sub)} bars ({sub.index[0].date()} to {sub.index[-1].date()})")
                except Exception as ex:
                    pass
        except Exception as e:
            print(f"Chunk error: {e}")
        time.sleep(0.5)

    print(f"Successfully cached {len(univ)} stocks with 10Y history.")
    with open(CACHE_10Y_FILE, "wb") as f:
        pickle.dump(univ, f)
    with open(CACHE_BM_FILE, "wb") as f:
        pickle.dump(bm, f)
    return univ, bm

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
    
    # RSI 14
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    res["rsi14"] = 100 - (100 / (1 + rs))
    return res

def simulate_strategy(indicators, nifty_df, pattern_mode, start_date, end_date, init_capital=30000.0, max_pos=3):
    dates = nifty_df.loc[start_date:end_date].index
    if len(dates) < 50:
        return None
    
    cash = init_capital
    open_positions = {}
    closed_trades = []
    daily_equity = []
    
    for i in range(len(dates)):
        date_idx = dates[i]
        date_str = str(date_idx.date())
        
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
            
            # Stop-first conservative execution
            if l_px <= pos['stop_loss']:
                exit_reason = 'STOP_LOSS'
                exit_px = min(pos['stop_loss'], o_px)
            elif h_px >= pos['target']:
                exit_reason = 'TARGET_HIT'
                exit_px = pos['target']
            elif pos['days_held'] >= 10 and abs((c_px - pos['entry_price']) / pos['entry_price']) <= 0.02:
                # 10-session stagnation exit
                exit_reason = 'STAGNATION_10D'
                exit_px = c_px
            elif pos['days_held'] >= 15:
                # 15-session hard time stop
                exit_reason = 'TIME_STOP_15D'
                exit_px = c_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=exit_px, quantity=pos['qty'])
                closed_trades.append({
                    'ticker': sym, 'entry_date': pos['entry_date'], 'exit_date': date_str,
                    'entry_px': pos['entry_price'], 'exit_px': exit_px, 'qty': pos['qty'],
                    'days_held': pos['days_held'], 'reason': exit_reason,
                    'gross_pnl': costs.gross_pnl_rupees, 'net_pnl': costs.net_pnl_rupees,
                    'friction': costs.total_friction_rupees, 'ret_pct': costs.net_pnl_pct
                })
                cash += (pos['qty'] * exit_px) - costs.total_friction_rupees
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        # Daily portfolio mark-to-market
        invested_val = 0.0
        for sym, pos in open_positions.items():
            if date_idx in indicators[sym].index:
                invested_val += pos['qty'] * float(indicators[sym].loc[date_idx, 'Close'])
            else:
                invested_val += pos['qty'] * pos['entry_price']
        daily_equity.append({
            'date': date_idx, 'year_month': date_str[:7], 'equity': cash + invested_val,
            'cash': cash, 'invested': invested_val, 'open_count': len(open_positions)
        })
        
        # 2. Check Entries for Tomorrow (executing at Close for backtest consistency, next Open in production)
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
                
                # Minimum Stage 2 structure
                if c_px <= sma50 or sma50 <= sma200:
                    continue
                    
                if pattern_mode == "VCP":
                    # Minervini VCP Breakout
                    high20 = float(bar['high20']) if not np.isnan(bar['high20']) else 0.0
                    if vcp <= 0.65 and rvol >= 1.35 and c_px >= high20 * 0.995:
                        score = (1.0 - vcp) * 10.0 + rvol
                        candidates.append((sym, score, c_px, bar))
                elif pattern_mode == "SWEET_SPOT":
                    # 20 EMA Sweet Spot Rebound
                    if 0.0 <= dist <= 2.2 and l_px <= ema20 * 1.015 and c_px > o_px:
                        score = 10.0 - dist + (rvol * 0.5)
                        candidates.append((sym, score, c_px, bar))
                elif pattern_mode == "BREAKOUT_50D":
                    high50 = float(bar['high50']) if not np.isnan(bar['high50']) else 0.0
                    if c_px >= high50 and rvol >= 1.2 and rsi >= 60.0:
                        score = rvol * 2.0 + (rsi / 10.0)
                        candidates.append((sym, score, c_px, bar))
                        
            candidates.sort(key=lambda x: x[1], reverse=True)
            slots_free = max_pos - len(open_positions)
            for sym, score, entry_px, bar in candidates[:slots_free]:
                pos_alloc = min(cash, init_capital / max_pos)
                qty = int(pos_alloc // entry_px)
                if qty > 0 and cash >= (qty * entry_px):
                    cash -= (qty * entry_px)
                    atr = float(bar['atr14']) if not np.isnan(bar['atr14']) else entry_px * 0.025
                    stop_px = round(max(entry_px - (1.8 * atr), entry_px * 0.955), 2)
                    tp_px = round(entry_px * 1.15, 2)
                    open_positions[sym] = {
                        'entry_price': entry_px, 'qty': qty, 'stop_loss': stop_px,
                        'target': tp_px, 'peak_price': entry_px, 'days_held': 0,
                        'entry_date': date_str, 'atr': atr
                    }
                    
    # Metrics
    df_eq = pd.DataFrame(daily_equity)
    df_tr = pd.DataFrame(closed_trades)
    
    if df_tr.empty:
        return {'trades': 0, 'net_pnl': 0.0, 'win_rate': 0.0, 'pf': 0.0, 'max_dd': 0.0}
        
    wins = df_tr[df_tr['net_pnl'] > 0]
    losses = df_tr[df_tr['net_pnl'] <= 0]
    wr = len(wins) / len(df_tr) * 100.0
    tot_pnl = df_tr['net_pnl'].sum()
    gross_win = wins['net_pnl'].sum() if not wins.empty else 0.0
    gross_loss = abs(losses['net_pnl'].sum()) if not losses.empty else 1.0
    pf = gross_win / gross_loss if gross_loss > 0 else 99.0
    
    # Peak-to-trough Drawdown
    df_eq['peak'] = df_eq['equity'].cummax()
    df_eq['dd'] = (df_eq['equity'] - df_eq['peak']) / df_eq['peak'] * 100.0
    max_dd = df_eq['dd'].min()
    
    # Block Bootstrap CI on trade expectancy
    pnls = df_tr['net_pnl'].values
    mean_exp = np.mean(pnls)
    b_means = []
    block_size = min(10, len(pnls))
    n_blocks = len(pnls) // block_size
    if n_blocks > 0:
        blocks = [pnls[k*block_size:(k+1)*block_size] for k in range(n_blocks)]
        np.random.seed(42)
        for _ in range(3000):
            sample = np.random.choice(len(blocks), size=len(blocks), replace=True)
            resampled = np.concatenate([blocks[idx] for idx in sample])
            b_means.append(np.mean(resampled))
        ci_low, ci_high = np.percentile(b_means, [2.5, 97.5])
    else:
        ci_low, ci_high = mean_exp, mean_exp
        
    # Exposure %
    avg_invested = (df_eq['invested'] / df_eq['equity']).mean() * 100.0
    
    return {
        'pattern': pattern_mode,
        'trades': len(df_tr),
        'win_rate': wr,
        'net_pnl': tot_pnl,
        'ret_pct': (tot_pnl / init_capital) * 100.0,
        'pf': pf,
        'max_dd': max_dd,
        'mean_exp': mean_exp,
        'ci_low': ci_low,
        'ci_high': ci_high,
        'avg_invested': avg_invested
    }

def run_experiment():
    syms = get_symbols()
    univ, bm = download_10y_data(syms, max_stocks=65)
    nifty = bm['^NSEI']
    
    print(f"Enriching indicators for {len(univ)} stocks...")
    indicators = {s: enrich_stock(df) for s, df in univ.items()}
    
    # Define Split Dates
    oos_start = "2016-10-24"
    oos_end   = "2021-10-01"
    is_start  = "2021-10-18"
    is_end    = "2026-10-16"
    
    # Benchmark Returns
    nifty_oos_ret = ((nifty.loc[oos_end, 'Close'] - nifty.loc[oos_start, 'Close']) / nifty.loc[oos_start, 'Close']) * 100.0
    nifty_is_ret  = ((nifty.loc[is_end, 'Close'] - nifty.loc[is_start, 'Close']) / nifty.loc[is_start, 'Close']) * 100.0
    
    print("\n" + "="*80)
    print("BENCHMARK RETURNS (^NSEI):")
    print(f"Out-of-Sample (2016-2021): {nifty_oos_ret:+.2f}%")
    print(f"In-Sample     (2021-2026): {nifty_is_ret:+.2f}%")
    print("="*80)
    
    patterns = ["VCP", "SWEET_SPOT", "BREAKOUT_50D"]
    
    print("\n" + "="*80)
    print("TRUE OUT-OF-SAMPLE TEST RESULTS (2016 - 2021 | UNSEEN 5 YEARS | INCLUDES 2018 BEAR & 2020 CRASH)")
    print("="*80)
    for p in patterns:
        res = simulate_strategy(indicators, nifty, p, oos_start, oos_end)
        if res:
            print(f"[{p}] Trades: {res['trades']:3d} | WR: {res['win_rate']:4.1f}% | Net P&L: Rs {res['net_pnl']:+8.1f} ({res['ret_pct']:+5.1f}%) | PF: {res['pf']:4.2f} | Max DD: {res['max_dd']:5.1f}% | Exp: Rs {res['mean_exp']:+6.1f} [{res['ci_low']:+6.1f}, {res['ci_high']:+6.1f}] | Exp%: {res['avg_invested']:4.1f}%")

    print("\n" + "="*80)
    print("IN-SAMPLE TEST RESULTS (2021 - 2026 | TUNING 5 YEARS)")
    print("="*80)
    for p in patterns:
        res = simulate_strategy(indicators, nifty, p, is_start, is_end)
        if res:
            print(f"[{p}] Trades: {res['trades']:3d} | WR: {res['win_rate']:4.1f}% | Net P&L: Rs {res['net_pnl']:+8.1f} ({res['ret_pct']:+5.1f}%) | PF: {res['pf']:4.2f} | Max DD: {res['max_dd']:5.1f}% | Exp: Rs {res['mean_exp']:+6.1f} [{res['ci_low']:+6.1f}, {res['ci_high']:+6.1f}] | Exp%: {res['avg_invested']:4.1f}%")

if __name__ == "__main__":
    run_experiment()
