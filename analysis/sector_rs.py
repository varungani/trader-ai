"""
TraderAI - Sector Relative Strength (RS) Engine
Compares sectoral index momentum against Nifty 50 to identify institutional sector tailwinds and drags.
Stocks in leading sectors receive score bonuses; stocks in lagging sectors receive penalties.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from data.market_data import fetch_live_quote
from config import INDICES

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

# Cache sector RS in memory for 10 minutes to avoid redundant network requests across 500 stocks
_SECTOR_RS_CACHE: dict = {}
_LAST_CACHE_TIME: float = 0.0
_CACHE_TTL_SECONDS: float = 600.0  # 10 minutes


def refresh_sector_relative_strengths() -> dict:
    """Fetch all sector index live quotes and compute Relative Strength vs Nifty 50."""
    global _SECTOR_RS_CACHE, _LAST_CACHE_TIME

    now = time.time()
    if _SECTOR_RS_CACHE and (now - _LAST_CACHE_TIME < _CACHE_TTL_SECONDS):
        return _SECTOR_RS_CACHE

    try:
        nifty_quote = fetch_live_quote("^NSEI")
        n_px = float(nifty_quote.get("price") or 0.0)
        n_prev = float(nifty_quote.get("previous_close") or n_px or 1.0)
        nifty_chg = ((n_px - n_prev) / n_prev * 100.0) if n_prev > 0 else 0.0

        cache = {}
        for sector, idx_sym in SECTOR_TO_INDEX.items():
            try:
                q = fetch_live_quote(idx_sym)
                s_px = float(q.get("price") or 0.0)
                s_prev = float(q.get("previous_close") or s_px or 1.0)
                s_chg = ((s_px - s_prev) / s_prev * 100.0) if s_prev > 0 else 0.0
                rs = round(s_chg - nifty_chg, 2)

                # Determine bonus/penalty based on relative strength
                if rs >= 2.0:
                    status = "LEADING"
                    bonus = 5.0
                elif rs >= 0.75:
                    status = "OUTPERFORMING"
                    bonus = 3.0
                elif rs >= -0.75:
                    status = "NEUTRAL"
                    bonus = 0.0
                elif rs >= -1.75:
                    status = "LAGGING"
                    bonus = -4.0
                else:
                    status = "SEVERE_DRAG"
                    bonus = -7.0

                cache[sector] = {
                    "sector": sector,
                    "index_symbol": idx_sym,
                    "sector_change_pct": round(s_chg, 2),
                    "nifty_change_pct": round(nifty_chg, 2),
                    "relative_strength_pct": rs,
                    "status": status,
                    "bonus_points": bonus,
                }
            except Exception as e:
                logger.debug(f"Failed fetching quote for sector {sector} ({idx_sym}): {e}")
                cache[sector] = {
                    "sector": sector,
                    "index_symbol": idx_sym,
                    "sector_change_pct": 0.0,
                    "nifty_change_pct": round(nifty_chg, 2),
                    "relative_strength_pct": 0.0,
                    "status": "NEUTRAL",
                    "bonus_points": 0.0,
                }

        _SECTOR_RS_CACHE = cache
        _LAST_CACHE_TIME = now
        return _SECTOR_RS_CACHE

    except Exception as e:
        logger.error(f"Error refreshing sector relative strengths: {e}")
        return _SECTOR_RS_CACHE or {}


def compute_sector_rs(sector: Optional[str]) -> dict:
    """Return Relative Strength data and score adjustment for a given sector name."""
    if not sector:
        return {
            "sector": "General",
            "index_symbol": "^NSEI",
            "sector_change_pct": 0.0,
            "nifty_change_pct": 0.0,
            "relative_strength_pct": 0.0,
            "status": "NEUTRAL",
            "bonus_points": 0.0,
        }

    all_rs = refresh_sector_relative_strengths()
    return all_rs.get(
        sector,
        {
            "sector": sector,
            "index_symbol": "^NSEI",
            "sector_change_pct": 0.0,
            "nifty_change_pct": 0.0,
            "relative_strength_pct": 0.0,
            "status": "NEUTRAL",
            "bonus_points": 0.0,
        },
    )
