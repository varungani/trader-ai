"""
Extensive 10-Year Consistency Audit (2016-2026):
Audits individual calendar year performance for:
1. Indian Equities Swing Engine (₹30,000 Seed)
2. Crypto Parabolic Moonshot Satellite Engine (₹3,000 Seed)
3. Combined Barbell Portfolio

Tests whether the strategy delivers:
- Consistent profits across changing regimes
- Strictly controlled "less losses" (micro-losses vs large wins)
- Capital preservation during major market crashes (2018 bear, 2020 COVID, 2022 crypto winter)
"""
import os, sys, pickle, numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.costs import compute_indian_delivery_costs

with open("data/cache/universe_10y.pkl", "rb") as f:
    univ = pickle.load(f)
with open("data/cache/benchmarks_10y.pkl", "rb") as f:
    bm = pickle.load(f)
with open("data/cache/crypto_10y.pkl", "rb") as f:
    crypto_univ = pickle.load(f)

# Prep Benchmarks
nifty_df = bm['^NSEI'].copy()
if isinstance(nifty_df.columns, pd.MultiIndex):
    nifty_df.columns = nifty_df.columns.get_level_values(0)
nifty_df['sma50'] = nifty_df['Close'].rolling(50).mean()

btc_df = crypto_univ['BTC-USD'].copy()
if isinstance(btc_df.columns, pd.MultiIndex):
    btc_df.columns = btc_df.columns.get_level_values(0)
btc_df.columns = [c.lower() for c in btc_df.columns]
btc_c = btc_df['close'].dropna()
btc_ema50 = btc_c.ewm(span=50, adjust=False).mean()

# Indicators
def enrich_stock(df):
    res = df.copy()
    if isinstance(res.columns, pd.MultiIndex):
        res.columns = res.columns.get_level_values(0)
    c, h, l, v = res["Close"], res["High"], res["Low"], res["Volume"]
    res["ema10"] = c.ewm(span=10, adjust=False).mean()
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

stock_ind = {s: enrich_stock(df) for s, df in univ.items()}

def enrich_crypto(df):
    res = df.copy()
    if isinstance(res.columns, pd.MultiIndex):
        res.columns = res.columns.get_level_values(0)
    res.columns = [c.lower() for c in res.columns]
    c, h, l, v = res["close"], res["high"], res["low"], res["volume"]
    res['ema10'] = c.ewm(span=10, adjust=False).mean()
    res['ema20'] = c.ewm(span=20, adjust=False).mean()
    res['vol_sma20'] = v.rolling(20).mean()
    res['rvol'] = v / res['vol_sma20'].replace(0, np.nan)
    res['high20'] = h.rolling(20).max().shift(1)
    return res

crypto_ind = {s: enrich_crypto(df) for s, df in crypto_univ.items()}
high_beta_tokens = ["SOL-USD", "AVAX-USD", "NEAR-USD", "DOGE-USD", "LINK-USD", "ETH-USD"]

# Run Stock Simulation
dates = nifty_df.loc["2016-10-24":"2026-10-16"].index
stock_cash = 30000.0
stock_open_positions = {}
stock_closed_trades = []
stock_daily_equity = []

for i in range(len(dates)):
    dt = dates[i]
    nifty_bar = nifty_df.loc[dt]
    nifty_c = float(nifty_bar['Close'])
    nifty_sma50 = float(nifty_bar['sma50']) if not np.isnan(nifty_bar['sma50']) else 0.0
    
    to_close = []
    for sym, pos in stock_open_positions.items():
        ind = stock_ind[sym]
        if dt not in ind.index:
            pos['days_held'] += 1
            continue
        bar = ind.loc[dt]
        o_px, h_px, l_px, c_px = float(bar['Open']), float(bar['High']), float(bar['Low']), float(bar['Close'])
        pos['days_held'] += 1
        
        exit_reason = None
        exit_px = 0.0
        
        if l_px <= pos['stop_loss']:
            exit_reason = 'STOP_LOSS'
            exit_px = min(pos['stop_loss'], o_px)
        elif not pos['partial_booked'] and h_px >= pos['entry_price'] * 1.15:
            pos['partial_booked'] = True
            booked_qty = int(pos['qty'] * 0.35)
            if booked_qty > 0:
                booked_px = pos['entry_price'] * 1.15
                costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=booked_px, quantity=booked_qty)
                stock_cash += (booked_qty * booked_px) - costs.total_friction_rupees
                pos['qty'] -= booked_qty
                pos['realized_partial_pnl'] = costs.net_pnl_rupees
            pos['stop_loss'] = pos['entry_price'] * 1.01
        elif pos['partial_booked'] and c_px < float(bar['ema10']):
            exit_reason = '10_EMA_TRAIL'
            exit_px = c_px
        elif pos['days_held'] >= 10 and abs((c_px - pos['entry_price']) / pos['entry_price']) <= 0.02:
            exit_reason = 'STAGNATION_10D'
            exit_px = c_px
        elif pos['days_held'] >= 25:
            exit_reason = 'TIME_STOP_25D'
            exit_px = c_px
            
        if exit_reason:
            costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=exit_px, quantity=pos['qty'])
            tot_pnl = costs.net_pnl_rupees + pos.get('realized_partial_pnl', 0.0)
            stock_closed_trades.append({
                'date': dt, 'year': dt.year, 'ticker': sym, 'net_pnl': tot_pnl,
                'ret_pct': (tot_pnl / (pos['entry_price'] * (pos['qty'] + int(pos['qty']*0.35 if pos['partial_booked'] else 0)))) * 100.0,
                'reason': exit_reason, 'days': pos['days_held']
            })
            stock_cash += (pos['qty'] * exit_px) - costs.total_friction_rupees
            to_close.append(sym)
            
    for s in to_close:
        del stock_open_positions[s]
        
    invested = sum(pos['qty'] * (float(stock_ind[sym].loc[dt, 'Close']) if dt in stock_ind[sym].index else pos['entry_price']) for sym, pos in stock_open_positions.items())
    tot_eq = stock_cash + invested
    stock_daily_equity.append((dt, tot_eq))
    
    if nifty_c >= nifty_sma50 and len(stock_open_positions) < 3:
        candidates = []
        for sym, ind in stock_ind.items():
            if sym in stock_open_positions or dt not in ind.index:
                continue
            bar = ind.loc[dt]
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
        slots_free = 3 - len(stock_open_positions)
        slot_budget = tot_eq / 3.0
        for sym, score, entry_px in candidates[:slots_free]:
            alloc = min(stock_cash, slot_budget)
            qty = int(alloc // entry_px)
            if qty > 0 and stock_cash >= (qty * entry_px):
                stock_cash -= (qty * entry_px)
                stock_open_positions[sym] = {
                    'entry_price': entry_px, 'qty': qty,
                    'stop_loss': round(entry_px * 0.955, 2),
                    'days_held': 0, 'partial_booked': False, 'realized_partial_pnl': 0.0
                }

df_stock_eq = pd.DataFrame(stock_daily_equity, columns=['date', 'equity']).set_index('date')
df_stock_trades = pd.DataFrame(stock_closed_trades)

# Run Crypto Simulation
c_dates = btc_c.loc["2016-10-24":"2026-10-16"].index
crypto_cash = 3000.0
crypto_open_positions = {}
crypto_closed_trades = []
crypto_daily_equity = []

for i in range(len(c_dates)):
    dt = c_dates[i]
    b_c = btc_c.loc[dt]
    b_ema = btc_ema50.loc[dt]
    
    to_close = []
    for sym, pos in crypto_open_positions.items():
        ind = crypto_ind[sym]
        if dt not in ind.index:
            continue
        bar = ind.loc[dt]
        c_px, l_px, h_px = float(bar['close']), float(bar['low']), float(bar['high'])
        pos['days_held'] += 1
        
        exit_reason = None
        exit_px = 0.0
        
        if l_px <= pos['stop_loss']:
            exit_reason = 'STOP'
            exit_px = pos['stop_loss']
        elif not pos['partial_booked'] and h_px >= pos['entry_price'] * 1.30:
            pos['partial_booked'] = True
            pos['stop_loss'] = pos['entry_price'] * 1.02
        elif pos['partial_booked'] and c_px < float(bar['ema20']):
            exit_reason = 'RUNNER_TRAIL'
            exit_px = c_px
        elif pos['days_held'] >= 28:
            exit_reason = 'TIME_STOP'
            exit_px = c_px
            
        if exit_reason:
            gross_val = pos['shares'] * exit_px
            fee = gross_val * 0.0020
            tds = gross_val * 0.0100
            net_val = gross_val - fee - tds
            crypto_cash += net_val
            tot_pnl = net_val - pos['orig_alloc']
            crypto_closed_trades.append({
                'date': dt, 'year': dt.year, 'ticker': sym, 'net_pnl': tot_pnl,
                'ret_pct': (tot_pnl / pos['orig_alloc']) * 100.0,
                'reason': exit_reason, 'days': pos['days_held']
            })
            to_close.append(sym)
            
    for s in to_close:
        del crypto_open_positions[s]
        
    c_inv = sum(p['shares'] * float(crypto_ind[s].loc[dt, 'close']) for s, p in crypto_open_positions.items() if dt in crypto_ind[s].index)
    c_tot_eq = crypto_cash + c_inv
    crypto_daily_equity.append((dt, c_tot_eq))
    
    if b_c >= b_ema and len(crypto_open_positions) < 2:
        cands = []
        for sym in high_beta_tokens:
            if sym in crypto_open_positions or sym not in crypto_ind or dt not in crypto_ind[sym].index:
                continue
            bar = crypto_ind[sym].loc[dt]
            c_px, rvol, high20 = float(bar['close']), float(bar['rvol']), float(bar['high20'])
            if rvol >= 1.8 and c_px >= high20 * 0.995:
                cands.append((sym, rvol, c_px))
                
        cands.sort(key=lambda x: x[1], reverse=True)
        slots_free = 2 - len(crypto_open_positions)
        slot_budget = c_tot_eq / 2.0
        for sym, rvol, c_px in cands[:slots_free]:
            alloc = min(crypto_cash, slot_budget)
            if alloc >= 200:
                fee = alloc * 0.0020
                shares = (alloc - fee) / (c_px * 1.0010)
                crypto_cash -= alloc
                crypto_open_positions[sym] = {
                    'entry_price': c_px * 1.0010, 'shares': shares,
                    'orig_alloc': alloc,
                    'stop_loss': c_px * (1.0 - 0.065),
                    'days_held': 0, 'partial_booked': False
                }

df_crypto_eq = pd.DataFrame(crypto_daily_equity, columns=['date', 'equity']).set_index('date')
df_crypto_trades = pd.DataFrame(crypto_closed_trades)

# Combined equity
df_comb = pd.DataFrame(index=df_stock_eq.index)
df_comb['stock'] = df_stock_eq['equity']
df_comb['crypto'] = df_crypto_eq['equity'].reindex(df_stock_eq.index).ffill()
df_comb['total'] = df_comb['stock'] + df_comb['crypto']

years = sorted(list(set(df_stock_eq.index.year)))

print("="*105)
print("EXTENSIVE 10-YEAR CONSISTENCY AUDIT: YEAR-BY-YEAR PERFORMANCE (2016-2026)")
print("="*105)

print("\n--- 1. INDIAN EQUITIES SWING (10-Year Calendar Breakdown) ---")
print(f"{'Year':<6} | {'Trades':<6} | {'Win Rate':<8} | {'Avg Win':<8} | {'Avg Loss':<9} | {'Net Return':<10} | {'Max DD':<8} | {'Nifty Context'}")
print("-" * 105)

for y in years:
    y_sub = df_stock_trades[df_stock_trades['year'] == y] if len(df_stock_trades) > 0 else pd.DataFrame()
    y_eq = df_stock_eq[df_stock_eq.index.year == y]['equity']
    if len(y_eq) < 2:
        continue
    ret = (y_eq.iloc[-1] - y_eq.iloc[0]) / y_eq.iloc[0] * 100.0
    pk = y_eq.cummax()
    dd = ((y_eq - pk) / pk).min() * 100.0
    n_tr = len(y_sub)
    if n_tr > 0:
        w_df = y_sub[y_sub['net_pnl'] > 0]
        l_df = y_sub[y_sub['net_pnl'] <= 0]
        wr = len(w_df) / n_tr * 100.0
        aw = w_df['ret_pct'].mean() if len(w_df) > 0 else 0.0
        al = l_df['ret_pct'].mean() if len(l_df) > 0 else 0.0
    else:
        wr = aw = al = 0.0
        
    ctx = "Bull Market" if ret > 15 else ("Sideways/Chop" if ret >= 0 else "Bear/Correction")
    print(f"{y:<6} | {n_tr:<6} | {wr:6.1f}% | {aw:+6.1f}% | {al:7.1f}% | {ret:+9.1f}% | {dd:7.1f}% | {ctx}")

print("\n--- 2. CRYPTO PARABOLIC MOONSHOT (10-Year Calendar Breakdown) ---")
print(f"{'Year':<6} | {'Trades':<6} | {'Win Rate':<8} | {'Avg Win':<8} | {'Avg Loss':<9} | {'Net Return':<10} | {'Max DD':<8} | {'Crypto Regime'}")
print("-" * 105)

for y in years:
    y_sub = df_crypto_trades[df_crypto_trades['year'] == y] if len(df_crypto_trades) > 0 else pd.DataFrame()
    y_eq = df_crypto_eq[df_crypto_eq.index.year == y]['equity']
    if len(y_eq) < 2:
        continue
    ret = (y_eq.iloc[-1] - y_eq.iloc[0]) / y_eq.iloc[0] * 100.0
    pk = y_eq.cummax()
    dd = ((y_eq - pk) / pk).min() * 100.0
    n_tr = len(y_sub)
    if n_tr > 0:
        w_df = y_sub[y_sub['net_pnl'] > 0]
        l_df = y_sub[y_sub['net_pnl'] <= 0]
        wr = len(w_df) / n_tr * 100.0
        aw = w_df['ret_pct'].mean() if len(w_df) > 0 else 0.0
        al = l_df['ret_pct'].mean() if len(l_df) > 0 else 0.0
    else:
        wr = aw = al = 0.0
        
    ctx = "Euphoric Bull" if ret > 50 else ("Consolidation" if ret >= 0 else "Bear Winter (Cash Gate)")
    print(f"{y:<6} | {n_tr:<6} | {wr:6.1f}% | {aw:+6.1f}% | {al:7.1f}% | {ret:+9.1f}% | {dd:7.1f}% | {ctx}")

print("\n--- 3. COMBINED BARBELL PORTFOLIO (Annual Compounding) ---")
print(f"{'Year':<6} | {'Start Value':<12} | {'End Value':<12} | {'Annual Net P&L':<15} | {'Annual Net %':<12} | {'Yearly Result'}")
print("-" * 105)

for y in years:
    y_eq = df_comb[df_comb.index.year == y]['total']
    if len(y_eq) < 2:
        continue
    s_val = y_eq.iloc[0]
    e_val = y_eq.iloc[-1]
    pnl = e_val - s_val
    ret = (pnl / s_val) * 100.0
    res = "PROFITABLE YEAR [GREEN]" if ret > 0 else "LOSS YEAR [RED]"
    print(f"{y:<6} | Rs {s_val:9,.2f} | Rs {e_val:9,.2f} | Rs {pnl:+12,.2f} | {ret:+10.1f}% | {res}")

print("="*105)
