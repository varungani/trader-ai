"""
TraderAI - Judge LLM (SEPARATE model / role)
Independent auditor that looks at engine maths + analyst narrative from the OUTSIDE.
Flags hallucinations, unsupported claims, and action/score mismatches.
Never generates the original recommendation — only critiques it.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from llm.client import chat_json, llm_available
from config import LLM_JUDGE_MIN_SCORE, LLM_JUDGE_BLOCK_ON_FAIL

logger = logging.getLogger(__name__)

JUDGE_SYSTEM = """You are TraderAI Judge — an independent risk auditor.
You did NOT create the recommendation. You only verify it.

Your job:
1. Detect HALLUCINATIONS: claims in the analyst text not present in FACTS.
2. Detect INCONSISTENCY: action vs scores (e.g. STRONG_BUY with final_score 42).
3. Detect OVERCONFIDENCE: high confidence with thin news / missing data.
4. Detect RISK BLINDNESS: ignoring HIGH event risk, bad reward:risk, or heat.
5. You must stay skeptical. Prefer FAIL or REVISE over PASS when unsure.

Output JSON ONLY:
{
  "verdict": "PASS" | "REVISE" | "FAIL",
  "hallucination_score": 0-100,   // higher = more hallucination risk
  "consistency_score": 0-100,     // higher = more consistent with facts
  "overall_trust": 0-100,         // higher = safer to paper-trade
  "hallucinated_claims": [ {"claim": "...", "why": "not in facts"} ],
  "inconsistencies": [ {"issue": "...", "severity": "LOW|MEDIUM|HIGH"} ],
  "missing_evidence": ["..."],
  "recommended_override_action": null | "BUY"|"HOLD"|"SELL"|"AVOID"|"TRIM",
  "rationale": "short paragraph",
  "allow_paper_trade": true | false
}

Rules for allow_paper_trade:
- false if verdict is FAIL
- false if hallucination_score >= 40
- false if overall_trust < 55
- false if action is BUY/STRONG_BUY but final_score < 60 unless revise justifies
"""


def _heuristic_precheck(rec: dict, analyst: Optional[dict]) -> list[dict]:
    """Deterministic checks the judge also sees — reduces pure LLM drift."""
    issues = []
    action = (rec.get("action") or "").upper()
    score = float(rec.get("final_score") or 50)
    rr = float(rec.get("reward_risk") or 0)
    event = float(rec.get("event_risk_score") or 50)

    if action in ("BUY", "STRONG_BUY") and score < 60:
        issues.append({"issue": f"{action} with final_score {score} < 60", "severity": "HIGH"})
    if action in ("SELL", "STRONG_SELL") and score > 55:
        issues.append({"issue": f"{action} with final_score {score} > 55", "severity": "MEDIUM"})
    if action in ("BUY", "STRONG_BUY") and rr and rr < 1.5:
        issues.append({"issue": f"Reward:risk {rr} below 1.5", "severity": "HIGH"})
    if action in ("BUY", "STRONG_BUY") and event < 30:
        issues.append({"issue": f"Event risk score {event} too low for buys", "severity": "HIGH"})
    if analyst and analyst.get("agrees_with_action") is False:
        issues.append({"issue": "Analyst disagrees with engine action", "severity": "MEDIUM"})
    return issues


def judge_recommendation(
    rec: dict,
    analyst: Optional[dict] = None,
    macro: Optional[dict] = None,
) -> dict:
    """
    Separate judge pass. Falls back to heuristic-only verdict if LLM offline.
    """
    pre = _heuristic_precheck(rec, analyst)
    packet = {
        "recommendation": {
            "ticker": rec.get("ticker"),
            "action": rec.get("action"),
            "final_score": rec.get("final_score"),
            "scores": {
                "technical": rec.get("technical_score"),
                "fundamental": rec.get("fundamental_score"),
                "sentiment": rec.get("sentiment_score"),
                "macro": rec.get("macro_score"),
                "event_risk": rec.get("event_risk_score"),
            },
            "price": rec.get("current_price"),
            "stop_loss": rec.get("stop_loss"),
            "target_price": rec.get("target_price"),
            "reward_risk": rec.get("reward_risk"),
            "risk_level": rec.get("risk_level"),
            "engine_reasoning": rec.get("reasoning") or rec.get("action_rationale"),
            "news_positive": rec.get("top_positive_news") or [],
            "news_negative": rec.get("top_negative_news") or [],
            "key_events": rec.get("key_events") or [],
        },
        "analyst_output": analyst or {"skipped": True},
        "macro": {"regime": (macro or {}).get("regime"), "score": (macro or {}).get("score")},
        "deterministic_flags": pre,
    }

    if not llm_available("judge"):
        return _heuristic_verdict(rec, pre, reason="LLM judge offline — heuristic only")

    try:
        result = chat_json(
            JUDGE_SYSTEM,
            "Audit this packet. Flag anything not grounded in FACTS.\n"
            + json.dumps(packet, default=str),
            role="judge",
            temperature=0.05,
        )
        if result.get("parse_error"):
            return _heuristic_verdict(rec, pre, reason="Judge parse error", raw=result.get("raw"))

        result = _normalize_verdict(result, rec, pre)
        result["role"] = "judge"
        result["ticker"] = rec.get("ticker")
        result["deterministic_flags"] = pre
        return result
    except Exception as e:
        logger.error(f"Judge LLM failed for {rec.get('ticker')}: {e}")
        return _heuristic_verdict(rec, pre, reason=str(e))


def _normalize_verdict(result: dict, rec: dict, pre: list[dict]) -> dict:
    verdict = (result.get("verdict") or "REVISE").upper()
    if verdict not in ("PASS", "REVISE", "FAIL"):
        verdict = "REVISE"
    hall = float(result.get("hallucination_score") or 50)
    trust = float(result.get("overall_trust") or 50)
    allow = bool(result.get("allow_paper_trade"))

    # Hard floors from deterministic flags
    if any(i.get("severity") == "HIGH" for i in pre):
        if verdict == "PASS":
            verdict = "REVISE"
        allow = False
        trust = min(trust, 50)

    if hall >= 40 or trust < LLM_JUDGE_MIN_SCORE:
        allow = False
        if verdict == "PASS":
            verdict = "REVISE"

    if verdict == "FAIL":
        allow = False

    if LLM_JUDGE_BLOCK_ON_FAIL and verdict in ("FAIL", "REVISE") and (rec.get("action") or "") in (
        "BUY", "STRONG_BUY",
    ):
        # Suggest safer override when blocking
        if not result.get("recommended_override_action"):
            result["recommended_override_action"] = "HOLD"

    result["verdict"] = verdict
    result["hallucination_score"] = hall
    result["overall_trust"] = trust
    result["allow_paper_trade"] = allow
    return result


def _heuristic_verdict(rec: dict, pre: list[dict], reason: str = "", raw: str = "") -> dict:
    flags = list(pre)
    high = [i for i in flags if i.get("severity") == "HIGH"]
    
    # If LLM failed due to an error, rate-limit (429), parse issue or timeout, fail-safe!
    is_api_failure = bool(reason) and any(
        kw in reason.lower() for kw in ("error", "429", "rate limit", "quota", "too many requests", "failed", "timeout", "offline", "parse")
    )
    
    if high:
        verdict, allow, trust, hall = "FAIL", False, 35, 20
    elif is_api_failure:
        # Never pass unverified picks when API errors occur
        verdict, allow, trust, hall = "REVISE", False, 45, 25
        flags.append({"issue": f"Judge unverified ({reason})", "severity": "HIGH"})
    elif flags:
        verdict, allow, trust, hall = "REVISE", False, 50, 15
    else:
        verdict, allow, trust, hall = "PASS", True, 70, 5

    return {
        "role": "judge",
        "ticker": rec.get("ticker"),
        "verdict": verdict,
        "hallucination_score": hall,
        "consistency_score": max(10, 100 - 20 * len(flags)),
        "overall_trust": trust,
        "hallucinated_claims": [],
        "inconsistencies": flags,
        "missing_evidence": ["API verification incomplete"] if is_api_failure else [],
        "recommended_override_action": "HOLD" if not allow and (rec.get("action") in ("BUY", "STRONG_BUY")) else None,
        "rationale": f"⚠️ Audit Unverified: {reason}" if is_api_failure else (reason or "Heuristic judge (no LLM)."),
        "allow_paper_trade": allow,
        "deterministic_flags": flags,
        "raw": raw,
        "heuristic_only": True,
    }


def judge_batch(
    items: list[dict],
    macro: Optional[dict] = None,
    limit: int = 8,
) -> list[dict]:
    """
    items: [{recommendation, analyst?}, ...]
    """
    out = []
    for item in items[:limit]:
        rec = item.get("recommendation") or item
        analyst = item.get("analysis") or item.get("analyst")
        out.append(judge_recommendation(rec, analyst=analyst, macro=macro))
    return out
