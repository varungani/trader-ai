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

    Ranking blend:
      - 3m / 1m momentum
      - RVOL volume expansion & institutional ignition
      - proximity to 52w high (not chasing extremes blindly)
      - liquidity proxy (avg rupee volume >= ₹2 Cr)
      - lower volatility preferred slightly for small capital
    """
    if not tickers:
        return []

    logger.info(f"Pre-screening {len(tickers)} tickers (top_n={top_n})")
    data = pd.DataFrame()
    try:
        data = yf.download(
            tickers,
            period=period,
            group_by="ticker",
            progress=False,
            threads=True,
        )
    except Exception as e:
        logger.debug(f"Batch download failed: {e}, falling back to cache")

    from data.market_data import _get_cached_history

    rows = []
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
                df = _get_cached_history(ticker, period=period)

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
            ret_3m = float(close.iloc[-1] / close.iloc[-66] - 1) if len(close) >= 66 else ret_1m
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

            # Calculate RVOL (Relative Volume Surge: Latest Session Volume / 20-Day Average)
            latest_vol = float(vol.iloc[-1]) if len(vol) else 0.0
            rvol = round(latest_vol / avg_vol, 2) if avg_vol > 0 else 1.0

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

            # Pattern Detection: Minervini VCP & 20 EMA Sweet Spot
            high = df["High"].dropna() if "High" in df.columns else close
            low = df["Low"].dropna() if "Low" in df.columns else close
            high_5d = float(high.tail(5).max()) if len(high) >= 5 else float(high.max())
            low_5d = float(low.tail(5).min()) if len(low) >= 5 else float(low.min())
            high_20d = float(high.tail(20).max()) if len(high) >= 20 else float(high.max())
            low_20d = float(low.tail(20).min()) if len(low) >= 20 else float(low.min())
            range_20d = high_20d - low_20d
            vcp_ratio = (high_5d - low_5d) / range_20d if range_20d > 0 else 1.0

            ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
            dist_ema20 = ((price - ema20) / ema20 * 100.0) if ema20 > 0 else 0.0

            cur_open = float(df["Open"].iloc[-1]) if "Open" in df.columns else price
            is_bullish_bar = bool(price >= cur_open)
            day_range = float(high.iloc[-1] - low.iloc[-1]) if len(high) else 1.0
            close_loc = (price - float(low.iloc[-1])) / day_range if day_range > 0 else 0.5
            is_institutional_ignition = bool(rvol >= 1.7 and close_loc >= 0.70 and is_bullish_bar)

            is_52w_breakout = bool(pos >= 0.85 and rvol >= 1.3 and price >= high_20d * 0.98)
            is_vcp = bool(vcp_ratio <= 0.65 and rvol >= 1.3 and price >= high_20d * 0.98)
            is_sweet_spot = bool(0.0 <= dist_ema20 <= 2.5 and is_bullish_bar)
            is_monster_breakout = bool(
                rvol >= 1.6
                and (is_52w_breakout or is_vcp or is_institutional_ignition)
                and (ret_1m >= 0.03 or pos >= 0.85)
                and is_bullish_bar
            )

            pattern_tag = "NONE"
            pattern_bonus = 0.0
            if is_monster_breakout or is_institutional_ignition:
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

            # Score 0-100: Momentum (30%), RVOL Volume Expansion (25%), Range (20%), Liquidity (15%), Volatility (10%) + Pattern Bonus
            mom = 50 + ret_1m * 80 + ret_3m * 40
            # Range score: High-volume Stage-2 breakouts at top of range get full credit (85).
            # Low-volume exhaustion tops (>0.85 with rvol < 1.3) are penalized (40). Broken bottoms (<0.15) get 30.
            if pos >= 0.85:
                range_score = 85 if rvol >= 1.3 else 40
            elif 0.35 <= pos < 0.85:
                range_score = 70
            else:
                range_score = 45 if pos >= 0.15 else 30
            liq_score = min(100, 40 + avg_value_cr * 2)
            vol_score = 75 if vol_ann < 0.25 else (55 if vol_ann < 0.4 else 35)

            screen_score = (
                0.30 * max(0, min(100, mom))
                + 0.25 * rvol_score
                + 0.20 * range_score
                + 0.15 * liq_score
                + 0.10 * vol_score
                + pattern_bonus
            )

            rows.append(
                {
                    "ticker": ticker,
                    "screen_score": round(screen_score, 1),
                    "price": round(price, 2),
                    "ret_1m_pct": round(ret_1m * 100, 2),
                    "ret_3m_pct": round(ret_3m * 100, 2),
                    "rvol": rvol,
                    "vcp_ratio": round(vcp_ratio, 2),
                    "setup_pattern": pattern_tag,
                    "is_runner_candidate": bool(pattern_tag in ("MONSTER_BREAKOUT", "52W_HIGH_BREAKOUT") or (pattern_tag == "VCP_BREAKOUT" and rvol >= 1.5)),
                    "range_position": round(pos, 2),
                    "volatility_ann": round(vol_ann * 100, 1),
                    "avg_value_cr": round(avg_value_cr, 2),
                }
            )
        except Exception as e:
            logger.debug(f"Screen skip {ticker}: {e}")

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
