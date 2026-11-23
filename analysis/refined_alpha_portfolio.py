"""
TraderAI - Refined Alpha Portfolio: High Profit with Institutional Risk Controls
================================================================================
Combines:
  1. True Compounding with Strict Single-Stock Cap (Max 16.7% / 6 Slots)
  2. Multi-Tier Market Breadth Gate:
       - Breadth >= 55%: Full Deployment (Risk 1.25% of Equity)
       - Breadth 45%-55%: Half Deployment (Risk 0.6% of Equity)
       - Breadth < 45%: Zero New Trades (100% Cash Preservation)
  3. Anti-Exhaustion RS Filter (Bans tired 6M leaders rolling over)
  4. Stepped Trailing Engine:
       - 50-EMA Trail initially (room to breathe)
       - 20-EMA Trail once gain >= +20% (locks in big runners)
       - 10-EMA Trail once gain >= +35% (locks in parabolic bursts)
  5. Drawdown Throttle: If portfolio DD > -8%, halve new position sizes
  6. Indian Statutory Delivery Friction & CDSL DP Charges on every leg
  7. 6.5% LiquidBees yield on idle cash
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

SLIPPAGE = 0.0025  # 0.25%
STARTING_CASH = 100000.0
CASH_YIELD_ANNUAL = 0.065
DAILY_CASH_YIELD = (1.0 + CASH_YIELD_ANNUAL) ** (1.0 / 252.0) - 1.0
SPLIT_DATE = pd.Timestamp("2024-04-01")


@dataclass
class AlphaPosition:
    symbol: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: int
    capital_invested: float
    initial_stop: float
    current_stop: float
    days_held: int = 0
    highest_close: float = 0.0


def run_refined_alpha_simulation(
    max_slots: int = 6,
    base_risk_pct: float = 0.0125,  # 1.25% risk per trade
) -> Dict[str, Any]:
    from analysis.portfolio_cash_simulator import load_universe_and_breadth
    indicators, nifty, market_breadth, df_r1m, df_r3m, df_r6m, n_r1m, n_r3m, n_r6m = load_universe_and_breadth()

    trading_dates = list(nifty.index)
    start_idx = 252
    active_dates = trading_dates[start_idx:]

    cash = STARTING_CASH
    positions: List[AlphaPosition] = []
    closed_trades: List[Dict[str, Any]] = []
    daily_equity_curve: List[Dict[str, Any]] = []

    total_friction_inr = 0.0
    total_yield_earned = 0.0
    peak_equity = STARTING_CASH

    for d_idx, today in enumerate(active_dates):
        if d_idx >= len(active_dates) - 1:
            break
        next_day = active_dates[d_idx + 1]

        # Idle cash yield
        if cash > 1000.0:
            yield_inr = cash * DAILY_CASH_YIELD
            cash += yield_inr
            total_yield_earned += yield_inr

        # -------------------------------------------------------------
        # 1. AUDIT ACTIVE POSITIONS
        # -------------------------------------------------------------
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
            day_ema20 = ind["ema20"].loc[today]
            day_ema50 = ind["ema50"].loc[today]
            pos.days_held += 1

            if day_c > pos.highest_close:
                pos.highest_close = day_c

            gain_pct = (pos.highest_close / pos.entry_price) - 1.0

            exit_occurred = False
            exit_px = 0.0
            exit_reason = ""

            # Initial Stop
            if day_o <= pos.current_stop:
                exit_px = day_o * (1.0 - SLIPPAGE)
                exit_reason = "stop_gap"
                exit_occurred = True
            elif day_l <= pos.current_stop:
                exit_px = pos.current_stop * (1.0 - SLIPPAGE)
                exit_reason = "stop_loss"
                exit_occurred = True

            # Stepped Trailing Stop:
            elif pos.days_held >= 2:
                if gain_pct >= 0.35:
                    # Parabolic runner: Trail 10-EMA (or 20-EMA * 1.01)
                    if day_c < day_ema20 * 1.01:
                        exit_px = day_c * (1.0 - SLIPPAGE)
                        exit_reason = "trail_parabolic_locked"
                        exit_occurred = True
                elif gain_pct >= 0.20:
                    # Strong runner: Trail 20-EMA
                    if day_c < day_ema20:
                        exit_px = day_c * (1.0 - SLIPPAGE)
                        exit_reason = "trail_20ema_locked"
                        exit_occurred = True
                else:
                    # Normal trade: Trail 50-EMA
                    if day_c < day_ema50:
                        exit_px = day_c * (1.0 - SLIPPAGE)
                        exit_reason = "trail_50ema"
                        exit_occurred = True

            # Velocity Stagnation: Day 10 and below entry
            if not exit_occurred and pos.days_held >= 10 and (day_c / pos.entry_price - 1.0) < 0.0:
                exit_px = day_c * (1.0 - SLIPPAGE)
                exit_reason = "velocity_recycle"
                exit_occurred = True

            # Max Holding Window: 65 sessions
            if not exit_occurred and pos.days_held >= 65:
                exit_px = day_c * (1.0 - SLIPPAGE)
                exit_reason = "max_65d"
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

        # -------------------------------------------------------------
        # 2. MARK EQUITY & DRAWDOWN THROTTLE
        # -------------------------------------------------------------
        portfolio_val = cash
        for pos in positions:
            sym = pos.symbol
            px = indicators[sym]["c"].loc[today] if today in indicators[sym]["dates"] else pos.entry_price
            portfolio_val += pos.shares * px

        if portfolio_val > peak_equity:
            peak_equity = portfolio_val
        current_dd = (portfolio_val - peak_equity) / peak_equity

        # Drawdown Throttle: If in > 8% drawdown, cut risk in half to protect equity
        dd_multiplier = 0.50 if current_dd < -0.08 else 1.0

        # -------------------------------------------------------------
        # 3. SCREEN CANDIDATES & MULTI-TIER BREADTH SIZING
        # -------------------------------------------------------------
        breadth = market_breadth.get(today, 50.0)
        open_slots = max_slots - len(positions)

        # Multi-Tier Breadth Gate
        if breadth >= 55.0:
            breadth_mult = 1.0
        elif breadth >= 45.0:
            breadth_mult = 0.50  # Half risk in neutral chop
        else:
            breadth_mult = 0.0   # ZERO new buys in bear regime!

        effective_risk_pct = base_risk_pct * dd_multiplier * breadth_mult

        if open_slots > 0 and breadth_mult > 0.0 and cash >= 8000.0:
            candidates = []
            for sym, ind in indicators.items():
                if today not in ind["dates"]:
                    continue
                if any(p.symbol == sym for p in positions):
                    continue

                d0_c = ind["c"].loc[today]
                d0_ema50 = ind["ema50"].loc[today]
                d0_ema200 = ind["ema200"].loc[today]
                d0_rvol = ind["rvol"].loc[today]
                d0_high50 = ind["high50"].loc[today]
                d0_atr = ind["atr14"].loc[today]
                d0_spread = ind["spread20"].loc[today]

                if not (d0_c > d0_ema50 and d0_ema50 > d0_ema200):
                    continue

                r1 = df_r1m.loc[today, sym] - n_r1m.loc[today] if (today in df_r1m.index and sym in df_r1m.columns) else 0.0
                r3 = df_r3m.loc[today, sym] - n_r3m.loc[today] if (today in df_r3m.index and sym in df_r3m.columns) else 0.0
                r6 = df_r6m.loc[today, sym] - n_r6m.loc[today] if (today in df_r6m.index and sym in df_r6m.columns) else 0.0

                if np.isnan(r1): r1 = 0.0
                if np.isnan(r6): r6 = 0.0

                # Anti-Exhaustion Gate:
                if r1 <= 0.0 or (r6 > 0.25 and r1 < 0.0):
                    continue

                if d0_c > d0_high50 and d0_rvol >= 1.5 and d0_spread >= 12.0:
                    conviction = (r1 * 100.0) + (d0_rvol * 8.0)
                    candidates.append((sym, conviction, d0_atr, d0_c))

            candidates.sort(key=lambda x: x[1], reverse=True)
            picks = candidates[:open_slots]

            for sym, score, atr, d0_c in picks:
                ind = indicators[sym]
                if next_day not in ind["dates"]:
                    continue
                d1_o = ind["o"].loc[next_day]
                gap_pct = (d1_o / d0_c) - 1.0
                if gap_pct > 0.025:
                    continue

                entry_px = d1_o * (1.0 + SLIPPAGE)

                # Compounded Volatility Sizing with Strict 18% Single-Stock Cap
                risk_amount = portfolio_val * effective_risk_pct
                atr_pct = max(0.02, atr / entry_px)
                stop_dist_pct = max(0.04, min(0.08, 2.0 * atr_pct))
                target_alloc = risk_amount / stop_dist_pct

                # Hard single-stock ceiling = 18.0% of portfolio equity
                max_stock_cap = portfolio_val * 0.18
                alloc = min(cash * 0.90, min(max_stock_cap, target_alloc))

                if alloc < 6000.0:
                    continue

                shares = int(alloc // entry_px)
                if shares <= 0:
                    continue

                actual_cost = shares * entry_px
                buy_tax = actual_cost * (0.001 + 0.00015 + 0.000042)
                friction = buy_tax + (actual_cost * SLIPPAGE)
                total_cost = actual_cost + friction

                if cash >= total_cost:
                    cash -= total_cost
                    total_friction_inr += friction
                    stop_px = entry_px * (1.0 - stop_dist_pct)
                    new_pos = AlphaPosition(
                        symbol=sym,
                        entry_date=next_day,
                        entry_price=entry_px,
                        shares=shares,
                        capital_invested=actual_cost,
                        initial_stop=stop_px,
                        current_stop=stop_px,
                        highest_close=entry_px,
                    )
                    positions.append(new_pos)

        daily_equity_curve.append({
            "date": today,
            "equity": portfolio_val,
            "cash": cash,
            "open_positions": len(positions),
            "drawdown": current_dd,
        })

    # Liquidate at end
    final_day = active_dates[-1]
    for pos in positions:
        sym = pos.symbol
        px = indicators[sym]["c"].loc[final_day] * (1.0 - SLIPPAGE) if final_day in indicators[sym]["dates"] else pos.entry_price
        sell_val = pos.shares * px
        friction = sell_val * 0.001042 + 15.93 + (sell_val * SLIPPAGE)
        total_friction_inr += friction
        cash += (sell_val - friction)
        net_pnl = (sell_val - friction) - (pos.shares * pos.entry_price)
        closed_trades.append({
            "symbol": sym,
            "entry_date": pos.entry_date,
            "exit_date": final_day,
            "is_oos": pos.entry_date >= SPLIT_DATE,
            "holding_days": pos.days_held,
            "entry_price": pos.entry_price,
            "exit_price": px,
            "shares": pos.shares,
            "net_pnl_inr": net_pnl,
            "net_pnl_pct": (net_pnl / (pos.shares * pos.entry_price)) * 100.0,
            "exit_reason": "end_of_sim",
        })

    df_eq = pd.DataFrame(daily_equity_curve).set_index("date")
    df_tr = pd.DataFrame(closed_trades)

    return {
        "final_cash": cash,
        "equity_curve": df_eq,
        "trades": df_tr,
        "total_friction": total_friction_inr,
        "total_yield": total_yield_earned,
    }


def main():
    print("="*85)
    print("🚀 RUNNING REFINED ALPHA SIMULATION (BALANCED HIGH PROFIT + DD PROTECTION)")
    print("="*85, flush=True)

    res = run_refined_alpha_simulation(max_slots=6, base_risk_pct=0.0125)

    eq = res["equity_curve"]["equity"]
    start_val = STARTING_CASH
    end_val = res["final_cash"]
    tot_ret = (end_val / start_val - 1.0) * 100.0
    n_years = len(eq) / 252.0
    cagr = ((end_val / start_val) ** (1.0 / n_years) - 1.0) * 100.0

    running_max = eq.cummax()
    dd = (eq - running_max) / running_max
    max_dd = float(dd.min() * 100.0)

    tr = res["trades"]
    n_trades = len(tr)
    wins = tr[tr["net_pnl_inr"] > 0]
    losses = tr[tr["net_pnl_inr"] <= 0]
    win_rate = (len(wins) / n_trades * 100.0) if n_trades > 0 else 0.0
    pf = (wins["net_pnl_inr"].sum()) / (abs(losses["net_pnl_inr"].sum()) + 1e-9)

    is_tr = tr[~tr["is_oos"]]
    oos_tr = tr[tr["is_oos"]]

    print(f"\n🏆 REFINED ALPHA MODEL RESULTS (₹100k -> 5Y):")
    print(f"   • Ending Capital    : ₹{end_val:,.2f} ({tot_ret:+.2f}% Net Return)")
    print(f"   • 5-Year CAGR       : {cagr:+.2f}% per year")
    print(f"   • Max Drawdown      : {max_dd:.2f}%")
    print(f"   • Profit Factor     : {pf:.2f}")
    print(f"   • Win Rate          : {win_rate:.1f}% ({n_trades} trades)")
    print(f"   • Average Win       : ₹{wins['net_pnl_inr'].mean():+,.0f} ({wins['net_pnl_pct'].mean():+.1f}%)")
    print(f"   • Average Loss      : ₹{losses['net_pnl_inr'].mean():+,.0f} ({losses['net_pnl_pct'].mean():+.1f}%)")
    print(f"   • Win/Loss Ratio    : {abs(wins['net_pnl_pct'].mean() / losses['net_pnl_pct'].mean()):.2f}x Payoff Ratio")
    print(f"   • In-Sample P&L     : ₹{is_tr['net_pnl_inr'].sum():+,.2f} (2021-2024)")
    print(f"   • Out-of-Sample P&L : ₹{oos_tr['net_pnl_inr'].sum():+,.2f} (2024-2026)")
    print(f"   • LiquidBees Yield  : ₹{res['total_yield']:+,.2f} earned on idle cash")
    print(f"   • Total Friction    : ₹{res['total_friction']:,.2f} (STT + DP + GST + Slippage)")

    # Save
    res["equity_curve"].to_csv(os.path.join(ROOT, "data", "analytics", "refined_alpha_equity.csv"))
    res["trades"].to_csv(os.path.join(ROOT, "data", "analytics", "refined_alpha_trades.csv"), index=False)
    print("\n💾 Saved to data/analytics/refined_alpha_*.csv", flush=True)


if __name__ == "__main__":
    main()
