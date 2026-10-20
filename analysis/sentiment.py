"""
TraderAI - Sentiment Analysis Engine
Hybrid approach: VADER for fast triage + Gemini for deep analysis.
"""
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import logging

logger = logging.getLogger(__name__)

# Initialize VADER
_vader = SentimentIntensityAnalyzer()


def vader_score_headlines(headlines: list[dict]) -> list[dict]:
    """
    Fast triage: Score a batch of headlines using VADER.
    
    Args:
        headlines: List of dicts with 'headline' and optionally 'summary' keys
    
    Returns:
        Same list with added 'vader_score' (-1 to +1) and 'vader_label' fields,
        sorted by absolute score (most significant first)
    """
    scored = []
    for article in headlines:
        text = article.get("headline", "") + " " + article.get("summary", "")
        if not text.strip():
            continue

        vs = _vader.polarity_scores(text)
        compound = vs["compound"]

        if compound >= 0.3:
            label = "POSITIVE"
        elif compound <= -0.3:
            label = "NEGATIVE"
        else:
            label = "NEUTRAL"

        scored.append({
            **article,
            "vader_score": round(compound, 3),
            "vader_label": label,
            "vader_pos": round(vs["pos"], 3),
            "vader_neg": round(vs["neg"], 3),
        })

    # Keep chronological order when datetime exists; else keep input order
    def _sort_key(item):
        return item.get("datetime") or ""

    scored.sort(key=_sort_key, reverse=True)
    return scored


def compute_sentiment_score(headlines: list[dict], ticker: str = "") -> dict:
    """
    Compute overall sentiment score for a stock from its news.
    
    Uses VADER for all headlines. Flags high-impact ones for Gemini deep analysis.
    
    Args:
        headlines: List of news articles
        ticker: Stock symbol for labeling
    
    Returns:
        Dict with overall score, top headlines, and items flagged for LLM analysis
    """
    if not headlines:
        return {
            "ticker": ticker,
            "score": 0.0,
            "label": "NO_DATA",
            "total_articles": 0,
            "signal": "NEUTRAL",
        }

    scored = vader_score_headlines(headlines)
    
    if not scored:
        return {
            "ticker": ticker,
            "score": 0.0,
            "label": "NO_DATA",
            "total_articles": 0,
            "signal": "NEUTRAL",
        }

    # Calculate aggregate scores
    all_scores = [s["vader_score"] for s in scored]
    avg_score = sum(all_scores) / len(all_scores)

    positive = [s for s in scored if s["vader_label"] == "POSITIVE"]
    negative = [s for s in scored if s["vader_label"] == "NEGATIVE"]
    neutral = [s for s in scored if s["vader_label"] == "NEUTRAL"]

    # Sentiment momentum: recent (by time) vs older — scored is newest-first
    recent_scores = all_scores[:5]
    older_scores = all_scores[5:10] if len(all_scores) > 5 else all_scores
    momentum = (
        (sum(recent_scores) / len(recent_scores)) - (sum(older_scores) / len(older_scores))
        if older_scores else 0
    )

    # High-impact headlines for deeper review / UI highlight
    by_impact = sorted(scored, key=lambda x: abs(x["vader_score"]), reverse=True)
    flagged_for_llm = [s for s in by_impact if abs(s["vader_score"]) > 0.5][:5]

    # Determine signal
    if avg_score > 0.3:
        signal = "STRONG_POSITIVE"
        score_100 = 80 + min(20, avg_score * 40)
    elif avg_score > 0.1:
        signal = "POSITIVE"
        score_100 = 60 + avg_score * 50
    elif avg_score > -0.1:
        signal = "NEUTRAL"
        score_100 = 50
    elif avg_score > -0.3:
        signal = "NEGATIVE"
        score_100 = 40 + avg_score * 50
    else:
        signal = "STRONG_NEGATIVE"
        score_100 = 20 + max(-20, avg_score * 40)

    return {
        "ticker": ticker,
        "score": round(avg_score, 3),          # -1 to +1
        "score_100": round(score_100, 1),       # 0 to 100 (for scorer)
        "signal": signal,
        "total_articles": len(scored),
        "positive_count": len(positive),
        "negative_count": len(negative),
        "neutral_count": len(neutral),
        "sentiment_momentum": round(momentum, 3),
        "top_positive": [
            {"headline": s["headline"], "score": s["vader_score"]}
            for s in positive[:3]
        ],
        "top_negative": [
            {"headline": s["headline"], "score": s["vader_score"]}
            for s in negative[:3]
        ],
        "flagged_for_llm": flagged_for_llm,
    }


def compute_sector_sentiment(sector_news: dict[str, list[dict]]) -> dict:
    """
    Compute sentiment across sectors.
    
    Args:
        sector_news: Dict mapping sector name -> list of articles
    
    Returns:
        Dict mapping sector -> sentiment score and signal
    """
    results = {}
    for sector, articles in sector_news.items():
        result = compute_sentiment_score(articles, ticker=sector)
        results[sector] = {
            "score": result["score"],
            "signal": result["signal"],
            "article_count": result["total_articles"],
        }
    return results
