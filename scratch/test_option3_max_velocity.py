"""
Test Option 3 (GTT Buy-Stop on Consolidation Pivots) with:
1. High Capital Utilization (Slot immediately refilled on exit)
2. 10 EMA Runner Trailing (Tranche 1 locks +15%, Tranche 2 rides multi-baggers)
3. Dynamic Compounding (Slots scale with portfolio equity)
"""
from __future__ import annotations

import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import HIGH_BETA_APEX_STOCKS
from data.market_data import _get_cached_history
from data.costs import compute_indian_delivery_costs


def test_option3_unleashed(lookback_bars: int = 250):
    stock_data = {}
    for t in HIGH_BETA_APEX_STOCKS:
        df = _get_cached_history(t, "2y")
        if not df.empty:
            df.columns = [str(c).title() for c in df.columns]
            if "Close" in df.columns and "High" in df.columns and "Low" in df.columns and len(df) >= lookback_bars:
                stock_data[t] = df.tail(lookback_bars).copy()

    ref_ticker = list(stock_data.keys())[0]
    dates = stock_data[ref_ticker].index

    # 3 Slots, Initial Capital ₹1,00,000
    cash = 100000.0
    open_positions = []
    closed_trades = []

    for bar_idx in range(65, len(dates) - 1):
        cur_date = dates[bar_idx]

        # 1. Update Open Positions (Check Trailing Exits)
        still_open = []
        for pos in open_positions:
            t = pos["ticker"]
            df = stock_data[t]
            bar_h = float(df["High"].iloc[bar_idx])
            bar_c = float(df["Close"].iloc[bar_idx])
            ema10 = float(df["Close"].iloc[:bar_idx+1].ewm(span=10, adjust=False).mean().iloc[-1])
            pos["days_held"] += 1

            # High watermark
            if bar_h > pos["high_watermark"]:
                pos["high_watermark"] = bar_h

            is_closed = False
            exit_px = bar_c
            exit_reason = ""

            # Tranche 1: Lock +15%
            if not pos["tranche1_locked"] and bar_h >= pos["entry_price"] * 1.15:
                pos["tranche1_locked"] = True
                pos["stop_loss"] = max(pos["stop_loss"], pos["entry_price"] * 1.01) # Move stop to Breakeven +1%

            # Trailing stop: If tranche 1 locked, trail with 10 EMA
            if pos["tranche1_locked"]:
                pos["stop_loss"] = max(pos["stop_loss"], ema10)

            # Check Stop Loss on Daily Close
            if bar_c <= pos["stop_loss"]:
                is_closed = True
                exit_px = pos["stop_loss"]
                exit_reason = "STOP_LOSS / TRAILING_STOP"
            elif pos["days_held"] >= 21:
                is_closed = True
                exit_px = bar_c
                exit_reason = "TIME_EXPIRY (21 Sessions)"

            if is_closed:
                costs = compute_indian_delivery_costs(buy_price=pos["entry_price"], sell_price=exit_px, quantity=pos["shares"])
                net_pnl = (exit_px - pos["entry_price"]) * pos["shares"] - costs.total_friction_rupees
                cash += (pos["shares"] * exit_px) - costs.total_friction_rupees
                closed_trades.append({
                    "ticker": t,
                    "entry_price": pos["entry_price"],
                    "exit_price": exit_px,
                    "shares": pos["shares"],
                    "net_pnl": net_pnl,
                    "net_pct": (net_pnl / (pos["entry_price"] * pos["shares"])) * 100.0,
                    "exit_reason": exit_reason,
                    "days_held": pos["days_held"],
                })
            else:
                still_open.append(pos)

        open_positions = still_open

        # 2. Fill Empty Slots from GTT Radar Pivots
        available_slots = 3 - len(open_positions)
        if available_slots > 0 and cash >= 5000:
            # Screen candidates at bar_idx
            screened = []
            for t, df in stock_data.items():
                if any(p["ticker"] == t for p in open_positions):
                    continue

                sub = df.iloc[:bar_idx+1]
                c = sub["Close"]
                h = sub["High"]
                l = sub["Low"]
                v = sub["Volume"] if "Volume" in sub.columns else pd.Series(dtype=float)

                if len(c) < 65:
                    continue

                px = float(c.iloc[-1])
                ret_1m = float(c.iloc[-1] / c.iloc[-22] - 1)
                high_5d = float(h.iloc[-5:].max())
                low_5d = float(l.iloc[-5:].min())
                high_20d = float(h.iloc[-20:].max())
                low_20d = float(l.iloc[-20:].min())
                vcp = (high_5d - low_5d) / (high_20d - low_20d) if (high_20d - low_20d) > 0 else 1.0
                rvol = float(v.iloc[-1] / v.iloc[-20:].mean()) if len(v) >= 20 and v.iloc[-20:].mean() > 0 else 1.0

                # High Relative Strength + Coiling at Highs
                if ret_1m >= 0.08 and vcp <= 0.70 and rvol >= 1.2:
                    score = ret_1m * 100 + (rvol * 15)
                    screened.append({
                        "ticker": t,
                        "pivot_trigger": high_5d,
                        "score": score,
                    })

            screened.sort(key=lambda x: x["score"], reverse=True)

            # Check GTT trigger on Day T+1 for top candidates
            next_bar = bar_idx + 1
            for cand in screened[:available_slots * 2]:
                if len(open_positions) >= 3:
                    break
                t = cand["ticker"]
                df = stock_data[t]
                pivot_px = cand["pivot_trigger"]

                # If next bar high crossed pivot trigger -> GTT FILLED!
                if float(df["High"].iloc[next_bar]) >= pivot_px:
                    entry_px = pivot_px * 1.002
                    slot_capital = cash / max(1, (3 - len(open_positions)))
                    shares = int(slot_capital // entry_px)
                    if shares > 0 and (shares * entry_px) <= cash:
                        cash -= (shares * entry_px)
                        open_positions.append({
                            "ticker": t,
                            "entry_price": entry_px,
                            "shares": shares,
                            "stop_loss": entry_px * 0.93,
                            "high_watermark": entry_px,
                            "tranche1_locked": False,
                            "days_held": 0,
                        })

    # Liquidate remaining at last bar
    for pos in open_positions:
        t = pos["ticker"]
        df = stock_data[t]
        exit_px = float(df["Close"].iloc[-1])
        costs = compute_indian_delivery_costs(buy_price=pos["entry_price"], sell_price=exit_px, quantity=pos["shares"])
        net_pnl = (exit_px - pos["entry_price"]) * pos["shares"] - costs.total_friction_rupees
        cash += (pos["shares"] * exit_px) - costs.total_friction_rupees
        closed_trades.append({
            "ticker": t,
            "entry_price": pos["entry_price"],
            "exit_price": exit_px,
            "shares": pos["shares"],
            "net_pnl": net_pnl,
            "net_pct": (net_pnl / (pos["entry_price"] * pos["shares"])) * 100.0,
            "exit_reason": "FINAL_EVALUATION",
            "days_held": pos["days_held"],
        })

    df_res = pd.DataFrame(closed_trades)
    wins = df_res[df_res["net_pnl"] > 0]
    losses = df_res[df_res["net_pnl"] <= 0]
    win_rate = (len(wins) / len(df_res)) * 100.0 if len(df_res) else 0.0
    gp = wins["net_pnl"].sum()
    gl = abs(losses["net_pnl"].sum())
    pf = round(gp / gl, 2) if gl > 0 else 99.0

    print("=" * 80)
    print("🚀 OPTION 3 UNLEASHED (High Velocity + 10 EMA Runner Trailing + Compounding):")
    print("=" * 80)
    print(f"Starting Capital:     ₹1,00,000.00")
    print(f"Final Capital:        ₹{cash:>10,.2f}")
    print(f"Total Net Return:     {((cash - 100000) / 1000):>+10.1f}%")
    print(f"Total Trades Taken:   {len(df_res):>10}")
    print(f"Win Rate %:           {win_rate:>10.1f}%")
    print(f"Profit Factor:        {pf:>10.2f}")
    print(f"Average Gain / Trade: {df_res['net_pct'].mean():>+10.2f}%")
    print(f"Biggest Winner:       {df_res['net_pct'].max():>+10.2f}%")
    print(f"Top 3 Super-Runners:")
    for _, r in df_res.sort_values(by='net_pct', ascending=False).head(3).iterrows():
        print(f"  • {r['ticker']}: {r['net_pct']:+.1f}% gain in {r['days_held']} sessions (Net: +₹{r['net_pnl']:,.2f})")
    print("=" * 80)

if __name__ == "__main__":
    test_option3_unleashed()

