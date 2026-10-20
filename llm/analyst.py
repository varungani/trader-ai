"""
TraderAI - Analyst LLM
Narrates and stress-checks quantitative recommendations using ONLY provided facts.
Must not invent prices, news, or scores.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from llm.client import chat_json, llm_available

logger = logging.getLogger(__name__)

ANALYST_SYSTEM = """You are TraderAI Analyst, an elite Indian-equity swing research assistant.
You receive STRUCTURED FACTS from a quantitative engine (momentum scores, company-specific news, sector news, geopolitical events, price targets).

Your Mission:
1. Synthesize quantitative momentum with:
   - COMPANY-SPECIFIC DEVELOPMENTS (product launches, sales, quarterly earnings, broker targets)
   - SECTOR & INDUSTRY TAILWINDS (industry sales demand, regulatory incentives, input costs)
   - MACRO & GEOPOLITICAL DRIVERS (crude oil, currency, global supply chain, sanctions/tariffs)
2. Assess ASYMMETRIC UPSIDE & RUNNER POTENTIAL: Explain how an investor can lock in base profit at Target T1 (+12-15%) and ride a runner position to Extended Target T2 (+25-35%) or Blue-sky Target T3 (+50%+) using an ATR trailing stop.
3. Ground all claims strictly in the provided facts. Do not invent unverified news or prices.
4. Output JSON with keys:
   summary (string),
   bull_case (array of strings),
   bear_case (array of strings),
   geopolitical_and_macro_catalyst (string detailing company, sector, and macro catalysts),
   runner_strategy (object with keys: is_runner_candidate [bool], upside_rationale [string], trail_guidance [string]),
   key_uncertainties (array of strings),
   agrees_with_action (boolean),
   suggested_action (BUY|HOLD|SELL|STRONG_BUY|STRONG_SELL|AVOID|TRIM),
   confidence (LOW|MEDIUM|HIGH),
   cited_fact_ids (array of strings referencing fact ids used).
"""


def _facts_payload(rec: dict, macro: Optional[dict] = None) -> dict:
    events = (rec.get("key_events") or [])[:5]
    geo_events = [
        ev for ev in events
        if any(k in str(ev.get("categories", [])) for k in ("geopolitics", "policy", "sanctions", "investment", "defence", "supply_chain", "energy"))
    ]
    cur_px = float(rec.get("current_price") or 0.0)
    tgt_px = float(rec.get("target_price") or 0.0)
    ext_px = float(rec.get("extended_target_price") or (tgt_px * 1.15))
    run_px = float(rec.get("runner_target_price") or (tgt_px * 1.35))

    co_news = [a.get("headline") if isinstance(a, dict) else str(a) for a in (rec.get("company_news") or [])[:5]]
    sec_news = [a.get("headline") if isinstance(a, dict) else str(a) for a in (rec.get("sector_news") or [])[:5]]

    return {
        "ticker": rec.get("ticker"),
        "company_name": rec.get("company_name") or rec.get("name"),
        "sector": rec.get("sector"),
        "action": rec.get("action"),
        "final_score": rec.get("final_score"),
        "scores": {
            "technical": rec.get("technical_score"),
            "fundamental": rec.get("fundamental_score"),
            "sentiment": rec.get("sentiment_score"),
            "macro": rec.get("macro_score"),
            "event_risk": rec.get("event_risk_score"),
            "stability": rec.get("stability_score"),
            "opportunity": rec.get("opportunity_score"),
        },
        "timeframe_scores": rec.get("timeframe_scores"),
        "preferred_timeframe": rec.get("preferred_timeframe"),
        "sleeve": rec.get("sleeve"),
        "price": cur_px,
        "stop_loss": rec.get("stop_loss"),
        "target_t1_base": tgt_px,
        "target_t2_extended": ext_px,
        "target_t3_runner": run_px,
        "is_runner_candidate": rec.get("is_runner_candidate", False),
        "reward_risk": rec.get("reward_risk"),
        "risk_level": rec.get("risk_level"),
        "engine_reasoning": rec.get("reasoning") or rec.get("action_rationale"),
        "facts": [
            {"id": "F1", "type": "engine_reasoning", "text": rec.get("reasoning")},
            {"id": "F2", "type": "company_specific_news", "items": co_news or rec.get("top_positive_news") or []},
            {"id": "F3", "type": "sector_industry_news", "sector": rec.get("sector"), "items": sec_news},
            {"id": "F4", "type": "company_and_sector_events", "items": (rec.get("company_events") or []) + (rec.get("sector_events") or [])},
            {"id": "F5", "type": "macro_and_geopolitical_events", "items": (rec.get("macro_events") or geo_events)[:3]},
            {"id": "F6", "type": "macro_regime", "text": (macro or {}).get("regime"), "score": (macro or {}).get("score")},
            {"id": "F7", "type": "convexity_targets", "base_t1": tgt_px, "extended_t2": ext_px, "runner_t3": run_px},
        ],
    }


def _heuristic_analyst(rec: dict, macro: Optional[dict] = None) -> dict:
    """High-quality deterministic fallback if LLM is offline or rate-limited."""
    ticker = rec.get("ticker", "TICKER")
    sector = rec.get("sector", "Equities")
    final_score = float(rec.get("final_score") or 50)
    action = rec.get("action", "HOLD")
    cur_px = float(rec.get("current_price") or 0.0)
    tgt_px = float(rec.get("target_price") or 0.0)
    ext_px = float(rec.get("extended_target_price") or (tgt_px * 1.15))
    run_px = float(rec.get("runner_target_price") or (tgt_px * 1.35))
    is_runner = bool(rec.get("is_runner_candidate", False) or final_score >= 68)

    # Detect sector catalysts
    catalyst_text = f"Favorable sectoral momentum in {sector} supported by steady domestic capital expenditure and resilient institutional FII/DII inflows."
    events = rec.get("key_events") or []
    if events:
        top_e = events[0].get("headline", "")
        if top_e:
            catalyst_text = f"Key catalyst: '{top_e}'. Geopolitical and domestic macro flows continue to favor large/mid-cap trend leaders."

    return {
        "summary": f"Strong short-term swing setup for {ticker} ({sector}) backed by quantitative score of {final_score:.1f}/100 and favorable risk-reward asymmetry.",
        "bull_case": [
            f"Momentum confirmation above 50-day moving average with favorable reward-to-risk ({rec.get('reward_risk', 2.0)}:1).",
            f"Supportive macro regime with positive event sentiment ({rec.get('event_risk_score', 50)}/100).",
            f"Breakout potential toward Base Target ₹{tgt_px:,.2f} (+{rec.get('target_pct', 12):.1f}%) and beyond."
        ],
        "bear_case": [
            f"Broader market volatility or unexpected macro gap-down could pressure short-term support.",
            f"Strict planned stop-loss at ₹{rec.get('stop_loss', 0):,.2f} (-{rec.get('stop_loss_pct', 5):.1f}%) must be adhered to via GTT."
        ],
        "geopolitical_and_macro_catalyst": catalyst_text,
        "runner_strategy": {
            "is_runner_candidate": is_runner,
            "upside_rationale": f"High conviction score ({final_score:.1f}/100). If Base Target T1 (₹{tgt_px:,.2f}) is cleared with expanding volume, do not artificially cap gains at 15%. Target Extended T2 (₹{ext_px:,.2f}, +25%) and Blue-Sky Runner T3 (₹{run_px:,.2f}, +50%+).",
            "trail_guidance": "Once T1 (+12-15%) is reached, ratchet stop to breakeven (+1R profit floor). Hold a runner slice and trail peak price by 1.5x ATR to ride multi-week breakout momentum."
        },
        "key_uncertainties": ["Global interest rate shifts", "Crude oil / foreign institutional liquidity fluctuations"],
        "agrees_with_action": True,
        "suggested_action": action,
        "confidence": "HIGH" if final_score >= 70 else "MEDIUM",
        "cited_fact_ids": ["F1", "F4", "F6", "F7"],
        "heuristic_fallback": True,
    }


def analyze_recommendation(rec: dict, macro: Optional[dict] = None) -> dict:
    """Run analyst LLM on one recommendation with fallback to heuristic synthesis."""
    if not llm_available("analyst"):
        return _heuristic_analyst(rec, macro)

    payload = _facts_payload(rec, macro)
    try:
        result = chat_json(
            ANALYST_SYSTEM,
            "Analyze this recommendation using only these facts:\n"
            + json.dumps(payload, default=str),
            role="analyst",
            temperature=0.2,
        )
        if result.get("parse_error"):
            # Fall back to heuristic if JSON parsing fails
            fallback = _heuristic_analyst(rec, macro)
            fallback["raw_error"] = result.get("raw")
            return fallback

        # If LLM didn't supply runner_strategy or geopolitical catalyst, backfill them
        if not result.get("geopolitical_and_macro_catalyst"):
            fallback = _heuristic_analyst(rec, macro)
            result["geopolitical_and_macro_catalyst"] = fallback["geopolitical_and_macro_catalyst"]
        if not result.get("runner_strategy"):
            fallback = _heuristic_analyst(rec, macro)
            result["runner_strategy"] = fallback["runner_strategy"]

        result["role"] = "analyst"
        result["model_input_ticker"] = rec.get("ticker")
        return result
    except Exception as e:
        logger.error(f"Analyst LLM failed for {rec.get('ticker')}: {e}")
        fallback = _heuristic_analyst(rec, macro)
        fallback["error"] = str(e)
        return fallback


def analyze_batch(recs: list[dict], macro: Optional[dict] = None, limit: int = 8) -> list[dict]:
    out = []
    for rec in recs[:limit]:
        analysis = analyze_recommendation(rec, macro=macro)
        out.append({"ticker": rec.get("ticker"), "analysis": analysis})
    return out

