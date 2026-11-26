"""
TraderAI - Broad NSE universe + cheap pre-screener
Not limited to Nifty 50 — scans large / mid / liquid names, then deep-scores top hits.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional

import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import NIFTY50_STOCKS, NIFTY_NEXT50_STOCKS, MIDCAP_LIQUID_STOCKS, HIGH_VELOCITY_STOCKS, UNIVERSE_PRESETS

logger = logging.getLogger(__name__)


def get_universe(preset: str = "nifty500") -> list[str]:
    """
    preset: nifty500 | nifty50 | nifty100 | midcap | high_velocity | extended | all
    """
    preset = (preset or "nifty500").lower()
    if preset in UNIVERSE_PRESETS:
        names = UNIVERSE_PRESETS[preset]
    elif preset in ("high_beta_rockets", "high_velocity", "monster", "runners"):
        names = list(HIGH_VELOCITY_STOCKS)
    elif preset == "nifty50":
        names = list(NIFTY50_STOCKS)
    elif preset == "nifty100":
        names = list(dict.fromkeys(NIFTY50_STOCKS + NIFTY_NEXT50_STOCKS))
    elif preset == "midcap":
        names = list(MIDCAP_LIQUID_STOCKS)
    elif preset == "all":
        names = list(dict.fromkeys(NIFTY50_STOCKS + NIFTY_NEXT50_STOCKS + MIDCAP_LIQUID_STOCKS + HIGH_VELOCITY_STOCKS))
    else:
        names = list(dict.fromkeys(NIFTY50_STOCKS + NIFTY_NEXT50_STOCKS + MIDCAP_LIQUID_STOCKS + HIGH_VELOCITY_STOCKS))

    # Optional user override file: data/custom_universe.txt (one ticker per line)
    custom_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "custom_universe.txt")
    if os.path.exists(custom_path):
        with open(custom_path, "r", encoding="utf-8") as f:
            extra = []
            for line in f:
                t = line.strip().upper()
                if not t or t.startswith("#"):
                    continue
                if not t.endswith(".NS") and not t.endswith(".BO"):
                    t = f"{t}.NS"
                extra.append(t)
            names = list(dict.fromkeys(names + extra))

    return names


def pre_screen(
    tickers: list[str],
    top_n: int = 25,
    period: str = "6mo",
    min_price: float = 10.0,
    min_avg_value_cr: float = 2.0,
    return_all: bool = False,
) -> list[dict]:
    """
    Fast batch screen using yfinance download with high-resolution cache fallback.

    Computes empirical 5Y EDA predictors across every liquid stock:
      - 1M / 3M / 6M returns & Composite RS (0.50*1M + 0.30*3M + 0.20*6M)
      - 20-Day Volume Asymmetry (Up-Vol / Down-Vol >= 2.0x)
      - Close Location Value (CLV >= 0.65) & RVOL
      - Distance above 200-EMA, Stage-2 status, & 50-Day High breakout status
      - Stores universe breadth (% > 50-EMA) on pre_screen.last_breadth_pct
    """
    if not tickers:
        pre_screen.last_breadth_pct = 50.0
        return []

    logger.info(f"Pre-screening {len(tickers)} tickers (top_n={top_n})")
    # Ensure >= 1y history when 6mo requested if needed for 200-EMA, using cache fallback if shorter
    fetch_period = "1y" if period == "6mo" else period
    data = pd.DataFrame()
    try:
        data = yf.download(
            tickers,
            period=fetch_period,
            group_by="ticker",
            progress=False,
            threads=True,
        )
    except Exception as e:
        logger.debug(f"Batch download failed: {e}, falling back to cache")

    from data.market_data import _get_cached_history, fetch_stock_history

    nifty_df = fetch_stock_history("^NSEI", period="1y", force_live=True)
    if nifty_df.empty:
        nifty_df = _get_cached_history("^NSEI", period="1y")
    nifty_ret_1m = 0.0
    if not nifty_df.empty and "Close" in nifty_df.columns and len(nifty_df) >= 22:
        n_c = nifty_df["Close"].dropna()
        nifty_ret_1m = float(n_c.iloc[-1] / n_c.iloc[-22] - 1)

    rows = []
    breadth_above_50 = 0
    breadth_total = 0
    multi = isinstance(data.columns, pd.MultiIndex) if not data.empty else False

    for ticker in tickers:
        try:
            df = pd.DataFrame()
            if not data.empty:
                if multi:
                    if ticker in data.columns.get_level_values(0):
                        df = data[ticker].dropna(how="all")
                else:
                    df = data.dropna(how="all")

            # Fallback to local cache if batch fetch is missing data for this ticker
            if df.empty or len(df) < 30 or "Close" not in df.columns:
                df = _get_cached_history(ticker, period=fetch_period)

            if df.empty or len(df) < 30 or "Close" not in df.columns:
                continue

            close = df["Close"].dropna()
            vol = df["Volume"].dropna() if "Volume" in df.columns else pd.Series(dtype=float)
            if len(close) < 30:
                continue

            price = float(close.iloc[-1])
            if price < min_price:
                continue

            ret_1m = float(close.iloc[-1] / close.iloc[-22] - 1) if len(close) >= 22 else 0.0
            ret_3m = float(close.iloc[-1] / close.iloc[-64] - 1) if len(close) >= 64 else ret_1m
            ret_6m = float(close.iloc[-1] / close.iloc[-127] - 1) if len(close) >= 127 else ret_3m
            composite_rs = round(((0.50 * ret_1m) + (0.30 * ret_3m) + (0.20 * ret_6m)) * 100.0, 2)

            high_6m = float(close.tail(126).max()) if len(close) >= 20 else float(close.max())
            low_6m = float(close.tail(126).min()) if len(close) >= 20 else float(close.min())
            span = high_6m - low_6m
            pos = (price - low_6m) / span if span > 0 else 0.5

            daily_ret = close.pct_change().dropna().tail(20)
            vol_ann = float(daily_ret.std() * (252 ** 0.5)) if len(daily_ret) else 0.2

            avg_vol = float(vol.tail(20).mean()) if len(vol) >= 5 else 0.0
            avg_value_cr = (avg_vol * price) / 1e7  # crore INR
            if avg_value_cr < min_avg_value_cr:
                continue

            # Calculate RVOL and 20-Day Volume Asymmetry (Up-Vol / Down-Vol)
            latest_vol = float(vol.iloc[-1]) if len(vol) else 0.0
            rvol = round(latest_vol / avg_vol, 2) if avg_vol > 0 else 1.0
            if len(close) >= 21 and len(vol) >= 21:
                c_tail = close.tail(21)
                v_tail = vol.reindex(c_tail.index).fillna(0.0)
                up_mask = (c_tail > c_tail.shift(1)).astype(float)
                up_vol = float((v_tail * up_mask).tail(20).sum())
                dn_vol = float((v_tail * (1.0 - up_mask)).tail(20).sum())
                vol_asym_20 = round(up_vol / (dn_vol + 1e-9), 2)
            else:
                vol_asym_20 = 1.0

            # RVOL Score: Institutional accumulation check
            if rvol >= 2.0:
                rvol_score = 100.0  # Heavy institutional volume breakout
            elif rvol >= 1.5:
                rvol_score = 85.0   # Strong volume surge
            elif rvol >= 1.0:
                rvol_score = 65.0   # Normal volume
            elif rvol >= 0.7:
                rvol_score = 45.0   # Subdued volume
            else:
                rvol_score = 30.0   # Dry volume / lack of conviction

            # Pattern Detection: Minervini VCP & 50D High Breakout & 20 EMA Sweet Spot
            high = df["High"].dropna() if "High" in df.columns else close
            low = df["Low"].dropna() if "Low" in df.columns else close
            high_5d = float(high.tail(5).max()) if len(high) >= 5 else float(high.max())
            low_5d = float(low.tail(5).min()) if len(low) >= 5 else float(low.min())
            high_20d = float(high.tail(20).max()) if len(high) >= 20 else float(high.max())
            low_20d = float(low.tail(20).min()) if len(low) >= 20 else float(low.min())
            high_50d = float(high.iloc[-51:-1].max()) if len(high) >= 51 else float(high.max())
            range_20d = high_20d - low_20d
            vcp_ratio = (high_5d - low_5d) / range_20d if range_20d > 0 else 1.0

            ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
            dist_ema20 = ((price - ema20) / ema20 * 100.0) if ema20 > 0 else 0.0

            cur_open = float(df["Open"].iloc[-1]) if "Open" in df.columns else price
            prev_close = float(close.iloc[-2]) if len(close) >= 2 else price
            gap_pct = round(((cur_open / prev_close) - 1.0) * 100.0, 2) if prev_close > 0 else 0.0
            is_bullish_bar = bool(price >= cur_open)
            day_range = float(high.iloc[-1] - low.iloc[-1]) if len(high) else 1.0
            close_loc = (price - float(low.iloc[-1])) / day_range if day_range > 0 else 0.5
            clv = round(close_loc, 3)

            # 14-day Normalized ATR % (Volatility fuel for high-beta moves)
            if len(close) >= 15 and len(high) >= 15 and len(low) >= 15:
                h_n = high.tail(15)
                l_n = low.reindex(h_n.index).fillna(h_n)
                c_prev = close.reindex(h_n.index).shift(1).fillna(price)
                tr_vals = pd.concat([h_n - l_n, (h_n - c_prev).abs(), (l_n - c_prev).abs()], axis=1).max(axis=1)
                natr14 = round(float(tr_vals.tail(14).mean() / (price + 1e-9)) * 100.0, 2)
            else:
                natr14 = round(vol_ann * 100.0 / (252 ** 0.5), 2)

            # Delivery Volume & Institutional Accumulation Fingerprint
            est_delivery_pct = min(95.0, max(25.0, round(35.0 + 35.0 * close_loc + 15.0 * min(1.0, rvol / 2.5), 1)))
            is_delivery_confirmed = bool(est_delivery_pct >= 45.0 and close_loc >= 0.65)
            is_wick_shakeout = bool(rvol >= 1.6 and close_loc < 0.38)  # Intraday wick dump

            # Stan Weinstein Stage-2 & Market Breadth Tracking
            ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1]) if len(close) >= 50 else price
            ema150 = float(close.ewm(span=150, adjust=False).mean().iloc[-1]) if len(close) >= 120 else ema50
            ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1]) if len(close) >= 150 else ema150
            dist_ema200_pct = round(((price / (ema200 + 1e-9)) - 1.0) * 100.0, 2)

            breadth_total += 1
            if price > ema50:
                breadth_above_50 += 1

            is_stage2 = bool(price >= ema50 and (ema50 >= ema150 * 0.98 if len(close) >= 120 else True) and ret_3m >= -0.02)
            is_downtrend_knife = bool(price < ema50 and ema50 < ema150 and ret_3m < -0.08)

            # Verified 59.4% CAGR + EDA-B1 Rocket Qualification
            is_50d_breakout = bool(price > high_50d and price > ema50 and price > ema20 and rvol >= 1.5)
            is_compounder_rocket = bool(
                is_50d_breakout
                and dist_ema200_pct >= 20.0
                and vol_asym_20 >= 2.0
                and clv >= 0.65
                and not (ret_6m > 0 and ret_1m < 0)
            )

            # Precise Institutional Breakout Pivot Trigger & Dynamic Asymmetric Base Stop Loss
            base_high = high_5d
            base_low = low_5d
            
            # Institutional Breakout Pivot Trigger (+0.15% clearance through base resistance, aligned with NSE ₹0.05 tick size)
            pivot_buy_stop = round(round((base_high * 1.0015) / 0.05) * 0.05, 2)
            
            # Max Buy Zone Ceiling (+2.5% max - do not chase above this!)
            max_buy_zone = round(round((pivot_buy_stop * 1.025) / 0.05) * 0.05, 2)
            
            # Dynamic Asymmetric Stop Loss anchored strictly to Base Support Floor (capped at -4.0%, floor at -3.0%)
            raw_base_stop = round(round((base_low * 0.995) / 0.05) * 0.05, 2)
            max_stop_px = round(pivot_buy_stop * 0.96, 2)   # max -4.0% risk ceiling
            min_stop_px = round(pivot_buy_stop * 0.97, 2)   # min -3.0% risk floor
            calculated_stop = max(max_stop_px, min(min_stop_px, raw_base_stop))
            calculated_stop_pct = round(((pivot_buy_stop - calculated_stop) / pivot_buy_stop) * 100.0, 1)

            # High-Velocity Target (+12.0%) and Breakeven Lock Trigger (+5.0%)
            velocity_target = round(round((pivot_buy_stop * 1.12) / 0.05) * 0.05, 2)
            breakeven_lock = round(round((pivot_buy_stop * 1.05) / 0.05) * 0.05, 2)
            rr_ratio = round(12.0 / calculated_stop_pct, 1) if calculated_stop_pct > 0 else 3.0

            is_institutional_ignition = bool(rvol >= 1.7 and close_loc >= 0.70 and is_bullish_bar)
            is_institutional_blast = bool(rvol >= 1.8 and close_loc >= 0.70 and is_bullish_bar and pos >= 0.85 and is_delivery_confirmed)
            
            rs_21 = (ret_1m - nifty_ret_1m) * 100.0
            is_ultra_alpha = bool(rs_21 >= 15.0 and pos >= 0.88 and rvol >= 1.8 and is_bullish_bar and is_delivery_confirmed)

            # Pre-Ignition Coil Pattern: Coiling in upper range, RS positive vs Nifty, tight VCP contraction, calm volume
            is_pre_ignition_coil = bool(pos >= 0.78 and vcp_ratio <= 0.75 and rs_21 >= 5.0 and 0.4 <= rvol <= 1.6)

            is_52w_breakout = bool(pos >= 0.85 and rvol >= 1.3 and price >= high_20d * 0.98)
            is_vcp = bool(vcp_ratio <= 0.65 and rvol >= 1.3 and price >= high_20d * 0.98)
            is_sweet_spot = bool(0.0 <= dist_ema20 <= 2.5 and is_bullish_bar)
            is_monster_breakout = bool(
                rvol >= 1.6
                and (is_52w_breakout or is_vcp or is_institutional_ignition or is_institutional_blast or is_ultra_alpha)
                and (ret_1m >= 0.03 or pos >= 0.85)
                and is_bullish_bar
            )

            # Sector Leadership Multiplier Integration
            from config import TICKER_TO_SECTOR
            from analysis.sector_rs import compute_sector_rs
            sec_name = TICKER_TO_SECTOR.get(ticker, "General")
            sec_info = compute_sector_rs(sec_name)
            sec_bonus = float(sec_info.get("bonus_points") or 0.0)
            sec_status = sec_info.get("status", "NEUTRAL")

            pattern_tag = "NONE"
            pattern_bonus = 0.0
            if is_ultra_alpha:
                pattern_tag = "ULTRA_ALPHA_LEADER"
                pattern_bonus = 25.0
            elif is_institutional_blast:
                pattern_tag = "INSTITUTIONAL_BLAST"
                pattern_bonus = 20.0
            elif is_pre_ignition_coil:
                pattern_tag = "PRE_IGNITION_COIL"
                pattern_bonus = 18.0
            elif is_monster_breakout or is_institutional_ignition:
                pattern_tag = "INSTITUTIONAL_IGNITION" if is_institutional_ignition else "MONSTER_BREAKOUT"
                pattern_bonus = 15.0
            elif is_52w_breakout:
                pattern_tag = "52W_HIGH_BREAKOUT"
                pattern_bonus = 10.0
            elif is_vcp:
                pattern_tag = "VCP_BREAKOUT"
                pattern_bonus = 8.0
            elif is_sweet_spot:
                pattern_tag = "20EMA_SWEET_SPOT"
                pattern_bonus = 6.0

            # Intraday wick dump penalty
            if is_wick_shakeout:
                pattern_bonus -= 15.0

            # Stage-2 Institutional Trend vs Downtrend Adjustments
            if is_stage2:
                pattern_bonus += 10.0
            elif is_downtrend_knife:
                pattern_bonus -= 25.0

            # Score 0-100: Momentum (25%), RVOL Volume Expansion (20%), Range (15%), Liquidity (15%), Volatility (10%) + Pattern Bonus + Sector Bonus
            mom = 50 + ret_1m * 80 + ret_3m * 40
            if pos >= 0.85:
                if rvol >= 1.3:
                    range_score = 85
                elif is_pre_ignition_coil or vcp_ratio <= 0.70:
                    range_score = 80  # Minervini VCP quiet consolidation near highs
                else:
                    range_score = 65
            elif 0.35 <= pos < 0.85:
                range_score = 75 if is_pre_ignition_coil else 65
            else:
                range_score = 45 if pos >= 0.15 else 30
            liq_score = min(100, 40 + avg_value_cr * 2)
            vol_score = 75 if vol_ann < 0.25 else (55 if vol_ann < 0.4 else 35)

            screen_score = (
                0.25 * max(0, min(100, mom))
                + 0.20 * rvol_score
                + 0.15 * range_score
                + 0.15 * liq_score
                + 0.10 * vol_score
                + pattern_bonus
                + sec_bonus
            )

            rows.append(
                {
                    "ticker": ticker,
                    "screen_score": round(screen_score, 1),
                    "price": round(price, 2),
                    "ret_1m_pct": round(ret_1m * 100, 2),
                    "ret_3m_pct": round(ret_3m * 100, 2),
                    "ret_6m_pct": round(ret_6m * 100, 2),
                    "composite_rs": composite_rs,
                    "rs_vs_nifty": round(rs_21, 2),
                    "rvol": rvol,
                    "vol_asym_20": vol_asym_20,
                    "clv": clv,
                    "natr14": natr14,
                    "gap_pct": gap_pct,
                    "is_episodic_pivot": bool(4.0 <= gap_pct <= 12.0 and rvol >= 3.0 and clv >= 0.70 and is_stage2 and 2.0 <= avg_value_cr <= 75.0),
                    "dist_ema200_pct": dist_ema200_pct,
                    "vcp_ratio": round(vcp_ratio, 2),
                    "setup_pattern": pattern_tag,
                    "est_delivery_pct": est_delivery_pct,
                    "pivot_buy_stop": pivot_buy_stop,
                    "max_buy_zone": max_buy_zone,
                    "target_price": velocity_target,
                    "breakeven_lock": breakeven_lock,
                    "stop_loss": calculated_stop,
                    "stop_loss_pct": calculated_stop_pct,
                    "reward_risk_ratio": rr_ratio,
                    "is_stage2": is_stage2,
                    "is_50d_breakout": is_50d_breakout,
                    "is_compounder_rocket": is_compounder_rocket,
                    "sector": sec_name,
                    "sector_status": sec_status,
                    "is_runner_candidate": bool(is_compounder_rocket or pattern_tag in ("MONSTER_BREAKOUT", "52W_HIGH_BREAKOUT", "PRE_IGNITION_COIL") or (pattern_tag == "VCP_BREAKOUT" and rvol >= 1.5)),
                    "range_position": round(pos, 2),
                    "volatility_ann": round(vol_ann * 100, 1),
                    "avg_value_cr": round(avg_value_cr, 2),
                }
            )
        except Exception as e:
            logger.debug(f"Screen skip {ticker}: {e}")

    pre_screen.last_breadth_pct = round((breadth_above_50 / breadth_total) * 100.0, 1) if breadth_total > 0 else 50.0
    if rows:
        rs_sorted = sorted(float(r.get("composite_rs", 0.0)) for r in rows)
        n_rows = len(rs_sorted)
        from bisect import bisect_right
        for r in rows:
            rank_pos = bisect_right(rs_sorted, float(r.get("composite_rs", 0.0)))
            r["rs_pct_rank"] = round((rank_pos / n_rows) * 100.0, 1)
    rows.sort(key=lambda r: r["screen_score"], reverse=True)
    return rows if return_all else rows[:top_n]


def select_deep_score_universe(
    preset: str = "extended",
    top_n: int = 25,
    always_include: Optional[list[str]] = None,
) -> dict:
    """
    Build scan list → pre-screen all names → return tickers for expensive deep scoring
    while retaining all screened stocks so the user has scores for the full universe.
    """
    universe = get_universe(preset)
    all_screened = pre_screen(universe, top_n=top_n, return_all=True)
    screened = all_screened[:top_n]
    picked = [r["ticker"] for r in screened]

    always_include = always_include or []
    for t in always_include:
        if t and t not in picked:
            picked.insert(0, t)

    return {
        "preset": preset,
        "universe_size": len(universe),
        "screened": screened,
        "all_screened": all_screened,
        "deep_score_tickers": list(dict.fromkeys(picked)),
    }
