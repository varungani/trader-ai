"""
TraderAI - Pushing Past 50%+ 5-Year CAGR
========================================
Tests:
  1. 3-Slot Pinnacle Ultimate:
     - Slot 1 (#1 RS rocket): 45% Capital Cap
     - Slot 2 (#2 RS rocket): 30% Capital Cap
     - Slot 3 (#3 RS rocket): 25% Capital Cap
  2. Base-on-Base Pyramiding (+35% size add-on on secondary breakout)
  3. Bull Supercharger (Breadth >= 65% risks 3.25%)
"""
import os
import sys
import pandas as pd
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from analysis.hyper_cagr_pinnacle import run_pinnacle_simulation, STARTING_CASH

print("="*80)
print("🚀 TESTING 3-SLOT CONVICTION + PYRAMIDING TO CROSS 50%+ CAGR")
print("="*80)

# Let's run variations with 3 slots and 4 slots with higher risk / concentration:
for label, slots, risk, bull_mult in [
    ("Setup A: 4 Slots, Base Risk 2.65%, Bull Supercharge 1.35x", 4, 0.0265, True),
    ("Setup B: 4 Slots, Base Risk 2.85%, Bull Supercharge 1.35x", 4, 0.0285, True),
    ("Setup C: 3 Slots, Base Risk 2.85%, Bull Supercharge 1.35x", 3, 0.0285, True),
    ("Setup D: 3 Slots, Base Risk 3.00%, Bull Supercharge 1.40x", 3, 0.0300, True),
    ("Setup E: 3 Slots, Base Risk 3.25%, Bull Supercharge 1.40x", 3, 0.0325, True),
]:
    from analysis.hyper_cagr_pinnacle import PinnaclePosition, weekly_emas, vol_asym_dict, indicators, nifty, market_breadth, df_r1m, df_r3m, df_r6m, active_dates, DAILY_YIELD, SLIPPAGE, SPLIT_DATE
    
    cash = STARTING_CASH
    max_slots = slots
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

            # Pyramiding
            if not pos.pyramided and pos.days_held >= 20 and gain_pct >= 0.20:
                h20 = ind["high20"].loc[today]
                rvol = ind["rvol"].loc[today]
                if day_c > h20 and rvol >= 1.5:
                    add_shares = int(pos.shares * 0.35)
                    if add_shares > 0:
                        add_cost = add_shares * day_c * (1.0 + SLIPPAGE)
                        add_fric = (add_cost * 0.001192) + (add_cost * SLIPPAGE)
                        if cash >= add_cost + add_fric:
                            cash -= (add_cost + add_fric)
                            total_friction_inr += add_fric
                            total_shares = pos.shares + add_shares
                            pos.entry_price = ((pos.shares * pos.entry_price) + add_cost) / total_shares
                            pos.shares = total_shares
                            pos.current_stop = max(pos.current_stop, pos.entry_price * 0.98)
                            pos.pyramided = True

            exit_occurred = False
            exit_px = 0.0

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
                closed_trades.append({
                    "symbol": sym, "days_held": pos.days_held,
                    "net_pnl_inr": net_pnl, "net_pnl_pct": (net_pnl / (pos.shares * pos.entry_price)) * 100.0,
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
        daily_equity_curve.append({"date": today, "equity": current_equity})

        breadth_val = market_breadth.get(today, 50.0)
        nifty_c = nifty["Close"].loc[today]
        nifty_ema50 = nifty["EMA50"].loc[today]

        if breadth_val < 45.0 or nifty_c < nifty_ema50:
            continue

        open_slots = max_slots - len(positions)
        if open_slots <= 0: continue

        if breadth_val >= 65.0:
            slot_risk = risk * 1.35
        elif breadth_val >= 55.0:
            slot_risk = risk
        else:
            slot_risk = risk * 0.50

        if portfolio_dd < -0.08:
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
            if (next_o / day0_c - 1.0) > 0.025: continue

            entry_fill = next_o * (1.0 + SLIPPAGE)
            stop_distance = max(entry_fill * 0.07, 2.0 * atr_val)
            initial_stop_px = entry_fill - stop_distance

            target_risk_inr = current_equity * slot_risk
            risk_per_share = entry_fill - initial_stop_px
            if risk_per_share <= 0: continue

            # Conviction cap: Top rank gets up to 40% cap, others 30%
            max_cap = current_equity * (0.40 if rank_idx == 0 else 0.30)
            shares = min(int(target_risk_inr / risk_per_share), int(max_cap / entry_fill))
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

            positions.append(PinnaclePosition(
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

    n_years = len(df_eq) / 252.0
    tot_ret = (final_equity / STARTING_CASH - 1.0) * 100.0
    cagr = ((final_equity / STARTING_CASH) ** (1.0 / n_years) - 1.0) * 100.0
    running_max = df_eq["equity"].cummax()
    max_dd = float(((df_eq["equity"] - running_max) / running_max).min() * 100.0)
    wins = df_trades[df_trades["net_pnl_inr"] > 0]["net_pnl_inr"]
    losses = df_trades[df_trades["net_pnl_inr"] <= 0]["net_pnl_inr"]
    pf = wins.sum() / (abs(losses.sum()) + 1e-9)

    print(f"\n📌 {label}:")
    print(f"   • Ending Capital : ₹{final_equity:,.2f} ({tot_ret:+.2f}% Net Return)")
    print(f"   • 5-Year CAGR    : {cagr:+.2f}% per year")
    print(f"   • Max Drawdown   : {max_dd:.2f}%")
    print(f"   • Profit Factor  : {pf:.2f} | Win Rate: {(len(wins)/len(df_trades)*100):.1f}% ({len(df_trades)} trades)")
    print(f"   • Friction Paid  : ₹{total_friction_inr:,.2f}")
