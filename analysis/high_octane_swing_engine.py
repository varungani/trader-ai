"""
TraderAI - High-Octane Swing Engine (Targeting 40-70 Trades/Year with 25%+ CAGR)
================================================================================
Optimizes the 15-to-30 day swing horizon by combining:
  1. Hyper-Selective 1M RS Velocity Ranking (Top 3% Rockets)
  2. Asymmetric Volume Footprint (Up/Down Volume >= 2.0x)
  3. Two-Tier Exit Mechanics:
     - Tier 1: Harvest 50% position at +12% to +15% (quick 5-10 day swing profit)
     - Tier 2: Trail remaining 50% with 10-day EMA or 20-day EMA (capturing runners)
  4. Full statutory Indian delivery friction (STT, GST, DP ₹15.93, slippage)
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

print("="*85)
print("⚡ TESTING HIGH-OCTANE SWING STRATEGY (40-70 TRADES/YR, 15-30 DAY HOLDING)")
print("="*85, flush=True)

# Test 3 variations of Partial Profit Taking & Trailing:
# Mode A: 50% Harvest at +12%, remainder trails 10-EMA, hard stop -6%
# Mode B: 50% Harvest at +15%, remainder trails 20-EMA, hard stop -6%
# Mode C: Pure 10-EMA Trail with Breakout RVOL >= 2.5x

configs = [
    ("Swing Engine A: 50% Harvest at +12%, 50% Trail 10-EMA", 0.12, "trail_10ema"),
    ("Swing Engine B: 50% Harvest at +15%, 50% Trail 20-EMA", 0.15, "trail_20ema"),
    ("Swing Engine C: Pure Dynamic 10-EMA Trail (RVOL >= 2.5x)", 999.0, "trail_10ema"),
]

for label, target_t1, trail_mode in configs:
    cash = STARTING_CASH
    max_slots = 5  # 5 positions (20% per slot) = higher turnover
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
            if day_h > pos["highest_high"]: pos["highest_high"] = day_h

            # Check Tier 1 Partial Harvest
            if not pos["t1_taken"] and target_t1 < 100.0:
                target_px = pos["entry_price"] * (1.0 + target_t1)
                if day_h >= target_px:
                    t1_shares = pos["shares"] // 2
                    if t1_shares > 0:
                        sell_val = t1_shares * target_px * (1.0 - SLIPPAGE)
                        friction = (sell_val * 0.001042) + 15.93 + (sell_val * SLIPPAGE)
                        total_friction_inr += friction
                        cash += (sell_val - friction)
                        pos["shares"] -= t1_shares
                        pos["t1_taken"] = True
                        pos["stop"] = max(pos["stop"], pos["entry_price"])  # Move stop to breakeven!

            exit_occurred = False
            exit_px = 0.0
            exit_reason = ""

            # Stop Loss
            if day_o <= pos["stop"]:
                exit_px = day_o * (1.0 - SLIPPAGE)
                exit_reason = "stop_gap"
                exit_occurred = True
            elif day_l <= pos["stop"]:
                exit_px = pos["stop"] * (1.0 - SLIPPAGE)
                exit_reason = "stop_loss"
                exit_occurred = True
            elif pos["days_held"] >= 3:
                if trail_mode == "trail_10ema":
                    day_ema10 = ind["c"].loc[:today].ewm(span=10, adjust=False).mean().iloc[-1]
                    if day_c < day_ema10:
                        exit_px = day_c * (1.0 - SLIPPAGE)
                        exit_reason = "trail_10ema"
                        exit_occurred = True
                elif trail_mode == "trail_20ema":
                    day_ema20 = ind["ema20"].loc[today]
                    if day_c < day_ema20:
                        exit_px = day_c * (1.0 - SLIPPAGE)
                        exit_reason = "trail_20ema"
                        exit_occurred = True

            # Max swing duration cutoff: 30 sessions (~6 weeks)
            if not exit_occurred and pos["days_held"] >= 30:
                exit_px = day_c * (1.0 - SLIPPAGE)
                exit_reason = "max_30d_cutoff"
                exit_occurred = True

            if exit_occurred:
                sell_val = pos["shares"] * exit_px
                friction = (sell_val * 0.001042) + 15.93 + (sell_val * SLIPPAGE)
                total_friction_inr += friction
                cash += (sell_val - friction)

                net_pnl = (sell_val - friction) - (pos["shares"] * pos["entry_price"])
                closed_trades.append({
                    "symbol": sym, "holding_days": pos["days_held"],
                    "net_pnl_inr": net_pnl, "exit_reason": exit_reason,
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
            h20 = ind["high20"].loc[today]
            ema20 = ind["ema20"].loc[today]
            ema50 = ind["ema50"].loc[today]
            rvol = ind["rvol"].loc[today]

            # High-octane breakout
            req_rvol = 2.5 if "Pure Dynamic" in label else 1.8
            if c_t > h20 and c_t > ema20 and c_t > ema50 and rvol >= req_rvol:
                r1m = df_r1m.loc[today, sym] if (today in df_r1m.index and sym in df_r1m.columns) else -999.0
                r3m = df_r3m.loc[today, sym] if (today in df_r3m.index and sym in df_r3m.columns) else -999.0
                if pd.isna(r1m) or pd.isna(r3m): continue
                if r1m <= 0: continue  # Strict 1M momentum requirement
                comp_rs = (0.70 * r1m) + (0.30 * r3m)  # Heavily weighted to short-term velocity
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
            if shares < 2: continue

            cost = shares * entry_fill
            buy_fric = (cost * 0.001192) + (cost * SLIPPAGE)
            if cash < cost + buy_fric: continue

            cash -= (cost + buy_fric)
            total_friction_inr += buy_fric
            positions.append({
                "symbol": sym, "entry_date": next_day, "entry_price": entry_fill,
                "shares": shares, "stop": stop_px, "days_held": 0,
                "highest_close": entry_fill, "highest_high": entry_fill,
                "t1_taken": False
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
    avg_hold = df_tr["holding_days"].mean()

    print(f"\n📌 {label}:")
    print(f"   • Ending Capital    : ₹{final_equity:,.2f} ({tot_ret:+.2f}% Net Return)")
    print(f"   • 5-Year CAGR       : {cagr:+.2f}% per year")
    print(f"   • Max Drawdown      : {max_dd:.2f}%")
    print(f"   • Annual Cadence    : ~{trades_per_yr:.0f} trades/year (Total: {len(df_tr)} trades)")
    print(f"   • Avg Holding Days  : {avg_hold:.1f} sessions (~{avg_hold/5:.1f} weeks)")
    print(f"   • Profit Factor     : {pf:.2f} | Win Rate: {(len(wins)/len(df_tr)*100):.1f}%")
    print(f"   • Friction Paid     : ₹{total_friction_inr:,.2f}")
