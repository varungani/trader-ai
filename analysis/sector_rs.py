"""
TraderAI - Sector Relative Strength (RS) Engine (v3.3.0-delivery-alpha)
Compares sectoral momentum against Nifty 50 over 1-Month (21-day) and 3-Month (63-day) horizons.
Identifies institutional sector tailwinds, awards Leadership Multipliers (+15 pts, 1.35x capital),
and protects capital against lagging sectors.
"""
from __future__ import annotations

import logging
import time
from typing import Optional
import numpy as np
import pandas as pd

from data.market_data import fetch_live_quote, _get_cached_history
from config import INDICES, SECTOR_MAP, SECTOR_ALLOCATION_MULTIPLIERS

logger = logging.getLogger(__name__)

SECTOR_TO_INDEX = {
    "IT": "^CNXIT",
    "Banking": "^NSEBANK",
    "Auto": "^CNXAUTO",
    "Pharma": "^CNXPHARMA",
    "Energy": "^CNXENERGY",
    "FMCG": "^CNXFMCG",
    "Metals": "^CNXMETAL",
    "Infra": "^CNXINFRA",
    "Finance": "^CNXFIN",
    "Consumer": "^CNXFMCG",
}

# Cache sector RS in memory for 10 minutes to avoid redundant calculations
_SECTOR_RS_CACHE: dict = {}
_LAST_CACHE_TIME: float = 0.0
_CACHE_TTL_SECONDS: float = 600.0  # 10 minutes


def _compute_offline_constituent_sector_rs() -> dict:
    """
    Compute robust 1-Month and 3-Month Sector Relative Strength from constituent stock medians.
    Operates resiliently offline, sandboxed, and across live market data.
    """
    nifty_df = _get_cached_history("^NSEI", period="3mo")
    n_ret_1m = 0.0
    n_ret_3m = 0.0
    if not nifty_df.empty:
        nifty_df.columns = [str(c).title() for c in nifty_df.columns]
        if "Close" in nifty_df.columns and len(nifty_df) >= 22:
            n_close = nifty_df["Close"].dropna()
            n_ret_1m = float(n_close.iloc[-1] / n_close.iloc[-22] - 1)
            if len(n_close) >= 66:
                n_ret_3m = float(n_close.iloc[-1] / n_close.iloc[-66] - 1)

    raw_results = {}
    for sector, tickers in SECTOR_MAP.items():
        rets_1m = []
        rets_3m = []
        for t in tickers:
            df = _get_cached_history(t, period="3mo")
            if not df.empty:
                df.columns = [str(c).title() for c in df.columns]
                if "Close" in df.columns and len(df) >= 22:
                    c = df["Close"].dropna()
                    r1 = float(c.iloc[-1] / c.iloc[-22] - 1)
                    rets_1m.append(r1)
                    if len(c) >= 66:
                        rets_3m.append(float(c.iloc[-1] / c.iloc[-66] - 1))

        if rets_1m:
            med_1m = float(np.median(rets_1m))
            med_3m = float(np.median(rets_3m)) if rets_3m else med_1m
            rs_1m = round((med_1m - n_ret_1m) * 100.0, 2)
            rs_3m = round((med_3m - n_ret_3m) * 100.0, 2)
            # Composite RS: 60% 1-Month (fast swing momentum) + 40% 3-Month (structural trend)
            composite_rs = round(0.60 * rs_1m + 0.40 * rs_3m, 2)
            raw_results[sector] = {
                "sector": sector,
                "index_symbol": SECTOR_TO_INDEX.get(sector, "^NSEI"),
                "sector_return_1m_pct": round(med_1m * 100.0, 2),
                "sector_return_3m_pct": round(med_3m * 100.0, 2),
                "nifty_return_1m_pct": round(n_ret_1m * 100.0, 2),
                "relative_strength_pct": rs_1m,
                "rs_3m_pct": rs_3m,
                "composite_rs": composite_rs,
                "constituent_count": len(rets_1m),
            }

    # Rank sectors by Composite RS
    sorted_sectors = sorted(raw_results.values(), key=lambda x: x["composite_rs"], reverse=True)
    top_2_names = {s["sector"] for s in sorted_sectors[:2]}

    cache = {}
    for rank, s_data in enumerate(sorted_sectors, 1):
        sec = s_data["sector"]
        rs = s_data["composite_rs"]

        if sec in top_2_names or rs >= 5.0:
            status = "LEADING"
            bonus = 15.0
            mult = SECTOR_ALLOCATION_MULTIPLIERS.get("LEADING", 1.35)
        elif rs >= 1.5:
            status = "OUTPERFORMING"
            bonus = 8.0
            mult = SECTOR_ALLOCATION_MULTIPLIERS.get("OUTPERFORMING", 1.15)
        elif rs >= -2.0:
            status = "NEUTRAL"
            bonus = 0.0
            mult = SECTOR_ALLOCATION_MULTIPLIERS.get("NEUTRAL", 1.00)
        else:
            status = "LAGGING"
            bonus = -10.0
            mult = SECTOR_ALLOCATION_MULTIPLIERS.get("LAGGING", 0.70)

        s_data["status"] = status
        s_data["bonus_points"] = bonus
        s_data["capital_multiplier"] = mult
        s_data["sector_rank"] = rank
        cache[sec] = s_data

    return cache


def refresh_sector_relative_strengths() -> dict:
    """Fetch sector relative strengths and compute institutional bonuses."""
    global _SECTOR_RS_CACHE, _LAST_CACHE_TIME

    now = time.time()
    if _SECTOR_RS_CACHE and (now - _LAST_CACHE_TIME < _CACHE_TTL_SECONDS):
        return _SECTOR_RS_CACHE

    # Compute robust constituent-level RS
    cache = _compute_offline_constituent_sector_rs()
    if cache:
        _SECTOR_RS_CACHE = cache
        _LAST_CACHE_TIME = now
        return _SECTOR_RS_CACHE

    return {}


def compute_sector_rs(sector: Optional[str]) -> dict:
    """Return Relative Strength data and score adjustment for a given sector name."""
    if not sector:
        return {
            "sector": "General",
            "index_symbol": "^NSEI",
            "sector_change_pct": 0.0,
            "relative_strength_pct": 0.0,
            "status": "NEUTRAL",
            "bonus_points": 0.0,
            "capital_multiplier": 1.0,
        }

    all_rs = refresh_sector_relative_strengths()
    return all_rs.get(
        sector,
        {
            "sector": sector,
            "index_symbol": SECTOR_TO_INDEX.get(sector, "^NSEI"),
            "sector_change_pct": 0.0,
            "relative_strength_pct": 0.0,
            "status": "NEUTRAL",
            "bonus_points": 0.0,
            "capital_multiplier": 1.0,
        },
    )


def get_top_leading_sectors(top_n: int = 3) -> list[dict]:
    """Return the current top-performing institutional sectors in India."""
    all_rs = refresh_sector_relative_strengths()
    sorted_secs = sorted(all_rs.values(), key=lambda x: x.get("composite_rs", 0.0), reverse=True)
    return sorted_secs[:top_n]
