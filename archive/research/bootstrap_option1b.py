"""
Run Block Bootstrap on Option 1B Weekly / Trade Net Expectancy
"""
import os, sys, pickle, numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backtesting.swing_midcap_backtest import load_cached_universe, compute_indicators
from data.costs import compute_indian_delivery_costs

univ, bm = load_cached_universe()
nifty_df = bm['^NSEI']

def enrich_indicators(df):
    res = compute_indicators(df)
    res['vol_sma20'] = res['Volume'].rolling(20).mean()
    res['vol_ratio'] = res['Volume'] / res['vol_sma20'].replace(0, np.nan)
    res['high50'] = res['High'].rolling(50).max().shift(1)
    return res

indicators = {sym: enrich_indicators(df) for sym, df in univ.items()}
all_dates = nifty_df.index

cash = 100000.0
open_positions = {}
trades = []

for i in range(200, len(all_dates)):
    date_idx = all_dates[i]
    date_str = str(date_idx.date())
    
    to_close = []
    for sym, pos in open_positions.items():
        ind = indicators[sym]
        if date_idx not in ind.index:
            pos['days_held'] += 1
            continue
        bar = ind.loc[date_idx]
        open_px = float(bar['Open'])
        high_px = float(bar['High'])
        low_px = float(bar['Low'])
        close_px = float(bar['Close'])
        pos['days_held'] += 1
        
        exit_reason = None
        exit_px = 0.0
        if low_px <= pos['stop_loss']:
            exit_reason = 'STOP_LOSS'
            exit_px = min(pos['stop_loss'], open_px)
        elif high_px >= pos['target']:
            exit_reason = 'TARGET_HIT'
            exit_px = pos['target']
        elif pos['days_held'] >= 20:
            exit_reason = 'TIME_EXPIRY_20D'
            exit_px = close_px
            
        if exit_reason:
            costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=exit_px, quantity=pos['qty'], apply_stcg=False)
            cash += (exit_px * pos['qty']) - costs.total_friction_rupees
            trades.append({
                'ticker': sym, 'net_pnl': costs.net_pnl_rupees, 'days_held': pos['days_held'],
                'exit_date': date_idx
            })
            to_close.append(sym)
            
    for s in to_close:
        del open_positions[s]
        
    nifty_loc = nifty_df.index.get_loc(date_idx)
    regime_bullish = True
    if nifty_loc >= 50:
        n_close = float(nifty_df['Close'].iloc[nifty_loc])
        n_sma50 = float(nifty_df['Close'].iloc[nifty_loc-49:nifty_loc+1].mean())
        if n_close < n_sma50:
            regime_bullish = False
            
    if len(open_positions) < 5 and regime_bullish:
        available = [s for s in univ.keys() if s not in open_positions]
        candidates = []
        for sym in available:
            ind = indicators[sym]
            if date_idx not in ind.index: continue
            loc = ind.index.get_loc(date_idx)
            if loc < 50: continue
            bar = ind.iloc[loc]
            close = float(bar['Close'])
            high50 = float(bar['high50'])
            rsi = float(bar['rsi14'])
            mom60 = float(bar['mom60'])
            adtv = float(bar['adtv_cr'])
            vol_r = float(bar['vol_ratio'])
            
            if adtv >= 5.0 and close > 10.0 and close >= high50 and vol_r >= 1.2 and rsi > 60.0:
                candidates.append((sym, mom60, close))
                
        candidates.sort(key=lambda x: x[1], reverse=True)
        for sym, mom60, close_px in candidates[:5-len(open_positions)]:
            alloc = min(cash, 20000.0)
            qty = int(alloc // close_px)
            if qty > 0 and cash >= (qty * close_px):
                stop_px = round(close_px * 0.955, 2)
                target_px = round(close_px * 1.12, 2)
                cash -= (qty * close_px)
                open_positions[sym] = {
                    'entry_price': close_px, 'qty': qty, 'stop_loss': stop_px,
                    'target': target_px, 'peak_price': close_px, 'days_held': 0,
                    'entry_date': date_str
                }

df_trades = pd.DataFrame(trades)
pnls = df_trades['net_pnl'].values
n_trades = len(pnls)

# Stationary / Moving block bootstrap (block size = 10 trades)
np.random.seed(42)
B = 5000
block_size = 10
boot_means = []
n_blocks = int(np.ceil(n_trades / block_size))

for _ in range(B):
    # Sample blocks
    sampled_indices = []
    for _ in range(n_blocks):
        start = np.random.randint(0, n_trades - block_size + 1)
        sampled_indices.extend(range(start, start + block_size))
    sample = pnls[sampled_indices[:n_trades]]
    boot_means.append(np.mean(sample))

ci_lower = np.percentile(boot_means, 2.5)
ci_upper = np.percentile(boot_means, 97.5)
mean_e = np.mean(pnls)

# Two-sided p-value
p_val_two_sided = np.mean(np.array(boot_means) <= 0) * 2

print(f"Total Trades: {n_trades}")
print(f"Mean Expectancy per trade: Rs {mean_e:+.2f}")
print(f"95% Block Bootstrap CI: [Rs {ci_lower:+.2f}, Rs {ci_upper:+.2f}]")
print(f"Bootstrap Two-Sided p-value: {p_val_two_sided:.4f}")
