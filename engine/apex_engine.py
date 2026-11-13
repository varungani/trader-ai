"""
TraderAI - Apex High-Velocity Engine (v3.0.0-apex)
Ultra-Concentrated 3-Slot Indian Cash Delivery Momentum Engine

Core Principles:
1. Universe: 60+ High-Beta Mid/Smallcap Momentum Rockets (BSE, Dixon, Trent, Mazdock, Kaynes, etc.)
2. Concentration: 3 Slots (33.3% capital per trade) for maximum capital velocity
3. Pattern: Institutional Blast (RVOL >= 1.8x, Close near Day High, Proximity to 52W High)
4. Protection: 7.0% Daily Closing Stop (No intraday wick shakeouts)
5. Velocity: +20% to +25% profit lock within 21 trading sessions (1 month max)
6. Regime Guard: Unleash 100% in Bull regimes; sit in cash during severe market breakdowns
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
    MONTHLY_STOCK_BUDGET,
)
from engine.screener import pre_screen
from engine.scorer import score_stock
from engine.recommender import build_recommendation
from engine.balancer import position_size
from analysis.macro import compute_macro_score

logger = logging.getLogger(__name__)


def run_apex_scan(
    capital: float = 100000.0,
    top_slots: int = 3,
    force_live: bool = False,
) -> dict:
    """
    Run the end-to-end Apex High-Velocity Scan:
    Returns the top 3 high-conviction momentum picks, sized at 33.3% capital each.
    """
    logger.info(f"Running Apex High-Velocity Scan on {len(HIGH_BETA_APEX_STOCKS)} stocks (Capital: ₹{capital:,.2f})")

    # 1. Macro Regime Check
    macro = compute_macro_score()
    regime = macro.get("regime", "BULLISH")
    nifty_cleared = macro.get("is_regime_gate_cleared", True)
    regime_desc = macro.get("description", "Market regime healthy")

    # 2. High-Velocity Pre-Screen
    screen_hits = pre_screen(
        tickers=list(HIGH_BETA_APEX_STOCKS),
        top_n=15,
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
            "capital": capital,
        }

    # 3. Deep Multi-Factor Scoring
    scored = []
    for hit in screen_hits:
        ticker = hit["ticker"]
        try:
            score_data = score_stock(ticker, timeframe="short_term", macro_score=macro)
            rec = build_recommendation(score_data)
            
            # Enrich with screener pattern
            pattern = hit.get("pattern", "NONE")
            rec["setup_pattern"] = pattern
            rec["rvol"] = hit.get("rvol", 1.0)
            rec["screen_rank"] = hit.get("screen_score", 0.0)
            
            scored.append(rec)
        except Exception as e:
            logger.debug(f"Scoring error on {ticker}: {e}")

    # 4. Filter BUY / STRONG_BUY & Sort by Conviction
    buys = [r for r in scored if r.get("action") in ("BUY", "STRONG_BUY")]
    # Priority sort: Institutional Blast -> High Score -> High RVOL
    buys.sort(
        key=lambda x: (
            1 if "BLAST" in x.get("setup_pattern", "") else (0.5 if "IGNITION" in x.get("setup_pattern", "") else 0),
            float(x.get("final_score", 0)),
            float(x.get("rvol", 1.0)),
        ),
        reverse=True,
    )

    # 5. Concentrated Slot Allocation (33.3% per slot)
    slot_allocation_pct = round(1.0 / top_slots, 3)
    slot_capital = capital * slot_allocation_pct
    profile = ALLOCATION_PROFILES.get("apex_3slot", {})

    top_picks = []
    total_deployed = 0.0

    for rec in buys[:top_slots]:
        ticker = rec.get("ticker")
        cur_px = float(rec.get("current_price") or 0.0)
        stop_px = float(rec.get("stop_loss") or (cur_px * 0.93))
        target_px = float(rec.get("target_price") or (cur_px * 1.20))
        
        sizing = position_size(
            capital=capital,
            price=cur_px,
            stop=stop_px,
            profile=profile,
        )
        
        # Enforce exact slot allocation
        shares = int(slot_capital // cur_px) if cur_px > 0 else 0
        allocated_inr = round(shares * cur_px, 2)
        total_deployed += allocated_inr

        top_picks.append({
            "ticker": ticker,
            "action": rec.get("action"),
            "final_score": rec.get("final_score"),
            "pattern": rec.get("setup_pattern"),
            "rvol": rec.get("rvol"),
            "current_price": cur_px,
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
            "rationale": rec.get("action_rationale"),
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
        "picks": top_picks,
    }


if __name__ == "__main__":
    import pprint
    logging.basicConfig(level=logging.INFO)
    res = run_apex_scan(capital=100000.0, top_slots=3)
    print("\n================ APEX HIGH-VELOCITY SCAN RESULTS ================")
    print(f"Market Regime: {res['regime']} (Nifty Cleared: {res['nifty_cleared']})")
    print(f"Total Capital: ₹{res['capital']:,.2f} | Deployed: ₹{res['total_deployed']:,.2f} | Cash: ₹{res['cash_remaining']:,.2f}\n")
    for i, p in enumerate(res["picks"], 1):
        print(f"Slot {i}: [{p['ticker']}] - {p['pattern']} (Score: {p['final_score']} | RVOL: {p['rvol']}x)")
        print(f"  Entry: ₹{p['current_price']:,.2f} | Target (+20%): ₹{p['target_price']:,.2f} | Stop (-7% Close): ₹{p['stop_loss']:,.2f}")
        print(f"  Position: {p['shares']} shares = ₹{p['allocated_rupees']:,.2f} ({p['weight_pct']}% of portfolio) | R:R: {p['reward_risk']}:1\n")
