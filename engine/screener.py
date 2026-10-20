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
from config import NIFTY50_STOCKS, NIFTY_NEXT50_STOCKS, MIDCAP_LIQUID_STOCKS, UNIVERSE_PRESETS

logger = logging.getLogger(__name__)


def get_universe(preset: str = "nifty500") -> list[str]:
    """
    preset: nifty500 | nifty50 | nifty100 | midcap | extended | all
    """
    preset = (preset or "nifty500").lower()
    if preset in UNIVERSE_PRESETS:
        names = UNIVERSE_PRESETS[preset]
    elif preset == "nifty50":
        names = list(NIFTY50_STOCKS)
    elif preset == "nifty100":
        names = list(dict.fromkeys(NIFTY50_STOCKS + NIFTY_NEXT50_STOCKS))
    elif preset == "midcap":
        names = list(MIDCAP_LIQUID_STOCKS)
    elif preset == "all":
        names = list(dict.fromkeys(NIFTY50_STOCKS + NIFTY_NEXT50_STOCKS + MIDCAP_LIQUID_STOCKS))
    else:
        names = list(dict.fromkeys(NIFTY50_STOCKS + NIFTY_NEXT50_STOCKS + MIDCAP_LIQUID_STOCKS))

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
    min_price: float = 50.0,
    min_avg_value_cr: float = 5.0,
) -> list[dict]:
    """
    Fast batch screen using yfinance download (no per-ticker news yet).

    Ranking blend:
      - 3m / 1m momentum
      - proximity to 52w high (not chasing extremes blindly)
      - liquidity proxy (avg rupee volume)
      - lower volatility preferred slightly for small capital
    """
    if not tickers:
        return []

    logger.info(f"Pre-screening {len(tickers)} tickers (top_n={top_n})")
    try:
        data = yf.download(
            tickers,
            period=period,
            group_by="ticker",
            progress=False,
            threads=True,
        )
    except Exception as e:
        logger.error(f"Batch download failed: {e}")
        return [{"ticker": t, "screen_score": 50, "error": str(e)} for t in tickers[:top_n]]

    rows = []
    multi = isinstance(data.columns, pd.MultiIndex)

    for ticker in tickers:
        try:
            if multi:
                if ticker not in data.columns.get_level_values(0):
                    continue
                df = data[ticker].dropna(how="all")
            else:
                df = data.dropna(how="all")

            if df.empty or len(df) < 40 or "Close" not in df.columns:
                continue

            close = df["Close"].dropna()
            vol = df["Volume"].dropna() if "Volume" in df.columns else pd.Series(dtype=float)
            if len(close) < 40:
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

            # Score 0-100
            mom = 50 + ret_1m * 80 + ret_3m * 40
            # Prefer not blown-off top (>0.95) or broken bottom (<0.15)
            range_score = 70 if 0.35 <= pos <= 0.85 else (45 if pos < 0.35 else 40)
            liq_score = min(100, 40 + avg_value_cr * 2)
            vol_score = 75 if vol_ann < 0.25 else (55 if vol_ann < 0.4 else 35)

            screen_score = 0.35 * max(0, min(100, mom)) + 0.25 * range_score + 0.25 * liq_score + 0.15 * vol_score

            rows.append(
                {
                    "ticker": ticker,
                    "screen_score": round(screen_score, 1),
                    "price": round(price, 2),
                    "ret_1m_pct": round(ret_1m * 100, 2),
                    "ret_3m_pct": round(ret_3m * 100, 2),
                    "range_position": round(pos, 2),
                    "volatility_ann": round(vol_ann * 100, 1),
                    "avg_value_cr": round(avg_value_cr, 2),
                }
            )
        except Exception as e:
            logger.debug(f"Screen skip {ticker}: {e}")

    rows.sort(key=lambda r: r["screen_score"], reverse=True)
    return rows[:top_n]


def select_deep_score_universe(
    preset: str = "extended",
    top_n: int = 20,
    always_include: Optional[list[str]] = None,
) -> dict:
    """
    Build scan list → pre-screen → return tickers for expensive deep scoring.
    always_include: holdings / forced names.
    """
    universe = get_universe(preset)
    screened = pre_screen(universe, top_n=top_n)
    picked = [r["ticker"] for r in screened]

    always_include = always_include or []
    for t in always_include:
        if t and t not in picked:
            picked.insert(0, t)

    return {
        "preset": preset,
        "universe_size": len(universe),
        "screened": screened,
        "deep_score_tickers": list(dict.fromkeys(picked)),
    }
