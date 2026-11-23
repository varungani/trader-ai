"""
TraderAI - Swing Sweet Spot Frontier: Finding the Exact Transition from Friction to Alpha
========================================================================================
Maps the exact mathematical curve of:
  Holding Horizon (5d, 10d, 15d, 20d, 30d, 45d, 60d, 90d, Weekly)
  vs.
  Trade Velocity (Trades / Year)
  vs.
  Friction Paid (INR)
  vs.
  Net Compounded CAGR (%)

This empirically answers:
"What is the shortest holding period that is mathematically viable and profitable in Indian delivery?"
"""
import os
import sys
import pickle
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from analysis.portfolio_cash_simulator import load_universe_and_breadth, STARTING_CASH, SLIPPAGE, SPLIT_DATE

indicators, nifty, market_breadth, df_r1m, df_r3m, df_r6m, n_r1m, n_r3m, n_r6m = load_universe_and_breadth()

trading_dates = list(nifty.index)
start_idx = 252
active_dates = trading_dates[start_idx:]
DAILY_YIELD = (1.0 + 0.065) ** (1.0 / 252.0) - 1.0

# Precalculate Weekly 10-Week EMA
weekly_emas = {}
for sym, ind in indicators.items():
    df_sym = pd.DataFrame({"Close": ind["c"]}).dropna()
    df_w = df_sym.resample("W-FRI").agg({"Close": "last"}).dropna()
    df_w["EMA10W"] = df_w["Close"].ewm(span=10, adjust=False).mean()
    weekly_emas[sym] = df_w

horizons = [
    ("5-Day Micro-Swing", 5, "days"),
    ("10-Day Quick Swing", 10, "days"),
    ("15-Day Standard Swing", 15, "days"),
    ("25-Day Extended Swing", 25, "days"),
    ("40-Day Position Swing", 40, "days"),
    ("60-Day Quarterly Trend", 60, "days"),
    ("Weekly 10-Week Institutional Trail", 999, "weekly_10w"),
]

print("="*95)
print("📈 MAPPING THE SWING SWEET SPOT FRONTIER: HOLDING TIME VS ALPHA VS FRICTION")
print("="*95, flush=True)

frontier_results = []

for label, max_hold, mode in horizons:
    cash = STARTING_CASH
    max_slots = 4
    positions = []
    closed_trades = []
    daily_equity_curve = []
    total_friction_inr = 0.0
    peak_equity = STARTING_CASH

    for d_idx, today in enumerate(active_dates):
        if d_idx >= len(active_dates) - 1: break
        next_day = active_dates[d_idx + 1]

        if cash > 1000.0:
            cash += cash * DAILY_YIELD

        is_friday = (today.weekday() == 4)

        open_positions = []
        for pos in positions:
            sym = pos["symbol"]
            ind = indicators[sym]
            if today not in ind["dates"]:
                open_positions.append(pos)
                continue

            day_o = ind["o"].loc[today]
            day_h = ind["h"].loc[today]
            day_l = ind["l"].loc[today]
            day_c = ind["c"].loc[today]
            pos["days_held"] += 1

            exit_occurred = False
            exit_px = 0.0
            exit_reason = ""

            # Hard Stop: 7%
            if day_o <= pos["stop"]:
                exit_px = day_o * (1.0 - SLIPPAGE)
                exit_reason = "stop_gap"
                exit_occurred = True
            elif day_l <= pos["stop"]:
                exit_px = pos["stop"] * (1.0 - SLIPPAGE)
                exit_reason = "stop_loss"
                exit_occurred = True
            elif mode == "days" and pos["days_held"] >= max_hold:
                exit_px = day_c * (1.0 - SLIPPAGE)
                exit_reason = f"max_{max_hold}d"
                exit_occurred = True
            elif mode == "weekly_10w" and is_friday and pos["days_held"] >= 5:
                w_df = weekly_emas.get(sym)
                if w_df is not None and today in w_df.index:
                    if w_df.loc[today, "Close"] < w_df.loc[today, "EMA10W"]:
                        exit_px = day_c * (1.0 - SLIPPAGE)
                        exit_reason = "trail_weekly_10w"
                        exit_occurred = True

            if exit_occurred:
                sell_val = pos["shares"] * exit_px
                friction = (sell_val * 0.001042) + 15.93 + (sell_val * SLIPPAGE)
                total_friction_inr += friction
                cash += (sell_val - friction)

                net_pnl = (sell_val - friction) - (pos["shares"] * pos["entry_price"])
                net_pnl_pct = (net_pnl / (pos["shares"] * pos["entry_price"])) * 100.0

                closed_trades.append({
                    "symbol": sym, "holding_days": pos["days_held"],
                    "net_pnl_inr": net_pnl, "net_pnl_pct": net_pnl_pct,
                })
            else:
                open_positions.append(pos)

        positions = open_positions

        current_equity = cash
        for p in positions:
            s = p["symbol"]
            ind = indicators[s]
            px = ind["c"].loc[today] if today in ind["dates"] else p["entry_price"]
            current_equity += p["shares"] * px

        if current_equity > peak_equity: peak_equity = current_equity
        daily_equity_curve.append({"date": today, "equity": current_equity})

        breadth = market_breadth.get(today, 50.0)
        nifty_c = nifty["Close"].loc[today]
        nifty_ema50 = nifty["EMA50"].loc[today]

        if breadth < 48.0 or nifty_c < nifty_ema50:
            continue

        open_slots = max_slots - len(positions)
        if open_slots <= 0: continue

        candidates = []
        for sym, ind in indicators.items():
            if any(p["symbol"] == sym for p in positions): continue
            if today not in ind["dates"]: continue

            c_t = ind["c"].loc[today]
            h50 = ind["high50"].loc[today]
            ema20 = ind["ema20"].loc[today]
            ema50 = ind["ema50"].loc[today]
            rvol = ind["rvol"].loc[today]

            if c_t > h50 and c_t > ema20 and c_t > ema50 and rvol >= 1.8:
                r1m = df_r1m.loc[today, sym] if (today in df_r1m.index and sym in df_r1m.columns) else -999.0
                r3m = df_r3m.loc[today, sym] if (today in df_r3m.index and sym in df_r3m.columns) else -999.0
                r6m = df_r6m.loc[today, sym] if (today in df_r6m.index and sym in df_r6m.columns) else -999.0
                if pd.isna(r1m) or pd.isna(r3m) or pd.isna(r6m): continue
                if r6m > 0 and r1m < 0: continue
                comp_rs = (0.50 * r1m) + (0.30 * r3m) + (0.20 * r6m)
                candidates.append((sym, comp_rs))

        if not candidates: continue
        candidates.sort(key=lambda x: x[1], reverse=True)
        chosen = candidates[:open_slots]

        for sym, _ in chosen:
            ind = indicators[sym]
            if next_day not in ind["dates"]: continue
            day0_c = ind["c"].loc[today]
            next_o = ind["o"].loc[next_day]
            if (next_o / day0_c - 1.0) > 0.025: continue

            entry_fill = next_o * (1.0 + SLIPPAGE)
            stop_px = entry_fill * 0.93  # 7% stop
            risk_inr = current_equity * 0.02  # 2% risk
            shares = min(int(risk_inr / (entry_fill - stop_px)), int((current_equity / max_slots) / entry_fill))
            if shares <= 0: continue

            cost = shares * entry_fill
            buy_fric = (cost * 0.001192) + (cost * SLIPPAGE)
            if cash < cost + buy_fric: continue

            cash -= (cost + buy_fric)
            total_friction_inr += buy_fric
            positions.append({
                "symbol": sym, "entry_date": next_day, "entry_price": entry_fill,
                "shares": shares, "stop": stop_px, "days_held": 0,
            })

    final_equity = cash
    last_d = active_dates[-1]
    for p in positions:
        s = p["symbol"]
        ind = indicators[s]
        px = ind["c"].loc[last_d] if last_d in ind["dates"] else p["entry_price"]
        sell_val = p["shares"] * px * (1.0 - SLIPPAGE)
        friction = (sell_val * 0.001042) + 15.93 + (sell_val * SLIPPAGE)
        total_friction_inr += friction
        final_equity += (sell_val - friction)

    df_eq = pd.DataFrame(daily_equity_curve)
    df_tr = pd.DataFrame(closed_trades)

    n_years = len(df_eq) / 252.0
    tot_ret = (final_equity / STARTING_CASH - 1.0) * 100.0
    cagr = ((final_equity / STARTING_CASH) ** (1.0 / n_years) - 1.0) * 100.0
    running_max = df_eq["equity"].cummax()
    max_dd = float(((df_eq["equity"] - running_max) / running_max).min() * 100.0)
    wins = df_tr[df_tr["net_pnl_inr"] > 0]["net_pnl_inr"]
    losses = df_tr[df_tr["net_pnl_inr"] <= 0]["net_pnl_inr"]
    pf = wins.sum() / (abs(losses.sum()) + 1e-9)
    trades_per_yr = len(df_tr) / n_years

    frontier_results.append({
        "Holding Strategy": label,
        "Trades/Yr": round(trades_per_yr, 0),
        "Total Trades": len(df_tr),
        "5Y Net Ret %": round(tot_ret, 1),
        "CAGR %": round(cagr, 1),
        "Max DD %": round(max_dd, 1),
        "Profit Factor": round(pf, 2),
        "Friction Paid (INR)": round(total_friction_inr, 0),
    })

df_res = pd.DataFrame(frontier_results)
print(df_res.to_string(index=False))
