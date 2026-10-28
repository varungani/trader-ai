"""
Empirical Pattern Exploration & Profit Optimization for US Equities (INDmoney Universe)
Tests 10-Year Historical Data (2016 - 2026):
1. Macro Gate: Dual SPY & QQQ > 50 SMA vs SPY only vs No gate
2. Trailing Runners: Fixed 18% target vs 10 EMA Trail vs 15 EMA Trail vs ATR Chandelier
3. Slot Sizing: 2-slot Bullet (50% each) vs 3-slot Balanced (33% each) vs 4-slot Conservative (25% each)
4. Mansfield RS & RVOL Edge verification
"""
import sys
import yfinance as yf
import pandas as pd
import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

US_SYMBOLS = [
    "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA",
    "PLTR", "AVGO", "AMD", "QCOM", "ARM", "MU", "TSM", "ASML",
    "COIN", "HOOD", "UBER", "APP", "CRWD", "ANET", "NET", "SNOW", "NOW", "SHOP", "NFLX",
    "QQQ", "SPY", "SMH", "IWM"
]

print("Fetching 10-year daily data for 30 US equities + SPY + QQQ...")
raw = yf.download(US_SYMBOLS + ["SPY", "QQQ"], period="10y", interval="1d", progress=False, group_by="ticker")

# Process Benchmarks
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
    res["sma200"] = c.rolling(200).mean()
    res["vol_sma20"] = v.rolling(20).mean()
    res["rvol"] = v / (res["vol_sma20"] + 1e-8)
    res["high20"] = h.rolling(20).max().shift(1)
    res["high10"] = h.rolling(10).max().shift(1)
    
    # ATR
    tr1 = h - l
    tr2 = (h - c.shift(1)).abs()
    tr3 = (l - c.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    res["atr14"] = tr.rolling(14).mean()
    
    # Range contraction
    range_5d = h.rolling(5).max() - l.rolling(5).min()
    range_20d = h.rolling(20).max() - l.rolling(20).min()
    res["vcp_ratio"] = range_5d / (range_20d + 1e-8)
    
    # Mansfield RS vs SPY
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

print(f"Enriched {len(us_data)} US Equities with 10-year technical & Mansfield indicators.")

def run_simulation(
    trail_type="ema10",  # "fixed", "ema10", "ema15"
    slots=3,
    macro_gate="dual",   # "none", "spy", "dual"
    rvol_filter=True,
    min_rs=0.0,
    stop_pct=0.055,
    partial_target=0.18,
    partial_scale=0.35
):
    dates = spy_df.loc["2016-10-24":"2026-10-16"].index
    init_cap = 5000.0  # $5,000 USD
    cash = init_cap
    open_positions = {}
    closed_trades = []
    equity_curve = []
    
    for dt in dates:
        spy_bar = spy_df.loc[dt]
        spy_c = float(spy_bar["close"])
        spy_sma50 = float(spy_bar["sma50"]) if not np.isnan(spy_bar["sma50"]) else 0.0
        
        qqq_c = float(qqq_df.loc[dt]["close"]) if dt in qqq_df.index else spy_c
        qqq_sma50 = float(qqq_df.loc[dt]["sma50"]) if dt in qqq_df.index and not np.isnan(qqq_df.loc[dt]["sma50"]) else 0.0
        
        # Macro Gate Check
        if macro_gate == "dual":
            gate_pass = (spy_c > spy_sma50) and (qqq_c > qqq_sma50)
        elif macro_gate == "spy":
            gate_pass = (spy_c > spy_sma50)
        else:
            gate_pass = True
            
        # 1. Manage Exits
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
            
            # Hard Stop (-5.5%)
            if l_px <= pos["stop_loss"]:
                exit_reason = "STOP_LOSS"
                exit_px = min(pos["stop_loss"], o_px)
            # Partial scale-out at Target 1 (+18%)
            elif not pos["partial_booked"] and h_px >= pos["entry_price"] * (1.0 + partial_target):
                pos["partial_booked"] = True
                booked_qty = pos["shares"] * partial_scale
                booked_px = pos["entry_price"] * (1.0 + partial_target)
                pos["shares"] -= booked_qty
                fee = (booked_qty * booked_px * 0.0000278) + (booked_qty * 0.0001)
                net_proceeds = (booked_qty * booked_px) - fee
                cash += net_proceeds
                pos["stop_loss"] = max(pos["stop_loss"], pos["entry_price"])  # Move stop to breakeven
                
            # Trailing Exit
            if exit_reason is None and trail_type != "fixed":
                trail_val = float(bar[trail_type])
                # Only trail runner once above entry
                if c_px < trail_val and (pos["partial_booked"] or c_px > pos["entry_price"]):
                    exit_reason = f"TRAIL_{trail_type.upper()}"
                    exit_px = c_px
            elif exit_reason is None and trail_type == "fixed":
                if h_px >= pos["entry_price"] * (1.0 + partial_target):
                    exit_reason = "FIXED_TARGET"
                    exit_px = pos["entry_price"] * (1.0 + partial_target)
                    
            # Max hold 45 days
            if exit_reason is None and pos["days"] >= 45:
                exit_reason = "TIME_STOP"
                exit_px = c_px
                
            if exit_reason:
                fee = (pos["shares"] * exit_px * 0.0000278) + (pos["shares"] * 0.0001)
                net_proceeds = (pos["shares"] * exit_px) - fee
                cash += net_proceeds
                
                tot_pnl = (cash + sum(p["shares"] * p["entry_price"] for s, p in open_positions.items() if s != sym)) - init_cap
                pct_return = ((exit_px - pos["entry_price"]) / pos["entry_price"]) * 100.0
                closed_trades.append({
                    "symbol": sym,
                    "entry_date": pos["entry_date"],
                    "exit_date": dt,
                    "pct_return": pct_return,
                    "reason": exit_reason,
                    "days": pos["days"]
                })
                to_close.append(sym)
            else:
                if trail_type != "fixed" and pos["partial_booked"]:
                    pos["stop_loss"] = max(pos["stop_loss"], float(bar[trail_type]) * 0.99)
                    
        for sym in to_close:
            del open_positions[sym]
            
        # 2. Candidate Entries
        available_slots = slots - len(open_positions)
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
                
                # Setup Criteria:
                # 1. Price > 20 EMA > 50 SMA
                # 2. Breakout: Close within 1% of 20-day high or breaking out
                # 3. Mansfield RS vs SPY > min_rs
                # 4. RVOL >= 1.2 if rvol_filter
                cond1 = c_px > ema20 and ema20 > sma50
                cond2 = c_px >= high20 * 0.99
                cond3 = m_rs >= min_rs
                cond4 = (rvol >= 1.25) if rvol_filter else True
                
                if cond1 and cond2 and cond3 and cond4:
                    score = m_rs + (rvol * 10.0) + ((1.0 - vcp) * 15.0)
                    candidates.append((sym, score, c_px))
                    
            candidates.sort(key=lambda x: x[1], reverse=True)
            
            # Current portfolio value
            port_val = cash
            for sym, pos in open_positions.items():
                if dt in us_data[sym].index:
                    port_val += pos["shares"] * float(us_data[sym].loc[dt]["close"])
                else:
                    port_val += pos["shares"] * pos["entry_price"]
                    
            slot_size = port_val / slots
            for sym, score, c_px in candidates[:available_slots]:
                invest_usd = min(cash, slot_size)
                if invest_usd >= 100.0:
                    shares = invest_usd / c_px
                    fee = (shares * c_px * 0.0000278) + (shares * 0.0001)
                    cash -= (invest_usd + fee)
                    open_positions[sym] = {
                        "entry_date": dt,
                        "entry_price": c_px,
                        "shares": shares,
                        "stop_loss": c_px * (1.0 - stop_pct),
                        "days": 0,
                        "partial_booked": False
                    }
                    
        # Track Equity Curve
        curr_equity = cash
        for sym, pos in open_positions.items():
            if dt in us_data[sym].index:
                curr_equity += pos["shares"] * float(us_data[sym].loc[dt]["close"])
            else:
                curr_equity += pos["shares"] * pos["entry_price"]
        equity_curve.append(curr_equity)
        
    final_cap = equity_curve[-1] if equity_curve else init_cap
    tot_ret = ((final_cap - init_cap) / init_cap) * 100.0
    cagr = ((final_cap / init_cap) ** (1.0 / 10.0) - 1.0) * 100.0
    
    # Drawdown
    eq_series = pd.Series(equity_curve)
    peak = eq_series.cummax()
    dd = (eq_series - peak) / peak
    max_dd = dd.min() * 100.0
    
    # Trade statistics
    if closed_trades:
        df_tr = pd.DataFrame(closed_trades)
        wins = df_tr[df_tr["pct_return"] > 0]
        losses = df_tr[df_tr["pct_return"] <= 0]
        win_rate = (len(wins) / len(df_tr)) * 100.0
        gross_win = wins["pct_return"].sum()
        gross_loss = abs(losses["pct_return"].sum()) if len(losses) > 0 else 1.0
        pf = gross_win / (gross_loss + 1e-8)
        avg_win = wins["pct_return"].mean() if len(wins) > 0 else 0.0
        avg_loss = losses["pct_return"].mean() if len(losses) > 0 else 0.0
        best_trade = df_tr["pct_return"].max()
    else:
        win_rate = pf = avg_win = avg_loss = best_trade = 0.0
        df_tr = pd.DataFrame()
        
    return {
        "final_capital": final_cap,
        "net_return": tot_ret,
        "cagr": cagr,
        "max_dd": max_dd,
        "trades": len(closed_trades),
        "win_rate": win_rate,
        "pf": pf,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "best_trade": best_trade
    }

print("\n" + "="*85)
print("10-YEAR US EQUITIES SYSTEMATIC TOURNAMENT & PATTERN EXPLORATION (2016-2026)")
print("="*85)

configs = [
    ("1. Fixed Target Baseline (18% Flat, 3 Slots, No Macro)", dict(trail_type="fixed", slots=3, macro_gate="none", rvol_filter=False)),
    ("2. Fixed Target + SPY Macro Gate (3 Slots)", dict(trail_type="fixed", slots=3, macro_gate="spy", rvol_filter=False)),
    ("3. 10 EMA Trailing Runner + SPY Macro Gate (3 Slots)", dict(trail_type="ema10", slots=3, macro_gate="spy", rvol_filter=False)),
    ("4. 10 EMA Trailing Runner + Dual SPY & QQQ Gate (3 Slots)", dict(trail_type="ema10", slots=3, macro_gate="dual", rvol_filter=False)),
    ("5. 10 EMA Trail + Dual Gate + RVOL & RS Filter (3 Slots)", dict(trail_type="ema10", slots=3, macro_gate="dual", rvol_filter=True, min_rs=2.0)),
    ("6. 15 EMA Wide Runner + Dual Gate + RVOL & RS (3 Slots)", dict(trail_type="ema15", slots=3, macro_gate="dual", rvol_filter=True, min_rs=2.0)),
    ("7. Bullet Concentrated (2 Slots @ 50% | 10 EMA Trail | Dual Gate)", dict(trail_type="ema10", slots=2, macro_gate="dual", rvol_filter=True, min_rs=2.0)),
    ("8. Ultra Concentrated Bullet (2 Slots @ 50% | 15 EMA Trail | Dual Gate)", dict(trail_type="ema15", slots=2, macro_gate="dual", rvol_filter=True, min_rs=2.0)),
]

results = []
for label, cfg in configs:
    res = run_simulation(**cfg)
    results.append((label, res))
    print(f"\n>>> {label}:")
    print(f"    Final Capital: ${res['final_capital']:,.2f} on $5,000 seed")
    print(f"    Net Return: +{res['net_return']:.1f}% | CAGR: {res['cagr']:.1f}% | Max DD: {res['max_dd']:.1f}%")
    print(f"    Total Trades: {res['trades']} | Win Rate: {res['win_rate']:.1f}% | Profit Factor: {res['pf']:.2f}")
    print(f"    Avg Win: +{res['avg_win']:.1f}% | Avg Loss: {res['avg_loss']:.1f}% | Best Trade: +{res['best_trade']:.1f}%")

print("\n" + "="*85)
print("AUDIT SUMMARY COMPLETE")
print("="*85)
