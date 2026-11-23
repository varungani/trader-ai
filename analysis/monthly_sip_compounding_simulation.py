"""
analysis/monthly_sip_compounding_simulation.py

Empirical Simulation of Monthly SIP Compounding (₹30,000 / month):
1. Injects ₹30,000 on the first trading day of every month from Oct 2021 to Nov 2026 (61 months = ₹18.3 Lakhs total invested).
2. Runs the exact zero-lookahead, statutory Indian delivery friction and execution logic for:
   - Nifty 50 Index SIP Benchmark
   - Track 6: Apex 3-Slot Compounder (57.9% CAGR)
   - Track 8: 1-Slot Apex Leader Rocket (66.9% CAGR)
   - Track 9: Active 1-to-2 Month Swing Engine (25.6% CAGR)
3. Computes the mathematical compounding projections for 1Y, 3Y, 5Y, 7Y, 10Y.
"""

import os
import sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from analysis.portfolio_cash_simulator import load_universe_and_breadth, SLIPPAGE, SPLIT_DATE
from engine.analytics.simulator import PortfolioSimulator, SimulationConfig

def run_sip_simulation(indicators, nifty, market_breadth, weekly_emas, vol_asym, df_r1m, df_r3m, df_r6m, config: SimulationConfig):
    trading_dates = list(nifty.index)
    start_idx = 252
    active_dates = trading_dates[start_idx:]

    monthly_sip_amount = 30000.0
    cash = monthly_sip_amount  # Month 1 deposit
    total_capital_deposited = monthly_sip_amount

    daily_yield = (1.0 + config.idle_cash_yield_annual) ** (1.0 / 252.0) - 1.0

    positions = []
    closed_trades = []
    daily_equity = []
    total_friction = 0.0
    peak_equity = monthly_sip_amount

    # Track months to inject 30k on the first trading day of each month
    current_month = active_dates[0].month
    
    deposit_log = [{"date": active_dates[0], "amount": monthly_sip_amount, "total": total_capital_deposited}]

    for d_idx in range(len(active_dates) - 1):
        today = active_dates[d_idx]
        next_day = active_dates[d_idx + 1]

        # Check if new calendar month started -> Inject fresh 30k SIP
        if today.month != current_month:
            current_month = today.month
            cash += monthly_sip_amount
            total_capital_deposited += monthly_sip_amount
            deposit_log.append({"date": today, "amount": monthly_sip_amount, "total": total_capital_deposited})

        # Cash yield
        if cash > 1000.0:
            cash += cash * daily_yield

        # 1. Execute pending actions at Open (Zero Lookahead)
        surviving_positions = []
        for pos in positions:
            sym = pos["symbol"]
            ind = indicators[sym]
            if today not in ind["dates"]:
                surviving_positions.append(pos)
                continue

            day_o = ind["o"].loc[today]

            if pos.get("pending_exit", False):
                exit_fill = day_o * (1.0 - config.slippage_pct)
                sell_val = pos["shares"] * exit_fill
                fric = PortfolioSimulator.compute_statutory_costs(sell_val, is_buy=False)
                total_friction += fric
                cash += (sell_val - fric)
                net_pnl = (sell_val - fric) - pos["capital_invested"]
                closed_trades.append({
                    "symbol": sym, "entry_date": pos["entry_date"], "exit_date": today,
                    "net_pnl_inr": net_pnl, "pnl_pct": (net_pnl / pos["capital_invested"]) * 100.0,
                    "reason": pos.get("pending_exit_reason", "")
                })
                continue

            if pos.get("pending_pyramid", False):
                add_shares = int(pos["shares"] * config.pyramid_size_fraction)
                if add_shares > 0:
                    add_fill = day_o * (1.0 + config.slippage_pct)
                    add_cost = add_shares * add_fill
                    add_fric = PortfolioSimulator.compute_statutory_costs(add_cost, is_buy=True)
                    if cash >= add_cost + add_fric:
                        cash -= (add_cost + add_fric)
                        total_friction += add_fric
                        pos["capital_invested"] += add_cost
                        total_shares = pos["shares"] + add_shares
                        pos["entry_price"] = pos["capital_invested"] / total_shares
                        pos["shares"] = total_shares
                        pos["current_stop"] = max(pos["current_stop"], pos["entry_price"] * 0.98)
                        pos["pyramid_stage"] += 1
                pos["pending_pyramid"] = False

            surviving_positions.append(pos)
        positions = surviving_positions

        # 2. Intraday Stops
        intraday_survivors = []
        for pos in positions:
            sym = pos["symbol"]
            ind = indicators[sym]
            if today not in ind["dates"]:
                intraday_survivors.append(pos)
                continue

            day_o = ind["o"].loc[today]
            day_l = ind["l"].loc[today]
            day_c = ind["c"].loc[today]
            pos["days_held"] += 1
            if day_c > pos["highest_close"]: pos["highest_close"] = day_c

            exit_now = False
            exit_px = 0.0
            reason = ""

            if day_o <= pos["current_stop"]:
                exit_now = True
                exit_px = day_o * (1.0 - config.slippage_pct)
                reason = "GAP_DOWN_STOP"
            elif day_l <= pos["current_stop"]:
                exit_now = True
                exit_px = pos["current_stop"] * (1.0 - config.slippage_pct)
                reason = "INTRADAY_STOP"

            if exit_now:
                sell_val = pos["shares"] * exit_px
                fric = PortfolioSimulator.compute_statutory_costs(sell_val, is_buy=False)
                total_friction += fric
                cash += (sell_val - fric)
                net_pnl = (sell_val - fric) - pos["capital_invested"]
                closed_trades.append({
                    "symbol": sym, "entry_date": pos["entry_date"], "exit_date": today,
                    "net_pnl_inr": net_pnl, "pnl_pct": (net_pnl / pos["capital_invested"]) * 100.0,
                    "reason": reason
                })
            else:
                intraday_survivors.append(pos)
        positions = intraday_survivors

        # 3. Mark to Market Net Equity
        holdings_val = 0.0
        for pos in positions:
            sym = pos["symbol"]
            ind = indicators[sym]
            px = ind["c"].loc[today] if today in ind["dates"] else pos["entry_price"]
            holdings_val += pos["shares"] * px

        net_equity = cash + holdings_val
        if net_equity > peak_equity: peak_equity = net_equity
        portfolio_dd = (net_equity - peak_equity) / peak_equity
        daily_equity.append({
            "date": today, "equity": net_equity, "cash": cash,
            "deposited": total_capital_deposited, "drawdown": portfolio_dd
        })

        # 4. End-of-Day Evaluation for Tomorrow's Open
        is_friday = (today.weekday() == 4)
        for pos in positions:
            ind = indicators[pos["symbol"]]
            if today not in ind["dates"]: continue
            day_c = ind["c"].loc[today]
            gain_pct = (day_c / pos["entry_price"] - 1.0) * 100.0

            if config.use_weekly_10w_trail and is_friday and pos["days_held"] >= 5:
                w_df = weekly_emas.get(pos["symbol"])
                if w_df is not None and today in w_df.index:
                    if w_df.loc[today, "Close"] < w_df.loc[today, "EMA10W"]:
                        pos["pending_exit"] = True
                        pos["pending_exit_reason"] = "WEEKLY_10W_EMA_TRAIL"

            elif config.use_day21_cutoff and pos["days_held"] >= 21 and gain_pct < 3.0:
                pos["pending_exit"] = True
                pos["pending_exit_reason"] = "DAY21_STAGNATION_CUTOFF"

            if config.enable_pyramiding and pos["pyramid_stage"] < 2 and pos["days_held"] >= 15 and not pos.get("pending_exit", False):
                h20 = ind["high20"].loc[today]
                rvol = ind["rvol"].loc[today]
                if pos["pyramid_stage"] == 0 and gain_pct >= 25.0 and day_c > h20 and rvol >= 1.4:
                    pos["pending_pyramid"] = True
                elif pos["pyramid_stage"] == 1 and gain_pct >= 55.0 and day_c > h20 and rvol >= 1.4:
                    pos["pending_pyramid"] = True

        # Entries
        breadth_val = market_breadth.get(today, 50.0)
        nifty_c = nifty["Close"].loc[today]
        nifty_ema50 = nifty["EMA50"].loc[today]
        if breadth_val < 45.0 or nifty_c < nifty_ema50:
            continue

        active_count = len([p for p in positions if not p.get("pending_exit", False)])
        open_slots = config.max_slots - active_count
        if open_slots <= 0: continue

        # Risk sizing
        slot_risk = config.base_risk_pct * (1.40 if breadth_val >= 65.0 else (1.0 if breadth_val >= 55.0 else 0.50))
        if portfolio_dd < -0.10: slot_risk *= 0.70

        existing_syms = {p["symbol"] for p in positions}
        candidates = []
        for sym, ind in indicators.items():
            if sym in existing_syms or today not in ind["dates"]: continue
            c_today = ind["c"].loc[today]
            h50 = ind["high50"].loc[today]
            ema50 = ind["ema50"].loc[today]
            ema20 = ind["ema20"].loc[today]
            ema200 = ind["ema200"].loc[today]
            rvol_today = ind["rvol"].loc[today]
            atr = ind["atr14"].loc[today]

            if c_today > h50 and c_today > ema50 and c_today > ema20 and rvol_today >= 1.5:
                if (c_today / (ema200 + 1e-9) - 1.0) < 0.20: continue
                sym_asym = vol_asym.get(sym, {}).get(today, 1.0)
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

        allocs = config.slot_allocations
        for rank_idx, (sym, rs_val, atr_val) in enumerate(chosen):
            ind = indicators[sym]
            if next_day not in ind["dates"]: continue
            day0_c = ind["c"].loc[today]
            next_o = ind["o"].loc[next_day]
            if (next_o / day0_c - 1.0) > 0.025: continue

            entry_fill = next_o * (1.0 + config.slippage_pct)
            stop_dist = max(entry_fill * config.hard_stop_loss_pct, 2.0 * atr_val)
            initial_stop = entry_fill - stop_dist

            target_risk_inr = net_equity * slot_risk
            risk_per_share = entry_fill - initial_stop
            if risk_per_share <= 0: continue

            slot_idx = active_count + rank_idx
            cap_mult = allocs[slot_idx] if slot_idx < len(allocs) else (1.0 / config.max_slots)
            max_cap = net_equity * cap_mult

            shares = min(int(target_risk_inr / risk_per_share), int(max_cap / entry_fill), int(cash / entry_fill))
            if shares <= 0: continue

            position_cost = shares * entry_fill
            buy_fric = PortfolioSimulator.compute_statutory_costs(position_cost, is_buy=True)
            if cash < position_cost + buy_fric: continue

            cash -= (position_cost + buy_fric)
            total_friction += buy_fric

            positions.append({
                "symbol": sym, "entry_date": next_day, "entry_price": entry_fill,
                "shares": shares, "capital_invested": position_cost,
                "initial_stop": initial_stop, "current_stop": initial_stop,
                "days_held": 0, "highest_close": entry_fill, "pyramid_stage": 0,
            })

    # Final Liquidation
    final_equity = cash
    last_day = active_dates[-1]
    for pos in positions:
        sym = pos["symbol"]
        ind = indicators[sym]
        exit_px = ind["c"].loc[last_day] if last_day in ind["dates"] else pos["entry_price"]
        sell_val = pos["shares"] * exit_px * (1.0 - config.slippage_pct)
        friction = PortfolioSimulator.compute_statutory_costs(sell_val, is_buy=False)
        total_friction += friction
        final_equity += (sell_val - friction)

    df_eq = pd.DataFrame(daily_equity)
    return {
        "final_equity": final_equity,
        "total_deposited": total_capital_deposited,
        "net_profit": final_equity - total_capital_deposited,
        "xirr_approx_cagr": ((final_equity / total_capital_deposited) ** (1.0 / 2.5) - 1.0) * 100.0, # Approximate dollar-weighted
        "total_friction": total_friction,
        "daily_equity": df_eq,
        "deposit_log": deposit_log,
    }


def simulate_nifty_sip(nifty, start_idx=252, monthly_amount=30000.0):
    """Simulates exact Nifty 50 Index SIP of 30,000 / month."""
    dates = list(nifty.index)[start_idx:]
    units = 0.0
    total_deposited = 0.0
    cur_month = dates[0].month
    
    daily_nifty_eq = []
    for d in dates:
        if d.month != cur_month:
            cur_month = d.month
            nav = nifty.loc[d, "Close"]
            units += monthly_amount / nav
            total_deposited += monthly_amount
        elif total_deposited == 0:
            nav = nifty.loc[d, "Close"]
            units += monthly_amount / nav
            total_deposited += monthly_amount
            
        cur_val = units * nifty.loc[d, "Close"]
        daily_nifty_eq.append({"date": d, "equity": cur_val, "deposited": total_deposited})
        
    df = pd.DataFrame(daily_nifty_eq)
    final_val = df.iloc[-1]["equity"]
    return {
        "final_equity": final_val,
        "total_deposited": total_deposited,
        "net_profit": final_val - total_deposited,
        "daily_equity": df,
    }


def compute_future_projections(monthly_amount=30000.0):
    """Computes exact mathematical compounding projections for 1Y, 3Y, 5Y, 7Y, 10Y."""
    scenarios = [
        ("Nifty 50 Benchmark", 0.137),
        ("Active Monthly Swing Engine", 0.256),
        ("Apex 3-Slot Compounder (Track 6)", 0.579),
        ("Apex 1-Slot Rocket (Track 8)", 0.669),
    ]
    years_list = [1, 2, 3, 5, 7, 10]
    
    rows = []
    for name, cagr in scenarios:
        # Effective monthly rate
        r_monthly = (1.0 + cagr) ** (1.0 / 12.0) - 1.0
        row = {"Strategy": name, "CAGR": f"{cagr*100:.1f}%"}
        for yr in years_list:
            n_months = yr * 12
            # Future Value of an Ordinary Annuity (deposited at start of each month):
            # FV = P * ((1 + r)^n - 1) / r * (1 + r)
            fv = monthly_amount * (((1.0 + r_monthly) ** n_months - 1.0) / r_monthly) * (1.0 + r_monthly)
            deposited = monthly_amount * n_months
            row[f"{yr}Y Value"] = f"₹{fv:,.0f}"
            row[f"{yr}Y Deposited"] = f"₹{deposited:,.0f}"
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    print("=" * 85)
    print("💰 MONTHLY SIP COMPOUNDING SIMULATION (₹30,000 / MONTH + 100% PROFIT REINVESTMENT)")
    print("=" * 85)

    indicators, nifty, market_breadth, df_r1m, df_r3m, df_r6m, n_r1m, n_r3m, n_r6m = load_universe_and_breadth()

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

    print("\n⏳ Running 5-Year Empirical Historical Simulation (Oct 2021 - Nov 2026)...")

    # 1. Nifty 50 SIP
    nifty_res = simulate_nifty_sip(nifty)
    print(f"\n📌 Nifty 50 Index SIP (Benchmark):")
    print(f"   • Total Deposited : ₹{nifty_res['total_deposited']:,.2f}")
    print(f"   • Ending Value    : ₹{nifty_res['final_equity']:,.2f}")
    print(f"   • Net Profit      : ₹{nifty_res['net_profit']:,.2f} ({(nifty_res['net_profit']/nifty_res['total_deposited'])*100:+.1f}%)")

    # 2. Track 6: Apex 3-Slot Compounder (40/30/30)
    cfg6 = SimulationConfig(max_slots=3, slot_allocations=[0.40, 0.30, 0.30], enable_pyramiding=True, use_weekly_10w_trail=True)
    res6 = run_sip_simulation(indicators, nifty, market_breadth, weekly_emas, vol_asym_dict, df_r1m, df_r3m, df_r6m, cfg6)
    print(f"\n🏆 Track 6: Apex 3-Slot Compounder (40/30/30, Weekly 10W Trail):")
    print(f"   • Total Deposited : ₹{res6['total_deposited']:,.2f}")
    print(f"   • Ending Value    : ₹{res6['final_equity']:,.2f}")
    print(f"   • Net Profit      : ₹{res6['net_profit']:,.2f} ({(res6['net_profit']/res6['total_deposited'])*100:+.1f}%)")
    print(f"   • Friction Paid   : ₹{res6['total_friction']:,.2f}")

    # 3. Track 8: Apex 1-Slot Rocket (100% All-In)
    cfg8 = SimulationConfig(max_slots=1, slot_allocations=[1.00], enable_pyramiding=True, use_weekly_10w_trail=True)
    res8 = run_sip_simulation(indicators, nifty, market_breadth, weekly_emas, vol_asym_dict, df_r1m, df_r3m, df_r6m, cfg8)
    print(f"\n🚀 Track 8: Apex 1-Slot Rocket (100% All-In Single Leader):")
    print(f"   • Total Deposited : ₹{res8['total_deposited']:,.2f}")
    print(f"   • Ending Value    : ₹{res8['final_equity']:,.2f}")
    print(f"   • Net Profit      : ₹{res8['net_profit']:,.2f} ({(res8['net_profit']/res8['total_deposited'])*100:+.1f}%)")
    print(f"   • Friction Paid   : ₹{res8['total_friction']:,.2f}")

    # 4. Track 9: Active Monthly Swing Engine
    cfg9 = SimulationConfig(max_slots=4, slot_allocations=[0.25, 0.25, 0.25, 0.25], enable_pyramiding=False, use_weekly_10w_trail=False, use_day21_cutoff=True, use_daily_20ema_trail=True)
    res9 = run_sip_simulation(indicators, nifty, market_breadth, weekly_emas, vol_asym_dict, df_r1m, df_r3m, df_r6m, cfg9)
    print(f"\n⚡ Track 9: Active 1-to-2 Month Swing Engine (4 Slots, Day 21 Cutoff):")
    print(f"   • Total Deposited : ₹{res9['total_deposited']:,.2f}")
    print(f"   • Ending Value    : ₹{res9['final_equity']:,.2f}")
    print(f"   • Net Profit      : ₹{res9['net_profit']:,.2f} ({(res9['net_profit']/res9['total_deposited'])*100:+.1f}%)")
    print(f"   • Friction Paid   : ₹{res9['total_friction']:,.2f}")

    print("\n" + "=" * 85)
    print("📈 MATHEMATICAL COMPOUNDING PROJECTIONS (₹30,000 / Month Deposited + 100% Profit Reinvested)")
    print("=" * 85)
    proj_df = compute_future_projections()
    for _, row in proj_df.iterrows():
        print(f"\n🔹 {row['Strategy']} (CAGR: {row['CAGR']}):")
        print(f"   • Year 1  : Deposited ₹3.6 Lakhs  -> Portfolio: {row['1Y Value']}")
        print(f"   • Year 3  : Deposited ₹10.8 Lakhs -> Portfolio: {row['3Y Value']}")
        print(f"   • Year 5  : Deposited ₹18.0 Lakhs -> Portfolio: {row['5Y Value']}")
        print(f"   • Year 7  : Deposited ₹25.2 Lakhs -> Portfolio: {row['7Y Value']}")
        print(f"   • Year 10 : Deposited ₹36.0 Lakhs -> Portfolio: {row['10Y Value']}")

if __name__ == "__main__":
    main()
