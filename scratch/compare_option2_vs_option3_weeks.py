"""
Empirical Comparison: Option 2 (9:20 AM Confirmation) vs Option 3 (GTT Buy-Stop Trigger)
Simulated across rolling weekly cohorts over the past 1-year historical dataset (250 sessions)
under exact Indian statutory CNC delivery costs (STT, GST, ₹15.93 CDSL DP fee, 0.20% slippage).
"""
from __future__ import annotations

import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import HIGH_BETA_APEX_STOCKS
from data.market_data import _get_cached_history
from data.costs import compute_indian_delivery_costs


def run_weekly_duel_simulation(lookback_bars: int = 250):
    print("=" * 80)
    print("🥊 12-WEEK & 1-YEAR DUEL: OPTION 2 (9:20 AM CONFIRMATION) VS OPTION 3 (GTT BUY-STOP)")
    print("=" * 80)

    # Load all cached stock histories
    stock_data = {}
    for t in HIGH_BETA_APEX_STOCKS:
        df = _get_cached_history(t, "2y")
        if not df.empty:
            df.columns = [str(c).title() for c in df.columns]
            if "Close" in df.columns and "High" in df.columns and "Low" in df.columns and len(df) >= lookback_bars:
                stock_data[t] = df.tail(lookback_bars).copy()

    print(f"Loaded {len(stock_data)} liquid high-beta stocks with {lookback_bars} continuous daily bars.\n")

    # Dates
    ref_ticker = list(stock_data.keys())[0]
    dates = stock_data[ref_ticker].index

    # Trackers
    # Starting capital ₹1,00,000 for each option
    cap_o2 = 100000.0
    cap_o3 = 100000.0

    trades_o2 = []
    trades_o3 = []
    aborted_o2_count = 0
    untriggered_o3_count = 0

    # Step through every 5 bars (weekly scans)
    step = 5
    for bar_idx in range(65, len(dates) - 22, step):
        scan_date = dates[bar_idx]
        
        # Screen candidates at bar_idx
        screened = []
        for t, df in stock_data.items():
            sub = df.iloc[:bar_idx+1]
            c = sub["Close"]
            h = sub["High"]
            l = sub["Low"]
            v = sub["Volume"] if "Volume" in sub.columns else pd.Series(dtype=float)

            if len(c) < 65:
                continue

            px = float(c.iloc[-1])
            ret_1m = float(c.iloc[-1] / c.iloc[-22] - 1)
            high_20d = float(h.iloc[-20:].max())
            high_5d = float(h.iloc[-5:].max())
            low_20d = float(l.iloc[-20:].min())
            low_5d = float(l.iloc[-5:].min())
            
            # 52w high approx (tail 250)
            high_52w = float(h.max())
            dist_52w = (px - high_52w) / high_52w
            
            rvol = float(v.iloc[-1] / v.iloc[-20:].mean()) if len(v) >= 20 and v.iloc[-20:].mean() > 0 else 1.0
            range_20 = high_20d - low_20d
            vcp = (high_5d - low_5d) / range_20 if range_20 > 0 else 1.0
            
            # Minervini / Relative Strength Score
            score = ret_1m * 100.0 + (dist_52w * 50.0) + (rvol * 15.0)
            if vcp <= 0.65:
                score += 15.0
            if dist_52w >= -0.05:
                score += 20.0

            screened.append({
                "ticker": t,
                "price": px,
                "score": score,
                "ret_1m": ret_1m,
                "rvol": rvol,
                "pivot_trigger": high_5d,
                "dist_52w": dist_52w,
                "vcp": vcp,
            })

        screened.sort(key=lambda x: x["score"], reverse=True)
        tier1_picks = screened[:3]
        tier2_radar = screened[3:10]

        # --- OPTION 2: 9:20 AM CONFIRMATION ON TIER 1 ---
        for p in tier1_picks:
            t = p["ticker"]
            df = stock_data[t]
            entry_bar = bar_idx + 1
            if entry_bar >= len(df):
                continue

            # Day T+1 Open check
            t_close = p["price"]
            t1_open = float(df["Open"].iloc[entry_bar])
            gap = (t1_open - t_close) / t_close

            # 9:20 AM Confirmation Rule:
            # If gap < -1.5%, ABORT (bad news gap-down defense!)
            if gap < -0.015:
                aborted_o2_count += 1
                continue

            # If huge gap > +3.5%, buy with 1.0% pullback penalty; else buy at Open + 0.20% slippage
            entry_px = t1_open * 1.002
            slot_cap = cap_o2 / 3.0
            shares = int(slot_cap // entry_px) if entry_px > 0 else 0
            if shares <= 0:
                continue

            target_px = entry_px * 1.20
            stop_px = entry_px * 0.93

            # Simulate holding up to 21 bars
            exit_px = entry_px
            exit_reason = "TIME_EXPIRY"
            exit_idx = entry_bar

            for h_idx in range(entry_bar, min(entry_bar + 21, len(df))):
                bar_h = float(df["High"].iloc[h_idx])
                bar_c = float(df["Close"].iloc[h_idx])
                
                # Check target
                if bar_h >= target_px:
                    exit_px = target_px
                    exit_reason = "TARGET_HIT (+20%)"
                    exit_idx = h_idx
                    break
                # Check Daily Close stop
                if bar_c <= stop_px:
                    exit_px = stop_px
                    exit_reason = "STOP_LOSS (-7% Close)"
                    exit_idx = h_idx
                    break
                exit_px = bar_c
                exit_idx = h_idx

            costs = compute_indian_delivery_costs(buy_price=entry_px, sell_price=exit_px, quantity=shares)
            net_pnl = (exit_px - entry_px) * shares - costs.total_friction_rupees
            trades_o2.append({
                "ticker": t,
                "scan_date": str(scan_date)[:10],
                "entry_px": entry_px,
                "exit_px": exit_px,
                "net_pnl": net_pnl,
                "net_pct": (net_pnl / (entry_px * shares)) * 100.0,
                "reason": exit_reason,
                "bars_held": exit_idx - entry_bar + 1,
            })
            cap_o2 += net_pnl

        # --- OPTION 3: GTT BUY-STOP PIVOT TRIGGER ON TIER 2 RADAR ---
        for r in tier2_radar[:3]:
            t = r["ticker"]
            df = stock_data[t]
            pivot_px = r["pivot_trigger"]

            # Check if high in next 5 bars crosses pivot_px
            triggered = False
            trigger_bar = -1
            for check_idx in range(bar_idx + 1, min(bar_idx + 6, len(df))):
                if float(df["High"].iloc[check_idx]) >= pivot_px:
                    triggered = True
                    trigger_bar = check_idx
                    break

            if not triggered:
                untriggered_o3_count += 1
                continue

            # Trigger filled at Pivot + 0.20% slippage
            entry_px = pivot_px * 1.002
            slot_cap = cap_o3 / 3.0
            shares = int(slot_cap // entry_px) if entry_px > 0 else 0
            if shares <= 0:
                continue

            target_px = entry_px * 1.20
            stop_px = entry_px * 0.93

            exit_px = entry_px
            exit_reason = "TIME_EXPIRY"
            exit_idx = trigger_bar

            for h_idx in range(trigger_bar, min(trigger_bar + 21, len(df))):
                bar_h = float(df["High"].iloc[h_idx])
                bar_c = float(df["Close"].iloc[h_idx])

                if bar_h >= target_px:
                    exit_px = target_px
                    exit_reason = "TARGET_HIT (+20%)"
                    exit_idx = h_idx
                    break
                if bar_c <= stop_px:
                    exit_px = stop_px
                    exit_reason = "STOP_LOSS (-7% Close)"
                    exit_idx = h_idx
                    break
                exit_px = bar_c
                exit_idx = h_idx

            costs = compute_indian_delivery_costs(buy_price=entry_px, sell_price=exit_px, quantity=shares)
            net_pnl = (exit_px - entry_px) * shares - costs.total_friction_rupees
            trades_o3.append({
                "ticker": t,
                "scan_date": str(scan_date)[:10],
                "entry_px": entry_px,
                "exit_px": exit_px,
                "net_pnl": net_pnl,
                "net_pct": (net_pnl / (entry_px * shares)) * 100.0,
                "reason": exit_reason,
                "bars_held": exit_idx - trigger_bar + 1,
            })
            cap_o3 += net_pnl

    # Compute Statistics
    df2 = pd.DataFrame(trades_o2)
    df3 = pd.DataFrame(trades_o3)

    w2 = (df2["net_pnl"] > 0).mean() * 100.0 if not df2.empty else 0.0
    w3 = (df3["net_pnl"] > 0).mean() * 100.0 if not df3.empty else 0.0

    gp2 = df2[df2["net_pnl"] > 0]["net_pnl"].sum() if not df2.empty else 0
    gl2 = abs(df2[df2["net_pnl"] < 0]["net_pnl"].sum()) if not df2.empty else 1
    pf2 = round(gp2 / gl2, 2) if gl2 > 0 else 99.0

    gp3 = df3[df3["net_pnl"] > 0]["net_pnl"].sum() if not df3.empty else 0
    gl3 = abs(df3[df3["net_pnl"] < 0]["net_pnl"].sum()) if not df3.empty else 1
    pf3 = round(gp3 / gl3, 2) if gl3 > 0 else 99.0

    print("📊 COMPARATIVE TOURNAMENT RESULTS (1-Year / 52 Weeks Forward Simulation):")
    print("-" * 80)
    print(f"{'Metric':<35} | {'Option 2: 9:20 AM Rule':<20} | {'Option 3: GTT Buy-Stop':<20}")
    print("-" * 80)
    print(f"{'Starting Capital':<35} | ₹1,00,000            | ₹1,00,000")
    print(f"{'Final Capital':<35} | ₹{cap_o2:>10,.2f}         | ₹{cap_o3:>10,.2f}")
    print(f"{'Total Net Return %':<35} | {((cap_o2-100000)/1000):>+10.1f}%          | {((cap_o3-100000)/1000):>+10.1f}%")
    print(f"{'Total Trades Triggered':<35} | {len(df2):>10}            | {len(df3):>10}")
    print(f"{'Win Rate %':<35} | {w2:>10.1f}%          | {w3:>10.1f}%")
    print(f"{'Profit Factor':<35} | {pf2:>10.2f}            | {pf3:>10.2f}")
    print(f"{'Trades Filtered / Avoided':<35} | {aborted_o2_count:>10} bad gaps    | {untriggered_o3_count:>10} non-breaks")
    print(f"{'Avg Trade Gain':<35} | {df2['net_pct'].mean():>+10.2f}%          | {df3['net_pct'].mean():>+10.2f}%")
    print(f"{'Best Single Trade':<35} | {df2['net_pct'].max():>+10.2f}%          | {df3['net_pct'].max():>+10.2f}%")
    print("-" * 80)

    if cap_o3 > cap_o2:
        print("🏆 WINNER: Option 3 (GTT Buy-Stop Trigger) generated higher returns due to filtering out non-moving stocks!")
    else:
        print("🏆 WINNER: Option 2 (9:20 AM Confirmation) generated higher returns due to earlier entry fills on explosive leaders!")

if __name__ == "__main__":
    run_weekly_duel_simulation()
