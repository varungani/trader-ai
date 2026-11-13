"""
TraderAI - Block Bootstrap Verification of the Optimal 1.8x RVOL Engine
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
    res["vol_sma20"] = v.rolling(20).mean()
    res["rvol"] = v / res["vol_sma20"].replace(0, np.nan)
    res["high20"] = h.rolling(20).max().shift(1)
    
    range_5d = h.rolling(5).max() - l.rolling(5).min()
    range_20d = h.rolling(20).max() - l.rolling(20).min()
    res["vcp_ratio"] = range_5d / range_20d.replace(0, np.nan)
    res["ret_6m"] = (c - c.shift(125)) / c.shift(125)
    return res

indicators = {s: enrich_stock(df) for s, df in univ.items()}

def run_trades():
    dates = nifty_df.loc["2016-10-24":"2026-10-16"].index
    cash = 30000.0
    open_positions = {}
    closed_trades = []
    
    for i in range(len(dates)):
        date_idx = dates[i]
        date_str = str(date_idx.date())
        nifty_bar = nifty_df.loc[date_idx]
        nifty_c = float(nifty_bar['Close'])
        nifty_sma50 = float(nifty_bar['sma50']) if not np.isnan(nifty_bar['sma50']) else 0.0
        
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
                    'ticker': sym, 'net_pnl': costs.net_pnl_rupees, 'friction': costs.total_friction_rupees
                })
                cash += (pos['qty'] * exit_px) - costs.total_friction_rupees
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        if nifty_c < nifty_sma50:
            continue
            
        if len(open_positions) < 3:
            candidates = []
            for sym, ind in indicators.items():
                if sym in open_positions or date_idx not in ind.index:
                    continue
                bar = ind.loc[date_idx]
                c_px, sma50, sma200, rvol, vcp, high20, ret_6m = (
                    float(bar['Close']), float(bar['sma50']), float(bar['sma200']),
                    float(bar['rvol']), float(bar['vcp_ratio']), float(bar['high20']), float(bar['ret_6m'])
                )
                if c_px <= sma50 or sma50 <= sma200 or ret_6m <= 0.10:
                    continue
                if vcp <= 0.65 and rvol >= 1.8 and c_px >= high20 * 0.995:
                    score = (1.0 - vcp) * 10.0 + rvol + (ret_6m * 2.0)
                    candidates.append((sym, score, c_px))
                    
            candidates.sort(key=lambda x: x[1], reverse=True)
            slots_free = 3 - len(open_positions)
            for sym, score, entry_px in candidates[:slots_free]:
                pos_alloc = min(cash, 10000.0)
                qty = int(pos_alloc // entry_px)
                if qty > 0 and cash >= (qty * entry_px):
                    cash -= (qty * entry_px)
                    open_positions[sym] = {
                        'entry_price': entry_px, 'qty': qty,
                        'stop_loss': round(entry_px * 0.955, 2),
                        'target': round(entry_px * 1.14, 2),
                        'days_held': 0, 'entry_date': date_str
                    }
    return closed_trades

trades = run_trades()
pnls = np.array([t['net_pnl'] for t in trades])

# Stationary Block Bootstrap
np.random.seed(42)
block_size = 10
n_blocks = len(pnls) // block_size
blocks = [pnls[k*block_size:(k+1)*block_size] for k in range(n_blocks)]

b_means = []
for _ in range(5000):
    sample = np.random.choice(len(blocks), size=len(blocks), replace=True)
    resampled = np.concatenate([blocks[idx] for idx in sample])
    b_means.append(np.mean(resampled))

b_means = np.array(b_means)
ci_low, ci_high = np.percentile(b_means, [2.5, 97.5])
two_sided_p = 2.0 * min(np.mean(b_means <= 0), np.mean(b_means >= 0))

print(f"Sample Size N:             {len(pnls)} trades")
print(f"Mean Net Expectancy:       Rs {np.mean(pnls):+.2f} per trade")
print(f"95% Block Bootstrap CI:    [Rs {ci_low:+.2f}, Rs {ci_high:+.2f}]")
print(f"Lower 95% Bound > 0:       {ci_low > 0}")
print(f"Two-Sided Bootstrap p-val: {two_sided_p:.5f}")
print(f"Passes Bonferroni (a=0.005): {two_sided_p < 0.005}")
