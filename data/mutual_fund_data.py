"""
TraderAI - Mutual Fund Data Fetcher
NAV, returns, and scheme details via mftool + mfapi.in.
"""
import requests
import pandas as pd
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

MFAPI_BASE = "https://api.mfapi.in/mf"


def fetch_mf_details(scheme_code: str) -> dict:
    """
    Fetch mutual fund scheme details and latest NAV.
    
    Args:
        scheme_code: AMFI scheme code (e.g., '119598')
    
    Returns:
        Dict with scheme name, NAV, date, and metadata
    """
    try:
        url = f"{MFAPI_BASE}/{scheme_code}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        meta = data.get("meta", {})
        nav_data = data.get("data", [])
        latest = nav_data[0] if nav_data else {}

        return {
            "scheme_code": scheme_code,
            "scheme_name": meta.get("scheme_name", "Unknown"),
            "fund_house": meta.get("fund_house", ""),
            "scheme_type": meta.get("scheme_type", ""),
            "scheme_category": meta.get("scheme_category", ""),
            "latest_nav": float(latest.get("nav", 0)),
            "nav_date": latest.get("date", ""),
            "total_data_points": len(nav_data),
        }
    except Exception as e:
        logger.error(f"Error fetching MF details for {scheme_code}: {e}")
        return {"scheme_code": scheme_code, "error": str(e)}


def fetch_mf_nav_history(scheme_code: str) -> pd.DataFrame:
    """
    Fetch historical NAV data for a mutual fund scheme.
    
    Returns:
        DataFrame with date and nav columns, sorted by date ascending
    """
    try:
        url = f"{MFAPI_BASE}/{scheme_code}"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()

        nav_data = data.get("data", [])
        if not nav_data:
            return pd.DataFrame()

        df = pd.DataFrame(nav_data)
        df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
        df["date"] = pd.to_datetime(df["date"], format="%d-%m-%Y", errors="coerce")
        df = df.dropna()
        df = df.sort_values("date").reset_index(drop=True)
        return df
    except Exception as e:
        logger.error(f"Error fetching MF NAV history for {scheme_code}: {e}")
        return pd.DataFrame()


def calculate_mf_returns(nav_df: pd.DataFrame) -> dict:
    """
    Calculate returns over various periods from NAV history.
    
    Returns:
        Dict with 1m, 3m, 6m, 1y, 3y, 5y returns as percentages
    """
    if nav_df.empty:
        return {}

    latest_nav = nav_df.iloc[-1]["nav"]
    latest_date = nav_df.iloc[-1]["date"]

    periods = {
        "1m": 30,
        "3m": 90,
        "6m": 180,
        "1y": 365,
        "3y": 1095,
        "5y": 1825,
    }

    returns = {}
    for label, days in periods.items():
        target_date = latest_date - pd.Timedelta(days=days)
        # Find the closest date
        past = nav_df[nav_df["date"] <= target_date]
        if not past.empty:
            past_nav = past.iloc[-1]["nav"]
            if past_nav > 0:
                ret = ((latest_nav - past_nav) / past_nav) * 100
                returns[label] = round(ret, 2)

    return returns


def fetch_portfolio_mfs(scheme_codes: list[str]) -> list[dict]:
    """
    Fetch details and returns for all mutual funds in portfolio.
    
    Args:
        scheme_codes: List of AMFI scheme codes
    
    Returns:
        List of dicts with scheme details and calculated returns
    """
    results = []
    for code in scheme_codes:
        details = fetch_mf_details(code)
        if "error" not in details:
            nav_history = fetch_mf_nav_history(code)
            returns = calculate_mf_returns(nav_history)
            details["returns"] = returns
        results.append(details)
    return results


def search_mf_schemes(query: str) -> list[dict]:
    """
    Search for mutual fund schemes by name.
    
    Args:
        query: Search query (e.g., 'SBI Blue Chip')
    
    Returns:
        List of matching schemes with code and name
    """
    try:
        url = f"{MFAPI_BASE}/search?q={query}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error searching MF schemes: {e}")
        return []
