"""
TraderAI - Open-source news aggregation
Primary: RSS / Google News (no API key).
Optional fallback: Finnhub if FINNHUB_API_KEY is set.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import quote_plus, urlparse

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import FINNHUB_API_KEY, HTTP_USER_AGENT, RSS_FEEDS

logger = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": HTTP_USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"})


def _strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_date(value: Optional[str]) -> str:
    if not value:
        return datetime.now().isoformat()
    try:
        return parsedate_to_datetime(value).isoformat()
    except Exception:
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except Exception:
        return datetime.now().isoformat()


def _local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def parse_rss_xml(content: str, source_hint: str = "") -> list[dict]:
    """Parse RSS/Atom XML into normalized article dicts."""
    articles = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        logger.debug(f"RSS parse error ({source_hint}): {e}")
        return []

    # RSS 2.0 items
    items = root.findall(".//item")
    # Atom entries
    if not items:
        items = [el for el in root.iter() if _local_tag(el.tag) == "entry"]

    for item in items:
        fields = {}
        for child in item:
            tag = _local_tag(child.tag).lower()
            if tag in ("title", "description", "summary", "link", "pubdate", "updated", "published", "category"):
                if tag == "link":
                    href = child.attrib.get("href")
                    fields["link"] = href or (child.text or "").strip()
                else:
                    fields[tag] = (child.text or "").strip()

        headline = _strip_html(fields.get("title", ""))
        if not headline:
            continue

        summary = _strip_html(fields.get("description") or fields.get("summary") or "")
        link = fields.get("link", "")
        published = _parse_date(
            fields.get("pubdate") or fields.get("published") or fields.get("updated")
        )
        host = urlparse(link).netloc if link else source_hint

        articles.append(
            {
                "headline": headline,
                "summary": summary[:500],
                "source": host or source_hint or "rss",
                "url": link,
                "datetime": published,
                "category": fields.get("category", "general"),
                "origin": "rss",
            }
        )
    return articles


def fetch_rss_feed(url: str, timeout: int = 12) -> list[dict]:
    """Fetch and parse a single RSS/Atom feed URL."""
    try:
        resp = _SESSION.get(url, timeout=timeout)
        resp.raise_for_status()
        return parse_rss_xml(resp.text, source_hint=urlparse(url).netloc)
    except Exception as e:
        logger.warning(f"RSS fetch failed ({url}): {e}")
        return []


def fetch_google_news(query: str, max_articles: int = 20) -> list[dict]:
    """Open Google News RSS search (no API key)."""
    url = (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"
    )
    articles = fetch_rss_feed(url)
    for a in articles:
        a["category"] = "company" if "company" in query.lower() else a.get("category", "search")
    return articles[:max_articles]


def fetch_feed_bundle(bundle: str = "market", max_articles: int = 40) -> list[dict]:
    """Fetch a configured RSS bundle and dedupe by headline."""
    urls = RSS_FEEDS.get(bundle, [])
    seen = set()
    out = []
    for url in urls:
        # Skip obvious HTML-only endpoints that aren't RSS
        if "BS_PressReleaseDisplay" in url:
            continue
        for article in fetch_rss_feed(url):
            key = article["headline"].lower()[:120]
            if key in seen:
                continue
            seen.add(key)
            article["bundle"] = bundle
            out.append(article)
            if len(out) >= max_articles:
                return out
    return out


def fetch_company_news_oss(ticker: str, company_name: str = "", days_back: int = 14) -> list[dict]:
    """
    Company news via Google News RSS + optional Finnhub.
    """
    symbol = ticker.replace(".NS", "").replace(".BO", "")
    queries = [f"{symbol} stock India OR NSE"]
    if company_name:
        clean_name = re.sub(r"\b(limited|ltd|corp|corporation)\b", "", company_name, flags=re.I).strip()
        queries.append(f'"{clean_name}" stock OR shares OR earnings')
        if clean_name.lower() != symbol.lower():
            queries.append(f"{clean_name} share price India")

    articles = []
    seen = set()
    cutoff = datetime.now() - timedelta(days=days_back)

    for q in queries:
        for a in fetch_google_news(q, max_articles=15):
            key = a["headline"].lower()[:120]
            if key in seen:
                continue
            seen.add(key)
            try:
                dt = datetime.fromisoformat(a["datetime"].replace("Z", "+00:00")).replace(tzinfo=None)
                if dt < cutoff:
                    continue
            except Exception:
                pass
            a["related"] = ticker
            articles.append(a)

    # Optional Finnhub enrichment
    if FINNHUB_API_KEY:
        try:
            from data.news_data import fetch_company_news as finnhub_company_news

            for a in finnhub_company_news(ticker, days_back=days_back):
                key = a["headline"].lower()[:120]
                if key in seen:
                    continue
                seen.add(key)
                a["origin"] = "finnhub"
                articles.append(a)
        except Exception as e:
            logger.debug(f"Finnhub company news skipped: {e}")

    return articles[:30]


def fetch_macro_news_bundle() -> dict[str, list[dict]]:
    """Pull market, policy, geopolitics, and India-market Google News."""
    return {
        "market": fetch_feed_bundle("market", 30),
        "policy": fetch_feed_bundle("policy", 20) + fetch_feed_bundle("google_news_india_markets", 20),
        "geopolitics": fetch_feed_bundle("geopolitics", 20),
    }


def fetch_sector_news(sector: str, max_articles: int = 15) -> list[dict]:
    """Sector-level news via Google News RSS."""
    sector_terms = {
        "Auto": "automobile auto EV vehicle sales India stocks",
        "Banking": "banking bank RBI credit Nifty Bank stocks India",
        "IT": "IT tech software TCS Infosys AI demand stocks India",
        "Pharma": "pharma healthcare USFDA drug approval India stocks",
        "Energy": "oil gas crude power renewable capex India stocks",
        "Metals": "steel metal aluminium mining commodity tariff India",
        "FMCG": "FMCG consumer goods rural demand consumption India",
        "Infra": "infrastructure capex construction order book India",
    }
    term = sector_terms.get(sector, f"{sector} sector industry")
    q = f"{term} OR NSE"
    articles = fetch_google_news(q, max_articles=max_articles)
    for a in articles:
        a["sector"] = sector
    return articles
