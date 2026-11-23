"""
TraderAI - Extreme Alpha & 100%+ Annual Return Research (2021-2026)
================================================================================
Investigates the theoretical and empirical ceiling of Cash Delivery Returns:
Can an ultra-concentrated systematic momentum engine achieve 100%, 200%, or 300%
annual returns (or 80%-100%+ 5-year CAGR) across 626 NSE stocks?

Explores:
  1. Ultra-Concentration: 2 High-Conviction Slots (50% Capital per Stock)
  2. The "Market King" Model: 60% in #1 RS Leader, 40% in #2 RS Leader
  3. Continuous Floating Profit Pyramiding (+40% add on secondary bases)
  4. Regime Leverage: 100% deployment in roaring bull regimes (Breadth >= 60%)
  5. Full statutory Indian delivery friction (STT, GST, DP ₹15.93, slippage)
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

# Precalculate Weekly 10W EMA and Volume Asymmetry
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


@dataclass
class ExtremePosition:
    symbol: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: int
    capital_invested: float
    initial_stop: float
    current_stop: float
    days_held: int = 0
    highest_close: float = 0.0
    pyramided: bool = False


def run_extreme_simulation(
    max_slots: int = 2,
    slot1_weight: float = 0.50,
    slot2_weight: float = 0.50,
    enable_pyramiding: bool = True,
    risk_pct_bull: float = 0.038,     # 3.8% equity risk
) -> Dict[str, Any]:
    cash = STARTING_CASH
    positions: List[ExtremePosition] = []
    closed_trades: List[Dict[str, Any]] = []
    daily_equity_curve: List[Dict[str, Any]] = []
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

            if day_c > pos.highest_close: pos.highest_close = day_c
            gain_pct = (day_c / pos.entry_price) - 1.0

            # Pyramiding: Add +40% shares on secondary breakout once gain >= +20%
            if enable_pyramiding and not pos.pyramided and pos.days_held >= 15 and gain_pct >= 0.20:
                h20 = ind["high20"].loc[today]
                rvol = ind["rvol"].loc[today]
                if day_c > h20 and rvol >= 1.5:
                    add_shares = int(pos.shares * 0.40)
                    if add_shares > 0:
                        add_cost = add_shares * day_c * (1.0 + SLIPPAGE)
                        add_fric = (add_cost * 0.001192) + (add_cost * SLIPPAGE)
                        if cash >= add_cost + add_fric:
                            cash -= (add_cost + add_fric)
                            total_friction_inr += add_fric
                            total_shares = pos.shares + add_shares
                            pos.entry_price = ((pos.shares * pos.entry_price) + add_cost) / total_shares
                            pos.shares = total_shares
                            pos.current_stop = max(pos.current_stop, pos.entry_price * 0.98) # Stop near breakeven
                            pos.pyramided = True

            exit_occurred = False
            exit_px = 0.0

            # Hard stop
            if day_o <= pos.current_stop:
                exit_px = day_o * (1.0 - SLIPPAGE)
                exit_occurred = True
            elif day_l <= pos.current_stop:
                exit_px = pos.current_stop * (1.0 - SLIPPAGE)
                exit_occurred = True
            elif is_friday and pos.days_held >= 5:
                w_df = weekly_emas.get(sym)
                if w_df is not None and today in w_df.index:
                    if w_df.loc[today, "Close"] < w_df.loc[today, "EMA10W"]:
                        exit_px = day_c * (1.0 - SLIPPAGE)
                        exit_occurred = True

            if exit_occurred:
                sell_val = pos.shares * exit_px
                friction = (sell_val * 0.001042) + 15.93 + (sell_val * SLIPPAGE)
                total_friction_inr += friction
                cash += (sell_val - friction)

                net_pnl = (sell_val - friction) - (pos.shares * pos.entry_price)
                net_pnl_pct = (net_pnl / (pos.shares * pos.entry_price)) * 100.0

                closed_trades.append({
                    "symbol": sym, "entry_date": pos.entry_date, "exit_date": today,
                    "is_oos": pos.entry_date >= SPLIT_DATE, "days_held": pos.days_held,
                    "net_pnl_inr": net_pnl, "net_pnl_pct": net_pnl_pct,
                })
            else:
                open_positions.append(pos)

        positions = open_positions

        current_equity = cash
        for pos in positions:
            sym = pos.symbol
            ind = indicators[sym]
            px = ind["c"].loc[today] if today in ind["dates"] else pos.entry_price
            current_equity += pos.shares * px

        if current_equity > peak_equity: peak_equity = current_equity
        portfolio_dd = (current_equity - peak_equity) / peak_equity
        daily_equity_curve.append({"date": today, "equity": current_equity, "drawdown": portfolio_dd})

        breadth_val = market_breadth.get(today, 50.0)
        nifty_c = nifty["Close"].loc[today]
        nifty_ema50 = nifty["EMA50"].loc[today]

        if breadth_val < 45.0 or nifty_c < nifty_ema50:
            continue

        open_slots = max_slots - len(positions)
        if open_slots <= 0: continue

        # Risk sizing
        if breadth_val >= 65.0:
            slot_risk = risk_pct_bull * 1.35
        elif breadth_val >= 55.0:
            slot_risk = risk_pct_bull
        else:
            slot_risk = risk_pct_bull * 0.50

        if portfolio_dd < -0.10:
            slot_risk *= 0.70

        existing_syms = {p.symbol for p in positions}
        candidates = []
        for sym, ind in indicators.items():
            if sym in existing_syms: continue
            if today not in ind["dates"]: continue

            c_today = ind["c"].loc[today]
            h50 = ind["high50"].loc[today]
            ema50 = ind["ema50"].loc[today]
            ema20 = ind["ema20"].loc[today]
            ema200 = ind["ema200"].loc[today]
            rvol_today = ind["rvol"].loc[today]
            atr = ind["atr14"].loc[today]

            if c_today > h50 and c_today > ema50 and c_today > ema20 and rvol_today >= 1.5:
                if (c_today / (ema200 + 1e-9) - 1.0) < 0.20: continue
                sym_asym = vol_asym_dict[sym].get(today, 1.0)
                if pd.isna(sym_asym) or sym_asym < 2.0: continue

                r1m = df_r1m.loc[today, sym] if (today in df_r1m.index and sym in df_r1m.columns) else -999.0
                r3m = df_r3m.loc[today, sym] if (today in df_r3m.index and sym in df_r3m.columns) else -999.0
                r6m = df_r6m.loc[today, sym] if (today in df_r6m.index and sym in df_r6m.columns) else -999.0

                if pd.isna(r1m) or pd.isna(r3m) or pd.isna(r6m): continue
                if r6m > 0 and r1m < 0: continue

                composite_rs = (0.50 * r1m) + (0.30 * r3m) + (0.20 * r6m)
                candidates.append((sym, composite_rs, atr))

        if not candidates: continue
        candidates.sort(key=lambda x: x[1], reverse=True)
        chosen = candidates[:open_slots]

        for rank_idx, (sym, rs_val, atr_val) in enumerate(chosen):
            ind = indicators[sym]
            if next_day not in ind["dates"]: continue

            day0_c = ind["c"].loc[today]
            next_o = ind["o"].loc[next_day]

            gap_pct = (next_o / day0_c) - 1.0
            if gap_pct > 0.025: continue

            entry_fill = next_o * (1.0 + SLIPPAGE)
            stop_distance = max(entry_fill * 0.07, 2.0 * atr_val)
            initial_stop_px = entry_fill - stop_distance

            target_risk_inr = current_equity * slot_risk
            risk_per_share = entry_fill - initial_stop_px
            if risk_per_share <= 0: continue

            # Slot weighting
            if len(positions) == 0 and rank_idx == 0:
                slot_cap = current_equity * slot1_weight
            else:
                slot_cap = current_equity * slot2_weight

            shares = min(int(target_risk_inr / risk_per_share), int(slot_cap / entry_fill))
            if shares <= 0: continue

            position_cost = shares * entry_fill
            buy_friction = (position_cost * 0.001192) + (position_cost * SLIPPAGE)
            if cash < position_cost + buy_friction:
                shares = int(cash / (entry_fill * 1.005))
                if shares <= 0: continue
                position_cost = shares * entry_fill
                buy_friction = (position_cost * 0.001192) + (position_cost * SLIPPAGE)
                if cash < position_cost + buy_friction: continue

            cash -= (position_cost + buy_friction)
            total_friction_inr += buy_friction

            positions.append(ExtremePosition(
                symbol=sym, entry_date=next_day, entry_price=entry_fill,
                shares=shares, capital_invested=position_cost,
                initial_stop=initial_stop_px, current_stop=initial_stop_px,
                days_held=0, highest_close=entry_fill,
            ))

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
    }


def main():
    print("=" * 85)
    print("🚀 EXTREME ALPHA & 100%+ ANNUAL RETURN EMPIRICAL RESEARCH (2021-2026)")
    print("=" * 85, flush=True)

    experiments = [
        ("Extreme Model 1: 2 Slots (50% each), Risk 3.8%, Pyramiding", 2, 0.50, 0.50, True, 0.038),
        ("Extreme Model 2: 2 Slots (60% / 40%), Risk 4.2%, Pyramiding", 2, 0.60, 0.40, True, 0.042),
        ("Extreme Model 3: 2 Slots (50% each), Risk 4.5%, Pyramiding", 2, 0.50, 0.50, True, 0.045),
        ("Extreme Model 4: 3 Slots (40% / 30% / 30%), Risk 3.8%, Pyramiding", 3, 0.40, 0.30, True, 0.038),
    ]

    for label, slots, w1, w2, pyr, risk in experiments:
        t0 = time.time()
        res = run_extreme_simulation(
            max_slots=slots, slot1_weight=w1, slot2_weight=w2,
            enable_pyramiding=pyr, risk_pct_bull=risk,
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

        # Yearly analysis: Did any year hit +100% or +200%?
        df_eq = res["daily_equity"].copy()
        df_eq["year"] = pd.to_datetime(df_eq["date"]).dt.year
        yearly_rets = []
        for y, g in df_eq.groupby("year"):
            y_ret = (g["equity"].iloc[-1] / g["equity"].iloc[0] - 1.0) * 100.0
            yearly_rets.append(f"{y}: {y_ret:+.1f}%")
        yearly_str = " | ".join(yearly_rets)

        print(f"\n📌 {label}:")
        print(f"   • Ending Capital    : ₹{end_val:,.2f} ({tot_ret:+.2f}% Net Return / {end_val/STARTING_CASH:.1f}x)")
        print(f"   • 5-Year CAGR       : {cagr:+.2f}% per year")
        print(f"   • Max Drawdown      : {max_dd:.2f}%")
        print(f"   • Total Trades      : {len(tr)} trades | Profit Factor: {pf:.2f}")
        print(f"   • Yearly Returns    : {yearly_str}")
        print(f"   • Friction Paid     : ₹{fric:,.2f}")


if __name__ == "__main__":
    main()
