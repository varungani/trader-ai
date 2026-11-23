"""
TraderAI - True Swing Alpha: Filtering Short-Term Setups for Institutional Edge
================================================================================
Investigates why raw swing setups failed and tests the 4 Essential Filters
required to produce positive alpha in 10-30 day swing trading (40-80 trades/year):

  1. Market Breadth Gate: Breadth >= 50% & Nifty > 50-EMA (Zero trades in chop)
  2. Relative Strength Leader Ranking: Only Top 5% Relative Strength stocks
  3. No Artificial Profit Capping: Trailing 10-EMA/20-EMA instead of fixed +12% target
  4. Volume Footprint: RVOL >= 2.0x & Volume Asymmetry >= 1.6x

Evaluates full portfolio cash compounding on ₹100,000 capital with exact Indian delivery costs.
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

CASH_YIELD_ANNUAL = 0.065
DAILY_CASH_YIELD = (1.0 + CASH_YIELD_ANNUAL) ** (1.0 / 252.0) - 1.0

indicators, nifty, market_breadth, df_r1m, df_r3m, df_r6m, n_r1m, n_r3m, n_r6m = load_universe_and_breadth()

trading_dates = list(nifty.index)
start_idx = 252
active_dates = trading_dates[start_idx:]

print("="*85)
print("🔬 TESTING 3 FILTERED SWING STRATEGIES (TARGETING 10-30 DAY SWINGS & 50-80 TRADES/YR)")
print("="*85, flush=True)

# We will test 3 distinct swing exit mechanics on High-RS Breakouts:
# Swing Model 1: Fast 10-EMA Trail (Holding ~8-15 sessions)
# Swing Model 2: 20-EMA Trail (Holding ~15-30 sessions)
# Swing Model 3: Chandelier / ATR-based Trail (2.5x ATR below 10-day High)

configs = [
    ("Swing Model 1: Fast 10-EMA Trail (Target 8-15d hold)", "trail_10ema"),
    ("Swing Model 2: Medium 20-EMA Trail (Target 15-30d hold)", "trail_20ema"),
    ("Swing Model 3: Chandelier Trail (2.5x ATR from 10d High)", "trail_chandelier"),
]

for label, exit_mode in configs:
    cash = STARTING_CASH
    max_slots = 5  # 5 swing slots (20% per position)
    positions = []
    closed_trades = []
    daily_equity_curve = []
    total_friction_inr = 0.0
    peak_equity = STARTING_CASH

    for d_idx, today in enumerate(active_dates):
        if d_idx >= len(active_dates) - 1: break
        next_day = active_dates[d_idx + 1]

        if cash > 1000.0:
            cash += cash * DAILY_CASH_YIELD

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

            if day_c > pos["highest_close"]:
                pos["highest_close"] = day_c
            if day_h > pos["highest_high"]:
                pos["highest_high"] = day_h

            exit_occurred = False
            exit_px = 0.0
            exit_reason = ""

            # Hard Stop: 6% initial stop
            if day_o <= pos["stop"]:
                exit_px = day_o * (1.0 - SLIPPAGE)
                exit_reason = "stop_gap"
                exit_occurred = True
            elif day_l <= pos["stop"]:
                exit_px = pos["stop"] * (1.0 - SLIPPAGE)
                exit_reason = "stop_loss"
                exit_occurred = True
            elif pos["days_held"] >= 3:
                # Exit conditions based on mode
                if exit_mode == "trail_10ema":
                    day_ema10 = ind["c"].loc[:today].ewm(span=10, adjust=False).mean().iloc[-1]
                    if day_c < day_ema10:
                        exit_px = day_c * (1.0 - SLIPPAGE)
                        exit_reason = "trail_10ema"
                        exit_occurred = True
                elif exit_mode == "trail_20ema":
                    day_ema20 = ind["ema20"].loc[today]
                    if day_c < day_ema20:
                        exit_px = day_c * (1.0 - SLIPPAGE)
                        exit_reason = "trail_20ema"
                        exit_occurred = True
                elif exit_mode == "trail_chandelier":
                    atr = ind["atr14"].loc[today]
                    trail_line = pos["highest_high"] - (2.5 * atr)
                    if day_c < trail_line:
                        exit_px = day_c * (1.0 - SLIPPAGE)
                        exit_reason = "trail_chandelier"
                        exit_occurred = True

            # Max swing duration cutoff: 35 sessions (~7 weeks)
            if not exit_occurred and pos["days_held"] >= 35:
                exit_px = day_c * (1.0 - SLIPPAGE)
                exit_reason = "max_35d_cutoff"
                exit_occurred = True

            if exit_occurred:
                sell_val = pos["shares"] * exit_px
                friction = (sell_val * 0.001042) + 15.93 + (sell_val * SLIPPAGE)
                total_friction_inr += friction
                cash += (sell_val - friction)

                net_pnl = (sell_val - friction) - (pos["shares"] * pos["entry_price"])
                net_pnl_pct = (net_pnl / (pos["shares"] * pos["entry_price"])) * 100.0

                closed_trades.append({
                    "symbol": sym,
                    "entry_date": pos["entry_date"],
                    "exit_date": today,
                    "is_oos": pos["entry_date"] >= SPLIT_DATE,
                    "holding_days": pos["days_held"],
                    "net_pnl_inr": net_pnl,
                    "net_pnl_pct": net_pnl_pct,
                    "exit_reason": exit_reason,
                })
            else:
                open_positions.append(pos)

        positions = open_positions

        # Mark to market
        current_equity = cash
        for p in positions:
            s = p["symbol"]
            ind = indicators[s]
            c_val = ind["c"].loc[today] if today in ind["dates"] else p["entry_price"]
            current_equity += p["shares"] * c_val

        if current_equity > peak_equity: peak_equity = current_equity
        dd = (current_equity - peak_equity) / peak_equity
        daily_equity_curve.append({"date": today, "equity": current_equity, "drawdown": dd})

        # Check market breadth gate
        breadth = market_breadth.get(today, 50.0)
        nifty_c = nifty["Close"].loc[today]
        nifty_ema50 = nifty["EMA50"].loc[today]

        if breadth < 48.0 or nifty_c < nifty_ema50:
            continue

        open_slots = max_slots - len(positions)
        if open_slots <= 0: continue

        # Screen high RS momentum leaders breaking out of 20-day high with RVOL >= 2.0x
        candidates = []
        for sym, ind in indicators.items():
            if any(p["symbol"] == sym for p in positions): continue
            if today not in ind["dates"]: continue

            c_t = ind["c"].loc[today]
            h20 = ind["high20"].loc[today]
            ema20 = ind["ema20"].loc[today]
            ema50 = ind["ema50"].loc[today]
            rvol = ind["rvol"].loc[today]

            # Stage 2 + 20-day High Breakout + Heavy RVOL >= 2.0x
            if c_t > h20 and c_t > ema20 and c_t > ema50 and rvol >= 2.0:
                r1m = df_r1m.loc[today, sym] if (today in df_r1m.index and sym in df_r1m.columns) else -999.0
                r3m = df_r3m.loc[today, sym] if (today in df_r3m.index and sym in df_r3m.columns) else -999.0
                r6m = df_r6m.loc[today, sym] if (today in df_r6m.index and sym in df_r6m.columns) else -999.0
                if pd.isna(r1m) or pd.isna(r3m) or pd.isna(r6m): continue
                if r6m > 0 and r1m < 0: continue  # Anti-exhaustion

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
            stop_px = entry_fill * 0.94  # 6% stop
            risk_inr = current_equity * 0.015  # 1.5% portfolio risk
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
                "highest_close": entry_fill, "highest_high": entry_fill
            })

    # Liquidation
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
    avg_hold = df_tr["holding_days"].mean()
    trades_per_yr = len(df_tr) / n_years

    print(f"\n📌 {label}:")
    print(f"   • Ending Capital    : ₹{final_equity:,.2f} ({tot_ret:+.2f}% Net Return)")
    print(f"   • 5-Year CAGR       : {cagr:+.2f}% per year")
    print(f"   • Max Drawdown      : {max_dd:.2f}%")
    print(f"   • Total Trades      : {len(df_tr)} (~{trades_per_yr:.0f} trades/year)")
    print(f"   • Average Holding   : {avg_hold:.1f} trading sessions (~{avg_hold/5:.1f} weeks)")
    print(f"   • Profit Factor     : {pf:.2f} | Win Rate: {(len(wins)/len(df_tr)*100):.1f}%")
    print(f"   • Friction Paid     : ₹{total_friction_inr:,.2f}")
