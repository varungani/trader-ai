"""
TraderAI - Quantitative High-Performance Grid Search Engine
================================================================================
Zero-Lookahead, Friction-Accurate, Multi-Core Combinatorial Optimization across 626 NSE Equities.

Architecture:
  1. Pre-computes technical indicators & Market Breadth across 626 stocks (2021-2026).
  2. Extracts ~47,500 trade candidate events with 65-day forward price paths.
  3. Pre-simulates all exit rules across all candidates in parallel using 12 CPU cores.
  4. Generates an immutable PnL matrix P[N_candidates, M_exit_rules].
  5. Slices PnL matrix across all Entry combinations in milliseconds via vectorized NumPy.
  6. Evaluates In-Sample (2021-2024) vs Out-of-Sample (2024-2026) degradation ratios.
  7. Ranks and exports robust parameter combinations surviving out-of-sample stress.
"""
from __future__ import annotations

import os
import sys
import time
import pickle
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Dict, List, Tuple, Any

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SLIPPAGE = 0.0025  # 0.25% per leg
POSITION_SIZE_INR = 50000.0  # ₹50,000 position slice for statutory DP charge calculation
SPLIT_DATE = pd.Timestamp("2024-04-01")


@dataclass
class TradeCandidate:
    """Immutable representation of a trade setup on Day 0 Close."""
    symbol: str
    d0_date: pd.Timestamp
    d1_date: pd.Timestamp
    d0_close: float
    d1_open: float
    d1_gap_pct: float
    atr14: float
    atr_pct: float
    base_low_5d: float
    rvol: float
    rs_percentile: float
    regime_tags: set[str]
    setup_tags: set[str]
    # Forward price paths (Day 1 through Day 65)
    fwd_open: np.ndarray
    fwd_high: np.ndarray
    fwd_low: np.ndarray
    fwd_close: np.ndarray
    fwd_ema20: np.ndarray
    fwd_ema50: np.ndarray


def load_data_and_precalculate() -> Tuple[List[TradeCandidate], pd.DataFrame]:
    """Load universe, benchmark, compute breadth, and extract all trade candidates with forward paths."""
    print("📦 Loading 5Y universe cache and benchmarks...", flush=True)
    cache_path = os.path.join(ROOT, "data", "cache", "universe_5y.pkl")
    bench_path = os.path.join(ROOT, "data", "cache", "benchmarks_5y.pkl")
    
    with open(cache_path, "rb") as f:
        universe: Dict[str, pd.DataFrame] = pickle.load(f)
    with open(bench_path, "rb") as f:
        benchmarks: Dict[str, pd.DataFrame] = pickle.load(f)

    nifty = benchmarks['^NSEI'].copy()
    nifty['EMA50'] = nifty['Close'].ewm(span=50, adjust=False).mean()
    nifty['EMA200'] = nifty['Close'].ewm(span=200, adjust=False).mean()

    print("📊 Computing Market Breadth & Relative Strength matrix across 626 stocks...", flush=True)
    all_dates = nifty.index
    breadth_series = pd.Series(0.0, index=all_dates)
    total_active_series = pd.Series(0, index=all_dates)

    stock_indicators: Dict[str, pd.DataFrame] = {}
    returns_6m: Dict[str, pd.Series] = {}

    for sym, raw_df in universe.items():
        if len(raw_df) < 250:
            continue
        df = raw_df.copy()
        c = df['Close']
        h = df['High']
        l = df['Low']
        v = df['Volume']

        df['EMA20'] = c.ewm(span=20, adjust=False).mean()
        df['EMA50'] = c.ewm(span=50, adjust=False).mean()
        df['EMA200'] = c.ewm(span=200, adjust=False).mean()
        
        # 14-day True Range and ATR
        prev_c = c.shift(1)
        tr = np.maximum(h - l, np.maximum((h - prev_c).abs(), (l - prev_c).abs()))
        df['ATR14'] = tr.rolling(14).mean()
        df['ATR_PCT'] = df['ATR14'] / (c + 1e-9)

        # Volume MA & RVOL
        df['VOL_MA20'] = v.rolling(20).mean()
        df['RVOL'] = v / (df['VOL_MA20'] + 1e-9)

        # Highs / Lows
        df['HIGH_20'] = h.shift(1).rolling(20).max()
        df['HIGH_50'] = h.shift(1).rolling(50).max()
        df['HIGH_252'] = h.shift(1).rolling(252).max()
        df['LOW_5'] = l.shift(1).rolling(5).min()

        # 6-Month (126-day) momentum return for RS percentile
        ret126 = c / c.shift(126) - 1.0
        returns_6m[sym] = ret126

        # Accumulate breadth
        above_50 = (c > df['EMA50']).astype(int)
        breadth_series = breadth_series.add(above_50, fill_value=0)
        total_active_series = total_active_series.add(above_50.notna().astype(int), fill_value=0)

        stock_indicators[sym] = df

    market_breadth_pct = (breadth_series / (total_active_series + 1e-9)) * 100.0

    # Build 6M RS Rank DataFrame
    rs_df = pd.DataFrame(returns_6m)
    rs_percentiles = rs_df.rank(axis=1, pct=True) * 100.0

    print(f"✅ Precalculated technical indicators for {len(stock_indicators)} stocks.", flush=True)
    print("🔍 Extracting all trade candidates with 65-day forward price paths...", flush=True)

    candidates: List[TradeCandidate] = []
    max_fwd_days = 65

    for sym, df in stock_indicators.items():
        n_rows = len(df)
        if n_rows < 260:
            continue
        
        c = df['Close'].values
        h = df['High'].values
        l = df['Low'].values
        o = df['Open'].values
        ema20 = df['EMA20'].values
        ema50 = df['EMA50'].values
        ema200 = df['EMA200'].values
        atr14 = df['ATR14'].values
        atr_pct = df['ATR_PCT'].values
        rvol = df['RVOL'].values
        high20 = df['HIGH_20'].values
        high50 = df['HIGH_50'].values
        high252 = df['HIGH_252'].values
        low5 = df['LOW_5'].values
        dates = df.index

        for i in range(252, n_rows - max_fwd_days - 1):
            d0_close = c[i]
            d1_open = o[i+1]
            d1_gap = (d1_open / d0_close) - 1.0

            # Anti-FOMO: If Day 1 gaps up > +2.5%, abort entry
            if d1_gap > 0.025:
                continue

            # Stage 2 condition: Close > 50 EMA > 200 EMA
            is_stage2 = (d0_close > ema50[i]) and (ema50[i] > ema200[i])
            if not is_stage2:
                continue

            # Setup patterns
            setups = set()
            if d0_close > high20[i]:
                setups.add("breakout_20d")
            if d0_close > high50[i]:
                setups.add("breakout_50d")
            if high252[i] > 0 and (d0_close >= high252[i] * 0.95) and (d0_close > high20[i]):
                setups.add("near_52w")
            
            # 20-EMA Bounce
            if (l[i] <= ema20[i] * 1.015 or l[i-1] <= ema20[i-1] * 1.015) and (d0_close > h[i-1]) and (d0_close > ema20[i]):
                setups.add("ema20_bounce")

            if not setups:
                continue

            d0_date = dates[i]
            d1_date = dates[i+1]

            # Regime tags
            regimes = {"none"}
            if d0_date in nifty.index:
                n_c = nifty.loc[d0_date, 'Close']
                if n_c > nifty.loc[d0_date, 'EMA50']:
                    regimes.add("nifty_gt_50ema")
                if n_c > nifty.loc[d0_date, 'EMA200']:
                    regimes.add("nifty_gt_200ema")
            
            mb = market_breadth_pct.get(d0_date, 50.0)
            if mb >= 50.0:
                regimes.add("breadth_gt_50")
            if mb >= 55.0:
                regimes.add("breadth_gt_55")

            # RS Percentile
            rs_val = rs_percentiles.loc[d0_date, sym] if (d0_date in rs_percentiles.index and sym in rs_percentiles.columns) else 50.0
            if np.isnan(rs_val):
                rs_val = 50.0

            fwd_idx = slice(i+1, i+1+max_fwd_days)
            cand = TradeCandidate(
                symbol=sym,
                d0_date=d0_date,
                d1_date=d1_date,
                d0_close=float(d0_close),
                d1_open=float(d1_open),
                d1_gap_pct=float(d1_gap),
                atr14=float(atr14[i]),
                atr_pct=float(atr_pct[i]),
                base_low_5d=float(low5[i]),
                rvol=float(rvol[i]),
                rs_percentile=float(rs_val),
                regime_tags=regimes,
                setup_tags=setups,
                fwd_open=o[fwd_idx],
                fwd_high=h[fwd_idx],
                fwd_low=l[fwd_idx],
                fwd_close=c[fwd_idx],
                fwd_ema20=ema20[fwd_idx],
                fwd_ema50=ema50[fwd_idx],
            )
            candidates.append(cand)

    print(f"🚀 Extracted {len(candidates):,} total trade candidate events across 2021-2026.", flush=True)
    return candidates, nifty


def simulate_trade_fast(
    cand: TradeCandidate,
    stop_rule: str,
    harvest_rule: str,
    trail_rule: str,
    time_stop_rule: str,
) -> float:
    """
    Simulates a single trade with high fidelity:
    - Entry at Day 1 Open * (1 + SLIPPAGE).
    - Checks stops, partial profit, trailing stops, and time limits day-by-day.
    - Applies Indian delivery charges (STT, DP, GST, stamp duty, slippage).
    Returns: net_pnl_pct
    """
    entry_px = cand.d1_open * (1.0 + SLIPPAGE)
    
    # 1. Determine Initial Stop Price
    if stop_rule == "fixed_4pct":
        stop_px = entry_px * 0.96
    elif stop_rule == "fixed_6pct":
        stop_px = entry_px * 0.94
    elif stop_rule == "fixed_8pct":
        stop_px = entry_px * 0.92
    elif stop_rule == "fixed_10pct":
        stop_px = entry_px * 0.90
    elif stop_rule == "atr_1.5":
        stop_px = entry_px - (1.5 * cand.atr14)
    elif stop_rule == "atr_2.0":
        stop_px = entry_px - (2.0 * cand.atr14)
    elif stop_rule == "atr_2.5":
        stop_px = entry_px - (2.5 * cand.atr14)
    elif stop_rule == "base_low_5d":
        stop_px = min(cand.base_low_5d, entry_px * 0.98)
    else:
        stop_px = entry_px * 0.94

    stop_px = max(stop_px, entry_px * 0.88)

    # 2. Determine Partial Harvest Target Price (T1)
    t1_px = 0.0
    if harvest_rule == "t1_5pct_be":
        t1_px = entry_px * 1.05
    elif harvest_rule == "t1_8pct_be":
        t1_px = entry_px * 1.08
    elif harvest_rule == "t1_2r_be":
        t1_px = entry_px + (2.0 * (entry_px - stop_px))

    # 3. Determine Fixed Target (if applicable)
    final_target_px = 0.0
    if trail_rule == "fixed_15pct":
        final_target_px = entry_px * 1.15
    elif trail_rule == "fixed_25pct":
        final_target_px = entry_px * 1.25

    position_pct = 1.0
    t1_hit = False
    realized_val = 0.0
    n_legs = 0
    cur_stop_px = stop_px
    highest_close = entry_px

    n_days = len(cand.fwd_open)

    for day_idx in range(n_days):
        day_open = cand.fwd_open[day_idx]
        day_high = cand.fwd_high[day_idx]
        day_low = cand.fwd_low[day_idx]
        day_close = cand.fwd_close[day_idx]
        holding_days = day_idx + 1

        if day_close > highest_close:
            highest_close = day_close

        if trail_rule == "chandelier_2.5atr":
            chandelier_stop = highest_close - (2.5 * cand.atr14)
            if chandelier_stop > cur_stop_px:
                cur_stop_px = chandelier_stop

        # A. Stop Loss Hit
        if day_open <= cur_stop_px:
            exit_px = day_open * (1.0 - SLIPPAGE)
            realized_val += position_pct * exit_px
            n_legs += 1
            return _calc_net_pnl_fast(entry_px, realized_val, n_legs)

        if day_low <= cur_stop_px:
            exit_px = cur_stop_px * (1.0 - SLIPPAGE)
            realized_val += position_pct * exit_px
            n_legs += 1
            return _calc_net_pnl_fast(entry_px, realized_val, n_legs)

        # B. Partial Profit Taking (T1)
        if t1_px > 0 and not t1_hit and position_pct == 1.0:
            if day_high >= t1_px:
                exit_px = t1_px * (1.0 - SLIPPAGE)
                realized_val += 0.5 * exit_px
                position_pct = 0.5
                n_legs += 1
                t1_hit = True
                be_stop = entry_px * 1.006
                if be_stop > cur_stop_px:
                    cur_stop_px = be_stop

        # C. Fixed Profit Target
        if final_target_px > 0 and day_high >= final_target_px:
            exit_px = final_target_px * (1.0 - SLIPPAGE)
            realized_val += position_pct * exit_px
            n_legs += 1
            return _calc_net_pnl_fast(entry_px, realized_val, n_legs)

        # D. Trailing Exit
        if day_idx >= 1:
            if trail_rule == "trail_20ema" and day_close < cand.fwd_ema20[day_idx]:
                exit_px = day_close * (1.0 - SLIPPAGE)
                realized_val += position_pct * exit_px
                n_legs += 1
                return _calc_net_pnl_fast(entry_px, realized_val, n_legs)

            if trail_rule == "trail_50ema" and day_close < cand.fwd_ema50[day_idx]:
                exit_px = day_close * (1.0 - SLIPPAGE)
                realized_val += position_pct * exit_px
                n_legs += 1
                return _calc_net_pnl_fast(entry_px, realized_val, n_legs)

        # E. Time Stop
        cur_pnl_pct = (day_close / entry_px) - 1.0
        if time_stop_rule == "kill_5d_stagnant" and holding_days >= 5 and cur_pnl_pct < 0.015:
            exit_px = day_close * (1.0 - SLIPPAGE)
            realized_val += position_pct * exit_px
            n_legs += 1
            return _calc_net_pnl_fast(entry_px, realized_val, n_legs)

        if time_stop_rule == "kill_10d_stagnant" and holding_days >= 10 and cur_pnl_pct < 0.020:
            exit_px = day_close * (1.0 - SLIPPAGE)
            realized_val += position_pct * exit_px
            n_legs += 1
            return _calc_net_pnl_fast(entry_px, realized_val, n_legs)

        if time_stop_rule == "max_30d" and holding_days >= 30:
            exit_px = day_close * (1.0 - SLIPPAGE)
            realized_val += position_pct * exit_px
            n_legs += 1
            return _calc_net_pnl_fast(entry_px, realized_val, n_legs)

        if time_stop_rule == "max_60d" and holding_days >= 60:
            exit_px = day_close * (1.0 - SLIPPAGE)
            realized_val += position_pct * exit_px
            n_legs += 1
            return _calc_net_pnl_fast(entry_px, realized_val, n_legs)

    # Max window reached
    exit_px = cand.fwd_close[-1] * (1.0 - SLIPPAGE)
    realized_val += position_pct * exit_px
    n_legs += 1
    return _calc_net_pnl_fast(entry_px, realized_val, n_legs)


def _calc_net_pnl_fast(entry_px: float, total_exit_value: float, n_legs: int) -> float:
    """Computes net return % deducting statutory Indian CNC delivery friction and DP charges."""
    gross_return = (total_exit_value / entry_px) - 1.0
    # Statutory Delivery Friction:
    # Buy: STT 0.10%, Stamp Duty 0.015%, Exch+SEBI+GST 0.0042% = 0.1192%
    # Sell: STT 0.10%, Exch+SEBI+GST 0.0042% = 0.1042%
    # DP charges: ₹15.93 flat per sell leg on ₹50k slice = 0.03186% per leg
    # Slippage: 0.25% buy + 0.25% sell = 0.50%
    buy_friction = 0.001192 + SLIPPAGE
    sell_friction = (0.001042 + SLIPPAGE) + ((15.93 * n_legs) / POSITION_SIZE_INR)
    total_friction = buy_friction + sell_friction
    return (gross_return - total_friction) * 100.0


def _worker_simulate_chunk(args: Tuple[List[TradeCandidate], List[Tuple[str, str, str, str]]]) -> np.ndarray:
    """Worker function for ProcessPoolExecutor: simulates a chunk of candidates across all exit rules."""
    chunk, exit_rules = args
    n_cands = len(chunk)
    n_rules = len(exit_rules)
    out = np.empty((n_cands, n_rules), dtype=np.float32)

    for i in range(n_cands):
        cand = chunk[i]
        for j in range(n_rules):
            out[i, j] = simulate_trade_fast(cand, exit_rules[j][0], exit_rules[j][1], exit_rules[j][2], exit_rules[j][3])

    return out


def build_parallel_pnl_matrix(
    candidates: List[TradeCandidate],
    exit_rules: List[Tuple[str, str, str, str]],
) -> np.ndarray:
    """Distributes candidates across all available CPU cores to compute the full PnL matrix."""
    n_workers = min(os.cpu_count() or 4, 12)
    n_cands = len(candidates)
    chunk_size = int(np.ceil(n_cands / n_workers))
    print(f"⚡ Simulating {n_cands:,} candidates x {len(exit_rules)} exit rules ({n_cands * len(exit_rules):,} trades) across {n_workers} CPU cores...", flush=True)
    t0 = time.time()

    chunks = []
    for w in range(n_workers):
        start = w * chunk_size
        end = min((w + 1) * chunk_size, n_cands)
        if start < end:
            chunks.append((candidates[start:end], exit_rules))

    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        matrix_blocks = list(executor.map(_worker_simulate_chunk, chunks))

    pnl_matrix = np.vstack(matrix_blocks)
    elapsed = time.time() - t0
    print(f"✅ Parallel PnL Matrix computed in {elapsed:.2f}s ({pnl_matrix.shape[0]:,} candidates x {pnl_matrix.shape[1]} rules).", flush=True)
    return pnl_matrix


def run_matrix_grid_search(
    candidates: List[TradeCandidate],
    grid_params: Dict[str, List[str]],
    min_trades: int = 40,
) -> pd.DataFrame:
    """Slices the precomputed PnL matrix across all entry filter combinations."""
    regimes = grid_params.get("regime", ["none"])
    setups = grid_params.get("setup", ["breakout_20d"])
    rvols = grid_params.get("rvol", ["rvol_1.3"])
    rss = grid_params.get("rs", ["rs_all"])
    stops = grid_params.get("stop", ["fixed_6pct"])
    harvests = grid_params.get("harvest", ["t1_5pct_be"])
    trails = grid_params.get("trail", ["trail_20ema"])
    time_stops = grid_params.get("time_stop", ["max_60d"])

    # Create exit rules list
    exit_rules: List[Tuple[str, str, str, str]] = []
    exit_rule_map: Dict[Tuple[str, str, str, str], int] = {}
    for stp in stops:
        for hrv in harvests:
            for trl in trails:
                for tm in time_stops:
                    rule = (stp, hrv, trl, tm)
                    exit_rule_map[rule] = len(exit_rules)
                    exit_rules.append(rule)

    # Compute full PnL Matrix in parallel
    pnl_matrix = build_parallel_pnl_matrix(candidates, exit_rules)

    print("🔍 Pre-indexing candidate attributes for vectorized entry slicing...", flush=True)
    is_split = np.array([c.d0_date < SPLIT_DATE for c in candidates], dtype=bool)
    oos_split = ~is_split

    regime_masks = {reg: np.array([reg in c.regime_tags for c in candidates], dtype=bool) for reg in regimes}
    setup_masks = {setp: np.array([setp in c.setup_tags for c in candidates], dtype=bool) for setp in setups}
    rvol_arr = np.array([c.rvol for c in candidates], dtype=np.float32)
    rs_arr = np.array([c.rs_percentile for c in candidates], dtype=np.float32)

    total_entry_combos = len(regimes) * len(setups) * len(rvols) * len(rss)
    total_evals = total_entry_combos * len(exit_rules)
    print(f"📊 Evaluating {total_evals:,} parameter combinations ({total_entry_combos} entry filters x {len(exit_rules)} exit rules)...", flush=True)
    
    t0 = time.time()
    results = []

    for reg in regimes:
        m_reg = regime_masks[reg]
        for setp in setups:
            m_setp = setup_masks[setp]
            for rv in rvols:
                min_rv = float(rv.split("_")[1])
                m_rv = rvol_arr >= min_rv
                for rs_f in rss:
                    min_rs = 0.0 if rs_f == "rs_all" else float(rs_f.split("_")[1])
                    m_rs = rs_arr >= min_rs

                    # Compound entry mask
                    entry_mask = m_reg & m_setp & m_rv & m_rs
                    is_mask = is_split & entry_mask
                    oos_mask = oos_split & entry_mask

                    n_is = int(np.sum(is_mask))
                    n_oos = int(np.sum(oos_mask))

                    if n_is < min_trades:
                        continue

                    # Slice PnL columns for this entry filter
                    is_sub = pnl_matrix[is_mask, :]
                    oos_sub = pnl_matrix[oos_mask, :]

                    for rule_idx, (stp, hrv, trl, tm) in enumerate(exit_rules):
                        col_is = is_sub[:, rule_idx]
                        col_oos = oos_sub[:, rule_idx]

                        # In-Sample stats
                        is_wins = col_is[col_is > 0]
                        is_losses = col_is[col_is <= 0]
                        is_winrate = (len(is_wins) / n_is) * 100.0
                        is_mean_pnl = float(np.mean(col_is))
                        is_gp = float(np.sum(is_wins)) if len(is_wins) > 0 else 0.0
                        is_gl = abs(float(np.sum(is_losses))) if len(is_losses) > 0 else 1e-9
                        is_pf = is_gp / is_gl
                        is_exp = (is_winrate/100.0 * (float(np.mean(is_wins)) if len(is_wins) else 0.0)) - \
                                 ((1.0 - is_winrate/100.0) * (abs(float(np.mean(is_losses))) if len(is_losses) else 0.0))

                        # Out-of-Sample stats
                        if n_oos >= 15:
                            oos_wins = col_oos[col_oos > 0]
                            oos_losses = col_oos[col_oos <= 0]
                            oos_winrate = (len(oos_wins) / n_oos) * 100.0
                            oos_mean_pnl = float(np.mean(col_oos))
                            oos_gp = float(np.sum(oos_wins)) if len(oos_wins) > 0 else 0.0
                            oos_gl = abs(float(np.sum(oos_losses))) if len(oos_losses) > 0 else 1e-9
                            oos_pf = oos_gp / oos_gl
                            oos_exp = (oos_winrate/100.0 * (float(np.mean(oos_wins)) if len(oos_wins) else 0.0)) - \
                                      ((1.0 - oos_winrate/100.0) * (abs(float(np.mean(oos_losses))) if len(oos_losses) else 0.0))
                            deg_ratio = oos_exp / (is_exp + 1e-9)
                        else:
                            oos_winrate = oos_mean_pnl = oos_pf = oos_exp = deg_ratio = 0.0

                        results.append({
                            "regime": reg,
                            "setup": setp,
                            "rvol": rv,
                            "rs": rs_f,
                            "stop": stp,
                            "harvest": hrv,
                            "trail": trl,
                            "time_stop": tm,
                            "is_trades": n_is,
                            "is_winrate": round(is_winrate, 1),
                            "is_mean_pnl": round(is_mean_pnl, 2),
                            "is_pf": round(is_pf, 2),
                            "is_expectancy": round(is_exp, 2),
                            "oos_trades": n_oos,
                            "oos_winrate": round(oos_winrate, 1),
                            "oos_mean_pnl": round(oos_mean_pnl, 2),
                            "oos_pf": round(oos_pf, 2),
                            "oos_expectancy": round(oos_exp, 2),
                            "degradation_ratio": round(deg_ratio, 2),
                        })

    elapsed = time.time() - t0
    df_res = pd.DataFrame(results)
    print(f"🏁 Combinatorial matrix sweep finished in {elapsed:.2f}s. Evaluated {len(df_res):,} viable strategies.", flush=True)
    return df_res


def main():
    parser = argparse.ArgumentParser(description="TraderAI Quantitative Multi-Core Grid Search")
    parser.add_argument("--mode", type=str, default="focused", choices=["focused", "deep"], help="Grid size: focused (~7.7k) or deep (~92k)")
    parser.add_argument("--top", type=int, default=30, help="Number of top strategies to display")
    parser.add_argument("--output", type=str, default="data/analytics/grid_search_results.csv", help="Output CSV path")
    args = parser.parse_args()

    candidates, nifty = load_data_and_precalculate()

    if args.mode == "focused":
        grid_matrix = {
            "regime": ["none", "nifty_gt_50ema", "breadth_gt_50"],
            "setup": ["breakout_20d", "breakout_50d", "ema20_bounce"],
            "rvol": ["rvol_1.0", "rvol_1.3", "rvol_1.7"],
            "rs": ["rs_all", "rs_75"],
            "stop": ["fixed_4pct", "fixed_6pct", "fixed_8pct", "atr_2.0"],
            "harvest": ["none", "t1_5pct_be", "t1_8pct_be"],
            "trail": ["fixed_15pct", "trail_20ema", "trail_50ema", "chandelier_2.5atr"],
            "time_stop": ["none", "kill_5d_stagnant", "max_60d"],
        }
    else:
        grid_matrix = {
            "regime": ["none", "nifty_gt_50ema", "breadth_gt_50", "breadth_gt_55"],
            "setup": ["breakout_20d", "breakout_50d", "near_52w", "ema20_bounce"],
            "rvol": ["rvol_1.0", "rvol_1.3", "rvol_1.7", "rvol_2.2"],
            "rs": ["rs_all", "rs_70", "rs_85"],
            "stop": ["fixed_4pct", "fixed_6pct", "fixed_8pct", "atr_1.5", "atr_2.0", "base_low_5d"],
            "harvest": ["none", "t1_5pct_be", "t1_8pct_be", "t1_2r_be"],
            "trail": ["fixed_15pct", "fixed_25pct", "trail_20ema", "trail_50ema", "chandelier_2.5atr"],
            "time_stop": ["none", "kill_5d_stagnant", "max_30d", "max_60d"],
        }

    df_results = run_matrix_grid_search(candidates, grid_matrix, min_trades=40)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    df_results.to_csv(args.output, index=False)
    print(f"💾 Full results saved to {args.output}", flush=True)

    # Robustness filter:
    robust = df_results[
        (df_results["is_expectancy"] >= 1.5) &
        (df_results["oos_expectancy"] >= 1.2) &
        (df_results["oos_pf"] >= 1.35) &
        (df_results["degradation_ratio"] >= 0.55) &
        (df_results["is_trades"] >= 50) &
        (df_results["oos_trades"] >= 30)
    ].sort_values(by="oos_expectancy", ascending=False)

    print("\n" + "="*95, flush=True)
    print("🏆 TOP ROBUST STRATEGIES SURVIVING OUT-OF-SAMPLE VALIDATION (2024-2026)", flush=True)
    print("="*95, flush=True)
    top_cols = [
        "regime", "setup", "rvol", "rs", "stop", "harvest", "trail", "time_stop",
        "is_trades", "is_pf", "is_expectancy", "oos_trades", "oos_pf", "oos_expectancy", "degradation_ratio"
    ]
    if len(robust) > 0:
        print(robust[top_cols].head(args.top).to_string(index=False), flush=True)
    else:
        print("No combination met strict robustness criteria. Showing top by OOS Expectancy:", flush=True)
        print(df_results.sort_values(by="oos_expectancy", ascending=False)[top_cols].head(args.top).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
