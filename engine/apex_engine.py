"""
TraderAI - Apex High-Velocity Engine (v3.3.0-delivery-alpha)
Ultra-Concentrated Indian Cash Delivery Momentum Engine with Two-Tier Execution Architecture:
- Tier 1: Apex Immediate Execution (Top 3 Slots, 33.3% Capital Each)
- Tier 2: High-Velocity Radar & Pre-Ignition Watchlist (Top 12 Candidates with Buy-Stop Pivots)
- Institutional Upgrades:
  1. Delivery Volume Gate (Delivery % >= 45%, CLV >= 0.70)
  2. Sector Leadership Multiplier (+15 pts for Top 2 Leading Sectors)
  3. Expanded Small-Cap & High-Beta Momentum Universe
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    HIGH_BETA_APEX_STOCKS,
    RISK_CONFIG,
    ALLOCATION_PROFILES,
    TICKER_TO_SECTOR,
)
from engine.screener import pre_screen
from engine.scorer import score_stock
from engine.recommender import build_recommendation
from engine.balancer import position_size
from analysis.macro import compute_macro_score
from analysis.sector_rs import get_top_leading_sectors, compute_sector_rs

logger = logging.getLogger(__name__)


def run_apex_scan(
    capital: float = 100000.0,
    top_slots: int = 3,
    radar_slots: int = 12,
    force_live: bool = False,
) -> dict:
    """
    Run the end-to-end Apex High-Velocity Scan:
    Returns:
      - picks: Top 3 immediate execution slots (33.3% capital each)
      - radar_watchlist: Top 10-15 coiled setups with exact pivot triggers to eliminate the shortlisting bottleneck
      - leading_sectors: Top institutional sectors with leadership tailwinds
    """
    logger.info(f"Running Apex High-Velocity Scan on {len(HIGH_BETA_APEX_STOCKS)} stocks (Capital: ₹{capital:,.2f})")

    # 1. Macro Regime Check
    macro = compute_macro_score()
    regime = macro.get("regime", "BULLISH")
    nifty_cleared = macro.get("is_regime_gate_cleared", True)
    regime_desc = macro.get("description", "Market regime healthy")

    # 2. Sector Leadership Matrix
    top_sectors = get_top_leading_sectors(top_n=3)

    # 3. High-Velocity Pre-Screen across full Nifty 500 universe (499 stocks)
    from engine.screener import get_universe
    scan_universe = get_universe("nifty500")
    screen_hits = pre_screen(
        tickers=scan_universe,
        top_n=50,
        period="6mo",
        min_price=15.0,
        min_avg_value_cr=2.0,
    )

    if not screen_hits:
        return {
            "status": "NO_CANDIDATES",
            "regime": regime,
            "regime_desc": regime_desc,
            "picks": [],
            "radar_watchlist": [],
            "leading_sectors": top_sectors,
            "capital": capital,
        }

    # 4. Deep Multi-Factor Scoring
    scored = []
    screen_map = {h["ticker"]: h for h in screen_hits}

    for hit in screen_hits[:25]:
        ticker = hit["ticker"]
        try:
            score_data = score_stock(ticker, timeframe="short_term", macro_score=macro)
            rec = build_recommendation(score_data)
            
            # Enrich with screener patterns, delivery and sector metadata
            rec["setup_pattern"] = hit.get("setup_pattern") or "NONE"
            rec["rvol"] = hit.get("rvol", 1.0)
            rec["rs_vs_nifty"] = hit.get("rs_vs_nifty", 0.0)
            rec["screen_rank"] = hit.get("screen_score", 0.0)
            rec["est_delivery_pct"] = hit.get("est_delivery_pct", 50.0)
            rec["pivot_buy_stop"] = hit.get("pivot_buy_stop") or float(rec.get("current_price") or 0.0)
            rec["sector"] = hit.get("sector") or TICKER_TO_SECTOR.get(ticker, "General")
            rec["sector_status"] = hit.get("sector_status", "NEUTRAL")
            rec["range_position"] = hit.get("range_position", 0.5)
            
            scored.append(rec)
        except Exception as e:
            logger.debug(f"Scoring error on {ticker}: {e}")

    # 5. Filter BUY / STRONG_BUY candidates
    buys = [r for r in scored if r.get("action") in ("BUY", "STRONG_BUY")]
    
    # Priority sorting:
    # 1. Ultra Alpha Leaders & Institutional Blasts
    # 2. Sector Leadership (+15 pts for Leading Sectors)
    # 3. Relative Strength vs Nifty
    # 4. Final Score & RVOL
    buys.sort(
        key=lambda x: (
            4 if "ULTRA_ALPHA" in str(x.get("setup_pattern", "")) else (
                3 if "BLAST" in str(x.get("setup_pattern", "")) else (
                    2 if "COIL" in str(x.get("setup_pattern", "")) else (
                        1 if "IGNITION" in str(x.get("setup_pattern", "")) else 0
                    )
                )
            ),
            1 if x.get("sector_status") == "LEADING" else 0,
            float(x.get("rs_vs_nifty", 0)),
            float(x.get("final_score", 0)),
            float(x.get("rvol", 1.0)),
        ),
        reverse=True,
    )

    # 6. Tier 1: Concentrated Immediate Execution Slots (Top 3, 33.3% Capital)
    slot_allocation_pct = round(1.0 / top_slots, 3)
    slot_capital = capital * slot_allocation_pct
    profile = ALLOCATION_PROFILES.get("apex_3slot", {})

    top_picks = []
    total_deployed = 0.0

    # For Tier 1, prioritize candidates firing today with high volume conviction
    firing_candidates = [b for b in buys if float(b.get("rvol", 1.0)) >= 1.5]
    immediate_pool = firing_candidates if len(firing_candidates) >= top_slots else buys

    for rec in immediate_pool[:top_slots]:
        ticker = rec.get("ticker")
        cur_px = float(rec.get("current_price") or 0.0)
        stop_px = float(rec.get("stop_loss") or (cur_px * 0.93))
        target_px = float(rec.get("target_price") or (cur_px * 1.20))
        pivot_px = float(rec.get("pivot_buy_stop") or (cur_px * 1.015))
        
        shares = int(slot_capital // cur_px) if cur_px > 0 else 0
        allocated_inr = round(shares * cur_px, 2)
        total_deployed += allocated_inr

        top_picks.append({
            "ticker": ticker,
            "name": ticker.replace(".NS", ""),
            "action": rec.get("action"),
            "final_score": rec.get("final_score"),
            "pattern": rec.get("setup_pattern"),
            "rvol": rec.get("rvol"),
            "rs_vs_nifty": rec.get("rs_vs_nifty", 0.0),
            "est_delivery_pct": rec.get("est_delivery_pct", 55.0),
            "sector": rec.get("sector", "General"),
            "sector_status": rec.get("sector_status", "NEUTRAL"),
            "current_price": cur_px,
            "pivot_buy_stop": pivot_px,
            "target_price": target_px,
            "target_pct": round((target_px - cur_px) / cur_px * 100, 2) if cur_px > 0 else 20.0,
            "stop_loss": stop_px,
            "stop_loss_pct": round((cur_px - stop_px) / cur_px * 100, 2) if cur_px > 0 else 7.0,
            "reward_risk": round((target_px - cur_px) / (cur_px - stop_px), 2) if (cur_px - stop_px) > 0 else 2.86,
            "shares": shares,
            "allocated_rupees": allocated_inr,
            "weight_pct": round(allocated_inr / capital * 100, 2) if capital > 0 else 33.3,
            "holding_window": "21 Sessions (~1 Month)",
            "stop_basis": "Daily Close",
            "tier": "TIER_1_EXECUTION",
            "rationale": rec.get("action_rationale"),
        })

    # 7. Tier 2: High-Velocity Radar & Pre-Ignition Watchlist (Top 10-15)
    # Solves the shortlisting problem by maintaining live tracking on runner setups
    tier1_tickers = {p["ticker"] for p in top_picks}
    radar_pool = [b for b in buys if b["ticker"] not in tier1_tickers]
    
    # Also add top screened candidates that are coiling near 52W highs
    for h in screen_hits:
        t = h["ticker"]
        if t not in tier1_tickers and not any(r["ticker"] == t for r in radar_pool):
            if h.get("setup_pattern") in ("PRE_IGNITION_COIL", "52W_HIGH_BREAKOUT", "INSTITUTIONAL_IGNITION", "20EMA_SWEET_SPOT") or h.get("screen_score", 0) >= 70:
                px = float(h.get("price") or 0.0)
                radar_pool.append({
                    "ticker": t,
                    "name": t.replace(".NS", ""),
                    "action": "WATCHLIST",
                    "final_score": h.get("screen_score", 70.0),
                    "setup_pattern": h.get("setup_pattern", "MOMENTUM_RUNNER"),
                    "rvol": h.get("rvol", 1.0),
                    "rs_vs_nifty": h.get("rs_vs_nifty", 0.0),
                    "est_delivery_pct": h.get("est_delivery_pct", 50.0),
                    "sector": h.get("sector") or TICKER_TO_SECTOR.get(t, "General"),
                    "sector_status": h.get("sector_status", "NEUTRAL"),
                    "current_price": px,
                    "stop_loss": round(px * 0.93, 2),
                    "target_price": round(px * 1.20, 2),
                    "pivot_buy_stop": h.get("pivot_buy_stop") or round(px * 1.015, 2),
                    "range_position": h.get("range_position", 0.85),
                })

    radar_watchlist = []
    for r in radar_pool[:radar_slots]:
        cur_px = float(r.get("current_price") or 0.0)
        target_px = float(r.get("target_price") or (cur_px * 1.20))
        stop_px = float(r.get("stop_loss") or (cur_px * 0.93))
        pivot_px = float(r.get("pivot_buy_stop") or cur_px)
        pattern = r.get("setup_pattern", "COIL")
        rvol = float(r.get("rvol", 1.0))
        
        # Determine Readiness State
        if "ULTRA" in pattern or "BLAST" in pattern or rvol >= 1.6:
            readiness = "⚡ FIRING TODAY (Volume Surge Active)"
            action_plan = f"Active momentum. If Slot 1-3 is filled, place GTT buy trigger at ₹{pivot_px:,.2f} on breakout."
        elif "COIL" in pattern:
            readiness = "⏳ COILING AT 52W HIGH (Awaiting Blast)"
            action_plan = f"Tight base consolidation. Place alert/GTT Buy Stop at ₹{pivot_px:,.2f} with volume confirmation."
        elif "20EMA" in pattern:
            readiness = "🎯 20 EMA SPRINGBOARD (Dip Support)"
            action_plan = f"Low-risk pull-back bounce near ₹{cur_px:,.2f}. 7% daily close stop at ₹{stop_px:,.2f}."
        else:
            readiness = "👀 STAGE-2 EXPANSION (High Relative Strength)"
            action_plan = f"Sector leader in Stage 2. Track for volume breakout above ₹{pivot_px:,.2f}."

        radar_watchlist.append({
            "ticker": r.get("ticker"),
            "name": r.get("ticker").replace(".NS", ""),
            "current_price": cur_px,
            "target_price": target_px,
            "target_pct": 20.0,
            "stop_loss": stop_px,
            "stop_loss_pct": 7.0,
            "pivot_buy_stop": pivot_px,
            "pattern": pattern,
            "readiness": readiness,
            "action_plan": action_plan,
            "rs_vs_nifty": r.get("rs_vs_nifty", 0.0),
            "rvol": rvol,
            "est_delivery_pct": r.get("est_delivery_pct", 50.0),
            "sector": r.get("sector", "General"),
            "sector_status": r.get("sector_status", "NEUTRAL"),
            "final_score": r.get("final_score", 70.0),
            "tier": "TIER_2_RADAR",
        })

    cash_remaining = round(capital - total_deployed, 2)

    return {
        "status": "OK",
        "regime": regime,
        "nifty_cleared": nifty_cleared,
        "regime_desc": regime_desc,
        "capital": capital,
        "total_deployed": round(total_deployed, 2),
        "cash_remaining": cash_remaining,
        "slot_count": top_slots,
        "picks": top_picks,                       # Tier 1: Top 3 Concentrated Active Slots
        "radar_watchlist": radar_watchlist,       # Tier 2: Top 12 Pre-Ignition / Coiling Leaders
        "leading_sectors": top_sectors,           # Top 3 Leading Sectors in India
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    res = run_apex_scan(capital=100000.0, top_slots=3, radar_slots=10)
    print("\n================ APEX HIGH-VELOCITY SCAN RESULTS ================")
    print(f"Market Regime: {res['regime']} (Nifty Cleared: {res['nifty_cleared']})")
    print(f"Total Capital: ₹{res['capital']:,.2f} | Deployed: ₹{res['total_deployed']:,.2f} | Cash: ₹{res['cash_remaining']:,.2f}")
    
    print("\n🏆 Top Leading Sectors in India:")
    for s in res.get("leading_sectors", []):
        print(f"  • {s['sector']}: Rank #{s.get('sector_rank', 1)} | Composite RS: {s.get('composite_rs', 0):+.2f}% ({s.get('status')})")

    print("\n⚡ TIER 1: ACTIVE 3-SLOT EXECUTION CARDS (33.3% Capital Each):")
    for i, p in enumerate(res["picks"], 1):
        print(f"Slot {i}: [{p['ticker']}] - {p['pattern']} | Sector: {p['sector']} ({p['sector_status']})")
        print(f"  Score: {p['final_score']} | RVOL: {p['rvol']}x | RS vs Nifty: {p.get('rs_vs_nifty', 0.0):+.1f}% | Delivery: {p.get('est_delivery_pct', 0)}%")
        print(f"  Entry: ₹{p['current_price']:,.2f} | Target (+20%): ₹{p['target_price']:,.2f} | Stop (-7% Close): ₹{p['stop_loss']:,.2f}")
        print(f"  Position: {p['shares']} shares = ₹{p['allocated_rupees']:,.2f} ({p['weight_pct']}% of portfolio)\n")

    print(f"📡 TIER 2: HIGH-VELOCITY RADAR WATCHLIST ({len(res['radar_watchlist'])} Stocks):")
    for r in res["radar_watchlist"][:8]:
        print(f"  • [{r['ticker']}] ₹{r['current_price']:,.2f} | Pivot Trigger: ₹{r['pivot_buy_stop']:,.2f} | RS: {r['rs_vs_nifty']:+.1f}% | {r['readiness']}")
        print(f"    Action: {r['action_plan']}")
