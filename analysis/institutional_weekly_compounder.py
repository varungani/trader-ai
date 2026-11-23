"""
TraderAI - Institutional Weekly Trend Compounding Simulator (2021-2026)
========================================================================
Combines:
  1. Frontier 1's Proven Edge: Institutional Weekly Trend Trailing (Friday Close < 10W/20W EMA)
  2. Frontier 3's Proven Sweet Spot: 4 High-Conviction Slots (25% Capital Per Position)
  3. No Artificial Day Caps: Let multi-baggers run as long as the weekly trend holds!
  4. Multi-Tier Market Breadth Gate (>= 50% for full deployment)
  5. Exact Indian Delivery Taxes (STT, GST, DP, Slippage) + 6.5% LiquidBees Yield on Cash
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

SLIPPAGE = 0.0025
STARTING_CASH = 100000.0
CASH_YIELD_ANNUAL = 0.065
DAILY_CASH_YIELD = (1.0 + CASH_YIELD_ANNUAL) ** (1.0 / 252.0) - 1.0
SPLIT_DATE = pd.Timestamp("2024-04-01")


@dataclass
class WeeklyPosition:
    symbol: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: int
    capital_invested: float
    initial_stop: float
    current_stop: float
    days_held: int = 0
    highest_close: float = 0.0


def run_weekly_trend_compounding(
    max_slots: int = 4,
    trailing_mode: str = "weekly_10w",  # "weekly_10w", "weekly_20w", "stepped_weekly"
    risk_pct_equity: float = 0.02,     # 2% risk per trade
) -> Dict[str, Any]:
    from analysis.portfolio_cash_simulator import load_universe_and_breadth
    indicators, nifty, market_breadth, df_r1m, df_r3m, df_r6m, n_r1m, n_r3m, n_r6m = load_universe_and_breadth()

    # Precalculate weekly EMAs for each symbol
    weekly_emas: Dict[str, pd.DataFrame] = {}
    for sym, ind in indicators.items():
        df_sym = pd.DataFrame({
            "Open": ind["o"], "High": ind["h"], "Low": ind["l"], "Close": ind["c"]
        }).dropna()
        df_w = df_sym.resample("W-FRI").agg({
            "Open": "first", "High": "max", "Low": "min", "Close": "last"
        }).dropna()
        df_w["EMA10W"] = df_w["Close"].ewm(span=10, adjust=False).mean()
        df_w["EMA20W"] = df_w["Close"].ewm(span=20, adjust=False).mean()
        weekly_emas[sym] = df_w

    trading_dates = list(nifty.index)
    start_idx = 252
    active_dates = trading_dates[start_idx:]

    cash = STARTING_CASH
    positions: List[WeeklyPosition] = []
    closed_trades: List[Dict[str, Any]] = []
    daily_equity_curve: List[Dict[str, Any]] = []

    total_friction_inr = 0.0
    total_yield_earned = 0.0
    peak_equity = STARTING_CASH

    for d_idx, today in enumerate(active_dates):
        if d_idx >= len(active_dates) - 1:
            break
        next_day = active_dates[d_idx + 1]

        if cash > 1000.0:
            yield_inr = cash * DAILY_CASH_YIELD
            cash += yield_inr
            total_yield_earned += yield_inr

        is_friday = (today.weekday() == 4)

        # 1. AUDIT ACTIVE POSITIONS
        open_positions = []
        for pos in positions:
            sym = pos.symbol
            ind = indicators[sym]
            if today not in ind["dates"]:
                open_positions.append(pos)
                continue

            day_o = ind["o"].loc[today]
            day_h = ind["h"].loc[today]
            day_l = ind["l"].loc[today]
            day_c = ind["c"].loc[today]
            pos.days_held += 1

            if day_c > pos.highest_close:
                pos.highest_close = day_c

            gain_pct = (pos.highest_close / pos.entry_price) - 1.0

            exit_occurred = False
            exit_px = 0.0
            exit_reason = ""

            # Hard Emergency Stop: -8% or gap down
            if day_o <= pos.current_stop:
                exit_px = day_o * (1.0 - SLIPPAGE)
                exit_reason = "stop_gap"
                exit_occurred = True
            elif day_l <= pos.current_stop:
                exit_px = pos.current_stop * (1.0 - SLIPPAGE)
                exit_reason = "stop_loss"
                exit_occurred = True

            # Weekly Institutional Trailing Stop (Checked on Friday Close)
            elif is_friday and pos.days_held >= 5:
                w_df = weekly_emas.get(sym)
                if w_df is not None and today in w_df.index:
                    w_close = w_df.loc[today, "Close"]
                    w_10 = w_df.loc[today, "EMA10W"]
                    w_20 = w_df.loc[today, "EMA20W"]

                    if trailing_mode == "weekly_10w":
                        if w_close < w_10:
                            exit_px = day_c * (1.0 - SLIPPAGE)
                            exit_reason = "trail_weekly_10w"
                            exit_occurred = True
                    elif trailing_mode == "weekly_20w":
                        if w_close < w_20:
                            exit_px = day_c * (1.0 - SLIPPAGE)
                            exit_reason = "trail_weekly_20w"
                            exit_occurred = True
                    elif trailing_mode == "stepped_weekly":
                        # If gain < +25%, give room with 20W EMA (~100d line)
                        # Once gain >= +25%, tighten to 10W EMA (~50d line)
                        # Once gain >= +60%, tighten to 5-day EMA (or 10W * 1.02)
                        if gain_pct >= 0.60 and day_c < ind["ema20"].loc[today]:
                            exit_px = day_c * (1.0 - SLIPPAGE)
                            exit_reason = "trail_stepped_ema20"
                            exit_occurred = True
                        elif gain_pct >= 0.25 and w_close < w_10:
                            exit_px = day_c * (1.0 - SLIPPAGE)
                            exit_reason = "trail_stepped_10w"
                            exit_occurred = True
                        elif gain_pct < 0.25 and w_close < w_20:
                            exit_px = day_c * (1.0 - SLIPPAGE)
                            exit_reason = "trail_stepped_20w"
                            exit_occurred = True

            if exit_occurred:
                sell_val = pos.shares * exit_px
                stt = sell_val * 0.001
                other_tax = sell_val * 0.000042
                dp = 15.93
                friction = stt + other_tax + dp + (sell_val * SLIPPAGE)
                total_friction_inr += friction
                cash += (sell_val - friction)

                net_pnl = (sell_val - friction) - (pos.shares * pos.entry_price)
                net_pnl_pct = (net_pnl / (pos.shares * pos.entry_price)) * 100.0

                closed_trades.append({
                    "symbol": sym,
                    "entry_date": pos.entry_date,
                    "exit_date": today,
                    "is_oos": pos.entry_date >= SPLIT_DATE,
                    "holding_days": pos.days_held,
                    "entry_price": pos.entry_price,
                    "exit_price": exit_px,
                    "shares": pos.shares,
                    "net_pnl_inr": net_pnl,
                    "net_pnl_pct": net_pnl_pct,
                    "exit_reason": exit_reason,
                })
            else:
                open_positions.append(pos)

        positions = open_positions

        # 2. MARK TO MARKET
        current_equity = cash
        for pos in positions:
            sym = pos.symbol
            ind = indicators[sym]
            if today in ind["dates"]:
                current_equity += pos.shares * ind["c"].loc[today]
            else:
                current_equity += pos.shares * pos.entry_price

        if current_equity > peak_equity:
            peak_equity = current_equity
        portfolio_dd = (current_equity - peak_equity) / peak_equity

        daily_equity_curve.append({
            "date": today,
            "equity": current_equity,
            "cash": cash,
            "positions_count": len(positions),
            "drawdown": portfolio_dd,
        })

        # 3. REGIME CHECK & NEW ENTRIES
        open_slots = max_slots - len(positions)
        if open_slots <= 0:
            continue

        breadth_val = market_breadth.get(today, 50.0)
        nifty_c = nifty["Close"].loc[today]
        nifty_ema50 = nifty["EMA50"].loc[today]

        if breadth_val < 45.0 or nifty_c < nifty_ema50:
            continue

        slot_risk = risk_pct_equity if breadth_val >= 55.0 else (risk_pct_equity * 0.5)
        if portfolio_dd < -0.08:
            slot_risk *= 0.7

        existing_syms = {p.symbol for p in positions}

        candidates = []
        for sym, ind in indicators.items():
            if sym in existing_syms:
                continue
            if today not in ind["dates"]:
                continue

            c_today = ind["c"].loc[today]
            h50 = ind["high50"].loc[today]
            ema50 = ind["ema50"].loc[today]
            ema20 = ind["ema20"].loc[today]
            rvol_today = ind["rvol"].loc[today]
            atr = ind["atr14"].loc[today]

            # Stage 2 + 50D Breakout + RVOL >= 1.5x
            if c_today > h50 and c_today > ema50 and c_today > ema20 and rvol_today >= 1.5:
                r1m = df_r1m.loc[today, sym] if (today in df_r1m.index and sym in df_r1m.columns) else -999.0
                r3m = df_r3m.loc[today, sym] if (today in df_r3m.index and sym in df_r3m.columns) else -999.0
                r6m = df_r6m.loc[today, sym] if (today in df_r6m.index and sym in df_r6m.columns) else -999.0

                if pd.isna(r1m) or pd.isna(r3m) or pd.isna(r6m):
                    continue

                # Anti-exhaustion RS filter
                if r6m > 0 and r1m < 0:
                    continue

                composite_rs = (0.50 * r1m) + (0.30 * r3m) + (0.20 * r6m)
                candidates.append((sym, composite_rs, atr))

        if not candidates:
            continue

        candidates.sort(key=lambda x: x[1], reverse=True)
        chosen = candidates[:open_slots]

        for sym, rs_val, atr_val in chosen:
            ind = indicators[sym]
            if next_day not in ind["dates"]:
                continue

            day0_c = ind["c"].loc[today]
            next_o = ind["o"].loc[next_day]

            gap_pct = (next_o / day0_c) - 1.0
            if gap_pct > 0.025:
                continue

            entry_fill = next_o * (1.0 + SLIPPAGE)
            stop_distance = max(entry_fill * 0.07, 2.0 * atr_val)
            initial_stop_px = entry_fill - stop_distance

            target_risk_inr = current_equity * slot_risk
            risk_per_share = entry_fill - initial_stop_px
            if risk_per_share <= 0:
                continue

            shares_by_risk = int(target_risk_inr / risk_per_share)
            max_capital_per_slot = current_equity / max_slots
            shares_by_cap = int(max_capital_per_slot / entry_fill)

            shares = min(shares_by_risk, shares_by_cap)
            if shares <= 0:
                continue

            position_cost = shares * entry_fill
            stt = position_cost * 0.001
            stamp = position_cost * 0.00015
            other = position_cost * 0.000042
            buy_friction = stt + stamp + other + (position_cost * SLIPPAGE)

            total_required = position_cost + buy_friction
            if cash < total_required:
                shares = int(cash / (entry_fill * 1.005))
                if shares <= 0:
                    continue
                position_cost = shares * entry_fill
                buy_friction = (position_cost * 0.001192) + (position_cost * SLIPPAGE)
                total_required = position_cost + buy_friction
                if cash < total_required:
                    continue

            cash -= total_required
            total_friction_inr += buy_friction

            positions.append(WeeklyPosition(
                symbol=sym,
                entry_date=next_day,
                entry_price=entry_fill,
                shares=shares,
                capital_invested=position_cost,
                initial_stop=initial_stop_px,
                current_stop=initial_stop_px,
                days_held=0,
                highest_close=entry_fill,
            ))

    # Liquidation at end
    final_equity = cash
    last_day = active_dates[-1]
    for pos in positions:
        sym = pos.symbol
        ind = indicators[sym]
        exit_px = ind["c"].loc[last_day] if last_day in ind["dates"] else pos.entry_price
        sell_val = pos.shares * exit_px * (1.0 - SLIPPAGE)
        friction = (sell_val * 0.001042) + 15.93 + (sell_val * SLIPPAGE)
        total_friction_inr += friction
        final_equity += (sell_val - friction)

    df_eq = pd.DataFrame(daily_equity_curve)
    df_trades = pd.DataFrame(closed_trades)

    return {
        "final_equity": final_equity,
        "daily_equity": df_eq,
        "trades": df_trades,
        "total_friction": total_friction_inr,
        "total_yield": total_yield_earned,
    }


def main():
    print("=" * 85)
    print("🚀 INSTITUTIONAL WEEKLY TREND COMPOUNDING SIMULATOR (5 YEARS: 2021-2026)")
    print("=" * 85, flush=True)

    configs = [
        ("Daily Stepped EMA (Base Model - 4 Slots)", 4, "daily_base"),
        ("Weekly 10-Week EMA Trailing (4 Slots)", 4, "weekly_10w"),
        ("Weekly 20-Week EMA Deep Trend (4 Slots)", 4, "weekly_20w"),
        ("Stepped Weekly Trend (20W -> 10W -> Tight Daily) (4 Slots)", 4, "stepped_weekly"),
        ("Stepped Weekly Trend (3 Slots - 33% Conviction)", 3, "stepped_weekly"),
    ]

    for label, slots, mode in configs:
        t0 = time.time()
        if mode == "daily_base":
            from analysis.high_octane_cagr_simulator import run_high_octane_simulation
            res = run_high_octane_simulation(max_slots=slots, enable_pyramiding=False, risk_pct_equity=0.0175)
            end_val = res["final_cash"]
            eq = res["equity_curve"]["equity"]
            tr = res["trades"]
            fric = res["total_friction"]
        else:
            res = run_weekly_trend_compounding(max_slots=slots, trailing_mode=mode, risk_pct_equity=0.0175)
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

        elapsed = time.time() - t0
        print(f"\n📌 {label}:")
        print(f"   • Ending Capital    : ₹{end_val:,.2f} ({tot_ret:+.2f}% Net Return)")
        print(f"   • 5-Year CAGR       : {cagr:+.2f}% per year")
        print(f"   • Max Drawdown      : {max_dd:.2f}%")
        print(f"   • Profit Factor     : {pf:.2f} | Win Rate: {(len(wins)/len(tr)*100):.1f}% ({len(tr)} trades)")
        print(f"   • Large Winners     : {hit_50} trades >= +50%, {hit_100} trades >= +100% (2x+ baggers)")
        print(f"   • Friction Paid     : ₹{fric:,.2f}")
        print(f"   • Time Taken        : {elapsed:.1f}s")


if __name__ == "__main__":
    main()
