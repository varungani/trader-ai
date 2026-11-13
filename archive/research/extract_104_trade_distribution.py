"""
Extract exact trade-level distribution and yearly performance for $104 capital (2 slots @ $52 each).
Computes:
1. Per-trade: Worst, Average Loss, Average Win, Best Trade
2. Monthly expectation: 1-2 trades/month
3. 1-Year outcome across 10 historical years (2016-2026): Worst Year, Median/Avg Year, Best Year
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import yfinance as yf
import pandas as pd
import numpy as np

US_SYMBOLS = [
    "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA",
    "PLTR", "AVGO", "AMD", "QCOM", "ARM", "MU", "TSM", "ASML",
    "COIN", "HOOD", "UBER", "APP", "CRWD", "ANET", "NET", "SNOW", "NOW", "SHOP", "NFLX",
    "QQQ", "SPY", "SMH", "IWM"
]

print("Fetching data to extract exact trade outcomes...")
raw = yf.download(US_SYMBOLS + ["SPY", "QQQ"], period="10y", interval="1d", progress=False, group_by="ticker")

spy_df = raw["SPY"].dropna(subset=["Close", "Volume"]).copy()
if isinstance(spy_df.columns, pd.MultiIndex):
    spy_df.columns = spy_df.columns.get_level_values(0)
spy_df.columns = [c.lower() for c in spy_df.columns]
spy_df["sma50"] = spy_df["close"].rolling(50).mean()

qqq_df = raw["QQQ"].dropna(subset=["Close", "Volume"]).copy()
if isinstance(qqq_df.columns, pd.MultiIndex):
    qqq_df.columns = qqq_df.columns.get_level_values(0)
qqq_df.columns = [c.lower() for c in qqq_df.columns]
qqq_df["sma50"] = qqq_df["close"].rolling(50).mean()

def enrich_stock(df):
    res = df.copy()
    if isinstance(res.columns, pd.MultiIndex):
        res.columns = res.columns.get_level_values(0)
    res.columns = [c.lower() for c in res.columns]
    c, h, l, v = res["close"], res["high"], res["low"], res["volume"]
    res["ema10"] = c.ewm(span=10, adjust=False).mean()
    res["ema15"] = c.ewm(span=15, adjust=False).mean()
    res["ema20"] = c.ewm(span=20, adjust=False).mean()
    res["sma50"] = c.rolling(50).mean()
    res["vol_sma20"] = v.rolling(20).mean()
    res["rvol"] = v / (res["vol_sma20"] + 1e-8)
    res["high20"] = h.rolling(20).max().shift(1)
    res["high10"] = h.rolling(10).max().shift(1)
    
    range_5d = h.rolling(5).max() - l.rolling(5).min()
    range_20d = h.rolling(20).max() - l.rolling(20).min()
    res["vcp_ratio"] = range_5d / (range_20d + 1e-8)
    
    aligned_spy = spy_df["close"].reindex(res.index).ffill()
    base_ratio = c / (aligned_spy + 1e-8)
    sma_base = base_ratio.rolling(50).mean()
    res["mansfield_rs"] = ((base_ratio / (sma_base + 1e-8)) - 1.0) * 100.0
    return res

us_data = {}
for s in US_SYMBOLS:
    try:
        if s in raw.columns.levels[0]:
            df = raw[s].dropna(subset=["Close", "Volume"])
            if len(df) >= 200:
                us_data[s] = enrich_stock(df)
    except Exception:
        pass

# Run 2-slot 15 EMA simulation tracking trade by trade
dates = spy_df.loc["2016-10-24":"2026-10-16"].index
init_cap = 104.0
cash = init_cap
open_positions = {}
closed_trades = []
daily_balance = {}

for dt in dates:
    spy_bar = spy_df.loc[dt]
    spy_c = float(spy_bar["close"])
    spy_sma50 = float(spy_bar["sma50"]) if not np.isnan(spy_bar["sma50"]) else 0.0
    
    qqq_c = float(qqq_df.loc[dt]["close"]) if dt in qqq_df.index else spy_c
    qqq_sma50 = float(qqq_df.loc[dt]["sma50"]) if dt in qqq_df.index and not np.isnan(qqq_df.loc[dt]["sma50"]) else 0.0
    
    gate_pass = (spy_c > spy_sma50) and (qqq_c > qqq_sma50)
    
    # Exits
    to_close = []
    for sym, pos in open_positions.items():
        stock_df = us_data[sym]
        if dt not in stock_df.index:
            pos["days"] += 1
            continue
        bar = stock_df.loc[dt]
        o_px, h_px, l_px, c_px = float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"])
        pos["days"] += 1
        
        exit_reason = None
        exit_px = 0.0
        
        # Hard stop (-5.5%)
        if l_px <= pos["stop_loss"]:
            exit_reason = "STOP_LOSS"
            exit_px = min(pos["stop_loss"], o_px)
        elif not pos["partial_booked"] and h_px >= pos["entry_price"] * 1.18:
            pos["partial_booked"] = True
            booked_qty = pos["shares"] * 0.35
            booked_px = pos["entry_price"] * 1.18
            pos["shares"] -= booked_qty
            cash += (booked_qty * booked_px)
            pos["stop_loss"] = max(pos["stop_loss"], pos["entry_price"])
            
        if exit_reason is None:
            trail_val = float(bar["ema15"])
            if c_px < trail_val and (pos["partial_booked"] or c_px > pos["entry_price"]):
                exit_reason = "TRAIL_15EMA"
                exit_px = c_px
                
        if exit_reason is None and pos["days"] >= 45:
            exit_reason = "TIME_STOP"
            exit_px = c_px
            
        if exit_reason:
            cash += pos["shares"] * exit_px
            pnl_pct = ((exit_px - pos["entry_price"]) / pos["entry_price"]) * 100.0
            pnl_usd = (pos["shares"] * exit_px) - (pos["entry_cost"] * (pos["shares"] / (pos["initial_shares"] + 1e-8)))
            closed_trades.append({
                "symbol": sym,
                "entry_date": str(pos["entry_date"])[:10],
                "exit_date": str(dt)[:10],
                "year": dt.year,
                "pct_return": pnl_pct,
                "entry_cost": pos["entry_cost"],
                "reason": exit_reason,
                "days": pos["days"]
            })
            to_close.append(sym)
            
    for sym in to_close:
        del open_positions[sym]
        
    # Entries
    available_slots = 2 - len(open_positions)
    if available_slots > 0 and gate_pass:
        candidates = []
        for sym, stock_df in us_data.items():
            if sym in open_positions or dt not in stock_df.index:
                continue
            bar = stock_df.loc[dt]
            c_px = float(bar["close"])
            ema20 = float(bar["ema20"])
            sma50 = float(bar["sma50"])
            high20 = float(bar["high20"]) if not np.isnan(bar["high20"]) else 0.0
            rvol = float(bar["rvol"]) if not np.isnan(bar["rvol"]) else 1.0
            m_rs = float(bar["mansfield_rs"]) if not np.isnan(bar["mansfield_rs"]) else 0.0
            vcp = float(bar["vcp_ratio"]) if not np.isnan(bar["vcp_ratio"]) else 1.0
            
            if c_px > ema20 and ema20 > sma50 and c_px >= high20 * 0.99 and m_rs >= 2.0 and rvol >= 1.25:
                score = m_rs + (rvol * 10.0) + ((1.0 - vcp) * 15.0)
                candidates.append((sym, score, c_px))
                
        candidates.sort(key=lambda x: x[1], reverse=True)
        
        # Portfolio value
        port_val = cash + sum(p["shares"] * float(us_data[s].loc[dt]["close"]) if dt in us_data[s].index else p["shares"] * p["entry_price"] for s, p in open_positions.items())
        slot_size = port_val / 2.0
        
        for sym, score, c_px in candidates[:available_slots]:
            invest = min(cash, slot_size)
            if invest >= 10.0:
                shares = invest / c_px
                cash -= invest
                open_positions[sym] = {
                    "entry_date": dt,
                    "entry_price": c_px,
                    "shares": shares,
                    "initial_shares": shares,
                    "entry_cost": invest,
                    "stop_loss": c_px * 0.945,
                    "days": 0,
                    "partial_booked": False
                }
                
    port_equity = cash + sum(p["shares"] * float(us_data[s].loc[dt]["close"]) if dt in us_data[s].index else p["shares"] * p["entry_price"] for s, p in open_positions.items())
    daily_balance[dt] = port_equity

df_tr = pd.DataFrame(closed_trades)
print(f"Total Closed Trades: {len(df_tr)}")

# Distribution stats
wins = df_tr[df_tr["pct_return"] > 0]
losses = df_tr[df_tr["pct_return"] <= 0]

print("\n--- PER TRADE OUTCOMES (ON A $52 SLOT) ---")
worst_loss_pct = df_tr["pct_return"].min()
avg_loss_pct = losses["pct_return"].mean()
median_loss_pct = losses["pct_return"].median()

worst_loss_usd = 52.0 * (worst_loss_pct / 100.0)
avg_loss_usd = 52.0 * (avg_loss_pct / 100.0)

avg_win_pct = wins["pct_return"].mean()
median_win_pct = wins["pct_return"].median()
avg_win_usd = 52.0 * (avg_win_pct / 100.0)
median_win_usd = 52.0 * (median_win_pct / 100.0)

top_10pct_pct = wins["pct_return"].quantile(0.90)
top_10pct_usd = 52.0 * (top_10pct_pct / 100.0)

best_trade_pct = df_tr["pct_return"].max()
best_trade_usd = 52.0 * (best_trade_pct / 100.0)

print(f"WORST Trade:        {worst_loss_pct:+.2f}%  ->  ${worst_loss_usd:+.2f} (Rs {worst_loss_usd * 86.50:+.2f})")
print(f"AVERAGE Loss:       {avg_loss_pct:+.2f}%  ->  ${avg_loss_usd:+.2f} (Rs {avg_loss_usd * 86.50:+.2f})")
print(f"MEDIAN Win:         {median_win_pct:+.2f}%  ->  ${median_win_usd:+.2f} (Rs {median_win_usd * 86.50:+.2f})")
print(f"AVERAGE Win:        {avg_win_pct:+.2f}%  ->  ${avg_win_usd:+.2f} (Rs {avg_win_usd * 86.50:+.2f})")
print(f"TOP 10% Monster Win:{top_10pct_pct:+.2f}%  ->  ${top_10pct_usd:+.2f} (Rs {top_10pct_usd * 86.50:+.2f})")
print(f"BEST Single Trade:  {best_trade_pct:+.2f}%  ->  ${best_trade_usd:+.2f} (Rs {best_trade_usd * 86.50:+.2f})")

# Yearly stats
s_bal = pd.Series(daily_balance)
yearly_ret = s_bal.resample("YE").last().pct_change() * 100.0
# Include first year
first_yr_ret = ((s_bal.loc["2016-10-24":"2016-12-31"].iloc[-1] - 104.0) / 104.0) * 100.0
print("\n--- YEARLY PERFORMANCE RANGE (OVER 10 YEARS) ---")
print(yearly_ret.dropna().describe())
for yr, ret in yearly_ret.dropna().items():
    print(f"  {yr.year}: {ret:+.1f}%")
