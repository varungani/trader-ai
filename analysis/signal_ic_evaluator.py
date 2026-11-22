"""
TraderAI — Quantitative Signal Information Coefficient (IC) & Monotonicity Evaluator
Evaluates raw signal predictive power independent of execution rules:
  1. Spearman Rank IC across rolling cross-sections (3-day & 5-day horizons).
  2. Information Ratio (IR) and t-statistic across evaluation dates.
  3. Quintile Return Ladder: Tests whether higher signal scores produce higher forward returns.
"""
from __future__ import annotations

import os
import sys
import pickle
import numpy as np
import pandas as pd
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from analysis.technical import compute_technical_score

CACHE_FILE = os.path.join(ROOT, "data", "cache", "high_beta_universe.pkl")


def load_universe_data() -> dict[str, pd.DataFrame]:
    """Load high-beta universe historical daily OHLCV DataFrames from disk cache."""
    if not os.path.exists(CACHE_FILE):
        raise FileNotFoundError(f"Cache file not found at {CACHE_FILE}")

    with open(CACHE_FILE, "rb") as f:
        data = pickle.load(f)

    clean_data = {}
    for ticker, df in data.items():
        if df is None or len(df) < 120:
            continue
        clean = pd.DataFrame(index=df.index)
        for col in ["open", "high", "low", "close", "volume"]:
            s_upper = df[col.title()] if col.title() in df.columns else pd.Series(dtype=float, index=df.index)
            s_lower = df[col.lower()] if col.lower() in df.columns else pd.Series(dtype=float, index=df.index)
            clean[col.title()] = s_upper.fillna(s_lower)
        clean = clean.dropna()
        clean = clean[~clean.index.duplicated(keep="first")].sort_index()
        if len(clean) >= 120:
            clean_data[ticker] = clean

    return clean_data


def run_signal_ic_audit(
    sample_stride: int = 5,
    eval_bars: int = 120,
    min_stocks_per_date: int = 15,
) -> dict:
    """
    Computes cross-sectional Rank IC and Quintile Monotonicity over the past `eval_bars` sessions.
    
    Args:
        sample_stride: Evaluate every N trading days (default 5 = weekly cross-sections).
        eval_bars: Number of recent trading sessions to backtest (default 120 bars = ~6 months).
        min_stocks_per_date: Minimum valid stock scores required on a date to compute IC.
    """
    universe = load_universe_data()
    print(f"Loaded {len(universe)} valid stocks with historical OHLCV depth.")

    # Find the common date index across the universe
    all_dates = sorted(list(set.intersection(*[set(df.index) for df in universe.values()])))
    if len(all_dates) < eval_bars:
        # Fall back to union if intersection is sparse
        all_dates = sorted(list(set.union(*[set(df.index) for df in universe.values()])))
    
    test_dates = all_dates[-eval_bars:-6]  # Leave 5 bars for forward return measurement
    eval_dates = test_dates[::sample_stride]
    print(f"Evaluating signal quality across {len(eval_dates)} cross-sectional dates (stride={sample_stride})...\n")

    ic_3d_records = []
    ic_5d_records = []
    quintile_records = []

    for dt in eval_dates:
        scores = []
        ret_3d = []
        ret_5d = []

        for ticker, df in universe.items():
            if dt not in df.index:
                continue
            idx = df.index.get_loc(dt)
            if idx < 60 or idx + 5 >= len(df):
                continue

            # Historical slice up to date dt (zero lookahead!)
            hist_slice = df.iloc[:idx + 1]
            try:
                score_dict = compute_technical_score(hist_slice, ticker=ticker)
                raw_score = float(score_dict.get("score", 50.0))
            except Exception:
                continue

            # Forward returns
            c_now = float(df["Close"].iloc[idx])
            c_3d = float(df["Close"].iloc[idx + 3])
            c_5d = float(df["Close"].iloc[idx + 5])

            if c_now <= 0:
                continue

            r3 = ((c_3d - c_now) / c_now) * 100.0
            r5 = ((c_5d - c_now) / c_now) * 100.0

            scores.append(raw_score)
            ret_3d.append(r3)
            ret_5d.append(r5)
            quintile_records.append({"date": dt, "ticker": ticker, "score": raw_score, "ret_3d": r3, "ret_5d": r5})

        if len(scores) >= min_stocks_per_date:
            s_series = pd.Series(scores)
            r3_series = pd.Series(ret_3d)
            r5_series = pd.Series(ret_5d)

            # Spearman Rank Correlation = Pearson correlation of ranks
            rank_ic_3d = s_series.rank().corr(r3_series.rank())
            rank_ic_5d = s_series.rank().corr(r5_series.rank())

            if not np.isnan(rank_ic_3d):
                ic_3d_records.append(rank_ic_3d)
            if not np.isnan(rank_ic_5d):
                ic_5d_records.append(rank_ic_5d)

    # 1. Information Coefficient Statistics
    ic3 = np.array(ic_3d_records)
    ic5 = np.array(ic_5d_records)

    mean_ic3 = float(np.mean(ic3)) if len(ic3) > 0 else 0.0
    std_ic3 = float(np.std(ic3)) if len(ic3) > 0 else 1.0
    ir3 = mean_ic3 / std_ic3 if std_ic3 > 0 else 0.0
    t_stat3 = ir3 * np.sqrt(len(ic3)) if len(ic3) > 0 else 0.0

    mean_ic5 = float(np.mean(ic5)) if len(ic5) > 0 else 0.0
    std_ic5 = float(np.std(ic5)) if len(ic5) > 0 else 1.0
    ir5 = mean_ic5 / std_ic5 if std_ic5 > 0 else 0.0
    t_stat5 = ir5 * np.sqrt(len(ic5)) if len(ic5) > 0 else 0.0

    # 2. Monotonicity Decile / Quintile Breakdown
    df_all = pd.DataFrame(quintile_records)
    quintile_summary = {}
    if not df_all.empty:
        df_all["quintile"] = pd.qcut(df_all["score"], q=5, labels=["Q1 (Lowest)", "Q2", "Q3", "Q4", "Q5 (Top Apex)"])
        grp = df_all.groupby("quintile", observed=False)
        quintile_summary = {
            "avg_score": grp["score"].mean().to_dict(),
            "avg_ret_3d": grp["ret_3d"].mean().to_dict(),
            "avg_ret_5d": grp["ret_5d"].mean().to_dict(),
            "count": grp["score"].count().to_dict(),
        }

    return {
        "dates_evaluated": len(ic3),
        "total_observations": len(quintile_records),
        "horizon_3d": {
            "mean_ic": round(mean_ic3, 4),
            "std_ic": round(std_ic3, 4),
            "information_ratio": round(ir3, 3),
            "t_statistic": round(t_stat3, 2),
            "pct_positive_dates": round(float(np.mean(ic3 > 0) * 100.0), 1) if len(ic3) > 0 else 0.0,
        },
        "horizon_5d": {
            "mean_ic": round(mean_ic5, 4),
            "std_ic": round(std_ic5, 4),
            "information_ratio": round(ir5, 3),
            "t_statistic": round(t_stat5, 2),
            "pct_positive_dates": round(float(np.mean(ic5 > 0) * 100.0), 1) if len(ic5) > 0 else 0.0,
        },
        "quintiles": quintile_summary,
    }


if __name__ == "__main__":
    results = run_signal_ic_audit(sample_stride=3, eval_bars=150)
    print("=" * 70)
    print("📊 SIGNAL QUALITY (INFORMATION COEFFICIENT & MONOTONICITY AUDIT)")
    print("=" * 70)
    print(f"Total Stock Observations : {results['total_observations']}")
    print(f"Cross-Sectional Dates     : {results['dates_evaluated']}")
    print("-" * 70)
    h3 = results["horizon_3d"]
    print(f"3-Day Forward Horizon:")
    print(f"  • Mean Rank IC         : {h3['mean_ic']:+.4f} (Benchmark: > +0.03 is significant)")
    print(f"  • Information Ratio (IR): {h3['information_ratio']:.3f}")
    print(f"  • t-statistic          : {h3['t_statistic']:.2f} {'(Statistically Significant)' if abs(h3['t_statistic']) >= 2.0 else '(Indistinguishable from Zero)'}")
    print(f"  • % Positive Dates     : {h3['pct_positive_dates']:.1f}%")
    print("-" * 70)
    h5 = results["horizon_5d"]
    print(f"5-Day Forward Horizon:")
    print(f"  • Mean Rank IC         : {h5['mean_ic']:+.4f}")
    print(f"  • Information Ratio (IR): {h5['information_ratio']:.3f}")
    print(f"  • t-statistic          : {h5['t_statistic']:.2f} {'(Statistically Significant)' if abs(h5['t_statistic']) >= 2.0 else '(Indistinguishable from Zero)'}")
    print(f"  • % Positive Dates     : {h5['pct_positive_dates']:.1f}%")
    print("=" * 70)
    print("📈 QUINTILE LADDER (Tests Monotonicity: Does Higher Score = Higher Return?)")
    print("=" * 70)
    q = results.get("quintiles", {})
    if q:
        for q_name in q["avg_score"].keys():
            sc = q["avg_score"][q_name]
            r3 = q["avg_ret_3d"][q_name]
            r5 = q["avg_ret_5d"][q_name]
            cnt = q["count"][q_name]
            print(f"{q_name:<16} | Avg Score: {sc:5.1f} | 3-Day Return: {r3:+6.2f}% | 5-Day Return: {r5:+6.2f}% | (N={cnt})")
    print("=" * 70)
