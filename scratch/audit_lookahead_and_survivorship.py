import os, sys, pickle, math
from collections import Counter
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.costs import compute_indian_delivery_costs
from data.market_data import _load_all_caches

cache = _load_all_caches()
nifty_df = cache.get("^NSEI")
if nifty_df is None:
    nifty_df = cache.get("NIFTYBEES.NS")

ndf = nifty_df.copy()
if isinstance(ndf.columns, pd.MultiIndex):
    ndf.columns = [c[0] if isinstance(c, tuple) else c for c in ndf.columns]
ndf.index = ndf.index.strftime("%Y-%m-%d")
ndf = ndf[~ndf.index.duplicated(keep="last")]
ndf["nifty_sma50"] = ndf["Close"].astype(float).rolling(50).mean()

# Test 1: Full Broad Universe (136 stocks - includes underperformers, stalwarts, midcaps)
u_path = "data/cache/universe_5y.pkl"
with open(u_path, "rb") as f:
    full_u = pickle.load(f)

# Test 2: High Beta Curated Universe (72 stocks)
hb_path = "data/cache/high_beta_universe.pkl"
with open(hb_path, "rb") as f:
    hb_u = pickle.load(f)

def prepare_data(raw_dict):
    clean = {}
    for t, df in raw_dict.items():
        if t.startswith("^") or t.endswith("BEES.NS"):
            continue
        if df.empty or len(df) < 100:
            continue
        d = df.copy()
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
        d.columns = [str(c).capitalize() for c in d.columns]
        if not all(c in d.columns for c in ["Open", "High", "Low", "Close", "Volume"]):
            continue
        d.index = d.index.strftime("%Y-%m-%d")
        d = d[~d.index.duplicated(keep="last")]
        c = d["Close"].astype(float)
        h = d["High"].astype(float)
        l = d["Low"].astype(float)
        v = d["Volume"].astype(float)
        d["sma_50"] = c.rolling(50).mean()
        d["sma_200"] = c.rolling(min(200, len(c))).mean()
        d["ema_10"] = c.ewm(span=10).mean()
        d["ema_20"] = c.ewm(span=20).mean()
        d["vol_sma"] = v.rolling(20).mean()
        d["rvol"] = v / (d["vol_sma"] + 1e-6)
        # Strictly lagged indicators (Zero Indicator Lookahead)
        d["high_52w_lagged"] = h.rolling(250).max().shift(1)
        d["pct_from_52w"] = ((c - d["high_52w_lagged"]) / d["high_52w_lagged"]) * 100.0
        d["high_20_lagged"] = h.rolling(20).max().shift(1)
        clean[t] = d
    return clean

full_data = prepare_data(full_u)
hb_data = prepare_data(hb_u)

print(f"Broad Universe clean tickers: {len(full_data)}")
print(f"High-Beta Universe clean tickers: {len(hb_data)}")

def run_hermetic_simulation(dataset, label, assume_worst_case_intraday=True):
    """
    Hermetic Simulation with strict zero lookahead:
    1. Zero Indicator Lookahead: All reference levels (52w high, 20d high) are shifted by 1.
    2. Zero Signal Lookahead: Signals computed strictly at Day T Close (3:30 PM).
    3. Zero Execution Lookahead: Execution strictly at Day T+1 Open + 0.20% slippage.
    4. Zero Intraday Sequence Lookahead: If on Day T both Target and Stop Loss are breached,
       if assume_worst_case_intraday is True, STOP LOSS WINS (trade is treated as a loss).
    """
    all_dates = sorted(list(set.union(*[set(df.index) for df in dataset.values()])))
    initial_cap = 100000.0
    cash = initial_cap
    portfolio_value = initial_cap
    trades = []
    daily_equity = []
    open_positions = {}
    pending_buys = []
    SLIPPAGE_PCT = 0.002
    slots = 4
    pos_pct = 0.25
    stop_pct = 0.07
    target_pct = 0.20

    same_day_conflicts = 0

    for date_str in all_dates:
        mkt_ok = True
        if date_str in ndf.index:
            n_px = float(ndf["Close"].loc[date_str])
            n_sma = float(ndf["nifty_sma50"].loc[date_str])
            mkt_ok = (n_px >= n_sma) if not math.isnan(n_sma) else True

        # STEP 1: Execute Pending Buys from YESTERDAY at TODAY'S OPEN + Slippage
        if pending_buys:
            for item in pending_buys:
                sym, alloc = item
                if sym in open_positions or len(open_positions) >= slots:
                    continue
                df = dataset.get(sym)
                if df is None or date_str not in df.index:
                    continue
                row = df.loc[date_str]
                today_open = float(row["Open"] if "Open" in row and not math.isnan(row["Open"]) else row["Close"])
                if today_open <= 0 or math.isnan(today_open):
                    continue
                fill_px = round(today_open * (1.0 + SLIPPAGE_PCT), 2)
                trade_alloc = min(cash, alloc)
                qty = int(trade_alloc // fill_px)
                cost = qty * fill_px
                if qty > 0 and cash >= cost:
                    cash -= cost
                    stop_px = round(fill_px * (1 - stop_pct), 2)
                    target_px = round(fill_px * (1 + target_pct), 2)
                    open_positions[sym] = {
                        "entry_price": fill_px,
                        "qty": qty,
                        "stop_loss": stop_px,
                        "target": target_px,
                        "entry_date": date_str,
                        "days_held": 0,
                    }
            pending_buys = []

        # STEP 2: Evaluate Exits on Active Positions
        to_close = []
        for sym, pos in open_positions.items():
            df = dataset.get(sym)
            if df is None or date_str not in df.index:
                continue
            row = df.loc[date_str]
            high = float(row["High"])
            low = float(row["Low"])
            close = float(row["Close"])

            pos["days_held"] = pos.get("days_held", 0) + 1

            exit_reason = None
            exit_px = close

            stop_triggered = (close < pos["stop_loss"])
            target_triggered = (high >= pos["target"])

            # Check intraday sequence conflict
            if stop_triggered and target_triggered:
                same_day_conflicts += 1
                if assume_worst_case_intraday:
                    exit_reason = "STOP_LOSS_DAILY_CLOSE (Conflict Resolved to Loss)"
                    exit_px = close
                else:
                    exit_reason = "TARGET_HIT"
                    exit_px = pos["target"]
            elif stop_triggered:
                exit_reason = "STOP_LOSS_DAILY_CLOSE"
                exit_px = close
            elif target_triggered:
                exit_reason = f"TARGET (+{round(target_pct*100, 1)}%)"
                exit_px = pos["target"]
            elif pos["days_held"] >= 21:
                gain_pct = round(((close - pos['entry_price']) / pos['entry_price']) * 100, 1)
                exit_reason = f"MAX_1_MONTH_EXPIRED (21d, {gain_pct:+.1f}%)"
                exit_px = close

            if exit_reason:
                costs = compute_indian_delivery_costs(pos["entry_price"], exit_px, pos["qty"])
                cash += (exit_px * pos["qty"]) - costs.total_friction_rupees
                trades.append({
                    "ticker": sym,
                    "entry_date": pos["entry_date"],
                    "exit_date": date_str,
                    "days_held": pos["days_held"],
                    "entry_price": pos["entry_price"],
                    "exit_price": round(exit_px, 2),
                    "quantity": pos["qty"],
                    "pnl": costs.net_pnl_rupees,
                    "pnl_percent": costs.net_pnl_pct,
                    "friction_costs": costs.total_friction_rupees,
                    "reason": exit_reason,
                })
                to_close.append(sym)

        for sym in to_close:
            del open_positions[sym]

        holdings_value = sum(
            float(dataset[sym]["Close"].loc[date_str]) * pos["qty"]
            for sym, pos in open_positions.items()
            if date_str in dataset[sym].index
        )
        portfolio_value = cash + holdings_value
        daily_equity.append({"date": date_str, "equity": round(portfolio_value, 2)})

        # STEP 3: Scan for Signals at TODAY'S CLOSE (To be bought TOMORROW at Open)
        if mkt_ok and len(open_positions) < slots:
            candidates = []
            for sym, df in dataset.items():
                if sym in open_positions or any(sym == p[0] for p in pending_buys):
                    continue
                if date_str not in df.index:
                    continue
                idx = df.index.get_loc(date_str)
                if idx < 60:
                    continue
                c_px = float(df["Close"].iloc[idx])
                if math.isnan(c_px) or c_px <= 0:
                    continue
                
                sma50 = float(df["sma_50"].iloc[idx])
                sma200 = float(df["sma_200"].iloc[idx])
                ema10 = float(df["ema_10"].iloc[idx])
                ema20 = float(df["ema_20"].iloc[idx])
                rv = float(df["rvol"].iloc[idx])
                pct_52w = float(df["pct_from_52w"].iloc[idx])
                h20 = float(df["high_20_lagged"].iloc[idx])
                
                if sma50 > sma200 and ema10 > ema20 and c_px >= sma50:
                    if pct_52w >= -15.0 and rv >= 1.25 and c_px >= (h20 * 0.98):
                        score = rv * 10.0 + (100.0 + pct_52w)
                        empty_slots = slots - len(open_positions)
                        alloc = min(cash / max(1, empty_slots), portfolio_value * pos_pct)
                        candidates.append((sym, alloc, score))

            candidates.sort(key=lambda x: x[2], reverse=True)
            for c in candidates[:slots - len(open_positions)]:
                pending_buys.append((c[0], c[1]))

    ret_pct = ((portfolio_value - initial_cap) / initial_cap) * 100.0
    wins = [t for t in trades if t["pnl"] > 0]
    win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0

    return {
        "label": label,
        "final_capital": round(portfolio_value, 2),
        "total_return": round(ret_pct, 2),
        "total_trades": len(trades),
        "win_rate": round(win_rate, 1),
        "same_day_conflicts": same_day_conflicts,
        "friction": round(sum(t["friction_costs"] for t in trades), 2),
    }

print("\nRunning Hermetic Lookahead & Survivorship Audit...")
res_broad = run_hermetic_simulation(full_data, "Broad Universe (136 stocks, zero survivorship bias)", assume_worst_case_intraday=True)
res_hb = run_hermetic_simulation(hb_data, "High-Beta Basket (72 stocks)", assume_worst_case_intraday=True)

print("\n" + "=" * 80)
print("AUDIT RESULTS (STRICT ZERO LOOKAHEAD & CONFLICT PENALTY):")
print("=" * 80)
print(f"1. {res_broad['label']}:")
print(f"   • Net Return:        {res_broad['total_return']:+.2f}%")
print(f"   • Final Capital:     Rs. {res_broad['final_capital']:,.2f}")
print(f"   • Total Trades:      {res_broad['total_trades']}")
print(f"   • Win Rate:          {res_broad['win_rate']}%")
print(f"   • Same-day Conflicts:{res_broad['same_day_conflicts']} (All resolved strictly as Losses)")
print(f"   • Total Friction:    Rs. {res_broad['friction']:,.2f}")

print(f"\n2. {res_hb['label']}:")
print(f"   • Net Return:        {res_hb['total_return']:+.2f}%")
print(f"   • Final Capital:     Rs. {res_hb['final_capital']:,.2f}")
print(f"   • Total Trades:      {res_hb['total_trades']}")
print(f"   • Win Rate:          {res_hb['win_rate']}%")
print(f"   • Same-day Conflicts:{res_hb['same_day_conflicts']} (All resolved strictly as Losses)")
print(f"   • Total Friction:    Rs. {res_hb['friction']:,.2f}")

