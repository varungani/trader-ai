"""
TraderAI - 10-Year Full Empirical Audit of High-Conviction VCP Breakout
=====================================================================
Analyzes the robust High-Conviction Volume VCP Engine across the full 10 years (2016-2026):
- Year-by-year profit breakdown
- Monthly distribution (Best, Worst, Average)
- Block bootstrap 95% confidence intervals on expectancy
- Exposure-matched alpha vs NIFTY 50
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
    
    range_5d = h.rolling(5).max() - l.rolling(5).min()
    range_20d = h.rolling(20).max() - l.rolling(20).min()
    res["vcp_ratio"] = range_5d / range_20d.replace(0, np.nan)
    return res

indicators = {s: enrich_stock(df) for s, df in univ.items()}

def run_10y_audit(init_capital=30000.0, max_pos=3, rvol_thresh=1.5, target_pct=0.12, stop_pct=0.045):
    dates = nifty_df.loc["2016-10-24":"2026-10-16"].index
    cash = init_capital
    open_positions = {}
    closed_trades = []
    daily_equity = []
    
    for i in range(len(dates)):
        date_idx = dates[i]
        date_str = str(date_idx.date())
        year = date_idx.year
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
            elif pos['days_held'] >= 10 and abs((c_px - pos['entry_price']) / pos['entry_price']) <= 0.02:
                exit_reason = 'STAGNATION_10D'
                exit_px = c_px
            elif pos['days_held'] >= 20:
                exit_reason = 'TIME_STOP_20D'
                exit_px = c_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=exit_px, quantity=pos['qty'])
                closed_trades.append({
                    'ticker': sym, 'year': year, 'entry_date': pos['entry_date'], 'exit_date': date_str,
                    'entry_px': pos['entry_price'], 'exit_px': exit_px, 'qty': pos['qty'],
                    'days_held': pos['days_held'], 'reason': exit_reason,
                    'gross_pnl': costs.gross_pnl_rupees, 'net_pnl': costs.net_pnl_rupees,
                    'friction': costs.total_friction_rupees, 'ret_pct': costs.net_pnl_pct
                })
                cash += (pos['qty'] * exit_px) - costs.total_friction_rupees
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        invested = sum(pos['qty'] * (float(indicators[sym].loc[date_idx, 'Close']) if date_idx in indicators[sym].index else pos['entry_price']) for sym, pos in open_positions.items())
        daily_equity.append({
            'date': date_idx, 'year': year, 'year_month': date_str[:7],
            'equity': cash + invested, 'cash': cash, 'invested': invested
        })
        
        # Absolute Macro Regime Circuit Breaker
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
                rvol = float(bar['rvol']) if not np.isnan(bar['rvol']) else 1.0
                vcp = float(bar['vcp_ratio']) if not np.isnan(bar['vcp_ratio']) else 1.0
                high20 = float(bar['high20']) if not np.isnan(bar['high20']) else 0.0
                
                # Minervini Stage 2
                if c_px <= sma50 or sma50 <= sma200:
                    continue
                # High-Conviction VCP
                if vcp <= 0.65 and rvol >= rvol_thresh and c_px >= high20 * 0.995:
                    score = (1.0 - vcp) * 10.0 + rvol
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
                        'target': tp_px, 'days_held': 0, 'entry_date': date_str
                    }
                    
    df_tr = pd.DataFrame(closed_trades)
    df_eq = pd.DataFrame(daily_equity)
    
    # Yearly breakdown
    yearly = df_tr.groupby('year').agg(
        trades=('net_pnl', 'count'),
        wins=('net_pnl', lambda x: (x > 0).sum()),
        net_pnl=('net_pnl', 'sum'),
        friction=('friction', 'sum')
    )
    yearly['win_rate'] = (yearly['wins'] / yearly['trades']) * 100.0
    
    # Monthly analysis
    m_snaps = df_eq.groupby('year_month').last()
    m_pnl = m_snaps['equity'] - m_snaps['equity'].shift(1).fillna(init_capital)
    
    # Drawdown
    df_eq['peak'] = df_eq['equity'].cummax()
    df_eq['dd'] = (df_eq['equity'] - df_eq['peak']) / df_eq['peak'] * 100.0
    max_dd = df_eq['dd'].min()
    
    # Exposure %
    avg_invested = (df_eq['invested'] / df_eq['equity']).mean() * 100.0
    
    # Block Bootstrap CI on trade expectancy
    pnls = df_tr['net_pnl'].values
    mean_exp = np.mean(pnls)
    b_means = []
    block_size = 10
    n_blocks = len(pnls) // block_size
    blocks = [pnls[k*block_size:(k+1)*block_size] for k in range(n_blocks)]
    np.random.seed(42)
    for _ in range(5000):
        sample = np.random.choice(len(blocks), size=len(blocks), replace=True)
        resampled = np.concatenate([blocks[idx] for idx in sample])
        b_means.append(np.mean(resampled))
    ci_low, ci_high = np.percentile(b_means, [2.5, 97.5])
    two_sided_p = 2.0 * min(np.mean(np.array(b_means) <= 0), np.mean(np.array(b_means) >= 0))
    
    tot_pnl = df_tr['net_pnl'].sum()
    gross_w = df_tr[df_tr['net_pnl'] > 0]['net_pnl'].sum()
    gross_l = abs(df_tr[df_tr['net_pnl'] <= 0]['net_pnl'].sum())
    pf = gross_w / gross_l
    wr = len(df_tr[df_tr['net_pnl'] > 0]) / len(df_tr) * 100.0
    
    # Benchmark return over full 10Y
    nifty_start = nifty_df.loc["2016-10-24", "Close"]
    nifty_end   = nifty_df.loc["2026-10-16", "Close"]
    nifty_10y_ret = ((nifty_end - nifty_start) / nifty_start) * 100.0
    
    print("\n" + "="*80)
    print("10-YEAR FULL AUDIT RESULTS (2016-2026 | 111 LIQUID STOCKS | RS 30,000 ACCOUNT)")
    print("="*80)
    print(f"Total Closed Trades:       {len(df_tr)}")
    print(f"Win Rate:                  {wr:.1f}%")
    print(f"Total Net P&L:             Rs {tot_pnl:+,.2f} ({(tot_pnl/init_capital)*100:+.1f}%)")
    print(f"Total Statutory Friction:  Rs {df_tr['friction'].sum():,.2f}")
    print(f"Profit Factor:             {pf:.2f}")
    print(f"Max Portfolio Drawdown:    {max_dd:.2f}%")
    print(f"Average % Invested:        {avg_invested:.1f}% ({100-avg_invested:.1f}% Cash)")
    print(f"Trade Expectancy:          Rs {mean_exp:+.2f} per trade")
    print(f"95% Block Bootstrap CI:    [Rs {ci_low:+.2f}, Rs {ci_high:+.2f}]")
    print(f"Two-Sided Bootstrap p-val: {two_sided_p:.4f}")
    print(f"NIFTY 50 10Y Benchmark:    {nifty_10y_ret:+.1f}%")
    print(f"Exposure-Matched Nifty:    {nifty_10y_ret * (avg_invested/100):+.1f}%")
    print(f"Exposure-Matched Alpha:    {((tot_pnl/init_capital)*100) - (nifty_10y_ret * (avg_invested/100)):+.1f}%")
    
    print("\n" + "-"*80)
    print("YEAR-BY-YEAR P&L WATERFALL:")
    print("-"*80)
    for yr, row in yearly.iterrows():
        print(f"  Year {yr}: {int(row['trades']):3d} trades | WR: {row['win_rate']:4.1f}% | Net P&L: Rs {row['net_pnl']:+8.2f} | Fees: Rs {row['friction']:6.2f}")
        
    print("\n" + "-"*80)
    print("MONTHLY RETURN DISTRIBUTION:")
    print("-"*80)
    print(f"  Average Month:  Rs {m_pnl.mean():+6.2f} ({(m_pnl.mean()/init_capital)*100:+.2f}%)")
    print(f"  Best Month:     Rs {m_pnl.max():+6.2f} ({(m_pnl.max()/init_capital)*100:+.2f}%)")
    print(f"  Worst Month:    Rs {m_pnl.min():+6.2f} ({(m_pnl.min()/init_capital)*100:+.2f}%)")
    win_m = (m_pnl > 0).sum()
    print(f"  Positive Months: {win_m}/{len(m_pnl)} ({win_m/len(m_pnl)*100:.1f}%)")

if __name__ == "__main__":
    run_10y_audit()
