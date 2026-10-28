"""
Test and Optimize 10-Year Strategy for US Equities (INDmoney / Wall St Universe).
Tests:
1. Baseline: Fixed 15% Target
2. Optimized: Uncapped 10 EMA Trailing Runner (Scale 35% @ +18%)
3. S&P 500 / Nasdaq Macro Gate (SPY > 50 SMA)
"""
import yfinance as yf
import pandas as pd
import numpy as np

US_SYMBOLS = [
    "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA",
    "PLTR", "AVGO", "AMD", "QCOM", "ARM", "MU", "TSM", "ASML",
    "COIN", "HOOD", "UBER", "APP", "CRWD", "ANET", "NET", "SNOW", "NOW", "SHOP", "NFLX",
    "QQQ", "SPY", "SMH", "IWM"
]

print("Downloading 10-year historical data for US Equities & S&P 500 Benchmark...")
raw = yf.download(US_SYMBOLS + ["SPY"], period="10y", interval="1d", progress=False, group_by="ticker")

spy_df = raw["SPY"].dropna(subset=["Close", "Volume"]).copy()
if isinstance(spy_df.columns, pd.MultiIndex):
    spy_df.columns = spy_df.columns.get_level_values(0)
spy_df.columns = [c.lower() for c in spy_df.columns]
spy_df["sma50"] = spy_df["close"].rolling(50).mean()

def enrich_us_stock(df):
    res = df.copy()
    if isinstance(res.columns, pd.MultiIndex):
        res.columns = res.columns.get_level_values(0)
    res.columns = [c.lower() for c in res.columns]
    c, h, l, v = res["close"], res["high"], res["low"], res["volume"]
    res["ema10"] = c.ewm(span=10, adjust=False).mean()
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
    
    aligned_spy = spy_df["close"].reindex(res.index).ffill()
    base_ratio = c / (aligned_spy + 1e-8)
    sma_base = base_ratio.rolling(50).mean()
    res["mansfield_rs"] = ((base_ratio / (sma_base + 1e-8)) - 1.0) * 100.0
    return res

us_ind = {}
for s in US_SYMBOLS:
    try:
        if s in raw.columns.levels[0]:
            df = raw[s].dropna(subset=["Close", "Volume"])
            if len(df) >= 200:
                us_ind[s] = enrich_us_stock(df)
    except Exception:
        pass

print(f"Processed indicators for {len(us_ind)} US Equities.")

def simulate_us_strategy(name, trail_ema=True, max_slots=3, pt1=0.18, stop_pct=0.055):
    dates = spy_df.loc["2016-10-24":"2026-10-16"].index
    init_cap = 5000.0  # $5,000 USD seed (approx Rs 4.3 Lakhs)
    cash = init_cap
    open_positions = {}
    closed_trades = []
    equity_curve = []
    
    for dt in dates:
        spy_bar = spy_df.loc[dt]
        spy_c = float(spy_bar["close"])
        spy_sma50 = float(spy_bar["sma50"]) if not np.isnan(spy_bar["sma50"]) else 0.0
        
        # Exits
        to_close = []
        for sym, pos in open_positions.items():
            ind = us_ind[sym]
            if dt not in ind.index:
                pos["days"] += 1
                continue
            bar = ind.loc[dt]
            o_px, h_px, l_px, c_px = float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"])
            pos["days"] += 1
            
            exit_reason = None
            exit_px = 0.0
            
            # Hard stop
            if l_px <= pos["stop_loss"]:
                exit_reason = "STOP_LOSS"
                exit_px = min(pos["stop_loss"], o_px)
            # Partial scale-out at pt1 (+18%)
            elif not pos["partial_booked"] and h_px >= pos["entry_price"] * (1.0 + pt1):
                pos["partial_booked"] = True
                booked_qty = pos["shares"] * 0.35
                booked_px = pos["entry_price"] * (1.0 + pt1)
                # SEC fee + FINRA TAF ($0.0001 per share)
                fee = (booked_qty * booked_px) * 0.0002
                cash += (booked_qty * booked_px) - fee
                pos["shares"] -= booked_qty
                pos["realized_partial"] = ((booked_px - pos["entry_price"]) * booked_qty) - fee
                pos["stop_loss"] = pos["entry_price"] * 1.01 # Breakeven stop
            # Trailing 10 EMA exit
            elif trail_ema and pos["partial_booked"] and c_px < float(bar["ema10"]):
                exit_reason = "10_EMA_TRAIL"
                exit_px = c_px
            elif not trail_ema and h_px >= pos["entry_price"] * 1.18:
                exit_reason = "TARGET_18%"
                exit_px = pos["entry_price"] * 1.18
            elif pos["days"] >= 10 and abs((c_px - pos["entry_price"]) / pos["entry_price"]) <= 0.02:
                exit_reason = "STAGNATION_10D"
                exit_px = c_px
            elif pos["days"] >= 28:
                exit_reason = "TIME_STOP_28D"
                exit_px = c_px
                
            if exit_reason:
                fee = (pos["shares"] * exit_px) * 0.0002
                net_val = (pos["shares"] * exit_px) - fee
                tot_pnl = (net_val - (pos["shares"] * pos["entry_price"])) + pos.get("realized_partial", 0.0)
                tot_orig_cost = pos["orig_alloc"]
                closed_trades.append({
                    "ticker": sym, "pnl": tot_pnl, "ret": (tot_pnl / tot_orig_cost) * 100.0,
                    "reason": exit_reason, "days": pos["days"]
                })
                cash += net_val
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        inv = sum(p["shares"] * (float(us_ind[s].loc[dt, "close"]) if dt in us_ind[s].index else p["entry_price"]) for s, p in open_positions.items())
        tot_eq = cash + inv
        equity_curve.append((dt, tot_eq))
        
        # Macro Gate (SPY > 50 SMA)
        if spy_c < spy_sma50:
            continue
            
        # Entries
        if len(open_positions) < max_slots:
            cands = []
            for sym, ind in us_ind.items():
                if sym in open_positions or dt not in ind.index:
                    continue
                bar = ind.loc[dt]
                c_px, sma50, sma200, rvol, vcp, high20, ret_6m, m_rs = (
                    float(bar["close"]), float(bar["sma50"]), float(bar["sma200"]),
                    float(bar["rvol"]), float(bar["vcp_ratio"]), float(bar["high20"]),
                    float(bar["ret_6m"]), float(bar["mansfield_rs"])
                )
                if c_px <= sma50 or sma50 <= sma200 or ret_6m <= 0.05:
                    continue
                if vcp <= 0.70 and rvol >= 1.5 and c_px >= high20 * 0.995:
                    score = (1.0 - vcp) * 10.0 + rvol + (m_rs / 10.0)
                    cands.append((sym, score, c_px))
                    
            cands.sort(key=lambda x: x[1], reverse=True)
            slots_free = max_slots - len(open_positions)
            slot_budget = tot_eq / max_slots
            
            for sym, score, entry_px in cands[:slots_free]:
                alloc = min(cash, slot_budget)
                if alloc >= 300:
                    shares = alloc / entry_px
                    cash -= alloc
                    open_positions[sym] = {
                        "entry_price": entry_px, "shares": shares, "orig_alloc": alloc,
                        "stop_loss": round(entry_px * (1.0 - stop_pct), 2),
                        "days": 0, "partial_booked": False, "realized_partial": 0.0
                    }
                    
    df_eq = pd.DataFrame(equity_curve, columns=["date", "equity"]).set_index("date")
    fin_eq = df_eq["equity"].iloc[-1]
    net_p = fin_eq - init_cap
    net_r = (net_p / init_cap) * 100.0
    cagr = ((fin_eq / init_cap) ** (1.0 / 10.0) - 1.0) * 100.0
    pk = df_eq["equity"].cummax()
    max_dd = ((df_eq["equity"] - pk) / pk).min() * 100.0
    
    tdf = pd.DataFrame(closed_trades)
    wr = len(tdf[tdf["pnl"] > 0]) / len(tdf) * 100.0
    pf = tdf[tdf["pnl"] > 0]["pnl"].sum() / abs(tdf[tdf["pnl"] <= 0]["pnl"].sum())
    avg_w = tdf[tdf["pnl"] > 0]["ret"].mean()
    avg_l = tdf[tdf["pnl"] <= 0]["ret"].mean()
    best_t = tdf["ret"].max()
    
    print(f"\n[{name}]")
    print(f"  Final Equity: ${fin_eq:10,.2f} (+{net_r:.1f}% | CAGR: {cagr:.1f}%) | Net P&L: ${net_p:+,.2f}")
    print(f"  Trades: {len(tdf)} | Win Rate: {wr:.1f}% | Profit Factor: {pf:.2f} | Max DD: {max_dd:.1f}%")
    print(f"  Avg Win: {avg_w:+.1f}% | Avg Loss: {avg_l:.1f}% | Best Trade: {best_t:+.1f}%")

print("="*85)
print("10-YEAR US EQUITIES STRATEGY AUDIT (2016-2026)")
print("Initial Capital: $5,000 USD (INDmoney Traded Universe)")
print("="*85)

simulate_us_strategy("1. Baseline: Fixed 18% Target (No Trailing Runner)", trail_ema=False, max_slots=3)
simulate_us_strategy("2. OPTIMIZED: Uncapped 10 EMA Trailing Runner (Scale 35% @ +18%)", trail_ema=True, max_slots=3)
simulate_us_strategy("3. HIGH-VELOCITY 2-BULLET CONCENTRATION (50% each | 10 EMA Trail)", trail_ema=True, max_slots=2)
