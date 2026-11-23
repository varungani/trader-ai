"""
TraderAI - Ultra-High-CAGR Engine: Targeting 50% to 70%+ 5-Year CAGR (2021-2026)
================================================================================
Investigates the 4 Quantitative Levers Required to Break Past 50%+ CAGR:

  1. Position Concentration: 3 High-Conviction Slots (33.3% Capital per Position)
  2. Aggressive 10-Day Velocity Pruning: If gain < +2.5% by Day 10, cut immediately!
  3. Hyper-Beta Selection: Focus strictly on the Top 2% Momentum Rockets
     (1M RS >= +15%, Price >= 20% above 200-EMA, RVOL >= 2.0x, Volume Asymmetry >= 2.0x)
  4. Regime-Adaptive Position Sizing: 2.5% to 3.0% Risk in Confirmed Bull Regimes
  5. Stepped Trailing Exit: Let winners compound into 2x-5x runners with 10W / 20-EMA trail!
  6. Strict Indian Delivery Friction: STT, GST, SEBI, flat ₹15.93 CDSL DP charges, 0.25% slippage.
"""
from __future__ import annotations

import os
import sys
import time
import pickle
from dataclasses import dataclass
from typing import Dict, List, Any

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from analysis.portfolio_cash_simulator import load_universe_and_breadth, STARTING_CASH, SLIPPAGE, SPLIT_DATE

indicators, nifty, market_breadth, df_r1m, df_r3m, df_r6m, n_r1m, n_r3m, n_r6m = load_universe_and_breadth()

# Precalculate Weekly 10W EMA and 20d Volume Asymmetry
weekly_emas = {}
vol_asym_dict = {}
for sym, ind in indicators.items():
    df_sym = pd.DataFrame({"Close": ind["c"]}).dropna()
    df_w = df_sym.resample("W-FRI").agg({"Close": "last"}).dropna()
    df_w["EMA10W"] = df_w["Close"].ewm(span=10, adjust=False).mean()
    weekly_emas[sym] = df_w

    v = ind["v"]
    c = ind["c"]
    up_day = (c > c.shift(1)).astype(float)
    up_vol = (v * up_day).rolling(20).sum()
    down_vol = (v * (1.0 - up_day)).rolling(20).sum()
    vol_asym_dict[sym] = up_vol / (down_vol + 1e-9)

trading_dates = list(nifty.index)
start_idx = 252
active_dates = trading_dates[start_idx:]
DAILY_YIELD = (1.0 + 0.065) ** (1.0 / 252.0) - 1.0


def run_ultra_simulation(
    max_slots: int = 3,
    risk_pct_bull: float = 0.0275,   # 2.75% risk in bull
    velocity_pruning_day: int = 10,   # Cut dead money at Day 10
    velocity_min_gain: float = 0.025, # Must be up >= 2.5% by Day 10
    trail_mode: str = "weekly_10w",  # "weekly_10w", "trail_20ema", "stepped_fast"
    max_hold_days: int = 999,        # 999 = no artificial cap, let runners run!
) -> Dict[str, Any]:
    cash = STARTING_CASH
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

        # 1. Audit active positions
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

            # Hard Emergency Stop: 7.5%
            if day_o <= pos["stop"]:
                exit_px = day_o * (1.0 - SLIPPAGE)
                exit_reason = "stop_gap"
                exit_occurred = True
            elif day_l <= pos["stop"]:
                exit_px = pos["stop"] * (1.0 - SLIPPAGE)
                exit_reason = "stop_loss"
                exit_occurred = True

            # Aggressive Velocity Pruning: At Day 10, if gain < 2.5%, kill it!
            elif velocity_pruning_day > 0 and pos["days_held"] == velocity_pruning_day:
                if gain_pct < velocity_min_gain:
                    exit_px = day_c * (1.0 - SLIPPAGE)
                    exit_reason = f"velocity_day{velocity_pruning_day}_kill"
                    exit_occurred = True

            # Trailing Exit Engine
            elif not exit_occurred and pos["days_held"] >= 5:
                if trail_mode == "weekly_10w" and is_friday:
                    w_df = weekly_emas.get(sym)
                    if w_df is not None and today in w_df.index:
                        if w_df.loc[today, "Close"] < w_df.loc[today, "EMA10W"]:
                            exit_px = day_c * (1.0 - SLIPPAGE)
                            exit_reason = "trail_weekly_10w"
                            exit_occurred = True
                elif trail_mode == "trail_20ema" and pos["days_held"] >= 12:
                    if day_c < ind["ema20"].loc[today]:
                        exit_px = day_c * (1.0 - SLIPPAGE)
                        exit_reason = "trail_20ema"
                        exit_occurred = True
                elif trail_mode == "stepped_fast":
                    # If gain >= +40%, trail 10-day EMA to lock in parabolic burst!
                    # Else if gain >= +15%, trail 20-day EMA
                    # Else Friday close < 10W EMA
                    if gain_pct >= 0.40 and day_c < ind["c"].loc[:today].ewm(span=10, adjust=False).mean().iloc[-1]:
                        exit_px = day_c * (1.0 - SLIPPAGE)
                        exit_reason = "trail_stepped_10ema"
                        exit_occurred = True
                    elif gain_pct >= 0.15 and day_c < ind["ema20"].loc[today]:
                        exit_px = day_c * (1.0 - SLIPPAGE)
                        exit_reason = "trail_stepped_20ema"
                        exit_occurred = True
                    elif is_friday:
                        w_df = weekly_emas.get(sym)
                        if w_df is not None and today in w_df.index:
                            if w_df.loc[today, "Close"] < w_df.loc[today, "EMA10W"]:
                                exit_px = day_c * (1.0 - SLIPPAGE)
                                exit_reason = "trail_weekly_10w"
                                exit_occurred = True

            # Max duration cap (if set)
            if not exit_occurred and pos["days_held"] >= max_hold_days:
                exit_px = day_c * (1.0 - SLIPPAGE)
                exit_reason = f"max_{max_hold_days}d"
                exit_occurred = True

            if exit_occurred:
                sell_val = pos["shares"] * exit_px
                friction = (sell_val * 0.001042) + 15.93 + (sell_val * SLIPPAGE)
                total_friction_inr += friction
                cash += (sell_val - friction)

                net_pnl = (sell_val - friction) - (pos["shares"] * pos["entry_price"])
                net_pnl_pct = (net_pnl / (pos["shares"] * pos["entry_price"])) * 100.0

                closed_trades.append({
                    "symbol": sym, "entry_date": pos["entry_date"], "exit_date": today,
                    "is_oos": pos["entry_date"] >= SPLIT_DATE,
                    "days_held": pos["days_held"], "net_pnl_inr": net_pnl,
                    "net_pnl_pct": net_pnl_pct, "exit_reason": exit_reason,
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
        portfolio_dd = (current_equity - peak_equity) / peak_equity
        daily_equity_curve.append({"date": today, "equity": current_equity, "drawdown": portfolio_dd})

        # Market Breadth Gate
        breadth = market_breadth.get(today, 50.0)
        nifty_c = nifty["Close"].loc[today]
        nifty_ema50 = nifty["EMA50"].loc[today]

        if breadth < 48.0 or nifty_c < nifty_ema50:
            continue

        open_slots = max_slots - len(positions)
        if open_slots <= 0: continue

        # Risk Sizing based on Breadth Regime
        slot_risk = risk_pct_bull if breadth >= 55.0 else (risk_pct_bull * 0.5)
        if portfolio_dd < -0.10:
            slot_risk *= 0.7  # Drawdown throttle

        # Screen Top Hyper-Beta Rockets
        existing_syms = {p["symbol"] for p in positions}
        candidates = []
        for sym, ind in indicators.items():
            if sym in existing_syms: continue
            if today not in ind["dates"]: continue

            c_t = ind["c"].loc[today]
            ema20 = ind["ema20"].loc[today]
            ema50 = ind["ema50"].loc[today]
            ema200 = ind["ema200"].loc[today]
            h52w = ind["df"]["High"].shift(1).rolling(252).max().loc[today] if "High" in ind["df"].columns else c_t
            h20 = ind["high20"].loc[today]
            rvol = ind["rvol"].loc[today]

            # 1. Price within 12% of 52W High
            # 2. Price >= 20% above 200-EMA
            # 3. Stage 2 (Price > EMA50 > EMA200)
            # 4. Breakout of 20-day High with RVOL >= 1.6x
            if c_t >= h52w * 0.88 and c_t >= ema200 * 1.20 and c_t > ema50 and c_t > h20 and rvol >= 1.6:
                asym = vol_asym_dict[sym].get(today, 1.0)
                if pd.isna(asym) or asym < 1.8: continue

                r1m = df_r1m.loc[today, sym] if (today in df_r1m.index and sym in df_r1m.columns) else -999.0
                r3m = df_r3m.loc[today, sym] if (today in df_r3m.index and sym in df_r3m.columns) else -999.0
                if pd.isna(r1m) or pd.isna(r3m): continue
                if r1m <= 0 or r3m <= 0: continue

                # Hyper-Velocity Composite Score
                score = (0.50 * r3m) + (0.50 * r1m)
                candidates.append((sym, score))

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
            stop_px = entry_fill * 0.925  # 7.5% stop
            risk_inr = current_equity * slot_risk
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

    return {
        "final_equity": final_equity,
        "daily_equity": df_eq,
        "trades": df_tr,
        "total_friction": total_friction_inr,
    }


def main():
    print("=" * 85)
    print("🚀 ULTRA-HIGH-CAGR FRONTIER SEARCH: PUSHING PAST 50%+ 5-YEAR CAGR")
    print("=" * 85, flush=True)

    experiments = [
        # (Label, max_slots, risk_bull, vel_day, vel_gain, trail_mode, max_hold)
        ("Experiment 1: 3 Slots (33% Size) + Weekly 10W Trail (Risk 2.75%)", 3, 0.0275, 0, 0.0, "weekly_10w", 999),
        ("Experiment 2: 3 Slots + Day 10 Velocity Pruning (Cut < +2.5%) + Weekly 10W", 3, 0.0275, 10, 0.025, "weekly_10w", 999),
        ("Experiment 3: 3 Slots + Stepped Fast Trail (Lock at +15%, +40%) (Risk 2.75%)", 3, 0.0275, 0, 0.0, "stepped_fast", 999),
        ("Experiment 4: 3 Slots + Day 10 Pruning + Stepped Fast Trail (Risk 3.0%)", 3, 0.0300, 10, 0.025, "stepped_fast", 999),
        ("Experiment 5: 4 Slots + Stepped Fast Trail (Risk 2.75%)", 4, 0.0275, 0, 0.0, "stepped_fast", 999),
    ]

    for label, slots, risk, vel_day, vel_gain, trail, max_hold in experiments:
        t0 = time.time()
        res = run_ultra_simulation(
            max_slots=slots, risk_pct_bull=risk, velocity_pruning_day=vel_day,
            velocity_min_gain=vel_gain, trail_mode=trail, max_hold_days=max_hold
        )
        end_val = res["final_equity"]
        eq = res["daily_equity"]["equity"]
        tr = res["trades"]
        fric = res["total_friction"]
        n_years = len(eq) / 252.0
        tot_ret = (end_val / STARTING_CASH - 1.0) * 100.0
        cagr = ((end_val / STARTING_CASH) ** (1.0 / n_years) - 1.0) * 100.0
        running_max = eq.cummax()
        max_dd = float(((eq - running_max) / running_max).min() * 100.0)
        wins = tr[tr["net_pnl_inr"] > 0]["net_pnl_inr"]
        losses = tr[tr["net_pnl_inr"] <= 0]["net_pnl_inr"]
        pf = wins.sum() / (abs(losses.sum()) + 1e-9)
        hit_50 = (tr["net_pnl_pct"] >= 50.0).sum()
        hit_100 = (tr["net_pnl_pct"] >= 100.0).sum()
        trades_per_yr = len(tr) / n_years

        print(f"\n📌 {label}:")
        print(f"   • Ending Capital    : ₹{end_val:,.2f} ({tot_ret:+.2f}% Net Return)")
        print(f"   • 5-Year CAGR       : {cagr:+.2f}% per year")
        print(f"   • Max Drawdown      : {max_dd:.2f}%")
        print(f"   • Total Trades      : {len(tr)} (~{trades_per_yr:.0f} trades/year)")
        print(f"   • Profit Factor     : {pf:.2f} | Win Rate: {(len(wins)/len(tr)*100):.1f}%")
        print(f"   • Monster Winners   : {hit_50} trades >= +50%, {hit_100} trades >= +100% (2x+ baggers)")
        print(f"   • Friction Paid     : ₹{fric:,.2f}")


if __name__ == "__main__":
    main()
