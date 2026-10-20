"""
TraderAI - News Data Fetcher
Financial and market news via Finnhub API.
"""
import finnhub
import requests
from datetime import datetime, timedelta
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import FINNHUB_API_KEY

logger = logging.getLogger(__name__)


def _get_client() -> finnhub.Client:
    """Get Finnhub API client."""
    if not FINNHUB_API_KEY:
        raise ValueError("FINNHUB_API_KEY not set. Get one free at https://finnhub.io")
    return finnhub.Client(api_key=FINNHUB_API_KEY)


def _nse_to_finnhub_ticker(nse_ticker: str) -> str:
    """
    Convert NSE ticker to Finnhub symbol.
    Tries NSE:SYMBOL first (Indian listings). Callers should handle empty results.
    """
    symbol = nse_ticker.replace(".NS", "").replace(".BO", "").upper()
    if nse_ticker.upper().endswith(".BO"):
        return f"BSE:{symbol}"
    return f"NSE:{symbol}"


def fetch_company_news(ticker: str, days_back: int = 7) -> list[dict]:
    """
    Fetch recent news for a specific company.
    
    Args:
        ticker: Stock symbol (e.g., 'RELIANCE.NS')
        days_back: Number of days to look back
    
    Returns:
        List of news articles with headline, summary, source, url, datetime
    """
    try:
        client = _get_client()
        symbol = _nse_to_finnhub_ticker(ticker)
        
        today = datetime.now()
        from_date = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
        to_date = today.strftime("%Y-%m-%d")

        news = client.company_news(symbol, _from=from_date, to=to_date)

        return [
            {
                "headline": article.get("headline", ""),
                "summary": article.get("summary", ""),
                "source": article.get("source", ""),
                "url": article.get("url", ""),
                "datetime": datetime.fromtimestamp(article.get("datetime", 0)).isoformat(),
                "category": article.get("category", ""),
                "related": article.get("related", ""),
                "image": article.get("image", ""),
            }
            for article in news[:20]  # Limit to 20 most recent
        ]
    except Exception as e:
        logger.error(f"Error fetching company news for {ticker}: {e}")
        return []


def fetch_market_news(category: str = "general") -> list[dict]:
    """
    Fetch general market news.
    
    Args:
        category: 'general', 'forex', 'crypto', 'merger'
    
    Returns:
        List of news articles
    """
    try:
        client = _get_client()
        news = client.general_news(category, min_id=0)

        return [
            {
                "headline": article.get("headline", ""),
                "summary": article.get("summary", ""),
                "source": article.get("source", ""),
                "url": article.get("url", ""),
                "datetime": datetime.fromtimestamp(article.get("datetime", 0)).isoformat(),
                "category": article.get("category", ""),
            }
            for article in news[:30]  # Limit to 30 most recent
        ]
    except Exception as e:
        logger.error(f"Error fetching market news: {e}")
        return []


def fetch_market_sentiment(ticker: str) -> dict:
    """
    Fetch Finnhub's built-in sentiment data (social media buzz).
    
    Args:
        ticker: Stock symbol
    
    Returns:
        Dict with sentiment scores if available
    """
    try:
        client = _get_client()
        symbol = _nse_to_finnhub_ticker(ticker)
        sentiment = client.news_sentiment(symbol)
        
        if sentiment and "sentiment" in sentiment:
            s = sentiment["sentiment"]
            return {
                "symbol": ticker,
                "bullish_percent": s.get("bullishPercent", 0),
                "bearish_percent": s.get("bearishPercent", 0),
                "articles_in_last_week": sentiment.get("buzz", {}).get("articlesInLastWeek", 0),
                "buzz_score": sentiment.get("buzz", {}).get("buzz", 0),
                "sector_avg_bullish": sentiment.get("sectorAverageBullishPercent", 0),
                "company_news_score": sentiment.get("companyNewsScore", 0),
            }
        return {"symbol": ticker, "error": "No sentiment data available"}
    except Exception as e:
        logger.error(f"Error fetching sentiment for {ticker}: {e}")
        return {"symbol": ticker, "error": str(e)}


def fetch_insider_transactions(ticker: str) -> list[dict]:
    """
    Fetch insider trading/transactions (promoter buying/selling).
    """
    try:
        client = _get_client()
        symbol = _nse_to_finnhub_ticker(ticker)
        transactions = client.stock_insider_transactions(symbol)
        
        data = transactions.get("data", [])
        return [
            {
                "name": t.get("name", ""),
                "share": t.get("share", 0),
                "change": t.get("change", 0),
                "transaction_type": "Buy" if t.get("change", 0) > 0 else "Sell",
                "filing_date": t.get("filingDate", ""),
                "transaction_date": t.get("transactionDate", ""),
            }
            for t in data[:10]
        ]
    except Exception as e:
        logger.error(f"Error fetching insider transactions for {ticker}: {e}")
        return []


def fetch_earnings_calendar(ticker: str) -> list[dict]:
    """
    Fetch upcoming earnings dates for a stock.
    """
    try:
        client = _get_client()
        symbol = _nse_to_finnhub_ticker(ticker)
        
        today = datetime.now().strftime("%Y-%m-%d")
        future = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")
        earnings = client.earnings_calendar(_from=today, to=future, symbol=symbol)
        
        return [
            {
                "date": e.get("date", ""),
                "symbol": e.get("symbol", ""),
                "eps_estimate": e.get("epsEstimate", None),
                "eps_actual": e.get("epsActual", None),
                "revenue_estimate": e.get("revenueEstimate", None),
                "quarter": e.get("quarter", ""),
            }
            for e in earnings.get("earningsCalendar", [])
        ]
    except Exception as e:
        logger.error(f"Error fetching earnings calendar for {ticker}: {e}")
        return []
