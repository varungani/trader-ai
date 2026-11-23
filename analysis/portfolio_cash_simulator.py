"""
TraderAI - Full 5-Year Portfolio Cash Simulator (2021–2026)
================================================================================
Zero-Lookahead, Strict 5-Slot Cash Compounding, Indian Statutory Friction & DP Charges.

Compares 3 Systems Head-to-Head:
  1. Benchmark: Nifty 50 Buy-and-Hold
  2. System A: Legacy Algos (-4% Stop, +5% Breakeven Lock, +12% Target Ceiling)
  3. System B: Data-Backed Empirical Model (Breadth Gate + Anti-Exhaustion + 8% Stop + 50-EMA Trail)

Simulates day-by-day cash flows, real portfolio capital constraints, and exact taxes.
"""
from __future__ import annotations

import os
import sys
import time
import pickle
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SLIPPAGE = 0.0025  # 0.25% per leg
STARTING_CASH = 100000.0
MAX_SLOTS = 5
SPLIT_DATE = pd.Timestamp("2024-04-01")


@dataclass
class Position:
    symbol: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: int
    capital_invested: float
    initial_stop: float
    current_stop: float
    days_held: int = 0
    t1_harvested: bool = False
    highest_close: float = 0.0


def load_universe_and_breadth():
    print("📦 Loading 5Y universe cache and benchmarks...", flush=True)
    cache_path = os.path.join(ROOT, "data", "cache", "universe_5y.pkl")
    bench_path = os.path.join(ROOT, "data", "cache", "benchmarks_5y.pkl")
    with open(cache_path, "rb") as f:
        universe: Dict[str, pd.DataFrame] = pickle.load(f)
    with open(bench_path, "rb") as f:
        benchmarks: Dict[str, pd.DataFrame] = pickle.load(f)
    nifty = benchmarks['^NSEI'].copy()
    nifty['EMA50'] = nifty['Close'].ewm(span=50, adjust=False).mean()

    # Precalculate Market Breadth & Relative Strength
    print("📊 Computing Market Breadth & 1M/3M/6M Relative Strength...", flush=True)
    all_dates = nifty.index
    breadth_series = pd.Series(0.0, index=all_dates)
    total_active = pd.Series(0, index=all_dates)

    indicators: Dict[str, Dict[str, Any]] = {}
    returns_1m: Dict[str, pd.Series] = {}
    returns_3m: Dict[str, pd.Series] = {}
    returns_6m: Dict[str, pd.Series] = {}

    for sym, raw_df in universe.items():
        if len(raw_df) < 250:
            continue
        c = raw_df['Close']
        h = raw_df['High']
        l = raw_df['Low']
        o = raw_df['Open']
        v = raw_df['Volume']

        ema20 = c.ewm(span=20, adjust=False).mean()
        ema50 = c.ewm(span=50, adjust=False).mean()
        ema200 = c.ewm(span=200, adjust=False).mean()

        prev_c = c.shift(1)
        tr = np.maximum(h - l, np.maximum((h - prev_c).abs(), (l - prev_c).abs()))
        atr14 = tr.rolling(14).mean()

        vol_ma20 = v.rolling(20).mean()
        rvol = v / (vol_ma20 + 1e-9)

        high20 = h.shift(1).rolling(20).max()
        high50 = h.shift(1).rolling(50).max()
        low5 = l.shift(1).rolling(5).min()

        # Consolidation spread: (20d High / 20d Low) - 1
        h20_raw = h.rolling(20).max()
        l20_raw = l.rolling(20).min()
        spread20 = (h20_raw / (l20_raw + 1e-9) - 1.0) * 100.0

        r1 = c / c.shift(21) - 1.0
        r3 = c / c.shift(63) - 1.0
        r6 = c / c.shift(126) - 1.0
        returns_1m[sym] = r1
        returns_3m[sym] = r3
        returns_6m[sym] = r6

        above_50 = (c > ema50).astype(int)
        breadth_series = breadth_series.add(above_50, fill_value=0)
        total_active = total_active.add(above_50.notna().astype(int), fill_value=0)

        indicators[sym] = {
            "dates": set(raw_df.index),
            "df": raw_df,
            "c": c, "h": h, "l": l, "o": o, "v": v,
            "ema20": ema20, "ema50": ema50, "ema200": ema200,
            "atr14": atr14, "rvol": rvol,
            "high20": high20, "high50": high50, "low5": low5,
            "spread20": spread20,
        }

    market_breadth_pct = (breadth_series / (total_active + 1e-9)) * 100.0
    df_r1m = pd.DataFrame(returns_1m)
    df_r3m = pd.DataFrame(returns_3m)
    df_r6m = pd.DataFrame(returns_6m)

    n_r1m = nifty['Close'] / nifty['Close'].shift(21) - 1.0
    n_r3m = nifty['Close'] / nifty['Close'].shift(63) - 1.0
    n_r6m = nifty['Close'] / nifty['Close'].shift(126) - 1.0

    print(f"✅ Precalculated universe of {len(indicators)} stocks.", flush=True)
    return indicators, nifty, market_breadth_pct, df_r1m, df_r3m, df_r6m, n_r1m, n_r3m, n_r6m


# =====================================================================
# SIMULATOR CORE
# =====================================================================
def run_portfolio_simulation(
    system_type: str,
    indicators: Dict[str, Dict[str, Any]],
    nifty: pd.DataFrame,
    market_breadth: pd.Series,
    df_r1m: pd.DataFrame,
    df_r3m: pd.DataFrame,
    df_r6m: pd.DataFrame,
    n_r1m: pd.Series,
    n_r3m: pd.Series,
    n_r6m: pd.Series,
) -> Dict[str, Any]:
    """Runs day-by-day cash accounting across 1,256 market sessions."""
    trading_dates = list(nifty.index)
    start_idx = 252  # Allow 1 year warmup
    active_dates = trading_dates[start_idx:]

    cash = STARTING_CASH
    positions: List[Position] = []
    closed_trades: List[Dict[str, Any]] = []
    daily_equity_curve: List[Dict[str, Any]] = []

    total_friction_inr = 0.0

    for d_idx, today in enumerate(active_dates):
        if d_idx >= len(active_dates) - 1:
            break
        next_day = active_dates[d_idx + 1]

        # -----------------------------------------------------------------
        # STEP 1: AUDIT & UPDATE ACTIVE POSITIONS (During session 'today')
        # -----------------------------------------------------------------
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
            day_ema50 = ind["ema50"].loc[today]
            pos.days_held += 1

            if day_c > pos.highest_close:
                pos.highest_close = day_c

            exit_occurred = False
            exit_px = 0.0
            exit_shares = 0
            exit_reason = ""

            # Check stops and targets depending on system
            if system_type == "legacy":
                # Legacy Rule: Stop -4%, T1 at +5%, Target at +12%
                # 1. Stop hit?
                if day_o <= pos.current_stop:
                    exit_px = day_o * (1.0 - SLIPPAGE)
                    exit_shares = pos.shares
                    exit_reason = "stop_gap"
                    exit_occurred = True
                elif day_l <= pos.current_stop:
                    exit_px = pos.current_stop * (1.0 - SLIPPAGE)
                    exit_shares = pos.shares
                    exit_reason = "stop_loss"
                    exit_occurred = True
                elif not pos.t1_harvested and day_h >= pos.entry_price * 1.05:
                    # Harvest 50% at +5%, move stop to breakeven +0.6%
                    t1_shares = pos.shares // 2
                    if t1_shares > 0:
                        t1_px = pos.entry_price * 1.05 * (1.0 - SLIPPAGE)
                        # Deduct friction on T1 sale
                        sell_val = t1_shares * t1_px
                        stt = sell_val * 0.001
                        other_tax = sell_val * 0.000042
                        dp = 15.93
                        friction = stt + other_tax + dp + (sell_val * SLIPPAGE)
                        total_friction_inr += friction
                        cash += (sell_val - friction)
                        
                        pos.shares -= t1_shares
                        pos.t1_harvested = True
                        pos.current_stop = max(pos.current_stop, pos.entry_price * 1.006)
                
                # Check +12% target ceiling on runner
                if not exit_occurred and day_h >= pos.entry_price * 1.12:
                    exit_px = pos.entry_price * 1.12 * (1.0 - SLIPPAGE)
                    exit_shares = pos.shares
                    exit_reason = "target_12pct"
                    exit_occurred = True

                # Time stop: 10 sessions max
                if not exit_occurred and pos.days_held >= 10:
                    exit_px = day_c * (1.0 - SLIPPAGE)
                    exit_shares = pos.shares
                    exit_reason = "time_max_10d"
                    exit_occurred = True

            elif system_type == "data_backed":
                # Data-Backed Rule: 2x ATR / 8% Stop, 50-EMA Trail, Stagnation recycle
                # 1. Stop hit?
                if day_o <= pos.current_stop:
                    exit_px = day_o * (1.0 - SLIPPAGE)
                    exit_shares = pos.shares
                    exit_reason = "stop_gap"
                    exit_occurred = True
                elif day_l <= pos.current_stop:
                    exit_px = pos.current_stop * (1.0 - SLIPPAGE)
                    exit_shares = pos.shares
                    exit_reason = "stop_loss"
                    exit_occurred = True
                # 2. Trailing 50-day EMA (evaluated on Close starting Day 2)
                elif pos.days_held >= 2 and day_c < day_ema50:
                    exit_px = day_c * (1.0 - SLIPPAGE)
                    exit_shares = pos.shares
                    exit_reason = "trail_50ema"
                    exit_occurred = True
                # 3. Velocity stagnation kill: Day 10 and PnL < 1.5% and below entry
                elif pos.days_held >= 10 and (day_c / pos.entry_price - 1.0) < 0.0:
                    exit_px = day_c * (1.0 - SLIPPAGE)
                    exit_shares = pos.shares
                    exit_reason = "velocity_recycle"
                    exit_occurred = True
                # 4. Max holding window: 60 days
                elif pos.days_held >= 60:
                    exit_px = day_c * (1.0 - SLIPPAGE)
                    exit_shares = pos.shares
                    exit_reason = "max_60d"
                    exit_occurred = True

            if exit_occurred:
                sell_val = exit_shares * exit_px
                # Exact Indian friction: STT 0.1%, Exch/SEBI/GST 0.0042%, CDSL DP ₹15.93, slippage
                stt = sell_val * 0.001
                other_tax = sell_val * 0.000042
                dp = 15.93
                friction = stt + other_tax + dp + (sell_val * SLIPPAGE)
                total_friction_inr += friction
                cash += (sell_val - friction)

                net_pnl = (sell_val - friction) - (exit_shares * pos.entry_price)
                net_pnl_pct = (net_pnl / (exit_shares * pos.entry_price)) * 100.0

                closed_trades.append({
                    "symbol": sym,
                    "entry_date": pos.entry_date,
                    "exit_date": today,
                    "is_oos": pos.entry_date >= SPLIT_DATE,
                    "holding_days": pos.days_held,
                    "entry_price": pos.entry_price,
                    "exit_price": exit_px,
                    "shares": exit_shares,
                    "net_pnl_inr": net_pnl,
                    "net_pnl_pct": net_pnl_pct,
                    "exit_reason": exit_reason,
                })
            else:
                open_positions.append(pos)

        positions = open_positions

        # -----------------------------------------------------------------
        # STEP 2: SCREEN NEW CANDIDATES AT 15:30 TODAY FOR ENTRY TOMORROW
        # -----------------------------------------------------------------
        breadth = market_breadth.get(today, 50.0)
        open_slots = MAX_SLOTS - len(positions)

        # In Data-Backed System: Regime Gatekeeper (Breadth >= 50%)
        can_deploy = True
        if system_type == "data_backed" and breadth < 50.0:
            can_deploy = False

        if open_slots > 0 and can_deploy and cash >= 10000.0:
            candidates = []
            for sym, ind in indicators.items():
                if today not in ind["dates"]:
                    continue
                # Skip if already holding
                if any(p.symbol == sym for p in positions):
                    continue

                d0_c = ind["c"].loc[today]
                d0_h = ind["h"].loc[today]
                d0_ema50 = ind["ema50"].loc[today]
                d0_ema200 = ind["ema200"].loc[today]
                d0_rvol = ind["rvol"].loc[today]
                d0_high20 = ind["high20"].loc[today]
                d0_high50 = ind["high50"].loc[today]
                d0_atr = ind["atr14"].loc[today]
                d0_spread = ind["spread20"].loc[today]

                # Basic Stage 2 check
                if not (d0_c > d0_ema50 and d0_ema50 > d0_ema200):
                    continue

                if system_type == "legacy":
                    # Legacy: 20-day high breakout + RVOL >= 1.5
                    if d0_c > d0_high20 and d0_rvol >= 1.5:
                        candidates.append((sym, d0_rvol, d0_atr, d0_c))
                elif system_type == "data_backed":
                    # Data-Backed:
                    # 1. 50-day high breakout
                    # 2. RVOL >= 1.5
                    # 3. Consolidation spread > 12% (High-Beta explosive potential)
                    # 4. Anti-Exhaustion RS: 1M RS > 0 and NOT (6M > 25% and 1M < 0)
                    r1 = df_r1m.loc[today, sym] - n_r1m.loc[today] if (today in df_r1m.index and sym in df_r1m.columns) else 0.0
                    r3 = df_r3m.loc[today, sym] - n_r3m.loc[today] if (today in df_r3m.index and sym in df_r3m.columns) else 0.0
                    r6 = df_r6m.loc[today, sym] - n_r6m.loc[today] if (today in df_r6m.index and sym in df_r6m.columns) else 0.0

                    if np.isnan(r1): r1 = 0.0
                    if np.isnan(r6): r6 = 0.0

                    # Anti-Exhaustion gate
                    if r1 <= 0.0 or (r6 > 0.25 and r1 < 0.0):
                        continue

                    if d0_c > d0_high50 and d0_rvol >= 1.5 and d0_spread >= 12.0:
                        score = r1 * 100.0 + d0_rvol * 10.0
                        candidates.append((sym, score, d0_atr, d0_c))

            # Sort candidates by conviction
            candidates.sort(key=lambda x: x[1], reverse=True)
            picks = candidates[:open_slots]

            # Execute entries on next_day Open
            for sym, score, atr, d0_c in picks:
                ind = indicators[sym]
                if next_day not in ind["dates"]:
                    continue
                d1_o = ind["o"].loc[next_day]
                gap_pct = (d1_o / d0_c) - 1.0
                if gap_pct > 0.025:  # Anti-FOMO abort
                    continue

                entry_px = d1_o * (1.0 + SLIPPAGE)

                # Determine Position Size & Stop Loss
                if system_type == "legacy":
                    alloc = min(cash, 20000.0)
                    stop_px = entry_px * 0.96  # -4.0%
                elif system_type == "data_backed":
                    # Volatility Risk Parity: Risk ₹1,000 on 2.0x ATR stop
                    atr_pct = max(0.02, atr / entry_px)
                    stop_dist_pct = max(0.04, min(0.08, 2.0 * atr_pct))  # Cap stop at -8%
                    target_alloc = 1000.0 / stop_dist_pct
                    alloc = max(10000.0, min(25000.0, min(cash, target_alloc)))
                    stop_px = entry_px * (1.0 - stop_dist_pct)

                shares = int(alloc // entry_px)
                if shares <= 0:
                    continue

                actual_cost = shares * entry_px
                # Buy friction: STT 0.1%, Stamp duty 0.015%, Exch/SEBI/GST 0.0042%, slippage
                buy_tax = actual_cost * (0.001 + 0.00015 + 0.000042)
                friction = buy_tax + (actual_cost * SLIPPAGE)
                total_cost = actual_cost + friction

                if cash >= total_cost:
                    cash -= total_cost
                    total_friction_inr += friction
                    new_pos = Position(
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

        # -----------------------------------------------------------------
        # STEP 3: MARK TO MARKET PORTFOLIO EQUITY
        # -----------------------------------------------------------------
        portfolio_val = cash
        for pos in positions:
            sym = pos.symbol
            if today in indicators[sym]["dates"]:
                px = indicators[sym]["c"].loc[today]
            else:
                px = pos.entry_price
            portfolio_val += pos.shares * px

        daily_equity_curve.append({
            "date": today,
            "equity": portfolio_val,
            "cash": cash,
            "open_positions": len(positions),
        })

    # Liquidate remaining open positions at end
    final_day = active_dates[-1]
    for pos in positions:
        sym = pos.symbol
        if final_day in indicators[sym]["dates"]:
            exit_px = indicators[sym]["c"].loc[final_day] * (1.0 - SLIPPAGE)
        else:
            exit_px = pos.entry_price
        sell_val = pos.shares * exit_px
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
            "exit_price": exit_px,
            "shares": pos.shares,
            "net_pnl_inr": net_pnl,
            "net_pnl_pct": (net_pnl / (pos.shares * pos.entry_price)) * 100.0,
            "exit_reason": "end_of_sim",
        })

    df_eq = pd.DataFrame(daily_equity_curve).set_index("date")
    df_trades = pd.DataFrame(closed_trades)

    return {
        "final_cash": cash,
        "equity_curve": df_eq,
        "trades": df_trades,
        "total_friction_inr": total_friction_inr,
    }


def main():
    t0 = time.time()
    indicators, nifty, market_breadth, df_r1m, df_r3m, df_r6m, n_r1m, n_r3m, n_r6m = load_universe_and_breadth()

    print("\n" + "="*85)
    print("🚀 RUNNING HEAD-TO-HEAD 5-YEAR PORTFOLIO SIMULATIONS (2021–2026)")
    print("="*85, flush=True)

    print("\n1. Simulating System A: Legacy Algos (-4% Stop, +5% Breakeven Lock, +12% Target)...", flush=True)
    res_legacy = run_portfolio_simulation(
        "legacy", indicators, nifty, market_breadth,
        df_r1m, df_r3m, df_r6m, n_r1m, n_r3m, n_r6m
    )

    print("2. Simulating System B: Data-Backed Model (Breadth Gate + Anti-Exhaustion + 8% Stop + 50-EMA Trail)...", flush=True)
    res_databacked = run_portfolio_simulation(
        "data_backed", indicators, nifty, market_breadth,
        df_r1m, df_r3m, df_r6m, n_r1m, n_r3m, n_r6m
    )

    # Benchmark: Nifty 50 Buy-and-Hold
    start_date = res_legacy["equity_curve"].index[0]
    end_date = res_legacy["equity_curve"].index[-1]
    nifty_start = nifty.loc[start_date, 'Close']
    nifty_end = nifty.loc[end_date, 'Close']
    nifty_ret_pct = (nifty_end / nifty_start - 1.0) * 100.0

    # Process Metrics
    def compute_summary(res, name):
        eq = res["equity_curve"]["equity"]
        start_val = STARTING_CASH
        end_val = res["final_cash"]
        tot_ret = (end_val / start_val - 1.0) * 100.0
        n_years = len(eq) / 252.0
        cagr = ((end_val / start_val) ** (1.0 / n_years) - 1.0) * 100.0

        # Max Drawdown
        running_max = eq.cummax()
        dd = (eq - running_max) / running_max
        max_dd = float(dd.min() * 100.0)

        # Trades stats
        tr = res["trades"]
        n_trades = len(tr)
        wins = tr[tr["net_pnl_inr"] > 0]
        losses = tr[tr["net_pnl_inr"] <= 0]
        win_rate = (len(wins) / n_trades * 100.0) if n_trades > 0 else 0.0
        gross_profit = wins["net_pnl_inr"].sum() if len(wins) else 0.0
        gross_loss = abs(losses["net_pnl_inr"].sum()) if len(losses) else 1e-9
        pf = gross_profit / gross_loss

        # In-Sample vs Out-of-Sample PnL
        is_tr = tr[~tr["is_oos"]]
        oos_tr = tr[tr["is_oos"]]

        is_pnl = is_tr["net_pnl_inr"].sum() if len(is_tr) else 0.0
        oos_pnl = oos_tr["net_pnl_inr"].sum() if len(oos_tr) else 0.0

        return {
            "name": name,
            "starting_cash": start_val,
            "final_cash": round(end_val, 2),
            "total_return_pct": round(tot_ret, 2),
            "cagr_pct": round(cagr, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "trades_count": n_trades,
            "win_rate_pct": round(win_rate, 1),
            "profit_factor": round(pf, 2),
            "in_sample_pnl": round(is_pnl, 2),
            "out_of_sample_pnl": round(oos_pnl, 2),
            "total_friction_inr": round(res["total_friction_inr"], 2),
        }

    sum_legacy = compute_summary(res_legacy, "System A: Legacy Algos (-4% Stop, +5% BE Lock, +12% Cap)")
    sum_databacked = compute_summary(res_databacked, "System B: Data-Backed Model (Breadth + Anti-Exhaust + 8% Stop + 50-EMA Trail)")

    print("\n" + "="*85)
    print("🏆 FINAL PORTFOLIO PERFORMANCE COMPARISON (₹100,000 STARTING CAPITAL)")
    print("="*85)
    print(f"Nifty 50 Buy-and-Hold Return : {nifty_ret_pct:+.2f}%")
    print("-" * 85)
    for s in [sum_legacy, sum_databacked]:
        print(f"\n📌 {s['name']}:")
        print(f"   • Ending Capital    : ₹{s['final_cash']:,.2f} ({s['total_return_pct']:+.2f}% Net Return)")
        print(f"   • 5-Year CAGR       : {s['cagr_pct']:+.2f}% per year")
        print(f"   • Max Drawdown      : {s['max_drawdown_pct']:.2f}%")
        print(f"   • Profit Factor     : {s['profit_factor']:.2f}")
        print(f"   • Win Rate          : {s['win_rate_pct']:.1f}% ({s['trades_count']} trades)")
        print(f"   • In-Sample P&L     : ₹{s['in_sample_pnl']:+,.2f} (2021-2024)")
        print(f"   • Out-of-Sample P&L : ₹{s['out_of_sample_pnl']:+,.2f} (2024-2026)")
        print(f"   • Friction Deducted : ₹{s['total_friction_inr']:,.2f} (STT + DP + GST + Slippage)")

    # Save detailed trade logs & equity curve
    res_databacked["equity_curve"].to_csv(os.path.join(ROOT, "data", "analytics", "databacked_portfolio_equity.csv"))
    res_databacked["trades"].to_csv(os.path.join(ROOT, "data", "analytics", "databacked_portfolio_trades.csv"), index=False)
    print("\n💾 Simulation logs saved to data/analytics/databacked_portfolio_*.csv", flush=True)


if __name__ == "__main__":
    main()
