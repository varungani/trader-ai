"""
TraderAI - Portfolio Balancer
Balances:
  • risk vs stability
  • short / mid / long term sleeves
  • minimal losses vs maximum profit (reward:risk + position sizing + portfolio heat)
"""
from __future__ import annotations

import logging
import math
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    ALLOCATION_PROFILES,
    DEFAULT_ALLOCATION_PROFILE,
    RISK_CONFIG,
    TICKER_TO_SECTOR,
    MIN_DELIVERY_TICKET_RUPEES,
)

logger = logging.getLogger(__name__)


def weighted_score(components: dict, timeframe: str) -> float:
    from config import TIMEFRAMES

    weights = TIMEFRAMES.get(timeframe, TIMEFRAMES["short_term"])["weights"]
    total = 0.0
    wsum = 0.0
    for k, w in weights.items():
        if k in components:
            total += float(components[k]) * w
            wsum += w
    return round(total / wsum if wsum else 50.0, 1)


def multi_timeframe_scores(components: dict) -> dict:
    return {
        "short_term": weighted_score(components, "short_term"),
        "mid_term": weighted_score(components, "mid_term"),
        "long_term": weighted_score(components, "long_term"),
    }


def stability_score(rec: dict) -> float:
    """
    Higher = more defensive / capital-preserving.
    Favours strong fundamentals, calm volatility, clean events.
    Temporary weak technicals hurt less (long-horizon sleeve).
    """
    fund = float(rec.get("fundamental_score") or 50)
    events = float(rec.get("event_risk_score") or 50)
    tech = float(rec.get("technical_score") or 50)
    atr = float((rec.get("technical") or {}).get("atr_percent") or 0)
    risk = rec.get("risk_level") or "MEDIUM"

    # Volatility: main stability drag
    if atr > 3.5:
        vol_score = 25
    elif atr > 2.0:
        vol_score = 45
    elif atr > 1.2:
        vol_score = 65
    else:
        vol_score = 85

    risk_pen = {"LOW": 0, "MEDIUM": 5, "HIGH": 12}.get(risk, 8)
    # Fundamentals + events dominate; light technical touch
    score = 0.45 * fund + 0.30 * events + 0.20 * vol_score + 0.05 * tech
    score -= risk_pen
    return round(max(0, min(100, score)), 1)


def opportunity_score(rec: dict) -> float:
    """Higher = more profit / momentum potential (still gated by events)."""
    tech = float(rec.get("technical_score") or 50)
    sent = float(rec.get("sentiment_score") or 50)
    final = float(rec.get("final_score") or 50)
    events = float(rec.get("event_risk_score") or 50)
    rr = float(rec.get("reward_risk") or 0)
    rr_boost = min(15, max(0, (rr - 1.5) * 8))
    score = 0.35 * tech + 0.25 * sent + 0.25 * final + 0.15 * events + rr_boost
    return round(max(0, min(100, score)), 1)


def best_timeframe(tf_scores: dict) -> str:
    return "short_term"


def classify_sleeve(rec: dict) -> str:
    """Map a name into stability / growth / opportunistic sleeve."""
    stab = float(rec.get("stability_score") or stability_score(rec))
    opp = float(rec.get("opportunity_score") or opportunity_score(rec))
    tf = rec.get("preferred_timeframe") or best_timeframe(rec.get("timeframe_scores") or {})
    risk = rec.get("risk_level") or "MEDIUM"

    # Short-term high-risk = opportunistic only
    if tf == "short_term" and (risk == "HIGH" or opp > stab + 5):
        return "opportunistic"
    # Long-horizon / quality tilt = stability
    if tf == "long_term" or stab >= max(50, opp):
        return "stability"
    return "growth"


def compute_reward_risk(price: float, stop: Optional[float], target: Optional[float]) -> float:
    import math
    if not price or not stop or not target:
        return 0.0
    try:
        p, s, t = float(price), float(stop), float(target)
        if math.isnan(p) or math.isnan(s) or math.isnan(t) or p <= s:
            return 0.0
        risk = p - s
        reward = t - p
        if risk <= 0:
            return 0.0
        return round(reward / risk, 2)
    except Exception:
        return 0.0


def position_size(
    capital: float,
    price: float,
    stop: Optional[float],
    profile: dict,
) -> dict:
    """
    Size so that a stop-out loses ~risk_per_trade_pct of capital,
    capped by max_position_pct.
    """
    import math

    if not capital or math.isnan(capital) or capital <= 0:
        return {"qty": 0, "rupees": 0.0, "risk_rupees": 0.0, "weight_pct": 0.0}
    if not price or math.isnan(price) or price <= 0:
        return {"qty": 0, "rupees": 0.0, "risk_rupees": 0.0, "weight_pct": 0.0}
    if not stop or math.isnan(stop) or stop >= price or (price - stop) <= 0:
        return {"qty": 0, "rupees": 0.0, "risk_rupees": 0.0, "weight_pct": 0.0}

    risk_budget = capital * RISK_CONFIG["risk_per_trade_pct"]
    per_share_risk = price - stop
    qty_by_risk = int(risk_budget // per_share_risk) if per_share_risk > 0 else 0
    max_rupees = capital * RISK_CONFIG["max_position_pct"]
    qty_by_cap = int(max_rupees // price) if price > 0 else 0
    qty = max(0, min(qty_by_risk, qty_by_cap))
    rupees = round(qty * price, 2)
    risk_rupees = round(qty * per_share_risk, 2)
    binding = f"CAPITAL_CAP ({int(RISK_CONFIG['max_position_pct']*100)}%)" if qty_by_cap <= qty_by_risk else f"RISK_BUDGET ({int(RISK_CONFIG['risk_per_trade_pct']*100)}%)"
    planned_risk_pct = round((risk_rupees / capital) * 100, 2) if capital else 0.0

    below_min_ticket = bool(0 < rupees < MIN_DELIVERY_TICKET_RUPEES and capital >= MIN_DELIVERY_TICKET_RUPEES)
    if below_min_ticket:
        binding += f" | WARNING: Size < ₹{MIN_DELIVERY_TICKET_RUPEES:,.0f} (DP fee friction > 0.45%)"

    return {
        "qty": qty,
        "rupees": rupees,
        "risk_rupees": risk_rupees,
        "weight_pct": round(rupees / capital * 100, 2) if capital else 0.0,
        "binding_constraint": binding,
        "planned_risk_pct": planned_risk_pct,
        "below_min_ticket": below_min_ticket,
    }


def enrich_recommendation(rec: dict, capital: float = 0.0) -> dict:
    """Attach stability/opportunity, multi-TF scores, RR, and suggested size."""
    out = dict(rec)
    components = {
        "technical": float(rec.get("technical_score") or 50),
        "fundamental": float(rec.get("fundamental_score") or 50),
        "sentiment": float(rec.get("sentiment_score") or 50),
        "macro": float(rec.get("macro_score") or 50),
        "event_risk": float(rec.get("event_risk_score") or 50),
    }
    # Prefer components already computed inside nested blobs if present
    if rec.get("technical") and "score" in (rec.get("technical") or {}):
        components["technical"] = float(rec["technical"]["score"])

    tf_scores = rec.get("timeframe_scores") or multi_timeframe_scores(components)
    out["timeframe_scores"] = tf_scores
    out["preferred_timeframe"] = best_timeframe(tf_scores)

    price = float(rec.get("current_price") or 0)
    stop = rec.get("stop_loss")
    target = rec.get("target_price")

    # Enforce min reward:risk by stretching target if needed (recommendation only)
    rr = compute_reward_risk(price, stop, target)
    min_rr = RISK_CONFIG.get("min_reward_risk", 2.0)
    if price and stop and stop < price and rr < min_rr:
        risk = price - float(stop)
        target = round(price + min_rr * risk, 2)
        rr = min_rr
        out["target_price"] = target
        out["target_adjusted_for_rr"] = True

    out["reward_risk"] = rr
    out["stability_score"] = stability_score(out)
    out["opportunity_score"] = opportunity_score(out)
    out["sleeve"] = classify_sleeve(out)

    # Expectancy proxy: map final_score to win probability 0.35–0.72
    final = float(out.get("final_score") or 50)
    win_p = 0.35 + (final / 100.0) * 0.37
    # Normalise RR into unit risk
    out["expectancy_per_rupee_risk"] = round(win_p * rr - (1 - win_p) * 1.0, 3)
    out["win_prob_proxy"] = round(win_p, 3)

    if capital > 0:
        out["suggested_size"] = position_size(capital, price, stop, {})
    else:
        out["suggested_size"] = {"qty": 0, "rupees": 0.0, "risk_rupees": 0.0, "weight_pct": 0.0}

    # Gate buys that fail RR or negative expectancy
    if out.get("action") in ("BUY", "STRONG_BUY"):
        if rr < min_rr * 0.9:
            out["action"] = "HOLD"
            out["action_rationale"] = f"Blocked: reward:risk {rr} < {min_rr} minimum."
        elif out["expectancy_per_rupee_risk"] < 0:
            out["action"] = "HOLD"
            out["action_rationale"] = "Blocked: negative expectancy proxy (loss risk > edge)."

    return out


def _capital_base(portfolio: Optional[dict], capital_override: Optional[float]) -> float:
    if capital_override and capital_override > 0:
        return float(capital_override)
    if not portfolio:
        return 0.0
    val = float(portfolio.get("total_current_value") or 0)
    cash = float((portfolio.get("cash") if "cash" in portfolio else 0) or 0)
    # portfolio_summary doesn't include cash; allow broker/local raw
    return val + cash if val or cash else 0.0


def current_mix(recommendations: list[dict], portfolio: Optional[dict]) -> dict:
    """Estimate current sleeve / timeframe / risk mix from holdings."""
    holdings = {h["symbol"]: h for h in (portfolio or {}).get("holdings") or []}
    total = float((portfolio or {}).get("total_current_value") or 0)
    if total <= 0:
        return {
            "by_sleeve": {},
            "by_timeframe": {},
            "by_risk": {},
            "total": 0,
        }

    by_sleeve = {"stability": 0.0, "growth": 0.0, "opportunistic": 0.0}
    by_tf = {"short_term": 0.0, "mid_term": 0.0, "long_term": 0.0}
    by_risk = {"LOW": 0.0, "MEDIUM": 0.0, "HIGH": 0.0}

    rec_map = {r.get("ticker"): r for r in recommendations if r.get("ticker")}
    for sym, h in holdings.items():
        px = float(h.get("current_price") or h.get("avg_price") or 0)
        qty = float(h.get("quantity") or 0)
        value = px * qty
        rec = rec_map.get(sym) or {}
        # Prioritize user's designated timeframe bucket for this holding
        tf = h.get("timeframe") or rec.get("preferred_timeframe") or "short_term"
        risk = rec.get("risk_level") or "MEDIUM"
        sleeve = rec.get("sleeve") or "growth"
        by_sleeve[sleeve] = by_sleeve.get(sleeve, 0) + value
        by_tf[tf] = by_tf.get(tf, 0) + value
        by_risk[risk] = by_risk.get(risk, 0) + value

    def pct(d):
        return {k: round(v / total * 100, 1) for k, v in d.items()}

    return {
        "by_sleeve": pct(by_sleeve),
        "by_timeframe": pct(by_tf),
        "by_risk": pct(by_risk),
        "total": round(total, 2),
    }


def build_balance_plan(
    recommendations: list[dict],
    portfolio: Optional[dict] = None,
    profile_name: str = DEFAULT_ALLOCATION_PROFILE,
    capital: Optional[float] = None,
) -> dict:
    """
    Produce target allocation + concrete rebalance / deploy actions that
    balance risk↔stability, horizons, and loss-control vs upside.
    """
    profile = ALLOCATION_PROFILES.get(profile_name) or ALLOCATION_PROFILES[DEFAULT_ALLOCATION_PROFILE]
    capital_base = _capital_base(portfolio, capital)
    # If no portfolio value yet, use a notional so % plan still useful
    notional = capital_base if capital_base > 0 else 1_000_000.0
    using_notional = capital_base <= 0

    enriched = [enrich_recommendation(r, capital=notional) for r in recommendations]

    # Budget-Adaptive Ranking:
    # If notional capital <= 25,000, prioritize high-expectancy setups where the user can afford >= 2 shares
    def _rank_enriched(r):
        expectancy = float(r.get("expectancy_per_rupee_risk") or -99)
        final = float(r.get("final_score") or 0)
        px = float(r.get("current_price") or 0)
        if 0 < notional <= 25000 and px > 0:
            slot = notional * RISK_CONFIG.get("max_position_pct", 0.20)
            affordable_qty = int(slot // px)
            affordability_boost = 0.20 if affordable_qty >= 2 else (0.05 if affordable_qty == 1 else -0.50)
            return (expectancy + affordability_boost, final)
        return (expectancy, final)

    enriched.sort(key=_rank_enriched, reverse=True)

    current = current_mix(enriched, portfolio)
    targets = {
        "cash_pct": round(profile["cash_pct"] * 100, 1),
        "stability_pct": round(profile["stability_pct"] * 100, 1),
        "growth_pct": round(profile["growth_pct"] * 100, 1),
        "opportunistic_pct": round(profile["opportunistic_pct"] * 100, 1),
        "timeframe_pct": {
            k: round(v * 100, 1) for k, v in profile["timeframe_targets"].items()
        },
        "max_high_risk_pct": round(profile["max_high_risk_pct"] * 100, 1),
        "min_low_risk_pct": round(profile["min_low_risk_pct"] * 100, 1),
    }

    sleeve_budgets = {
        "stability": notional * profile["stability_pct"],
        "growth": notional * profile["growth_pct"],
        "opportunistic": notional * profile["opportunistic_pct"],
    }
    cash_budget = notional * profile["cash_pct"]

    deploy = []
    heat = 0.0
    max_heat = notional * RISK_CONFIG.get("max_portfolio_heat", 0.08)
    filled = {"stability": 0.0, "growth": 0.0, "opportunistic": 0.0}
    tf_filled = {"short_term": 0.0, "mid_term": 0.0, "long_term": 0.0}
    tf_targets_inr = {
        k: notional * (1 - profile["cash_pct"]) * v
        for k, v in profile["timeframe_targets"].items()
    }

    candidates = [
        r for r in enriched
        if r.get("action") in ("BUY", "STRONG_BUY")
        and float(r.get("expectancy_per_rupee_risk") or 0) > 0
        and float(r.get("reward_risk") or 0) >= RISK_CONFIG.get("min_reward_risk", 2.0) * 0.9
    ]

    for r in candidates:
        sleeve = r.get("sleeve") or "growth"
        tf = r.get("preferred_timeframe") or "short_term"
        size = position_size(
            notional,
            float(r.get("current_price") or 0),
            r.get("stop_loss"),
            profile,
        )
        if size["qty"] <= 0:
            continue
        # Respect sleeve remaining budget
        remaining = sleeve_budgets[sleeve] - filled[sleeve]
        if remaining <= 0:
            continue
        if size["rupees"] > remaining:
            # shrink
            px = float(r.get("current_price") or 0)
            if not px or math.isnan(px) or px <= 0:
                continue
            qty = int(remaining // px)
            if qty <= 0:
                continue
            size = {
                "qty": qty,
                "rupees": round(qty * px, 2),
                "risk_rupees": round(qty * (px - float(r["stop_loss"])), 2) if r.get("stop_loss") else 0,
                "weight_pct": round(qty * px / notional * 100, 2),
            }
        # Timeframe budget soft cap
        if tf_filled[tf] >= tf_targets_inr.get(tf, notional):
            # allow small overflow only for high expectancy
            if float(r.get("expectancy_per_rupee_risk") or 0) < 0.35:
                continue
        # Portfolio heat
        if heat + size["risk_rupees"] > max_heat:
            continue

        filled[sleeve] += size["rupees"]
        tf_filled[tf] += size["rupees"]
        heat += size["risk_rupees"]
        deploy.append(
            {
                "ticker": r.get("ticker"),
                "action": "DEPLOY",
                "sleeve": sleeve,
                "preferred_timeframe": tf,
                "final_score": r.get("final_score"),
                "stability_score": r.get("stability_score"),
                "opportunity_score": r.get("opportunity_score"),
                "reward_risk": r.get("reward_risk"),
                "expectancy_per_rupee_risk": r.get("expectancy_per_rupee_risk"),
                "qty": size["qty"],
                "rupees": size["rupees"],
                "risk_rupees": size["risk_rupees"],
                "weight_pct": size["weight_pct"],
                "stop_loss": r.get("stop_loss"),
                "target_price": r.get("target_price"),
                "risk_level": r.get("risk_level"),
            }
        )

    # Trim suggestions for holdings that break mix
    trims = []
    holdings = (portfolio or {}).get("holdings") or []
    rec_map = {r.get("ticker"): r for r in enriched}
    high_risk_pct = float((current.get("by_risk") or {}).get("HIGH") or 0)
    if high_risk_pct > profile["max_high_risk_pct"] * 100:
        for h in holdings:
            rec = rec_map.get(h.get("symbol")) or {}
            if rec.get("risk_level") == "HIGH" or rec.get("action") in ("SELL", "STRONG_SELL", "TRIM"):
                trims.append(
                    {
                        "ticker": h.get("symbol"),
                        "action": "TRIM",
                        "reason": f"High-risk sleeve overweight ({high_risk_pct}% > "
                                  f"{profile['max_high_risk_pct']*100:.0f}% cap).",
                        "risk_level": rec.get("risk_level"),
                        "final_score": rec.get("final_score"),
                    }
                )

    for h in holdings:
        rec = rec_map.get(h.get("symbol")) or {}
        if rec.get("action") in ("SELL", "STRONG_SELL"):
            trims.append(
                {
                    "ticker": h.get("symbol"),
                    "action": rec.get("action"),
                    "reason": rec.get("action_rationale") or "Score / event risk exit.",
                    "risk_level": rec.get("risk_level"),
                    "final_score": rec.get("final_score"),
                }
            )

    gaps = {
        "stability": round(targets["stability_pct"] - float((current.get("by_sleeve") or {}).get("stability") or 0), 1),
        "growth": round(targets["growth_pct"] - float((current.get("by_sleeve") or {}).get("growth") or 0), 1),
        "opportunistic": round(
            targets["opportunistic_pct"] - float((current.get("by_sleeve") or {}).get("opportunistic") or 0), 1
        ),
        "timeframes": {
            tf: round(
                targets["timeframe_pct"][tf] - float((current.get("by_timeframe") or {}).get(tf) or 0),
                1,
            )
            for tf in ("short_term", "mid_term", "long_term")
        },
    }

    balance_score = _balance_health(current, targets, profile)

    guidance = _guidance_text(profile, balance_score, gaps, heat, max_heat, using_notional, notional)

    return {
        "profile": profile_name,
        "profile_label": profile["label"],
        "profile_description": profile["description"],
        "capital_base": round(capital_base, 2),
        "notional_used": round(notional, 2),
        "using_notional": using_notional,
        "cash_budget": round(cash_budget, 2),
        "targets": targets,
        "current_mix": current,
        "gaps_pct": gaps,
        "balance_health": balance_score,
        "portfolio_heat_rupees": round(heat, 2),
        "max_heat_rupees": round(max_heat, 2),
        "heat_pct": round(heat / notional * 100, 2) if notional else 0,
        "deploy_plan": deploy,
        "trim_plan": trims,
        "enriched_recommendations": enriched,
        "top_stability": sorted(enriched, key=lambda r: r.get("stability_score") or 0, reverse=True)[:5],
        "top_opportunity": sorted(enriched, key=lambda r: r.get("opportunity_score") or 0, reverse=True)[:5],
        "guidance": guidance,
    }


def _balance_health(current: dict, targets: dict, profile: dict) -> dict:
    """0-100 health for risk mix, timeframe mix, and overall."""
    sleeve = current.get("by_sleeve") or {}
    tf = current.get("by_timeframe") or {}
    risk = current.get("by_risk") or {}

    def abs_gap(actual, target):
        return abs(float(actual or 0) - float(target or 0))

    sleeve_err = (
        abs_gap(sleeve.get("stability"), targets["stability_pct"])
        + abs_gap(sleeve.get("growth"), targets["growth_pct"])
        + abs_gap(sleeve.get("opportunistic"), targets["opportunistic_pct"])
    ) / 3

    tf_err = sum(
        abs_gap(tf.get(k), targets["timeframe_pct"][k])
        for k in ("short_term", "mid_term", "long_term")
    ) / 3

    high = float(risk.get("HIGH") or 0)
    low = float(risk.get("LOW") or 0)
    risk_pen = 0
    if high > targets["max_high_risk_pct"]:
        risk_pen += (high - targets["max_high_risk_pct"]) * 1.5
    if low < targets["min_low_risk_pct"]:
        risk_pen += (targets["min_low_risk_pct"] - low) * 1.2

    # empty portfolio: neutral-low until funded
    if current.get("total", 0) <= 0:
        return {
            "overall": 55,
            "sleeve": 55,
            "timeframe": 55,
            "risk": 55,
            "note": "No holdings yet — health reflects target plan readiness.",
        }

    sleeve_h = max(0, 100 - sleeve_err * 2)
    tf_h = max(0, 100 - tf_err * 2)
    risk_h = max(0, 100 - risk_pen)
    overall = round(0.35 * sleeve_h + 0.35 * tf_h + 0.30 * risk_h, 1)
    return {
        "overall": overall,
        "sleeve": round(sleeve_h, 1),
        "timeframe": round(tf_h, 1),
        "risk": round(risk_h, 1),
        "note": "Higher is better alignment to your chosen profile.",
    }


def _guidance_text(profile, health, gaps, heat, max_heat, using_notional, notional) -> list[str]:
    lines = [
        f"Profile: {profile['label']} — {profile['description']}.",
        f"Balance health: {health.get('overall')}/100 "
        f"(sleeve {health.get('sleeve')}, horizon {health.get('timeframe')}, risk {health.get('risk')}).",
    ]
    if using_notional:
        lines.append(
            f"No portfolio value detected — plan sized on notional INR {notional:,.0f}. "
            "Sync Kotak or add holdings for live sizing."
        )
    # Biggest gaps
    sleeve_gaps = [(k, v) for k, v in gaps.items() if k != "timeframes"]
    under = sorted(sleeve_gaps, key=lambda x: x[1])
    if under and under[0][1] < -5:
        lines.append(f"Overweight {under[0][0]} by {-under[0][1]:.0f}% — trim or stop adding.")
    over_need = sorted(sleeve_gaps, key=lambda x: -x[1])
    if over_need and over_need[0][1] > 5:
        lines.append(f"Underweight {over_need[0][0]} by {over_need[0][1]:.0f}% — deploy here first.")

    tf_gaps = gaps.get("timeframes") or {}
    for tf, g in sorted(tf_gaps.items(), key=lambda x: -abs(x[1])):
        if abs(g) >= 8:
            direction = "add" if g > 0 else "reduce"
            lines.append(f"Horizon: {direction} {tf.replace('_', ' ')} exposure (gap {g:+.0f}%).")
            break

    lines.append(
        f"Portfolio heat (capital at stop risk): INR {heat:,.0f} / INR {max_heat:,.0f} max "
        f"({RISK_CONFIG.get('max_portfolio_heat', 0.08)*100:.0f}% rule)."
    )
    lines.append(
        f"Every deploy aims for >={RISK_CONFIG.get('min_reward_risk', 2.0):.1f}:1 reward:risk "
        f"and risks only ~{RISK_CONFIG['risk_per_trade_pct']*100:.0f}% of capital if stopped out."
    )
    return lines
