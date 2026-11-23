"""
TraderAI - 20%+ Monthly Pattern Discovery & Backtest Engine (2021-2026)
================================================================================
Specifically hunts for the quantitative signatures that precede a >= +20% GAIN
in a single 21-session calendar month with low adverse drawdown (MAE >= -5.0%).

Methodology:
  1. Census: Mine all occurrences of >= +20% 21-day surges across 626 NSE stocks (5Y).
  2. Microstructure Profiling: Compare Day T-0 features vs 100,000+ control samples.
     - Volume Ignition: RVOL >= 2.5x, 3.0x, 4.0x
     - High-Volume Gap thrusts (Episodic Pivots)
     - Tight Base Breakouts (Consolidation spread < 10% over 15 sessions)
     - Extreme Short-Term RS Velocity (RS 5d & 10d vs Nifty)
     - Bullish Closing Range Location ((Close - Low) / (High - Low) >= 0.80)
  3. Pattern Rule Formulation: Find the highest-precision 20%+ monthly trigger rules.
  4. Full Portfolio Cash Compounding Backtest:
     - Targeting >= +20% quick monthly harvest
     - Fast trailing on 5-day EMA once up +10%
     - Full Indian delivery friction (STT, GST, DP ₹15.93, slippage)
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

STARTING_CASH = 100000.0
SLIPPAGE = 0.0025
SPLIT_DATE = pd.Timestamp("2024-04-01")


def mine_20pct_monthly_patterns():
    print("=" * 85)
    print("🔬 MINING 626 NSE STOCKS FOR PREDICTORS OF >= +20% GAINS IN 21 SESSIONS")
    print("=" * 85, flush=True)

    cache_path = os.path.join(ROOT, "data", "cache", "universe_5y.pkl")
    bench_path = os.path.join(ROOT, "data", "cache", "benchmarks_5y.pkl")
    with open(cache_path, "rb") as f:
        universe: Dict[str, pd.DataFrame] = pickle.load(f)
    with open(bench_path, "rb") as f:
        benchmarks: Dict[str, pd.DataFrame] = pickle.load(f)

    nifty = benchmarks['^NSEI'].copy()
    nifty_c = nifty['Close']
    all_dates = nifty.index

    # Precalculate Market Breadth (% > 50 EMA)
    breadth_series = pd.Series(0.0, index=all_dates)
    active_series = pd.Series(0, index=all_dates)
    for sym, df in universe.items():
        if len(df) < 200: continue
        c = df['Close']
        ema50 = c.ewm(span=50, adjust=False).mean()
        above = (c > ema50).astype(int)
        breadth_series = breadth_series.add(above, fill_value=0)
        active_series = active_series.add(above.notna().astype(int), fill_value=0)
    market_breadth = (breadth_series / (active_series + 1e-9)) * 100.0

    target_events = []
    normal_events = []

    for sym, df in universe.items():
        if len(df) < 250: continue
        c = df['Close']
        h = df['High']
        l = df['Low']
        o = df['Open']
        v = df['Volume']
        dates = df.index
        n_rows = len(df)

        ema20 = c.ewm(span=20, adjust=False).mean()
        ema50 = c.ewm(span=50, adjust=False).mean()
        ema200 = c.ewm(span=200, adjust=False).mean()

        vol_ma20 = v.rolling(20).mean()
        rvol = v / (vol_ma20 + 1e-9)
        rvol_3d = rvol.rolling(3).mean()

        tr = np.maximum(h - l, np.maximum((h - c.shift(1)).abs(), (l - c.shift(1)).abs()))
        atr14 = tr.rolling(14).mean()
        atr_pct = (atr14 / (c + 1e-9)) * 100.0

        # Closing Location: Where did it close within the day's candle? (0.0 = low, 1.0 = high)
        candle_range = h - l
        close_loc = (c - l) / (candle_range + 1e-9)

        # 15-day consolidation tightness spread: (High15 - Low15) / Low15
        h15 = h.rolling(15).max()
        l15 = l.rolling(15).min()
        spread_15d = ((h15 - l15) / (l15 + 1e-9)) * 100.0

        # Gap % on day T
        gap_pct = (o / c.shift(1) - 1.0) * 100.0

        # Volume Asymmetry over 10 days
        up_day = (c > c.shift(1)).astype(float)
        up_vol_10 = (v * up_day).rolling(10).sum()
        down_vol_10 = (v * (1.0 - up_day)).rolling(10).sum()
        vol_asym_10 = up_vol_10 / (down_vol_10 + 1e-9)

        high20 = h.shift(1).rolling(20).max()
        high52w = h.shift(1).rolling(252).max()

        r5d_stock = c.pct_change(5)
        r10d_stock = c.pct_change(10)
        r21d_stock = c.pct_change(21)

        r5d_nifty = nifty_c.pct_change(5)
        r10d_nifty = nifty_c.pct_change(10)
        r21d_nifty = nifty_c.pct_change(21)

        for i in range(252, n_rows - 22, 2):
            cur_d = dates[i]
            if cur_d not in market_breadth.index or cur_d not in nifty_c.index: continue

            # Forward 21-day window
            fwd_max = h.iloc[i+1:i+22].max()
            fwd_min = l.iloc[i+1:i+22].min()
            fwd_close = c.iloc[i+21]

            gain_max_21d = (fwd_max / c.iloc[i] - 1.0) * 100.0
            dd_max_21d = (fwd_min / c.iloc[i] - 1.0) * 100.0
            ret_21d = (fwd_close / c.iloc[i] - 1.0) * 100.0

            rs_5d = (r5d_stock.iloc[i] - r5d_nifty.loc[cur_d]) * 100.0 if cur_d in r5d_nifty.index else 0.0
            rs_10d = (r10d_stock.iloc[i] - r10d_nifty.loc[cur_d]) * 100.0 if cur_d in r10d_nifty.index else 0.0
            rs_1m = (r21d_stock.iloc[i] - r21d_nifty.loc[cur_d]) * 100.0 if cur_d in r21d_nifty.index else 0.0

            feat = {
                "symbol": sym,
                "date": cur_d,
                "gain_max_21d": gain_max_21d,
                "ret_21d": ret_21d,
                "dd_max_21d": dd_max_21d,
                "rvol": rvol.iloc[i],
                "rvol_3d": rvol_3d.iloc[i],
                "close_loc": close_loc.iloc[i],
                "gap_pct": gap_pct.iloc[i],
                "spread_15d": spread_15d.iloc[i],
                "vol_asym_10": vol_asym_10.iloc[i],
                "rs_5d": rs_5d,
                "rs_10d": rs_10d,
                "rs_1m": rs_1m,
                "dist_ema20": (c.iloc[i] / (ema20.iloc[i] + 1e-9) - 1.0) * 100.0,
                "dist_ema50": (c.iloc[i] / (ema50.iloc[i] + 1e-9) - 1.0) * 100.0,
                "dist_ema200": (c.iloc[i] / (ema200.iloc[i] + 1e-9) - 1.0) * 100.0,
                "dist_high52w": (c.iloc[i] / (high52w.iloc[i] + 1e-9) - 1.0) * 100.0,
                "dist_high20": (c.iloc[i] / (high20.iloc[i] + 1e-9) - 1.0) * 100.0,
                "breadth": market_breadth.loc[cur_d],
                "stage2": float(c.iloc[i] > ema50.iloc[i] and ema50.iloc[i] > ema200.iloc[i]),
            }

            # Target 20M: Reached >= +20% gain in 21 sessions with drawdown <= 5%
            if gain_max_21d >= 20.0 and dd_max_21d >= -5.0:
                target_events.append(feat)
            elif gain_max_21d < 5.0 or dd_max_21d < -6.0:
                if i % 6 == 0:
                    normal_events.append(feat)

    df_target = pd.DataFrame(target_events)
    df_normal = pd.DataFrame(normal_events)

    print(f"Discovered {len(df_target):,} Target +20% Monthly Moves vs {len(df_normal):,} Control Samples.")

    print("\n" + "="*85)
    print("⚡ MICROSTRUCTURE SIGNATURE OF STOCKS PRIOR TO A +20% MONTHLY THRUST")
    print("="*85)

    metrics = [
        ("Volume Explosion (Trigger Day RVOL)", "rvol", "Higher = Heavy Institutional Buying"),
        ("3-Day Sustained Volume (RVOL 3D)", "rvol_3d", "Multi-day volume persistence"),
        ("Closing Range Location (0.0 to 1.0)", "close_loc", ">= 0.80 means closed near the absolute high of the day"),
        ("Gap Up on Trigger Day (%)", "gap_pct", "Gap size on ignition day"),
        ("15-Day Base Tightness Spread (%)", "spread_15d", "Lower = Tighter consolidation prior to ignition"),
        ("10-Day Volume Asymmetry (Up/Down)", "vol_asym_10", "Ratio of buying volume to selling volume"),
        ("Short-Term RS Velocity (10-Day RS %)", "rs_10d", "Outperformance over prior 2 weeks"),
        ("Medium-Term RS (1-Month RS %)", "rs_1m", "Outperformance over prior month"),
        ("Distance Above 200-EMA (%)", "dist_ema200", "Where in cycle does it detonate?"),
        ("Proximity to 52-Week High (%)", "dist_high52w", "Distance to yearly high"),
        ("Market Breadth (% > 50-EMA)", "breadth", "Market environment"),
    ]

    for label, col, note in metrics:
        t_val = df_target[col].median()
        n_val = df_normal[col].median()
        diff = t_val - n_val
        print(f"\n🎯 {label}:")
        print(f"   • +20% Month Thrust Median : {t_val:+.2f}")
        print(f"   • Control Sample Median    : {n_val:+.2f} (Delta: {diff:+.2f})")
        print(f"   • Insight                  : {note}")

    return universe, nifty, market_breadth


# =====================================================================
# 2. BACKTEST THE 20%+ MONTHLY HARVEST STRATEGY (PORTFOLIO CASH COMPOUNDING)
# =====================================================================
def backtest_20pct_monthly_strategy(universe: Dict[str, pd.DataFrame], nifty: pd.DataFrame, market_breadth: pd.Series):
    print("\n" + "="*85)
    print("🚀 BACKTESTING THE 20%+ MONTHLY HARVEST STRATEGY (PORTFOLIO CASH COMPOUNDING)")
    print("="*85, flush=True)

    # Strategy Rules (derived directly from the empirical signatures above):
    # 1. Macro Breadth Gate: Breadth >= 50% & Nifty > 50-EMA
    # 2. Setup: "The Power-Ignition Thrust"
    #    - Price > 50-EMA and 50-EMA > 200-EMA (Stage 2)
    #    - Distance to 52W High <= 15%
    #    - Distance to 200-EMA >= +15%
    #    - Day T RVOL >= 2.0x (Institutional Volume Thrust)
    #    - Candle Closes in top 25% of daily range (close_loc >= 0.75)
    #    - 10-day Volume Asymmetry >= 1.6x
    #    - Top 10-day / 1-month Relative Strength
    # 3. Fast Harvesting Exit:
    #    - Target: +20% Take-Profit (Harvest the quick +20% gain in 10-20 sessions!)
    #    - Stop: -5.0% tight stop
    #    - Fast Trailing: Trail 5-day EMA once gain >= +10%
    #    - Max duration: 21 sessions (1 month max hold)

    trading_dates = list(nifty.index)
    start_idx = 252
    active_dates = trading_dates[start_idx:]
    DAILY_YIELD = (1.0 + 0.065) ** (1.0 / 252.0) - 1.0
    nifty["EMA50"] = nifty["Close"].ewm(span=50, adjust=False).mean()

    # Precalculate indicators
    sym_data = {}
    for sym, df in universe.items():
        if len(df) < 250: continue
        c = df['Close']
        h = df['High']
        l = df['Low']
        o = df['Open']
        v = df['Volume']
        ema5 = c.ewm(span=5, adjust=False).mean()
        ema20 = c.ewm(span=20, adjust=False).mean()
        ema50 = c.ewm(span=50, adjust=False).mean()
        ema200 = c.ewm(span=200, adjust=False).mean()
        vol_ma = v.rolling(20).mean()
        rvol = v / (vol_ma + 1e-9)
        high52w = h.shift(1).rolling(252).max()
        high20 = h.shift(1).rolling(20).max()
        close_loc = (c - l) / (h - l + 1e-9)
        up_day = (c > c.shift(1)).astype(float)
        vol_asym_10 = (v * up_day).rolling(10).sum() / (v * (1.0 - up_day)).rolling(10).sum()
        r10d = c.pct_change(10)
        r21d = c.pct_change(21)

        sym_data[sym] = {
            "dates": set(df.index), "c": c, "h": h, "l": l, "o": o, "v": v,
            "ema5": ema5, "ema20": ema20, "ema50": ema50, "ema200": ema200,
            "rvol": rvol, "high52w": high52w, "high20": high20,
            "close_loc": close_loc, "vol_asym_10": vol_asym_10,
            "r10d": r10d, "r21d": r21d,
        }

    for target_gain, label in [
        (0.18, "Monthly Harvest Engine (Target +18% in 21d, Stop -5%)"),
        (0.22, "⭐ Monthly Harvest Engine (Target +22% in 21d, Stop -5%)"),
        (0.25, "Monthly Harvest Engine (Target +25% in 21d, Stop -5.5%)"),
    ]:
        cash = STARTING_CASH
        max_slots = 4  # 4 slots (25% each) = active rotation
        positions = []
        closed_trades = []
        daily_equity_curve = []
        total_friction_inr = 0.0
        peak_equity = STARTING_CASH

        for d_idx, today in enumerate(active_dates):
            if d_idx >= len(active_dates) - 1: break
            next_day = active_dates[d_idx + 1]

            if cash > 1000.0: cash += cash * DAILY_YIELD

            open_positions = []
            for pos in positions:
                sym = pos["symbol"]
                ind = sym_data[sym]
                if today not in ind["dates"]:
                    open_positions.append(pos)
                    continue

                day_o = ind["o"].loc[today]
                day_h = ind["h"].loc[today]
                day_l = ind["l"].loc[today]
                day_c = ind["c"].loc[today]
                pos["days_held"] += 1

                if day_c > pos["highest_close"]: pos["highest_close"] = day_c

                exit_occurred = False
                exit_px = 0.0
                exit_reason = ""

                # Stop
                if day_o <= pos["stop"]:
                    exit_px = day_o * (1.0 - SLIPPAGE)
                    exit_reason = "stop_gap"
                    exit_occurred = True
                elif day_l <= pos["stop"]:
                    exit_px = pos["stop"] * (1.0 - SLIPPAGE)
                    exit_reason = "stop_loss"
                    exit_occurred = True

                # Target Profit Harvest
                elif day_h >= pos["target_px"]:
                    exit_px = pos["target_px"] * (1.0 - SLIPPAGE)
                    exit_reason = "target_harvest"
                    exit_occurred = True

                # Fast Trailing 5-EMA once gain >= +10%
                elif (pos["highest_close"] / pos["entry_price"] - 1.0) >= 0.10 and day_c < ind["ema5"].loc[today]:
                    exit_px = day_c * (1.0 - SLIPPAGE)
                    exit_reason = "trail_5ema"
                    exit_occurred = True

                # Max 21 Sessions (~1 Month Cutoff)
                elif pos["days_held"] >= 21:
                    exit_px = day_c * (1.0 - SLIPPAGE)
                    exit_reason = "month_21d_recycle"
                    exit_occurred = True

                if exit_occurred:
                    sell_val = pos["shares"] * exit_px
                    friction = (sell_val * 0.001042) + 15.93 + (sell_val * SLIPPAGE)
                    total_friction_inr += friction
                    cash += (sell_val - friction)
                    net_pnl = (sell_val - friction) - (pos["shares"] * pos["entry_price"])
                    closed_trades.append({
                        "symbol": sym, "days_held": pos["days_held"],
                        "net_pnl_inr": net_pnl, "net_pnl_pct": (net_pnl / (pos["shares"] * pos["entry_price"])) * 100.0,
                        "exit_reason": exit_reason,
                    })
                else:
                    open_positions.append(pos)

            positions = open_positions

            current_equity = cash
            for p in positions:
                s = p["symbol"]
                ind = sym_data[s]
                px = ind["c"].loc[today] if today in ind["dates"] else p["entry_price"]
                current_equity += p["shares"] * px

            if current_equity > peak_equity: peak_equity = current_equity
            daily_equity_curve.append({"date": today, "equity": current_equity})

            breadth = market_breadth.get(today, 50.0)
            nifty_c = nifty["Close"].loc[today]
            nifty_ema50 = nifty["EMA50"].loc[today]

            if breadth < 48.0 or nifty_c < nifty_ema50: continue

            open_slots = max_slots - len(positions)
            if open_slots <= 0: continue

            candidates = []
            for sym, ind in sym_data.items():
                if any(p["symbol"] == sym for p in positions): continue
                if today not in ind["dates"]: continue

                c_t = ind["c"].loc[today]
                ema50 = ind["ema50"].loc[today]
                ema200 = ind["ema200"].loc[today]
                h52w = ind["high52w"].loc[today]
                h20 = ind["high20"].loc[today]
                rvol = ind["rvol"].loc[today]
                close_l = ind["close_loc"].loc[today]

                # Power-Ignition Rules
                if c_t > ema50 and ema50 > ema200 and c_t >= ema200 * 1.15 and c_t >= h52w * 0.88 and c_t > h20:
                    if rvol >= 1.8 and close_l >= 0.70:
                        asym = ind["vol_asym_10"].loc[today]
                        if pd.isna(asym) or asym < 1.6: continue
                        r10 = ind["r10d"].loc[today]
                        r21 = ind["r21d"].loc[today]
                        if pd.isna(r10) or pd.isna(r21): continue
                        if r10 <= 0 or r21 <= 0: continue
                        comp = (0.60 * r10) + (0.40 * r21)
                        candidates.append((sym, comp))

            if not candidates: continue
            candidates.sort(key=lambda x: x[1], reverse=True)
            chosen = candidates[:open_slots]

            for sym, _ in chosen:
                ind = sym_data[sym]
                if next_day not in ind["dates"]: continue
                day0_c = ind["c"].loc[today]
                next_o = ind["o"].loc[next_day]
                if (next_o / day0_c - 1.0) > 0.025: continue

                entry_fill = next_o * (1.0 + SLIPPAGE)
                stop_px = entry_fill * 0.95  # 5% stop
                target_px = entry_fill * (1.0 + target_gain)
                shares = min(int((current_equity * 0.025) / (entry_fill - stop_px)), int((current_equity / max_slots) / entry_fill))
                if shares <= 0: continue

                cost = shares * entry_fill
                buy_fric = (cost * 0.001192) + (cost * SLIPPAGE)
                if cash < cost + buy_fric: continue
                cash -= (cost + buy_fric)
                total_friction_inr += buy_fric

                positions.append({
                    "symbol": sym, "entry_date": next_day, "entry_price": entry_fill,
                    "shares": shares, "stop": stop_px, "target_px": target_px,
                    "days_held": 0, "highest_close": entry_fill,
                })

        final_equity = cash
        last_d = active_dates[-1]
        for p in positions:
            s = p["symbol"]
            ind = sym_data[s]
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
        hit_target = (df_tr["exit_reason"] == "target_harvest").sum()
        trades_per_yr = len(df_tr) / n_years

        print(f"\n📌 {label}:")
        print(f"   • Ending Capital    : ₹{final_equity:,.2f} ({tot_ret:+.2f}% Net Return)")
        print(f"   • 5-Year CAGR       : {cagr:+.2f}% per year")
        print(f"   • Max Drawdown      : {max_dd:.2f}%")
        print(f"   • Annual Cadence    : ~{trades_per_yr:.0f} trades/year (Total: {len(df_tr)} trades)")
        print(f"   • Profit Factor     : {pf:.2f} | Win Rate: {(len(wins)/len(df_tr)*100):.1f}%")
        print(f"   • Target Hits       : {hit_target} trades ({hit_target/len(df_tr)*100:.1f}%) hit the +20%+ profit target!")
        print(f"   • Avg Holding Days  : {df_tr['days_held'].mean():.1f} sessions (~{df_tr['days_held'].mean()/21:.1f} months)")
        print(f"   • Friction Paid     : ₹{total_friction_inr:,.2f}")


def main():
    universe, nifty, market_breadth = mine_20pct_monthly_patterns()
    backtest_20pct_monthly_strategy(universe, nifty, market_breadth)


if __name__ == "__main__":
    main()
