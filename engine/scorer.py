"""
TraderAI - Multi-factor stock scorer
Combines technical, fundamental, sentiment, macro, and event-risk scores
using timeframe-specific weights from config.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import RISK_CONFIG, TIMEFRAMES, TICKER_TO_SECTOR
from data.market_data import fetch_stock_history, fetch_stock_info
from data.news_oss import fetch_company_news_oss, fetch_sector_news
from analysis.technical import compute_technical_score, compute_support_resistance
from analysis.fundamental import compute_fundamental_score
from analysis.sentiment import compute_sentiment_score
from analysis.event_risk import compute_event_risk_score, summarize_event_context

logger = logging.getLogger(__name__)


def _period_for_timeframe(timeframe: str) -> str:
    # Swing trading uses 1y of daily data to reliably calculate 20, 50, 200 SMA and ATR
    return "1y"


def score_stock(
    ticker: str,
    timeframe: str = "short_term",
    macro_score: Optional[dict] = None,
    macro_news: Optional[list] = None,
) -> dict:
    """
    Full multi-factor score for one ticker and timeframe (Pure Swing Trading Focus).

    Returns dict with component scores, final_score, action hint fields, reasoning.
    """
    if timeframe not in TIMEFRAMES:
        timeframe = "short_term"

    weights = TIMEFRAMES[timeframe]["weights"]
    sector = TICKER_TO_SECTOR.get(ticker, "")
    errors = []

    # Market / fundamentals
    period = _period_for_timeframe(timeframe)
    history = fetch_stock_history(ticker, period=period)
    info = fetch_stock_info(ticker)
    company_name = info.get("name") or ""

    technical = compute_technical_score(history, ticker=ticker)
    if technical.get("error"):
        errors.append(technical["error"])

    fundamental = compute_fundamental_score(info)
    if fundamental.get("error"):
        errors.append(fundamental["error"])

    # News + sentiment + events
    company_news = fetch_company_news_oss(ticker, company_name=company_name, days_back=10)
    sector_news = fetch_sector_news(sector, max_articles=12) if sector else []
    sentiment = compute_sentiment_score(company_news + sector_news[:5], ticker=ticker)
    event_risk = compute_event_risk_score(
        company_news=company_news,
        sector_news=sector_news,
        macro_news=macro_news or [],
        ticker=ticker,
    )

    if macro_score is None:
        from analysis.macro import compute_macro_score

        macro_score = compute_macro_score()

    # ─── DYNAMIC WEIGHT REDISTRIBUTION (Prevents Neutral Score Compression) ───
    # If auxiliary data streams (news NLP / specific event alerts) have NO_DATA,
    # we do NOT assign a lukewarm 50 penalty anchor that compresses 80+ breakouts.
    # We dynamically reallocate their weights to Technical Momentum (ground truth).
    has_sentiment = bool(sentiment.get("label") != "NO_DATA" and sentiment.get("total_articles", 0) > 0)
    has_event_risk = bool(event_risk.get("event_matches") or event_risk.get("has_event_data"))

    active_weights = dict(weights)
    if not has_sentiment and "sentiment" in active_weights:
        sent_w = active_weights.pop("sentiment")
        active_weights["technical"] = active_weights.get("technical", 0.45) + sent_w

    if not has_event_risk and "event_risk" in active_weights:
        ev_w = active_weights.pop("event_risk")
        active_weights["technical"] = active_weights.get("technical", 0.45) + (ev_w * 0.70)
        active_weights["fundamental"] = active_weights.get("fundamental", 0.10) + (ev_w * 0.30)

    components = {
        "technical": float(technical.get("score", 50)),
        "fundamental": float(fundamental.get("score", 50)),
        "sentiment": float(sentiment.get("score_100", 50)),
        "macro": float(macro_score.get("score", 50)),
        "event_risk": float(event_risk.get("score", 50)),
    }

    final = 0.0
    used_w = 0.0
    for key, w in active_weights.items():
        if key in components:
            final += components[key] * w
            used_w += w
    final_score = final / used_w if used_w else 50.0

    # Sector Relative Strength (RS) Bonus / Penalty (with Decoupled Alpha Bypass)
    from analysis.sector_rs import compute_sector_rs
    effective_sector = sector or info.get("sector", "")
    sector_rs_data = compute_sector_rs(effective_sector)
    sector_rs_bonus = float(sector_rs_data.get("bonus_points") or 0.0)

    tech_score = float(technical.get("score", 50))
    is_ignition = bool((technical.get("indicators") or {}).get("ignition", {}).get("is_ignition"))
    if sector_rs_bonus < 0 and (is_ignition or tech_score >= 72.0):
        # Do not penalize decoupled high-momentum leaders for broad sector drag
        sector_rs_bonus = 0.0

    final_score = max(0.0, min(100.0, final_score + sector_rs_bonus))

    # Levels
    levels = compute_support_resistance(history) if not history.empty else {}
    price = float(
        technical.get("current_price")
        or info.get("current_price")
        or levels.get("current_price")
        or 0
    )
    atr_pct = float(technical.get("atr_percent") or 0)
    # Dynamic ATR Stop: 2.0x ATR bounded between 3.5% (calm large caps) and 6.0% (hard risk ceiling)
    if atr_pct > 0:
        stop_pct = min(0.06, max(0.035, (atr_pct / 100.0) * 2.0))
    else:
        stop_pct = RISK_CONFIG.get("default_stop_loss_pct", 0.05)

    # Aim for min reward:risk using dynamic ATR-aware stop
    min_rr = RISK_CONFIG.get("min_reward_risk", 2.0)
    target_pct = max(RISK_CONFIG.get("default_target_pct", 0.12), stop_pct * min_rr)

    stop_loss = round(price * (1 - stop_pct), 2) if price else None
    target_price = round(price * (1 + target_pct), 2) if price else None

    from engine.balancer import multi_timeframe_scores, stability_score, opportunity_score, compute_reward_risk

    tf_scores = multi_timeframe_scores(components)
    pref_tf = "short_term"
    rr = compute_reward_risk(price, stop_loss, target_price)

    reasoning = _build_reasoning(
        ticker=ticker,
        timeframe=timeframe,
        components=components,
        technical=technical,
        fundamental=fundamental,
        sentiment=sentiment,
        event_risk=event_risk,
        macro_score=macro_score,
    )

    risk_level = _risk_level(components, event_risk, technical)

    base = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "ticker": ticker,
        "name": company_name,
        "sector": effective_sector,
        "sector_relative_strength": sector_rs_data,
        "timeframe": timeframe,
        "technical_score": round(components["technical"], 1),
        "fundamental_score": round(components["fundamental"], 1),
        "sentiment_score": round(components["sentiment"], 1),
        "macro_score": round(components["macro"], 1),
        "event_risk_score": round(components["event_risk"], 1),
        "final_score": round(final_score, 1),
        "timeframe_scores": tf_scores,
        "preferred_timeframe": pref_tf,
        "reward_risk": rr,
        "current_price": price,
        "stop_loss": stop_loss,
        "target_price": target_price,
        "risk_level": risk_level,
        "reasoning": reasoning,
        "weights": weights,
        "technical": technical,
        "fundamental": fundamental,
        "sentiment": sentiment,
        "event_risk": event_risk,
        "levels": levels,
        "errors": errors,
        "news_count": len(company_news),
        "company_news": company_news[:8],
        "sector_news": sector_news[:8],
        "company_name": company_name,
    }
    base["stability_score"] = stability_score(base)
    base["opportunity_score"] = opportunity_score(base)
    return base


def _risk_level(components: dict, event_risk: dict, technical: dict) -> str:
    atr = float(technical.get("atr_percent") or 0)
    if event_risk.get("signal") == "HIGH_RISK" or components["event_risk"] < 30:
        return "HIGH"
    if atr > 3.5 or components["technical"] < 35:
        return "HIGH"
    if atr > 2.0 or components["fundamental"] < 40:
        return "MEDIUM"
    return "LOW"


def _build_reasoning(
    ticker: str,
    timeframe: str,
    components: dict,
    technical: dict,
    fundamental: dict,
    sentiment: dict,
    event_risk: dict,
    macro_score: dict,
) -> str:
    parts = [
        f"{ticker} scored for {TIMEFRAMES[timeframe]['label']}.",
        f"Tech {components['technical']:.0f} | Fund {components['fundamental']:.0f} | "
        f"Sent {components['sentiment']:.0f} | Macro {components['macro']:.0f} | "
        f"Events {components['event_risk']:.0f}.",
    ]
    if technical.get("signal"):
        parts.append(f"Technical signal: {technical['signal']}.")
    for obs in (fundamental.get("observations") or [])[:2]:
        parts.append(obs)
    if sentiment.get("signal"):
        parts.append(
            f"News sentiment: {sentiment['signal']} "
            f"({sentiment.get('total_articles', 0)} articles)."
        )
    parts.extend(summarize_event_context(event_risk)[:3])
    if macro_score.get("regime"):
        parts.append(f"Market regime: {macro_score['regime']}.")
    return " ".join(parts)
