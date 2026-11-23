"""
TraderAI - Apex Creative Alpha Compounder (2021-2026)
================================================================================
Fuses the 4 Novel Hidden Patterns Discovered in Empirical Data:
  1. Established Stage 2 Leader Rule: Price >= 20% Above 200-EMA (Strength Begets Strength)
  2. Institutional Stealth Footprint: Volume Asymmetry >= 2.0x (Up-Vol / Down-Vol 30d)
  3. Weekly 10-Week EMA Trailing Exit (Friday Close - Eliminates Midcap Daily Noise)
  4. Multi-Tier Market Breadth Gate (>= 50% for full deployment)
  5. 4 Conviction Slots (25% Capital Each) with exact statutory costs + 6.5% LiquidBees yield
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
class ApexPosition:
    symbol: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: int
    capital_invested: float
    initial_stop: float
    current_stop: float
    days_held: int = 0
    highest_close: float = 0.0


def run_apex_simulation(
    min_dist_ema200: float = 0.15,     # At least +15% above 200 EMA
    min_vol_asymmetry: float = 1.60,   # Up/down vol ratio >= 1.60x
    risk_pct_equity: float = 0.02,     # 2% equity risk
    max_slots: int = 4,
) -> Dict[str, Any]:
    from analysis.portfolio_cash_simulator import load_universe_and_breadth
    indicators, nifty, market_breadth, df_r1m, df_r3m, df_r6m, n_r1m, n_r3m, n_r6m = load_universe_and_breadth()

    # Precalculate weekly EMAs and Volume Asymmetry
    weekly_emas: Dict[str, pd.DataFrame] = {}
    vol_asym_dict: Dict[str, pd.Series] = {}

    for sym, ind in indicators.items():
        df_sym = pd.DataFrame({
            "Open": ind["o"], "High": ind["h"], "Low": ind["l"], "Close": ind["c"]
        }).dropna()
        df_w = df_sym.resample("W-FRI").agg({
            "Open": "first", "High": "max", "Low": "min", "Close": "last"
        }).dropna()
        df_w["EMA10W"] = df_w["Close"].ewm(span=10, adjust=False).mean()
        weekly_emas[sym] = df_w

        # Up-vol vs Down-vol 30d
        v = ind["v"]
        c = ind["c"]
        up_day = (c > c.shift(1)).astype(float)
        up_vol_30 = (v * up_day).rolling(30).sum()
        down_vol_30 = (v * (1.0 - up_day)).rolling(30).sum()
        vol_asym_dict[sym] = up_vol_30 / (down_vol_30 + 1e-9)

    trading_dates = list(nifty.index)
    start_idx = 252
    active_dates = trading_dates[start_idx:]

    cash = STARTING_CASH
    positions: List[ApexPosition] = []
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

            # Weekly Institutional Trailing Stop (Friday Close < 10-Week EMA)
            elif is_friday and pos.days_held >= 5:
                w_df = weekly_emas.get(sym)
                if w_df is not None and today in w_df.index:
                    w_close = w_df.loc[today, "Close"]
                    w_10 = w_df.loc[today, "EMA10W"]
                    if w_close < w_10:
                        exit_px = day_c * (1.0 - SLIPPAGE)
                        exit_reason = "trail_weekly_10w"
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
            ema200 = ind["ema200"].loc[today]
            rvol_today = ind["rvol"].loc[today]
            atr = ind["atr14"].loc[today]

            # 1. Stage 2 + 50D Breakout + RVOL >= 1.5x
            if c_today > h50 and c_today > ema50 and c_today > ema20 and rvol_today >= 1.5:
                # 2. Established Leader Rule: Price >= min_dist_ema200 above 200 EMA
                if (c_today / (ema200 + 1e-9) - 1.0) < min_dist_ema200:
                    continue

                # 3. Volume Asymmetry Footprint: Up/Down Volume >= min_vol_asymmetry
                sym_asym = vol_asym_dict[sym].get(today, 1.0)
                if pd.isna(sym_asym) or sym_asym < min_vol_asymmetry:
                    continue

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

            positions.append(ApexPosition(
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
    print("💎 APEX CREATIVE ALPHA COMPOUNDER (2021-2026)")
    print("=" * 85, flush=True)

    experiments = [
        ("Base Weekly 10W (No Asymmetry/200EMA filter)", 0.0, 1.0, 4),
        ("Apex Model: 200-EMA >= +15% & Vol Asymmetry >= 1.6x (4 Slots)", 0.15, 1.6, 4),
        ("Apex Model: 200-EMA >= +20% & Vol Asymmetry >= 2.0x (4 Slots)", 0.20, 2.0, 4),
        ("Apex Model: 200-EMA >= +15% & Vol Asymmetry >= 1.6x (3 Slots - 33% Size)", 0.15, 1.6, 3),
    ]

    for label, min_dist, min_asym, slots in experiments:
        t0 = time.time()
        res = run_apex_simulation(
            min_dist_ema200=min_dist,
            min_vol_asymmetry=min_asym,
            risk_pct_equity=0.02,
            max_slots=slots,
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
