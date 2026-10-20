"""
TraderAI - Event / Geopolitics / Regulation Risk Engine (open-source)
Keyword + sentiment hybrid over news headlines covering:
sanctions, regulations, govt policy, investments, leadership, stability, geopolitics.
"""
from __future__ import annotations

import logging
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import EVENT_KEYWORDS, TICKER_TO_SECTOR

logger = logging.getLogger(__name__)


def _text_of(article: dict) -> str:
    return f"{article.get('headline', '')} {article.get('summary', '')}".lower()


def classify_events(articles: list[dict]) -> list[dict]:
    """Tag articles with matching event categories and impact weights."""
    tagged = []
    for article in articles:
        text = _text_of(article)
        matches = []
        impact = 0
        for category, meta in EVENT_KEYWORDS.items():
            hit_terms = [t for t in meta["terms"] if t in text]
            if hit_terms:
                matches.append({"category": category, "terms": hit_terms, "weight": meta["weight"]})
                impact += meta["weight"]

        if matches:
            tagged.append(
                {
                    **article,
                    "event_matches": matches,
                    "event_impact": impact,
                    "event_categories": [m["category"] for m in matches],
                }
            )
    return tagged


def compute_event_risk_score(
    company_news: list[dict],
    sector_news: list[dict] | None = None,
    macro_news: list[dict] | None = None,
    ticker: str = "",
) -> dict:
    """
    Score event risk / opportunity on 0-100 scale.
    50 = neutral baseline. Positive events raise score; sanctions/fraud lower it.
    """
    sector_news = sector_news or []
    macro_news = macro_news or []

    # Weight company > sector > macro
    buckets = [
        ("company", company_news, 1.0),
        ("sector", sector_news, 0.55),
        ("macro", macro_news, 0.25),
    ]

    category_hits = defaultdict(int)
    company_severe_hits = 0
    impact_total = 0.0
    key_events = []

    for bucket_name, articles, w in buckets:
        tagged = classify_events(articles)
        for item in tagged:
            # Cap single-article influence; macro articles are softer
            capped = max(-30, min(30, item["event_impact"])) * w
            impact_total += capped
            for cat in item["event_categories"]:
                category_hits[cat] += 1
                if bucket_name == "company" and cat in ("sanctions", "stability"):
                    company_severe_hits += 1
            key_events.append(
                {
                    "bucket": bucket_name,
                    "headline": item.get("headline", ""),
                    "impact": item["event_impact"],
                    "categories": item["event_categories"],
                    "source": item.get("source", ""),
                    "url": item.get("url", ""),
                }
            )

    if not key_events:
        score = 50.0
        signal = "NEUTRAL"
    else:
        # Blend average + cumulative pressure into 0-100
        avg_impact = impact_total / len(key_events)
        cum = max(-35, min(35, impact_total * 0.25 + avg_impact * 0.8))
        score = max(0, min(100, 50 + cum))

        if score >= 70:
            signal = "TAILWIND"
        elif score >= 55:
            signal = "MILD_POSITIVE"
        elif score >= 45:
            signal = "NEUTRAL"
        elif score >= 30:
            signal = "HEADWIND"
        else:
            signal = "HIGH_RISK"

    # Hard override ONLY for company-specific sanctions / insolvency / fraud
    if company_severe_hits > 0:
        score = min(score, 32)
        signal = "HIGH_RISK"

    company_events = [e for e in key_events if e["bucket"] == "company"]
    sector_events = [e for e in key_events if e["bucket"] == "sector"]
    macro_events = [e for e in key_events if e["bucket"] == "macro"]

    company_events.sort(key=lambda x: abs(x["impact"]), reverse=True)
    sector_events.sort(key=lambda x: abs(x["impact"]), reverse=True)
    macro_events.sort(key=lambda x: abs(x["impact"]), reverse=True)

    # Prioritize Company events first, then Sector events, then Macro events
    prioritized_key_events = company_events[:4] + sector_events[:3] + macro_events[:2]

    return {
        "ticker": ticker,
        "sector": TICKER_TO_SECTOR.get(ticker, ""),
        "score": round(score, 1),
        "signal": signal,
        "category_hits": dict(category_hits),
        "company_severe_hits": company_severe_hits,
        "key_events": prioritized_key_events,
        "company_events": company_events[:5],
        "sector_events": sector_events[:5],
        "macro_events": macro_events[:5],
        "article_count": len(company_news) + len(sector_news) + len(macro_news),
        "event_article_count": len(key_events),
    }


def summarize_event_context(event_result: dict) -> list[str]:
    """Human-readable bullets for recommendation reasoning."""
    lines = []
    signal = event_result.get("signal", "NEUTRAL")
    lines.append(f"Event/geopolitics signal: {signal} ({event_result.get('score', 50)}/100)")
    hits = event_result.get("category_hits") or {}
    if hits:
        top = sorted(hits.items(), key=lambda x: -x[1])[:5]
        lines.append("Themes: " + ", ".join(f"{k}×{v}" for k, v in top))
    for ev in (event_result.get("key_events") or [])[:3]:
        cats = ",".join(ev.get("categories") or [])
        lines.append(f"[{cats}] {ev.get('headline', '')[:140]}")
    return lines
