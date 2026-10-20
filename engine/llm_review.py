"""
TraderAI - LLM review orchestration
Runs Analyst then independent Judge; applies overrides for paper trading.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import LLM_JUDGE_BLOCK_ON_FAIL, LLM_MAX_REVIEW
from llm.analyst import analyze_recommendation
from llm.judge import judge_recommendation
from llm.client import llm_available

logger = logging.getLogger(__name__)


def review_recommendations(
    recommendations: list[dict],
    macro: Optional[dict] = None,
    limit: Optional[int] = None,
) -> dict:
    """
    Prefer reviewing buys, sells, and held names first.
    Returns reviews + recommendations with optional action overrides.
    """
    limit = limit or LLM_MAX_REVIEW
    prioritized = _prioritize(recommendations)[:limit]

    reviews = []
    updated = {r.get("ticker"): dict(r) for r in recommendations}

    backend_ok = llm_available("analyst") or llm_available("judge")
    for rec in prioritized:
        ticker = rec.get("ticker")
        analyst = analyze_recommendation(rec, macro=macro)
        judge = judge_recommendation(rec, analyst=analyst if not analyst.get("skipped") else None, macro=macro)

        override = None
        final_action = rec.get("action")

        # DETERMINISTIC RISK PROTECTION:
        # If an existing holding has breached its stop-loss or triggered an exit,
        # the AI is STRICTLY FORBIDDEN from overriding or suppressing a SELL signal.
        if rec.get("holding") and rec.get("action") in ("SELL", "STRONG_SELL"):
            final_action = rec.get("action")
            override = None
        elif LLM_JUDGE_BLOCK_ON_FAIL and not judge.get("allow_paper_trade"):
            if final_action in ("BUY", "STRONG_BUY"):
                override = judge.get("recommended_override_action") or "HOLD"
                final_action = override


        if ticker in updated:
            updated[ticker]["llm_analyst"] = analyst
            updated[ticker]["llm_judge"] = judge
            updated[ticker]["action_before_judge"] = rec.get("action")
            updated[ticker]["action"] = final_action
            if override:
                updated[ticker]["judge_override"] = override
                note = updated[ticker].get("portfolio_note") or ""
                updated[ticker]["portfolio_note"] = (
                    (note + " " if note else "")
                    + f"Judge {judge.get('verdict')}: blocked for paper deploy."
                ).strip()

        reviews.append(
            {
                "ticker": ticker,
                "action_original": rec.get("action"),
                "action_final": final_action,
                "analyst": analyst,
                "judge": judge,
            }
        )
        time.sleep(1.0)

    merged = list(updated.values())
    merged.sort(key=lambda r: float(r.get("final_score") or 0), reverse=True)

    summary = {
        "reviewed": len(reviews),
        "llm_backend_available": backend_ok,
        "pass": sum(1 for r in reviews if (r.get("judge") or {}).get("verdict") == "PASS"),
        "revise": sum(1 for r in reviews if (r.get("judge") or {}).get("verdict") == "REVISE"),
        "fail": sum(1 for r in reviews if (r.get("judge") or {}).get("verdict") == "FAIL"),
        "paper_allowed": sum(1 for r in reviews if (r.get("judge") or {}).get("allow_paper_trade")),
    }

    return {
        "reviews": reviews,
        "recommendations": merged,
        "summary": summary,
    }


def _prioritize(recs: list[dict]) -> list[dict]:
    def rank(r):
        action = r.get("action") or ""
        held = 1 if r.get("holding") else 0
        score = float(r.get("final_score") or 0)
        action_pri = {
            "STRONG_BUY": 0,
            "BUY": 1,
            "STRONG_SELL": 2,
            "SELL": 3,
            "TRIM": 4,
            "AVOID": 5,
            "HOLD": 6,
        }.get(action, 7)
        return (0 if held else 1, action_pri, -score)

    return sorted(recs, key=rank)
