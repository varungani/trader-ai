"""
TraderAI - Dual-Speed Hybrid Master Portfolio (50% 1-2M Swings + 50% Multi-Baggers)
===================================================================================
Simulates the ultimate tournament portfolio:
  - 2 Slots (50% capital) running the Supercharged 1-2 Month Swing Engine (~20-25 trades/yr)
  - 2 Slots (50% capital) running the Apex Weekly 10W Multi-Bagger Engine (~8-12 trades/yr)
  - Full Indian delivery friction + 6.5% LiquidBees yield on idle cash.
"""
from __future__ import annotations

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

# Precalculate Weekly 10W EMA
weekly_emas = {}
for sym, ind in indicators.items():
    df_sym = pd.DataFrame({"Close": ind["c"]}).dropna()
    df_w = df_sym.resample("W-FRI").agg({"Close": "last"}).dropna()
    df_w["EMA10W"] = df_w["Close"].ewm(span=10, adjust=False).mean()
    weekly_emas[sym] = df_w

trading_dates = list(nifty.index)
start_idx = 252
active_dates = trading_dates[start_idx:]
DAILY_YIELD = (1.0 + 0.065) ** (1.0 / 252.0) - 1.0

cash = STARTING_CASH
positions_swing = []   # Max 2 slots
positions_trend = []   # Max 2 slots
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

    # 1. Audit Swing Positions
    open_swing = []
    for pos in positions_swing:
        sym = pos["symbol"]
        ind = indicators[sym]
        if today not in ind["dates"]:
            open_swing.append(pos)
            continue

        day_o = ind["o"].loc[today]
        day_h = ind["h"].loc[today]
        day_l = ind["l"].loc[today]
        day_c = ind["c"].loc[today]
        pos["days_held"] += 1

        exit_occurred = False
        exit_px = 0.0
        exit_reason = ""

        # Hard stop 7%
        if day_o <= pos["stop"]:
            exit_px = day_o * (1.0 - SLIPPAGE)
            exit_reason = "stop_gap"
            exit_occurred = True
        elif day_l <= pos["stop"]:
            exit_px = pos["stop"] * (1.0 - SLIPPAGE)
            exit_reason = "stop_loss"
            exit_occurred = True
        elif pos["days_held"] == 21 and (day_c / pos["entry_price"] - 1.0) < 0.03:
            exit_px = day_c * (1.0 - SLIPPAGE)
            exit_reason = "stagnation_day21"
            exit_occurred = True
        elif pos["days_held"] >= 15 and day_c < ind["ema20"].loc[today]:
            exit_px = day_c * (1.0 - SLIPPAGE)
            exit_reason = "trail_20ema"
            exit_occurred = True
        elif pos["days_held"] >= 45:
            exit_px = day_c * (1.0 - SLIPPAGE)
            exit_reason = "max_45d"
            exit_occurred = True

        if exit_occurred:
            sell_val = pos["shares"] * exit_px
            friction = (sell_val * 0.001042) + 15.93 + (sell_val * SLIPPAGE)
            total_friction_inr += friction
            cash += (sell_val - friction)
            net_pnl = (sell_val - friction) - (pos["shares"] * pos["entry_price"])
            closed_trades.append({
                "type": "Swing", "symbol": sym, "days_held": pos["days_held"],
                "net_pnl_inr": net_pnl, "net_pnl_pct": (net_pnl / (pos["shares"] * pos["entry_price"])) * 100.0,
            })
        else:
            open_swing.append(pos)
    positions_swing = open_swing

    # 2. Audit Trend Positions
    open_trend = []
    for pos in positions_trend:
        sym = pos["symbol"]
        ind = indicators[sym]
        if today not in ind["dates"]:
            open_trend.append(pos)
            continue

        day_o = ind["o"].loc[today]
        day_h = ind["h"].loc[today]
        day_l = ind["l"].loc[today]
        day_c = ind["c"].loc[today]
        pos["days_held"] += 1

        exit_occurred = False
        exit_px = 0.0

        if day_o <= pos["stop"]:
            exit_px = day_o * (1.0 - SLIPPAGE)
            exit_occurred = True
        elif day_l <= pos["stop"]:
            exit_px = pos["stop"] * (1.0 - SLIPPAGE)
            exit_occurred = True
        elif is_friday and pos["days_held"] >= 5:
            w_df = weekly_emas.get(sym)
            if w_df is not None and today in w_df.index:
                if w_df.loc[today, "Close"] < w_df.loc[today, "EMA10W"]:
                    exit_px = day_c * (1.0 - SLIPPAGE)
                    exit_occurred = True

        if exit_occurred:
            sell_val = pos["shares"] * exit_px
            friction = (sell_val * 0.001042) + 15.93 + (sell_val * SLIPPAGE)
            total_friction_inr += friction
            cash += (sell_val - friction)
            net_pnl = (sell_val - friction) - (pos["shares"] * pos["entry_price"])
            closed_trades.append({
                "type": "Trend", "symbol": sym, "days_held": pos["days_held"],
                "net_pnl_inr": net_pnl, "net_pnl_pct": (net_pnl / (pos["shares"] * pos["entry_price"])) * 100.0,
            })
        else:
            open_trend.append(pos)
    positions_trend = open_trend

    # Total MTM
    current_equity = cash
    for p in positions_swing + positions_trend:
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

    open_swing_slots = 2 - len(positions_swing)
    open_trend_slots = 2 - len(positions_trend)

    if open_swing_slots <= 0 and open_trend_slots <= 0:
        continue

    # Screen candidates
    existing = {p["symbol"] for p in positions_swing + positions_trend}
    candidates = []
    for sym, ind in indicators.items():
        if sym in existing: continue
        if today not in ind["dates"]: continue

        c_t = ind["c"].loc[today]
        ema50 = ind["ema50"].loc[today]
        ema200 = ind["ema200"].loc[today]
        h52w = ind["df"]["High"].shift(1).rolling(252).max().loc[today] if "High" in ind["df"].columns else c_t
        h20 = ind["high20"].loc[today]
        rvol = ind["rvol"].loc[today]

        if c_t >= h52w * 0.88 and c_t >= ema200 * 1.20 and c_t > ema50 and c_t > h20 and rvol >= 1.5:
            r1m = df_r1m.loc[today, sym] if (today in df_r1m.index and sym in df_r1m.columns) else -999.0
            r3m = df_r3m.loc[today, sym] if (today in df_r3m.index and sym in df_r3m.columns) else -999.0
            if pd.isna(r1m) or pd.isna(r3m): continue
            if r3m <= 0: continue
            composite = (0.70 * r3m) + (0.30 * r1m)
            candidates.append((sym, composite))

    if not candidates: continue
    candidates.sort(key=lambda x: x[1], reverse=True)

    # Allocate to Trend first, then Swing
    cand_idx = 0
    while open_trend_slots > 0 and cand_idx < len(candidates):
        sym = candidates[cand_idx][0]
        cand_idx += 1
        ind = indicators[sym]
        if next_day not in ind["dates"]: continue
        day0_c = ind["c"].loc[today]
        next_o = ind["o"].loc[next_day]
        if (next_o / day0_c - 1.0) > 0.025: continue

        entry_fill = next_o * (1.0 + SLIPPAGE)
        stop_px = entry_fill * 0.93
        shares = min(int((current_equity * 0.02) / (entry_fill - stop_px)), int((current_equity / 4.0) / entry_fill))
        if shares <= 0: continue
        cost = shares * entry_fill
        buy_fric = (cost * 0.001192) + (cost * SLIPPAGE)
        if cash < cost + buy_fric: continue
        cash -= (cost + buy_fric)
        total_friction_inr += buy_fric
        positions_trend.append({"symbol": sym, "entry_date": next_day, "entry_price": entry_fill, "shares": shares, "stop": stop_px, "days_held": 0})
        open_trend_slots -= 1

    while open_swing_slots > 0 and cand_idx < len(candidates):
        sym = candidates[cand_idx][0]
        cand_idx += 1
        ind = indicators[sym]
        if next_day not in ind["dates"]: continue
        day0_c = ind["c"].loc[today]
        next_o = ind["o"].loc[next_day]
        if (next_o / day0_c - 1.0) > 0.025: continue

        entry_fill = next_o * (1.0 + SLIPPAGE)
        stop_px = entry_fill * 0.93
        shares = min(int((current_equity * 0.02) / (entry_fill - stop_px)), int((current_equity / 4.0) / entry_fill))
        if shares <= 0: continue
        cost = shares * entry_fill
        buy_fric = (cost * 0.001192) + (cost * SLIPPAGE)
        if cash < cost + buy_fric: continue
        cash -= (cost + buy_fric)
        total_friction_inr += buy_fric
        positions_swing.append({"symbol": sym, "entry_date": next_day, "entry_price": entry_fill, "shares": shares, "stop": stop_px, "days_held": 0})
        open_swing_slots -= 1

# Liquidation
final_equity = cash
last_d = active_dates[-1]
for p in positions_swing + positions_trend:
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

print("\n" + "="*85)
print("🏆 TOURNAMENT MASTER HYBRID PORTFOLIO (50% 1-2M SWINGS + 50% TREND COMPOUNDING)")
print("="*85)
print(f"• Ending Capital    : ₹{final_equity:,.2f} ({tot_ret:+.2f}% Net Return)")
print(f"• 5-Year CAGR       : {cagr:+.2f}% per year")
print(f"• Max Drawdown      : {max_dd:.2f}%")
print(f"• Total Trades      : {len(df_tr)} (~{trades_per_yr:.0f} trades/year)")
print(f"• Profit Factor     : {pf:.2f} | Win Rate: {(len(wins)/len(df_tr)*100):.1f}%")
print(f"• Friction Paid     : ₹{total_friction_inr:,.2f}")

# Breakdown by strategy type
sw_tr = df_tr[df_tr["type"] == "Swing"]
tr_tr = df_tr[df_tr["type"] == "Trend"]
print(f"\n📊 Sub-Engine Breakdown:")
print(f"   • Swing Trades   : {len(sw_tr)} trades (~{len(sw_tr)/n_years:.0f}/yr) | PnL: ₹{sw_tr['net_pnl_inr'].sum():+,.2f} | Avg Hold: {sw_tr['days_held'].mean():.1f}d")
print(f"   • Trend Trades   : {len(tr_tr)} trades (~{len(tr_tr)/n_years:.0f}/yr) | PnL: ₹{tr_tr['net_pnl_inr'].sum():+,.2f} | Avg Hold: {tr_tr['days_held'].mean():.1f}d")
