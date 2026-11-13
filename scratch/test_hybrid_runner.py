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

# Load clean datasets
data_by_ticker = {}
for t, df in cache.items():
    if t.startswith("^") or t.endswith("BEES.NS"):
        continue
    if not df.empty and len(df) >= 150:
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
        d["high_52w"] = h.rolling(250).max().shift(1)
        d["pct_from_52w"] = ((c - d["high_52w"]) / d["high_52w"]) * 100.0
        d["high_20"] = h.rolling(20).max().shift(1)
        data_by_ticker[t] = d

all_dates = sorted(list(set.union(*[set(df.index) for df in data_by_ticker.values()])))

def run_hybrid_engine(core_lock_pct=0.70, free_runner_pct=0.30):
    initial_cap = 100000.0
    cash = initial_cap
    portfolio_value = initial_cap
    trades = []
    daily_equity = []
    open_positions = {}
    pending_buys = []
    slots = 4
    pos_pct = 0.25
    SLIPPAGE_PCT = 0.002

    for date_str in all_dates:
        mkt_ok = True
        if date_str in ndf.index:
            n_px = float(ndf["Close"].loc[date_str])
            n_sma = float(ndf["nifty_sma50"].loc[date_str])
            mkt_ok = (n_px >= n_sma) if not math.isnan(n_sma) else True

        # Open fills
        if pending_buys:
            for item in pending_buys:
                sym, alloc = item
                if sym in open_positions or len(open_positions) >= slots:
                    continue
                df = data_by_ticker.get(sym)
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
                    stop_px = round(fill_px * 0.93, 2)
                    target_px = round(fill_px * 1.20, 2)
                    open_positions[sym] = {
                        "entry_price": fill_px,
                        "qty": qty,
                        "orig_qty": qty,
                        "stop_loss": stop_px,
                        "target": target_px,
                        "entry_date": date_str,
                        "peak_price": fill_px,
                        "days_held": 0,
                        "is_free_runner": False,
                        "core_locked": False,
                    }
            pending_buys = []

        # Exits
        to_close = []
        for sym, pos in open_positions.items():
            df = data_by_ticker.get(sym)
            if df is None or date_str not in df.index:
                continue
            row = df.loc[date_str]
            high = float(row["High"])
            close = float(row["Close"])
            ema20 = float(row["ema_20"])

            pos["days_held"] = pos.get("days_held", 0) + 1
            pos["peak_price"] = max(pos.get("peak_price", pos["entry_price"]), high)

            # Hit Target 1 (+20% in <= 21 days): Lock 70% Core Profit, Keep 30% as Free Runner!
            if not pos["core_locked"] and high >= pos["target"]:
                lock_qty = int(pos["orig_qty"] * core_lock_pct)
                if lock_qty > 0:
                    exit_px = pos["target"]
                    costs = compute_indian_delivery_costs(pos["entry_price"], exit_px, lock_qty)
                    cash += (exit_px * lock_qty) - costs.total_friction_rupees
                    trades.append({
                        "ticker": sym,
                        "entry_date": pos["entry_date"],
                        "exit_date": date_str,
                        "days_held": pos["days_held"],
                        "entry_price": pos["entry_price"],
                        "exit_price": round(exit_px, 2),
                        "quantity": lock_qty,
                        "pnl": costs.net_pnl_rupees,
                        "pnl_percent": costs.net_pnl_pct,
                        "friction_costs": costs.total_friction_rupees,
                        "reason": "TARGET_1_CORE_LOCK (+20.0%)",
                    })
                    pos["qty"] -= lock_qty
                pos["core_locked"] = True
                pos["is_free_runner"] = True
                # Move stop on the remaining 30% to breakeven + 5%
                pos["stop_loss"] = max(pos["stop_loss"], round(pos["entry_price"] * 1.05, 2))

            exit_reason = None
            exit_px = close

            # For Free Runners: Trail stop behind 20 EMA, NO 21-day time limit!
            if pos["is_free_runner"]:
                if close < ema20:
                    gain_pct = round(((close - pos['entry_price']) / pos['entry_price']) * 100, 1)
                    exit_reason = f"FREE_RUNNER_EMA20_EXIT ({pos['days_held']}d, {gain_pct:+.1f}%)"
                    exit_px = close
            else:
                # Standard swing rule: Stop loss on close or 21-day ceiling
                if close < pos["stop_loss"]:
                    exit_reason = "STOP_LOSS_DAILY_CLOSE"
                    exit_px = close
                elif pos["days_held"] >= 21:
                    gain_pct = round(((close - pos['entry_price']) / pos['entry_price']) * 100, 1)
                    exit_reason = f"MAX_1_MONTH_EXPIRED (21d, {gain_pct:+.1f}%)"
                    exit_px = close

            if exit_reason and pos["qty"] > 0:
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
            float(data_by_ticker[sym]["Close"].loc[date_str]) * pos["qty"]
            for sym, pos in open_positions.items()
            if date_str in data_by_ticker[sym].index
        )
        portfolio_value = cash + holdings_value
        daily_equity.append({"date": date_str, "equity": round(portfolio_value, 2)})

        # Scan for entries
        if mkt_ok and len(open_positions) < slots:
            candidates = []
            for sym, df in data_by_ticker.items():
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
                h20 = float(df["high_20"].iloc[idx])
                
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
        "final_capital": round(portfolio_value, 2),
        "total_return": round(ret_pct, 2),
        "total_trades": len(trades),
        "win_rate": round(win_rate, 1),
        "friction": round(sum(t["friction_costs"] for t in trades), 2),
        "trades": trades,
    }

res_hyb = run_hybrid_engine()
print(f"Hybrid Engine Result:")
print(f"• Final Capital: Rs. {res_hyb['final_capital']:,.2f} ({res_hyb['total_return']:+.2f}%)")
print(f"• Total Trades:  {res_hyb['total_trades']}")
print(f"• Win Rate:      {res_hyb['win_rate']}%")
print(f"• Total Taxes:   Rs. {res_hyb['friction']:,.2f}")

print("\n--- SAMPLE FREE RUNNER TRADES THAT RODE MULTI-MONTH WAVES ---")
tdf = pd.DataFrame(res_hyb["trades"])
runners = tdf[tdf["reason"].str.contains("FREE_RUNNER")]
print(f"Total Free Runners unleashed: {len(runners)}")
print(runners.sort_values(by="pnl_percent", ascending=False).head(10)[["ticker", "entry_date", "exit_date", "days_held", "pnl_percent", "pnl"]].to_string())

