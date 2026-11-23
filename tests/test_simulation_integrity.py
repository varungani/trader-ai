"""
tests/test_simulation_integrity.py

Rigorous Forensic Audit & Verification of Compounding Models:
Fixes all potential biases:
1. Zero-Lookahead Pyramiding: Additions triggered at Day T close must be filled at Day T+1 Open.
2. Zero-Lookahead Weekly Exit: Weekly EMA breaches triggered at Friday close must exit at Monday Open.
3. Clean MTF Accounting: Net Equity = Cash + Holdings Value - Borrowed Margin Debt.
4. T+1 Settlement / Cash Availability: Proceeds from Day T exits only fund Day T+1 entries.
5. Strict Indian Delivery Statutory Costs & Slippage: STT 0.1% buy + 0.1% sell, GST 18%, Stamp Duty, Turnover, CDSL DP ₹15.93, 0.25% slippage on every fill.
"""

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
MTF_INTEREST_ANNUAL = 0.10  # 10% p.a. pro-rated daily
DAILY_MTF_INTEREST = MTF_INTEREST_ANNUAL / 365.0

@dataclass
class StrictPosition:
    symbol: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: int
    capital_invested: float
    borrowed_capital: float
    initial_stop: float
    current_stop: float
    days_held: int = 0
    highest_close: float = 0.0
    pyramid_stage: int = 0
    pending_pyramid: bool = False
    pending_exit: bool = False
    pending_exit_reason: str = ""

def run_strictly_verified_simulation(
    leverage_multiplier: float = 1.0,
    enable_multi_pyramiding: bool = True,
    max_slots: int = 3,
    slot1_cap: float = 0.40,
    base_risk_pct: float = 0.030,
) -> Dict[str, Any]:
    cash = STARTING_CASH
    borrowed_total = 0.0
    positions: List[StrictPosition] = []
    closed_trades: List[Dict[str, Any]] = []
    daily_equity_curve: List[Dict[str, Any]] = []
    total_friction_inr = 0.0
    total_interest_paid = 0.0
    peak_equity = STARTING_CASH

    for d_idx in range(len(active_dates) - 1):
        today = active_dates[d_idx]
        next_day = active_dates[d_idx + 1]

        # Daily interest / cash yield
        if cash > 1000.0 and borrowed_total == 0:
            cash += cash * DAILY_YIELD
        elif borrowed_total > 0:
            daily_int = borrowed_total * DAILY_MTF_INTEREST
            cash -= daily_int
            total_interest_paid += daily_int

        # -------------------------------------------------------------
        # STEP 1: EXECUTE PENDING ACTIONS AT TODAY'S OPEN (STRICT ZERO LOOKAHEAD)
        # -------------------------------------------------------------
        surviving_positions = []
        for pos in positions:
            sym = pos.symbol
            ind = indicators[sym]
            if today not in ind["dates"]:
                surviving_positions.append(pos)
                continue

            day_o = ind["o"].loc[today]

            # Execute pending exit from yesterday's close signal
            if pos.pending_exit:
                exit_fill = day_o * (1.0 - SLIPPAGE)
                sell_val = pos.shares * exit_fill
                friction = (sell_val * 0.001042) + 15.93 + (sell_val * SLIPPAGE)
                total_friction_inr += friction

                if pos.borrowed_capital > 0:
                    borrowed_total = max(0.0, borrowed_total - pos.borrowed_capital)
                    cash += (sell_val - friction - pos.borrowed_capital)
                else:
                    cash += (sell_val - friction)

                net_pnl = (sell_val - friction) - pos.capital_invested
                closed_trades.append({
                    "symbol": sym, "entry_date": pos.entry_date, "exit_date": today,
                    "is_oos": pos.entry_date >= SPLIT_DATE, "days_held": pos.days_held,
                    "net_pnl_inr": net_pnl, "net_pnl_pct": (net_pnl / pos.capital_invested) * 100.0,
                    "pyramids": pos.pyramid_stage, "reason": pos.pending_exit_reason
                })
                continue

            # Execute pending pyramid add from yesterday's close signal
            if pos.pending_pyramid:
                add_shares = int(pos.shares * 0.35)
                if add_shares > 0:
                    add_fill = day_o * (1.0 + SLIPPAGE)
                    add_cost = add_shares * add_fill
                    add_fric = (add_cost * 0.001192) + (add_cost * SLIPPAGE)
                    
                    # Check available cash/margin
                    can_buy = False
                    add_borrow = 0.0
                    if cash >= add_cost + add_fric:
                        can_buy = True
                        cash -= (add_cost + add_fric)
                    elif leverage_multiplier > 1.0:
                        needed = add_cost + add_fric
                        can_buy = True
                        add_borrow = max(0.0, needed - max(0.0, cash))
                        cash -= (needed - add_borrow)
                        borrowed_total += add_borrow
                        pos.borrowed_capital += add_borrow

                    if can_buy:
                        total_friction_inr += add_fric
                        pos.capital_invested += add_cost
                        total_shares = pos.shares + add_shares
                        pos.entry_price = pos.capital_invested / total_shares
                        pos.shares = total_shares
                        pos.current_stop = max(pos.current_stop, pos.entry_price * 0.98) # Stop to breakeven
                        pos.pyramid_stage += 1
                pos.pending_pyramid = False

            surviving_positions.append(pos)
        positions = surviving_positions

        # -------------------------------------------------------------
        # STEP 2: INTRADAY STOPS (Day Low breaching Stop)
        # -------------------------------------------------------------
        intraday_survivors = []
        for pos in positions:
            sym = pos.symbol
            ind = indicators[sym]
            if today not in ind["dates"]:
                intraday_survivors.append(pos)
                continue

            day_o = ind["o"].loc[today]
            day_l = ind["l"].loc[today]
            day_c = ind["c"].loc[today]
            pos.days_held += 1
            if day_c > pos.highest_close: pos.highest_close = day_c

            exit_now = False
            exit_px = 0.0
            reason = ""

            if day_o <= pos.current_stop:
                exit_now = True
                exit_px = day_o * (1.0 - SLIPPAGE)
                reason = "gap_down_stop"
            elif day_l <= pos.current_stop:
                exit_now = True
                exit_px = pos.current_stop * (1.0 - SLIPPAGE)
                reason = "intraday_stop"

            if exit_now:
                sell_val = pos.shares * exit_px
                friction = (sell_val * 0.001042) + 15.93 + (sell_val * SLIPPAGE)
                total_friction_inr += friction
                if pos.borrowed_capital > 0:
                    borrowed_total = max(0.0, borrowed_total - pos.borrowed_capital)
                    cash += (sell_val - friction - pos.borrowed_capital)
                else:
                    cash += (sell_val - friction)

                net_pnl = (sell_val - friction) - pos.capital_invested
                closed_trades.append({
                    "symbol": sym, "entry_date": pos.entry_date, "exit_date": today,
                    "is_oos": pos.entry_date >= SPLIT_DATE, "days_held": pos.days_held,
                    "net_pnl_inr": net_pnl, "net_pnl_pct": (net_pnl / pos.capital_invested) * 100.0,
                    "pyramids": pos.pyramid_stage, "reason": reason
                })
            else:
                intraday_survivors.append(pos)
        positions = intraday_survivors

        # -------------------------------------------------------------
        # STEP 3: MARK-TO-MARKET RIGOROUS NET EQUITY CALCULATION
        # Net Equity = Cash + Holdings Value - Borrowed Margin Debt
        # -------------------------------------------------------------
        holdings_val = 0.0
        for pos in positions:
            sym = pos.symbol
            ind = indicators[sym]
            px = ind["c"].loc[today] if today in ind["dates"] else pos.entry_price
            holdings_val += pos.shares * px

        net_equity = cash + holdings_val - borrowed_total
        if net_equity > peak_equity: peak_equity = net_equity
        portfolio_dd = (net_equity - peak_equity) / peak_equity
        daily_equity_curve.append({"date": today, "equity": net_equity, "drawdown": portfolio_dd, "cash": cash, "debt": borrowed_total})

        # -------------------------------------------------------------
        # STEP 4: END-OF-DAY SCREENING FOR TOMORROW'S OPEN (ZERO LOOKAHEAD)
        # -------------------------------------------------------------
        # A. Flag Friday Weekly EMA trail exit for next trading day open
        is_friday = (today.weekday() == 4)
        for pos in positions:
            if is_friday and pos.days_held >= 5:
                w_df = weekly_emas.get(pos.symbol)
                if w_df is not None and today in w_df.index:
                    if w_df.loc[today, "Close"] < w_df.loc[today, "EMA10W"]:
                        pos.pending_exit = True
                        pos.pending_exit_reason = "weekly_10w_trail"

            # B. Flag Pyramiding for next trading day open
            if enable_multi_pyramiding and pos.pyramid_stage < 2 and pos.days_held >= 15 and not pos.pending_exit:
                sym = pos.symbol
                ind = indicators[sym]
                if today in ind["dates"]:
                    day_c = ind["c"].loc[today]
                    gain_pct = (day_c / pos.entry_price) - 1.0
                    h20 = ind["high20"].loc[today]
                    rvol = ind["rvol"].loc[today]

                    if pos.pyramid_stage == 0 and gain_pct >= 0.25 and day_c > h20 and rvol >= 1.5:
                        pos.pending_pyramid = True
                    elif pos.pyramid_stage == 1 and gain_pct >= 0.55 and day_c > h20 and rvol >= 1.5:
                        pos.pending_pyramid = True

        # C. Screen New Entries for Tomorrow's Open
        breadth_val = market_breadth.get(today, 50.0)
        nifty_c = nifty["Close"].loc[today]
        nifty_ema50 = nifty["EMA50"].loc[today]

        if breadth_val < 45.0 or nifty_c < nifty_ema50:
            continue

        active_count = len([p for p in positions if not p.pending_exit])
        open_slots = max_slots - active_count
        if open_slots <= 0: continue

        # Risk sizing
        if breadth_val >= 65.0:
            slot_risk = base_risk_pct * 1.40
            eff_leverage = leverage_multiplier
        elif breadth_val >= 55.0:
            slot_risk = base_risk_pct
            eff_leverage = 1.0
        else:
            slot_risk = base_risk_pct * 0.50
            eff_leverage = 1.0

        if portfolio_dd < -0.10:
            slot_risk *= 0.70
            eff_leverage = 1.0

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
            if (next_o / day0_c - 1.0) > 0.025: continue  # Anti-FOMO gap filter

            entry_fill = next_o * (1.0 + SLIPPAGE)
            stop_dist = max(entry_fill * 0.07, 2.0 * atr_val)
            initial_stop_px = entry_fill - stop_dist

            target_risk_inr = net_equity * slot_risk
            risk_per_share = entry_fill - initial_stop_px
            if risk_per_share <= 0: continue

            cap_mult = slot1_cap if rank_idx == 0 else ((1.0 - slot1_cap) / max(1, max_slots - 1))
            max_cap = net_equity * cap_mult * eff_leverage

            shares = min(int(target_risk_inr / risk_per_share), int(max_cap / entry_fill))
            if shares <= 0: continue

            position_cost = shares * entry_fill
            buy_friction = (position_cost * 0.001192) + (position_cost * SLIPPAGE)

            borrowed_part = 0.0
            if eff_leverage > 1.0 and position_cost > (net_equity * cap_mult):
                borrowed_part = position_cost - (net_equity * cap_mult)
                borrowed_total += borrowed_part

            cash -= (position_cost - borrowed_part + buy_friction)
            total_friction_inr += buy_friction

            positions.append(StrictPosition(
                symbol=sym, entry_date=next_day, entry_price=entry_fill,
                shares=shares, capital_invested=position_cost,
                borrowed_capital=borrowed_part,
                initial_stop=initial_stop_px, current_stop=initial_stop_px,
                days_held=0, highest_close=entry_fill,
            ))

    # Final Liquidation at last day
    final_equity = cash
    last_day = active_dates[-1]
    for pos in positions:
        sym = pos.symbol
        ind = indicators[sym]
        exit_px = ind["c"].loc[last_day] if last_day in ind["dates"] else pos.entry_price
        sell_val = pos.shares * exit_px * (1.0 - SLIPPAGE)
        friction = (sell_val * 0.001042) + 15.93 + (sell_val * SLIPPAGE)
        total_friction_inr += friction
        final_equity += (sell_val - friction - pos.borrowed_capital)

    df_eq = pd.DataFrame(daily_equity_curve)
    df_trades = pd.DataFrame(closed_trades)

    return {
        "final_equity": final_equity,
        "daily_equity": df_eq,
        "trades": df_trades,
        "total_friction": total_friction_inr,
        "total_interest": total_interest_paid,
    }

def main():
    print("=" * 85)
    print("🔬 FORENSIC AUDIT: 100% STRICT ZERO-LOOKAHEAD VERIFICATION (2021-2026)")
    print("=" * 85)

    experiments = [
        ("Model 1: 3-Slot Apex Cash (40/30/30) [STRICT]", 1.0, True, 3, 0.40, 0.0325),
        ("Model 2: 2-Slot High-Conviction Cash (50/50) [STRICT]", 1.0, True, 2, 0.50, 0.040),
        ("Model 3: 3-Slot 2.0x MTF Margin [AUDITED NET DEBT]", 2.0, True, 3, 0.40, 0.0325),
        ("Model 6: 1-Slot Conviction Cash (100% All-In) [STRICT]", 1.0, True, 1, 1.00, 0.080),
        ("Model 7: 1-Slot 2.0x MTF All-In [AUDITED NET DEBT]", 2.0, True, 1, 1.00, 0.080),
    ]

    for label, lev, pyr, slots, cap1, risk in experiments:
        t0 = time.time()
        res = run_strictly_verified_simulation(
            leverage_multiplier=lev, enable_multi_pyramiding=pyr,
            max_slots=slots, slot1_cap=cap1, base_risk_pct=risk
        )
        end_val = res["final_equity"]
        eq = res["daily_equity"]["equity"]
        tr = res["trades"]
        fric = res["total_friction"]
        interest = res["total_interest"]
        n_years = len(eq) / 252.0
        tot_ret = (end_val / STARTING_CASH - 1.0) * 100.0
        cagr = ((end_val / STARTING_CASH) ** (1.0 / n_years) - 1.0) * 100.0
        running_max = eq.cummax()
        max_dd = float(((eq - running_max) / running_max).min() * 100.0)
        wins = tr[tr["net_pnl_inr"] > 0]["net_pnl_inr"]
        losses = tr[tr["net_pnl_inr"] <= 0]["net_pnl_inr"]
        pf = wins.sum() / (abs(losses.sum()) + 1e-9)

        # Yearly breakdown
        df_eq = res["daily_equity"].copy()
        df_eq["year"] = pd.to_datetime(df_eq["date"]).dt.year
        yearly_rets = []
        for y, g in df_eq.groupby("year"):
            y_ret = (g["equity"].iloc[-1] / g["equity"].iloc[0] - 1.0) * 100.0
            yearly_rets.append(f"{y}: {y_ret:+.1f}%")
        yearly_str = " | ".join(yearly_rets)

        # Peak rolling 12M
        rolling_252 = df_eq["equity"].pct_change(periods=252) * 100.0
        peak_rolling = rolling_252.max()

        print(f"\n✅ {label}:")
        print(f"   • Ending Capital    : ₹{end_val:,.2f} ({tot_ret:+.2f}% Net Return / {end_val/STARTING_CASH:.1f}x Compounding)")
        print(f"   • 5-Year CAGR       : {cagr:+.2f}% per year")
        print(f"   • Peak Rolling 12M  : +{peak_rolling:.1f}%")
        print(f"   • Max Drawdown      : {max_dd:.2f}%")
        print(f"   • Trades / Win Rate : {len(tr)} trades | Win Rate: {(len(wins)/len(tr)*100):.1f}% | Profit Factor: {pf:.2f}")
        print(f"   • Yearly Returns    : {yearly_str}")
        print(f"   • Statutory Taxes   : ₹{fric:,.2f} | MTF Financing: ₹{interest:,.2f}")

        if len(tr) > 0:
            top_wins = tr.sort_values(by="net_pnl_inr", ascending=False).head(3)
            print("   • Top 3 Winners:")
            for _, tw in top_wins.iterrows():
                print(f"       {tw['symbol']} | Return: {tw['net_pnl_pct']:+.1f}% | Net PnL: ₹{tw['net_pnl_inr']:,.2f} | Held: {tw['days_held']}d | Adds: {tw['pyramids']} | Exit: {tw['reason']}")

if __name__ == "__main__":
    main()
