"""
TraderAI - Thorough Exploratory Data Analysis (EDA) for 1-to-2 Month Swing Horizon
==================================================================================
Empirically investigates what quantitative patterns and microstructure signatures
predict explosive +30% to +100% returns over a 1 to 2 month (21 to 45 trading sessions) holding window.

Features Evaluated (Day T-0 State):
  1. Trend & Stage: dist_ema20, dist_ema50, dist_ema200, slope_ema50
  2. Momentum & RS: rs_1m, rs_3m, rs_6m, rs_acceleration, rsi_14
  3. Volume Footprint: rvol_t0, rvol_5d, vol_asymmetry_20d, obv_trend
  4. Coiling & Volatility: atr_squeeze (ATR5/ATR20), bb_width, dist_high52w, dist_high20d
  5. Regime: market_breadth, nifty_dist_ema50

Outputs:
  - Spearman Rank Information Coefficients (IC) with forward 21d and 42d returns
  - Decile bucket performance (Top 10% vs Bottom 10%)
  - Non-linear pattern clusters for 1-2 month explosive runners
  - 5-year portfolio cash compounding simulation (₹100k, full Indian delivery taxes)
"""
from __future__ import annotations

import os
import sys
import time
import pickle
from typing import Dict, List, Any, Tuple

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SLIPPAGE = 0.0025
STARTING_CASH = 100000.0
CASH_YIELD_ANNUAL = 0.065
DAILY_CASH_YIELD = (1.0 + CASH_YIELD_ANNUAL) ** (1.0 / 252.0) - 1.0


def load_universe_and_benchmarks():
    print("📦 Loading 5Y universe cache and benchmarks...", flush=True)
    cache_path = os.path.join(ROOT, "data", "cache", "universe_5y.pkl")
    bench_path = os.path.join(ROOT, "data", "cache", "benchmarks_5y.pkl")
    with open(cache_path, "rb") as f:
        universe: Dict[str, pd.DataFrame] = pickle.load(f)
    with open(bench_path, "rb") as f:
        benchmarks: Dict[str, pd.DataFrame] = pickle.load(f)
    nifty = benchmarks['^NSEI'].copy()
    nifty['EMA20'] = nifty['Close'].ewm(span=20, adjust=False).mean()
    nifty['EMA50'] = nifty['Close'].ewm(span=50, adjust=False).mean()
    return universe, nifty


# =====================================================================
# 1. EXTRACT DATA MATRIX FOR 1-2 MONTH FORWARD PREDICTION
# =====================================================================
def extract_monthly_eda_matrix(universe: Dict[str, pd.DataFrame], nifty: pd.DataFrame):
    print("\n" + "="*85)
    print("🔬 EXTRACTING 5-YEAR FEATURE MATRIX FOR 1-TO-2 MONTH HOLDING HORIZON (21-45 DAYS)")
    print("="*85, flush=True)

    nifty_c = nifty['Close']
    all_dates = nifty.index

    # Precalculate Market Breadth (% above 50-EMA)
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

    nifty_r1m = nifty_c.pct_change(21)
    nifty_r3m = nifty_c.pct_change(63)
    nifty_r6m = nifty_c.pct_change(126)

    samples = []

    # Step through universe, sampling every 5 sessions to avoid excessive autocorrelation
    for sym, df in universe.items():
        if len(df) < 300: continue
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

        tr = np.maximum(h - l, np.maximum((h - c.shift(1)).abs(), (l - c.shift(1)).abs()))
        atr5 = tr.rolling(5).mean()
        atr20 = tr.rolling(20).mean()
        atr_squeeze = atr5 / (atr20 + 1e-9)

        vol_ma20 = v.rolling(20).mean()
        rvol = v / (vol_ma20 + 1e-9)
        rvol_5d = rvol.rolling(5).mean()

        up_day = (c > c.shift(1)).astype(float)
        up_vol_20 = (v * up_day).rolling(20).sum()
        down_vol_20 = (v * (1.0 - up_day)).rolling(20).sum()
        vol_asym_20 = up_vol_20 / (down_vol_20 + 1e-9)

        high20 = h.shift(1).rolling(20).max()
        high52w = h.shift(1).rolling(252).max()

        r1 = c.pct_change(21)
        r3 = c.pct_change(63)
        r6 = c.pct_change(126)

        # OBV slope 20d
        obv = (np.sign(c.diff()).fillna(0) * v).cumsum()
        obv_ma20 = obv.rolling(20).mean()
        obv_trend = (obv / (obv_ma20 + 1e-9) - 1.0) * 100.0

        for i in range(252, n_rows - 45, 5):
            cur_date = dates[i]
            if cur_date not in market_breadth.index or cur_date not in nifty_c.index: continue

            # Forward returns: 21 days (1 month) and 42 days (2 months)
            fwd_21_px = c.iloc[i+21]
            fwd_42_px = c.iloc[i+42]
            fwd_max_42_px = h.iloc[i+1:i+43].max()
            fwd_min_42_px = l.iloc[i+1:i+43].min()

            ret_21d = (fwd_21_px / c.iloc[i] - 1.0) * 100.0
            ret_42d = (fwd_42_px / c.iloc[i] - 1.0) * 100.0
            max_gain_42d = (fwd_max_42_px / c.iloc[i] - 1.0) * 100.0
            max_dd_42d = (fwd_min_42_px / c.iloc[i] - 1.0) * 100.0

            rs1 = (r1.iloc[i] - nifty_r1m.loc[cur_date]) * 100.0 if cur_date in nifty_r1m.index else 0.0
            rs3 = (r3.iloc[i] - nifty_r3m.loc[cur_date]) * 100.0 if cur_date in nifty_r3m.index else 0.0
            rs6 = (r6.iloc[i] - nifty_r6m.loc[cur_date]) * 100.0 if cur_date in nifty_r6m.index else 0.0
            rs_accel = rs1 - (rs3 / 3.0)  # RS Acceleration: 1M pace vs 3M pace

            samples.append({
                "symbol": sym,
                "date": cur_date,
                "ret_21d": ret_21d,
                "ret_42d": ret_42d,
                "max_gain_42d": max_gain_42d,
                "max_dd_42d": max_dd_42d,
                "is_super_mover": float(ret_42d >= 25.0 and max_dd_42d >= -8.0),
                # Trend / Stage
                "dist_ema20": (c.iloc[i] / (ema20.iloc[i] + 1e-9) - 1.0) * 100.0,
                "dist_ema50": (c.iloc[i] / (ema50.iloc[i] + 1e-9) - 1.0) * 100.0,
                "dist_ema200": (c.iloc[i] / (ema200.iloc[i] + 1e-9) - 1.0) * 100.0,
                "stage2": float(c.iloc[i] > ema50.iloc[i] and ema50.iloc[i] > ema200.iloc[i]),
                # Momentum & RS
                "rs_1m": rs1,
                "rs_3m": rs3,
                "rs_6m": rs6,
                "rs_accel": rs_accel,
                # Volume Footprint
                "rvol": rvol.iloc[i],
                "rvol_5d": rvol_5d.iloc[i],
                "vol_asym_20": vol_asym_20.iloc[i],
                "obv_trend": obv_trend.iloc[i],
                # Coiling & Proximity
                "atr_squeeze": atr_squeeze.iloc[i],
                "dist_high20": (c.iloc[i] / (high20.iloc[i] + 1e-9) - 1.0) * 100.0,
                "dist_high52w": (c.iloc[i] / (high52w.iloc[i] + 1e-9) - 1.0) * 100.0,
                # Macro
                "market_breadth": market_breadth.loc[cur_date],
                "nifty_above_50": float(nifty_c.loc[cur_date] > nifty['EMA50'].loc[cur_date]),
            })

    df_samples = pd.DataFrame(samples).dropna()
    print(f"Extracted {len(df_samples):,} cross-sectional observation points.")
    return df_samples


# =====================================================================
# 2. RUN STATISTICAL EDA & INFORMATION COEFFICIENTS (IC)
# =====================================================================
def run_statistical_eda(df: pd.DataFrame):
    print("\n" + "="*85)
    print("📊 INFORMATION COEFFICIENT (IC) RANK CORRELATION WITH FORWARD 1-2 MONTH RETURNS")
    print("="*85, flush=True)

    features = [
        ("rs_accel", "Relative Strength Acceleration (1M pace vs 3M pace)"),
        ("rs_1m", "1-Month Relative Strength vs Nifty"),
        ("rs_3m", "3-Month Relative Strength vs Nifty"),
        ("rs_6m", "6-Month Relative Strength vs Nifty"),
        ("vol_asym_20", "20-Day Volume Asymmetry (Up-Vol / Down-Vol)"),
        ("dist_ema200", "Distance Above 200-EMA (%)"),
        ("dist_high52w", "Distance to 52-Week High (%)"),
        ("dist_high20", "Distance to 20-Day High (%)"),
        ("obv_trend", "OBV 20-Day Accumulation Trend (%)"),
        ("rvol_5d", "5-Day Average Relative Volume"),
        ("rvol", "Single-Day Relative Volume"),
        ("atr_squeeze", "ATR Squeeze (ATR5 / ATR20)"),
        ("market_breadth", "Market Breadth (% Stocks > 50 EMA)"),
        ("dist_ema20", "Distance from 20-EMA (%)"),
    ]

    ic_results = []
    r_ret21 = df['ret_21d'].rank()
    r_ret42 = df['ret_42d'].rank()
    for col, desc in features:
        r_col = df[col].rank()
        ic_21 = float(r_col.corr(r_ret21))
        ic_42 = float(r_col.corr(r_ret42))
        ic_results.append({
            "Feature": col,
            "Description": desc,
            "IC_21d": ic_21,
            "IC_42d": ic_42,
        })

    df_ic = pd.DataFrame(ic_results).sort_values(by="IC_42d", ascending=False)
    for _, r in df_ic.iterrows():
        sig = "⭐⭐⭐" if abs(r['IC_42d']) > 0.05 else ("⭐⭐" if abs(r['IC_42d']) > 0.02 else "")
        print(f"  • {r['Feature']:<16} | 21d IC: {r['IC_21d']:+.4f} | 42d IC: {r['IC_42d']:+.4f} {sig:<4} | {r['Description']}")

    print("\n" + "="*85)
    print("🏆 DECILE PERFORMANCE AUDIT (FORWARD 42-DAY / 2-MONTH RETURN BY FEATURE DECILE)")
    print("="*85)

    top_features = ["rs_accel", "dist_ema200", "vol_asym_20", "rs_1m"]
    for feat in top_features:
        df['decile'] = pd.qcut(df[feat], q=10, labels=False, duplicates='drop')
        dec_perf = df.groupby('decile').agg({
            'ret_42d': 'mean',
            'is_super_mover': 'mean',
        })
        d10_ret = dec_perf.loc[9, 'ret_42d'] if 9 in dec_perf.index else 0.0
        d1_ret = dec_perf.loc[0, 'ret_42d'] if 0 in dec_perf.index else 0.0
        spread = d10_ret - d1_ret
        super_pct = dec_perf.loc[9, 'is_super_mover'] * 100.0 if 9 in dec_perf.index else 0.0

        print(f"\n📌 Feature: {feat.upper()}:")
        print(f"   • Decile 10 (Top 10%) Mean 42d Return : {d10_ret:+.2f}% (Super-Mover Hit Rate: {super_pct:.1f}%)")
        print(f"   • Decile 1  (Bottom 10%) Mean Return  : {d1_ret:+.2f}%")
        print(f"   • Top-Minus-Bottom Monotonic Spread   : {spread:+.2f}% spread over 2 months!")


# =====================================================================
# 3. BACKTEST THE 1-TO-2 MONTH OPTIMIZED ENGINE (PORTFOLIO CASH COMPOUNDING)
# =====================================================================
def backtest_monthly_engine(universe: Dict[str, pd.DataFrame], nifty: pd.DataFrame):
    print("\n" + "="*85)
    print("🚀 BACKTESTING THE 1-TO-2 MONTH OPTIMIZED SWING ENGINE (2021-2026)")
    print("="*85, flush=True)

    # Strategy:
    # 1. Holding Period: 21 to 42 sessions (~1 to 2 months).
    # 2. Portfolio Slots: 4 Slots (25% capital each) = ~20 to 35 high-conviction trades/year.
    # 3. Rebalance / Rotation Gate:
    #    - Screen Top RS Acceleration + Volume Asymmetry >= 1.8x + Stage 2 Leader
    #    - Exit: Trail 20-day EMA starting Day 15, or fixed 42-day rotation rebalance!
    # 4. Multi-tier Breadth Gate (>= 50% for full size).
    # 5. Full Indian statutory delivery friction + 6.5% LiquidBees yield on cash.

    from analysis.portfolio_cash_simulator import load_universe_and_breadth, SPLIT_DATE
    indicators, nifty, market_breadth, df_r1m, df_r3m, df_r6m, n_r1m, n_r3m, n_r6m = load_universe_and_breadth()

    # Precalculate Volume Asymmetry 20d
    vol_asym_dict = {}
    for sym, ind in indicators.items():
        v = ind["v"]
        c = ind["c"]
        up_day = (c > c.shift(1)).astype(float)
        up_vol = (v * up_day).rolling(20).sum()
        down_vol = (v * (1.0 - up_day)).rolling(20).sum()
        vol_asym_dict[sym] = up_vol / (down_vol + 1e-9)

    trading_dates = list(nifty.index)
    start_idx = 252
    active_dates = trading_dates[start_idx:]

    for max_hold_days, label in [
        (25, "1-Month Active Rotation (Max 25 Days Hold)"),
        (42, "2-Month Position Rotation (Max 42 Days Hold)"),
        (42, "⭐ 2-Month Hybrid (Trail 20-EMA after Day 15, Max 42d)"),
    ]:
        cash = STARTING_CASH
        max_slots = 4
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

                exit_occurred = False
                exit_px = 0.0
                exit_reason = ""

                # Hard Stop: 7.5%
                if day_o <= pos["stop"]:
                    exit_px = day_o * (1.0 - SLIPPAGE)
                    exit_reason = "stop_gap"
                    exit_occurred = True
                elif day_l <= pos["stop"]:
                    exit_px = pos["stop"] * (1.0 - SLIPPAGE)
                    exit_reason = "stop_loss"
                    exit_occurred = True
                elif "Hybrid" in label and pos["days_held"] >= 15:
                    day_ema20 = ind["ema20"].loc[today]
                    if day_c < day_ema20:
                        exit_px = day_c * (1.0 - SLIPPAGE)
                        exit_reason = "trail_20ema"
                        exit_occurred = True

                if not exit_occurred and pos["days_held"] >= max_hold_days:
                    exit_px = day_c * (1.0 - SLIPPAGE)
                    exit_reason = f"rebalance_{max_hold_days}d"
                    exit_occurred = True

                if exit_occurred:
                    sell_val = pos["shares"] * exit_px
                    friction = (sell_val * 0.001042) + 15.93 + (sell_val * SLIPPAGE)
                    total_friction_inr += friction
                    cash += (sell_val - friction)

                    net_pnl = (sell_val - friction) - (pos["shares"] * pos["entry_price"])
                    net_pnl_pct = (net_pnl / (pos["shares"] * pos["entry_price"])) * 100.0

                    closed_trades.append({
                        "symbol": sym, "days_held": pos["days_held"],
                        "net_pnl_inr": net_pnl, "net_pnl_pct": net_pnl_pct,
                        "exit_reason": exit_reason,
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
                ema20 = ind["ema20"].loc[today]
                ema50 = ind["ema50"].loc[today]
                ema200 = ind["ema200"].loc[today]
                h20 = ind["high20"].loc[today]
                rvol = ind["rvol"].loc[today]

                # Stage 2 + Leader + Volume Asymmetry
                if c_t > ema50 and ema50 > ema200 and c_t > ema200 * 1.15 and c_t > h20 and rvol >= 1.6:
                    asym = vol_asym_dict[sym].get(today, 1.0)
                    if pd.isna(asym) or asym < 1.7: continue

                    r1m = df_r1m.loc[today, sym] if (today in df_r1m.index and sym in df_r1m.columns) else -999.0
                    r3m = df_r3m.loc[today, sym] if (today in df_r3m.index and sym in df_r3m.columns) else -999.0
                    if pd.isna(r1m) or pd.isna(r3m): continue
                    if r1m <= 0: continue

                    # RS Acceleration factor
                    rs_accel = r1m - (r3m / 3.0)
                    composite_score = (0.60 * rs_accel) + (0.40 * r1m)
                    candidates.append((sym, composite_score))

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
                stop_px = entry_fill * 0.925  # 7.5% stop
                risk_inr = current_equity * 0.02  # 2% equity risk
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
        avg_hold = df_tr["days_held"].mean()
        hit_25 = (df_tr["net_pnl_pct"] >= 25.0).sum()
        hit_50 = (df_tr["net_pnl_pct"] >= 50.0).sum()

        print(f"\n📌 {label}:")
        print(f"   • Ending Capital    : ₹{final_equity:,.2f} ({tot_ret:+.2f}% Net Return)")
        print(f"   • 5-Year CAGR       : {cagr:+.2f}% per year")
        print(f"   • Max Drawdown      : {max_dd:.2f}%")
        print(f"   • Annual Cadence    : ~{trades_per_yr:.0f} trades/year (Total: {len(df_tr)} trades)")
        print(f"   • Avg Holding Days  : {avg_hold:.1f} sessions (~{avg_hold/21:.1f} months)")
        print(f"   • Profit Factor     : {pf:.2f} | Win Rate: {(len(wins)/len(df_tr)*100):.1f}%")
        print(f"   • Big Winners       : {hit_25} trades >= +25%, {hit_50} trades >= +50%")
        print(f"   • Friction Paid     : ₹{total_friction_inr:,.2f}")


def main():
    universe, nifty = load_universe_and_benchmarks()
    df_samples = extract_monthly_eda_matrix(universe, nifty)
    run_statistical_eda(df_samples)
    backtest_monthly_engine(universe, nifty)


if __name__ == "__main__":
    main()
