"""
Calculate exact 10-Year (2016-2026) Monthly Return Distributions for:
1. Indian Equities (Optimized 3-Slot Uncapped 10 EMA Runner)
2. Crypto (Parabolic Moonshot High-Beta 15 EMA Runner)
3. Combined Portfolio

Computes:
- Avg monthly return across all 120 months
- Avg winning month (+%)
- Avg losing month (-%)
- Monthly win rate (% of months ending green)
- Worst single month in 10 years
- Best single month in 10 years
- Worst drawdown & consecutive losing months
"""
import os, sys, pickle, numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.costs import compute_indian_delivery_costs

# Load stock & crypto data
with open("data/cache/universe_10y.pkl", "rb") as f:
    univ = pickle.load(f)
with open("data/cache/benchmarks_10y.pkl", "rb") as f:
    bm = pickle.load(f)
with open("data/cache/crypto_10y.pkl", "rb") as f:
    crypto_univ = pickle.load(f)

nifty_df = bm['^NSEI'].copy()
if isinstance(nifty_df.columns, pd.MultiIndex):
    nifty_df.columns = nifty_df.columns.get_level_values(0)
nifty_df['sma50'] = nifty_df['Close'].rolling(50).mean()

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

# 1. Run Stock Simulation
dates = nifty_df.loc["2016-10-24":"2026-10-16"].index
cash = 30000.0
open_positions = {}
stock_equity = []

for i in range(len(dates)):
    dt = dates[i]
    nifty_bar = nifty_df.loc[dt]
    nifty_c = float(nifty_bar['Close'])
    nifty_sma50 = float(nifty_bar['sma50']) if not np.isnan(nifty_bar['sma50']) else 0.0
    
    to_close = []
    for sym, pos in open_positions.items():
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
                cash += (booked_qty * booked_px) - costs.total_friction_rupees
                pos['qty'] -= booked_qty
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
            cash += (pos['qty'] * exit_px) - costs.total_friction_rupees
            to_close.append(sym)
            
    for s in to_close:
        del open_positions[s]
        
    invested = sum(pos['qty'] * (float(stock_ind[sym].loc[dt, 'Close']) if dt in stock_ind[sym].index else pos['entry_price']) for sym, pos in open_positions.items())
    tot_eq = cash + invested
    stock_equity.append((dt, tot_eq))
    
    if nifty_c >= nifty_sma50 and len(open_positions) < 3:
        candidates = []
        for sym, ind in stock_ind.items():
            if sym in open_positions or dt not in ind.index:
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
        slots_free = 3 - len(open_positions)
        slot_budget = tot_eq / 3.0
        for sym, score, entry_px in candidates[:slots_free]:
            alloc = min(cash, slot_budget)
            qty = int(alloc // entry_px)
            if qty > 0 and cash >= (qty * entry_px):
                cash -= (qty * entry_px)
                open_positions[sym] = {
                    'entry_price': entry_px, 'qty': qty,
                    'stop_loss': round(entry_px * 0.955, 2),
                    'target': round(entry_px * 1.15, 2),
                    'days_held': 0, 'partial_booked': False
                }

df_stock_eq = pd.DataFrame(stock_equity, columns=['date', 'equity']).set_index('date')

# 2. Run Crypto Simulation
btc_df = crypto_univ['BTC-USD'].copy()
if isinstance(btc_df.columns, pd.MultiIndex):
    btc_df.columns = btc_df.columns.get_level_values(0)
btc_df.columns = [c.lower() for c in btc_df.columns]
btc_c = btc_df['close'].dropna()
btc_ema50 = btc_c.ewm(span=50, adjust=False).mean()

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

c_dates = btc_c.loc["2016-10-24":"2026-10-16"].index
c_cash = 3000.0
c_positions = {}
crypto_equity = []

for i in range(len(c_dates)):
    dt = c_dates[i]
    b_c = btc_c.loc[dt]
    b_ema = btc_ema50.loc[dt]
    
    # Exits
    to_close = []
    for sym, pos in c_positions.items():
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
            c_cash += net_val
            to_close.append(sym)
            
    for s in to_close:
        del c_positions[s]
        
    c_inv = sum(p['shares'] * float(crypto_ind[s].loc[dt, 'close']) for s, p in c_positions.items() if dt in crypto_ind[s].index)
    c_tot_eq = c_cash + c_inv
    crypto_equity.append((dt, c_tot_eq))
    
    # Entries (only if BTC > 50 EMA)
    if b_c >= b_ema and len(c_positions) < 2:
        cands = []
        for sym in high_beta_tokens:
            if sym in c_positions or sym not in crypto_ind or dt not in crypto_ind[sym].index:
                continue
            bar = crypto_ind[sym].loc[dt]
            c_px, rvol, high20 = float(bar['close']), float(bar['rvol']), float(bar['high20'])
            if rvol >= 1.8 and c_px >= high20 * 0.995:
                cands.append((sym, rvol, c_px))
                
        cands.sort(key=lambda x: x[1], reverse=True)
        slots_free = 2 - len(c_positions)
        slot_budget = c_tot_eq / 2.0
        for sym, rvol, c_px in cands[:slots_free]:
            alloc = min(c_cash, slot_budget)
            if alloc >= 200:
                fee = alloc * 0.0020
                shares = (alloc - fee) / (c_px * 1.0010)
                c_cash -= alloc
                c_positions[sym] = {
                    'entry_price': c_px * 1.0010, 'shares': shares,
                    'stop_loss': c_px * (1.0 - 0.065),
                    'days_held': 0, 'partial_booked': False
                }

df_crypto_eq = pd.DataFrame(crypto_equity, columns=['date', 'equity']).set_index('date')

def analyze_monthly(df, name):
    m_eq = df['equity'].resample('ME').last()
    m_ret = m_eq.pct_change().dropna() * 100.0
    
    total_months = len(m_ret)
    pos_months = m_ret[m_ret > 0]
    neg_months = m_ret[m_ret <= 0]
    
    win_rate = len(pos_months) / total_months * 100.0
    avg_mo = m_ret.mean()
    median_mo = m_ret.median()
    avg_win = pos_months.mean()
    avg_loss = neg_months.mean()
    worst_mo = m_ret.min()
    best_mo = m_ret.max()
    
    # Max consecutive losing months
    is_neg = (m_ret <= 0).astype(int)
    max_consec = 0
    cur_consec = 0
    for v in is_neg:
        if v == 1:
            cur_consec += 1
            max_consec = max(max_consec, cur_consec)
        else:
            cur_consec = 0
            
    print(f"\n[{name}] - Analyzed across {total_months} Months (10 Years)")
    print(f"  Monthly Win Rate:       {win_rate:.1f}% ({len(pos_months)} Green Months / {len(neg_months)} Red Months)")
    print(f"  Average Monthly Return: {avg_mo:+.2f}% (Median: {median_mo:+.2f}%)")
    print(f"  Average Winning Month:  {avg_win:+.2f}%")
    print(f"  Average Losing Month:   {avg_loss:.2f}%")
    print(f"  Worst Month (Worst Case): {worst_mo:.2f}%")
    print(f"  Best Month:             {best_mo:+.2f}%")
    print(f"  Max Consecutive Losses: {max_consec} months")

analyze_monthly(df_stock_eq, "1. INDIAN EQUITIES SWING (10 Years)")
analyze_monthly(df_crypto_eq, "2. CRYPTO PARABOLIC MOONSHOT (10 Years)")

# Combined Barbell Portfolio (Initial: 30k stocks + 3k crypto = 33k total)
df_comb = pd.DataFrame(index=df_stock_eq.index)
df_comb['stock'] = df_stock_eq['equity']
df_comb['crypto'] = df_crypto_eq['equity'].reindex(df_stock_eq.index).ffill()
df_comb['total'] = df_comb['stock'] + df_comb['crypto']
analyze_monthly(pd.DataFrame({'equity': df_comb['total']}), "3. COMBINED BARBELL PORTFOLIO (90% Stocks / 10% Crypto)")
