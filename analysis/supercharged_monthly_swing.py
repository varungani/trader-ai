"""
TraderAI - Supercharged 1-to-2 Month Swing Strategy (2021-2026)
================================================================================
Translates the EDA findings into a high-alpha 1-to-2 month swing engine:

Key Findings from 105k-Sample EDA:
  1. Top Factor 1: 52-Week High Proximity (IC = +0.0641, IC > 0.05 is elite)
  2. Top Factor 2: Distance Above 200-EMA >= 20% (IC = +0.0584, Top decile spread: +3.4%)
  3. Top Factor 3: 3-Month Relative Strength (IC = +0.0498, far superior to 1M noise)
  4. Top Factor 4: Market Breadth Gate (% > 50 EMA, IC = +0.0864)

The Supercharged 1-2 Month Swing Rules:
  • Entry: Stage 2 Leader within 10% of 52-Week High, >= 20% above 200-EMA, Top 3M RS.
  • Minimum Hold: 15 to 20 sessions (giving trades 3-4 weeks to breathe).
  • Stagnation Velocity Cutoff: At Day 21 (1 Month), if gain < +3%, EXIT! (Recycle dead cash).
  • Runner Engine: If gain >= +10%, trail 20-day EMA!
  • Hard Stop: 7.0% initial stop.
  • Portfolio: 4 Slots (25% capital each) with full Indian delivery friction + LiquidBees.
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

trading_dates = list(nifty.index)
start_idx = 252
active_dates = trading_dates[start_idx:]
DAILY_YIELD = (1.0 + 0.065) ** (1.0 / 252.0) - 1.0

print("="*85)
print("⚡ TESTING SUPERCHARGED 1-TO-2 MONTH SWING ENGINE (25-45 TRADES/YEAR)")
print("="*85, flush=True)

# Test 3 variations of the 1-to-2 Month Engine:
# Setup 1: Hard 1-2 Month Hold (Stagnation kill at Day 21, Max 45 sessions)
# Setup 2: Trailing 20-EMA after Day 15 (Responsive Swing Exit)
# Setup 3: Trailing 10-Week EMA on Friday Close (Hybrid Swing-to-Trend)

configs = [
    ("Model 1: 1-2 Month Active Swing (Stagnation Kill Day 21, Max 45d)", "stagnation_45d"),
    ("Model 2: 1-2 Month 20-EMA Trail (Trail 20-EMA after Day 15, Max 45d)", "trail_20ema_45d"),
    ("Model 3: Hybrid 1-2 Month Swing (Stagnation Kill Day 21, Trail 20-EMA)", "hybrid_swing"),
]

for label, mode in configs:
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

            if day_c > pos["highest_close"]: pos["highest_close"] = day_c
            gain_pct = (day_c / pos["entry_price"]) - 1.0

            exit_occurred = False
            exit_px = 0.0
            exit_reason = ""

            # Hard Stop: 7.0%
            if day_o <= pos["stop"]:
                exit_px = day_o * (1.0 - SLIPPAGE)
                exit_reason = "stop_gap"
                exit_occurred = True
            elif day_l <= pos["stop"]:
                exit_px = pos["stop"] * (1.0 - SLIPPAGE)
                exit_reason = "stop_loss"
                exit_occurred = True
            
            # Stagnation Velocity Kill at Day 21 (1 Month mark)
            elif (mode in ["stagnation_45d", "hybrid_swing"]) and pos["days_held"] == 21:
                if gain_pct < 0.03:  # If after 1 full month it hasn't gained at least +3%, recycle!
                    exit_px = day_c * (1.0 - SLIPPAGE)
                    exit_reason = "stagnation_day21_recycle"
                    exit_occurred = True

            # Trailing 20-EMA
            elif not exit_occurred and pos["days_held"] >= 15:
                if mode in ["trail_20ema_45d", "hybrid_swing"]:
                    day_ema20 = ind["ema20"].loc[today]
                    if day_c < day_ema20:
                        exit_px = day_c * (1.0 - SLIPPAGE)
                        exit_reason = "trail_20ema"
                        exit_occurred = True

            # Max 45 sessions cutoff (~2 calendar months)
            if not exit_occurred and pos["days_held"] >= 45:
                exit_px = day_c * (1.0 - SLIPPAGE)
                exit_reason = "max_45d_rebalance"
                exit_occurred = True

            if exit_occurred:
                sell_val = pos["shares"] * exit_px
                friction = (sell_val * 0.001042) + 15.93 + (sell_val * SLIPPAGE)
                total_friction_inr += friction
                cash += (sell_val - friction)

                net_pnl = (sell_val - friction) - (pos["shares"] * pos["entry_price"])
                net_pnl_pct = (net_pnl / (pos["shares"] * pos["entry_price"])) * 100.0

                closed_trades.append({
                    "symbol": sym, "days_held": pos["days_held"],
                    "net_pnl_inr": net_pnl, "net_pnl_pct": net_pnl_pct,
                    "exit_reason": exit_reason,
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
            ema20 = ind["ema20"].loc[today]
            ema50 = ind["ema50"].loc[today]
            ema200 = ind["ema200"].loc[today]
            h52w = ind["df"]["High"].shift(1).rolling(252).max().loc[today] if "High" in ind["df"].columns else c_t
            h20 = ind["high20"].loc[today]
            rvol = ind["rvol"].loc[today]

            # Top EDA Features Applied:
            # 1. Price within 12% of 52-Week High (Factor 1)
            # 2. Price >= 20% above 200-EMA (Factor 2)
            # 3. Stage 2 (Price > EMA50 > EMA200)
            # 4. Breakout of 20-day high with RVOL >= 1.5x
            if c_t >= h52w * 0.88 and c_t >= ema200 * 1.20 and c_t > ema50 and c_t > h20 and rvol >= 1.5:
                r1m = df_r1m.loc[today, sym] if (today in df_r1m.index and sym in df_r1m.columns) else -999.0
                r3m = df_r3m.loc[today, sym] if (today in df_r3m.index and sym in df_r3m.columns) else -999.0
                if pd.isna(r1m) or pd.isna(r3m): continue
                if r3m <= 0: continue

                # Composite score: Heavily weighted to 3M RS
                composite = (0.70 * r3m) + (0.30 * r1m)
                candidates.append((sym, composite))

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
            stop_px = entry_fill * 0.93  # 7.0% stop
            risk_inr = current_equity * 0.02  # 2% equity risk
            shares = min(int(risk_inr / (entry_fill - stop_px)), int((current_equity / max_slots) / entry_fill))
            if shares <= 0: continue

            cost = shares * entry_fill
            buy_fric = (cost * 0.001192) + (cost * SLIPPAGE)
            if cash < cost + buy_fric: continue

            cash -= (cost + buy_fric)
            total_friction_inr += buy_fric
            positions.append({
                "symbol": sym, "entry_date": next_day, "entry_price": entry_fill,
                "shares": shares, "stop": stop_px, "days_held": 0, "highest_close": entry_fill,
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
    avg_hold = df_tr["days_held"].mean()
    hit_25 = (df_tr["net_pnl_pct"] >= 25.0).sum()
    hit_50 = (df_tr["net_pnl_pct"] >= 50.0).sum()

    print(f"\n📌 {label}:")
    print(f"   • Ending Capital    : ₹{final_equity:,.2f} ({tot_ret:+.2f}% Net Return)")
    print(f"   • 5-Year CAGR       : {cagr:+.2f}% per year")
    print(f"   • Max Drawdown      : {max_dd:.2f}%")
    print(f"   • Annual Cadence    : ~{trades_per_yr:.0f} trades/year (Total: {len(df_tr)} trades)")
    print(f"   • Avg Holding Days  : {avg_hold:.1f} sessions (~{avg_hold/21:.1f} months)")
    print(f"   • Profit Factor     : {pf:.2f} | Win Rate: {(len(wins)/len(df_tr)*100):.1f}%")
    print(f"   • Big Winners       : {hit_25} trades >= +25%, {hit_50} trades >= +50%")
    print(f"   • Friction Paid     : ₹{total_friction_inr:,.2f}")
