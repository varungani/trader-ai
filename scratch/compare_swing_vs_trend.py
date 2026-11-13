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

def test_simulation(mode="1_MONTH_MAX_HOLD"):
    """
    mode = '1_MONTH_MAX_HOLD': Capped strictly at 21 market sessions (~30 calendar days).
    mode = 'MULTI_BAGGER_TREND_RIDER': No arbitrary time limit! Ride the trend with 20 EMA / 50 SMA trailing stops.
    """
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
                    open_positions[sym] = {
                        "entry_price": fill_px,
                        "qty": qty,
                        "stop_loss": stop_px,
                        "target": round(fill_px * 1.20, 2),
                        "entry_date": date_str,
                        "peak_price": fill_px,
                        "days_held": 0,
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
            sma50 = float(row["sma_50"])

            pos["days_held"] = pos.get("days_held", 0) + 1
            pos["peak_price"] = max(pos.get("peak_price", pos["entry_price"]), high)

            exit_reason = None
            exit_px = close

            if mode == "1_MONTH_MAX_HOLD":
                if close < pos["stop_loss"]:
                    exit_reason = "STOP_LOSS_DAILY_CLOSE"
                    exit_px = close
                elif high >= pos["target"]:
                    exit_reason = "TARGET (+20.0%)"
                    exit_px = pos["target"]
                elif pos["days_held"] >= 21:
                    gain_pct = round(((close - pos['entry_price']) / pos['entry_price']) * 100, 1)
                    exit_reason = f"MAX_1_MONTH_EXPIRED (21d, {gain_pct:+.1f}%)"
                    exit_px = close

            elif mode == "MULTI_BAGGER_TREND_RIDER":
                # Trailing stop based on moving averages:
                # If gain >= 15%, trail stop behind 20 EMA!
                # If gain >= 35%, trail stop behind 10 EMA to lock monster profits!
                current_gain = (close - pos["entry_price"]) / pos["entry_price"] * 100.0
                if current_gain >= 35.0:
                    pos["stop_loss"] = max(pos["stop_loss"], float(row["ema_10"]))
                elif current_gain >= 15.0:
                    pos["stop_loss"] = max(pos["stop_loss"], ema20)

                if close < pos["stop_loss"]:
                    exit_reason = f"TREND_EXIT ({current_gain:+.1f}%, Held {pos['days_held']}d)"
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
        "mode": mode,
        "final_capital": round(portfolio_value, 2),
        "total_return": round(ret_pct, 2),
        "total_trades": len(trades),
        "win_rate": round(win_rate, 1),
        "friction": round(sum(t["friction_costs"] for t in trades), 2),
        "avg_hold": round(sum(t["days_held"] for t in trades) / len(trades), 1) if trades else 0,
        "trades": trades,
        "runners_50pct": sum(1 for t in trades if t["pnl_percent"] >= 50.0),
        "runners_100pct": sum(1 for t in trades if t["pnl_percent"] >= 100.0),
    }

print("Running Comparison: 1-Month Max Hold vs Multi-Bagger Trend Riding...")
res_1mo = test_simulation("1_MONTH_MAX_HOLD")
res_trend = test_simulation("MULTI_BAGGER_TREND_RIDER")

print("\n" + "=" * 80)
print("🏁 HEAD TO HEAD: 1-MONTH MAX HOLD vs UNLEASHED TREND RIDING")
print("=" * 80)
print(f"1. 1-MONTH MAX HOLD (Strict 21 Days):")
print(f"   • Net Return:        {res_1mo['total_return']:+.2f}%")
print(f"   • Final Capital:     Rs. {res_1mo['final_capital']:,.2f}")
print(f"   • Total Trades:      {res_1mo['total_trades']}")
print(f"   • Win Rate:          {res_1mo['win_rate']}%")
print(f"   • Avg Holding:       {res_1mo['avg_hold']} sessions")
print(f"   • Taxes & Friction:  Rs. {res_1mo['friction']:,.2f}")

print(f"\n2. MULTI-BAGGER TREND RIDER (No 1-Month Cut - Trail with Moving Averages):")
print(f"   • Net Return:        {res_trend['total_return']:+.2f}%")
print(f"   • Final Capital:     Rs. {res_trend['final_capital']:,.2f}")
print(f"   • Total Trades:      {res_trend['total_trades']}")
print(f"   • Win Rate:          {res_trend['win_rate']}%")
print(f"   • Avg Holding:       {res_trend['avg_hold']} sessions")
print(f"   • Taxes & Friction:  Rs. {res_trend['friction']:,.2f}")
print(f"   • Monster Runners >= 50%:  {res_trend['runners_50pct']} trades")
print(f"   • Multi-Baggers >= 100%:   {res_trend['runners_100pct']} trades")

# Top winners in trend riding
print("\n--- TOP 10 GREATEST TREND-RIDING MONSTERS ---")
tdf = pd.DataFrame(res_trend["trades"]).sort_values(by="pnl", ascending=False).head(10)
for idx, r in tdf.iterrows():
    print(f"{r['ticker']:12s} | Entry: {r['entry_date']} -> Exit: {r['exit_date']} ({r['days_held']:3d}d) | PnL: {r['pnl_percent']:+6.1f}% (Rs.{r['pnl']:+9,.1f})")

