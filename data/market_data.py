"""
TraderAI - Market Data Fetcher
Historical and live stock/commodity/index data via yfinance.
"""
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


def fetch_stock_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """
    Fetch historical OHLCV data for a stock.
    
    Args:
        ticker: Stock symbol (e.g., 'RELIANCE.NS')
        period: Data period - 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, max
        interval: Data interval - 1m, 5m, 15m, 1h, 1d, 1wk, 1mo
    
    Returns:
        DataFrame with Open, High, Low, Close, Volume columns
    """
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period=period, interval=interval)
        if df.empty:
            logger.warning(f"No data returned for {ticker}")
            return pd.DataFrame()
        df = df.dropna(subset=["Close"])
        df.index = df.index.tz_localize(None) if df.index.tz else df.index
        return df
    except Exception as e:
        logger.error(f"Error fetching history for {ticker}: {e}")
        return pd.DataFrame()


def fetch_stock_info(ticker: str) -> dict:
    """
    Fetch fundamental info for a stock (P/E, market cap, sector, etc.)
    
    Returns:
        Dict with stock info fields
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        return {
            "symbol": ticker,
            "name": info.get("longName", ""),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "market_cap": info.get("marketCap", 0),
            "pe_ratio": info.get("trailingPE", None),
            "forward_pe": info.get("forwardPE", None),
            "peg_ratio": info.get("pegRatio", None),
            "price_to_book": info.get("priceToBook", None),
            "roe": info.get("returnOnEquity", None),
            "roce": info.get("returnOnAssets", None),  # closest proxy in yfinance
            "debt_to_equity": info.get("debtToEquity", None),
            "revenue_growth": info.get("revenueGrowth", None),
            "earnings_growth": info.get("earningsGrowth", None),
            "dividend_yield": info.get("dividendYield", None),
            "current_price": info.get("currentPrice", info.get("regularMarketPrice", 0)),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh", None),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow", None),
            "avg_volume": info.get("averageVolume", 0),
            "beta": info.get("beta", None),
            "promoter_holding": info.get("heldPercentInsiders", None),
        }
    except Exception as e:
        logger.error(f"Error fetching info for {ticker}: {e}")
        return {"symbol": ticker, "error": str(e)}


def fetch_live_quote(ticker: str) -> dict:
    """
    Fetch latest price quote for a stock.
    """
    try:
        stock = yf.Ticker(ticker)
        fast_info = stock.fast_info
        return {
            "symbol": ticker,
            "price": fast_info.get("lastPrice", 0),
            "previous_close": fast_info.get("previousClose", 0),
            "open": fast_info.get("open", 0),
            "day_high": fast_info.get("dayHigh", 0),
            "day_low": fast_info.get("dayLow", 0),
            "volume": fast_info.get("lastVolume", 0),
            "market_cap": fast_info.get("marketCap", 0),
        }
    except Exception as e:
        logger.error(f"Error fetching quote for {ticker}: {e}")
        return {"symbol": ticker, "error": str(e)}


def fetch_index_data(index_symbol: str, period: str = "1y") -> pd.DataFrame:
    """
    Fetch historical data for a market index.
    
    Args:
        index_symbol: e.g., '^NSEI' for Nifty 50, '^BSESN' for Sensex
        period: Data period
    """
    df = fetch_stock_history(index_symbol, period=period)
    if df.empty:
        fallbacks = {
            "^NSEI": "NIFTYBEES.NS",
            "^NSEBANK": "BANKBEES.NS",
            "^CNXIT": "ITBEES.NS",
        }
        fallback_sym = fallbacks.get(index_symbol)
        if fallback_sym:
            logger.info(f"Using fallback {fallback_sym} for index {index_symbol}")
            return fetch_stock_history(fallback_sym, period=period)
    return df


def fetch_commodity_data(commodity_symbol: str, period: str = "1y") -> pd.DataFrame:
    """
    Fetch historical data for a commodity.
    
    Args:
        commodity_symbol: e.g., 'GC=F' for Gold, 'CL=F' for Crude Oil
        period: Data period
    """
    return fetch_stock_history(commodity_symbol, period=period)


def fetch_batch_quotes(tickers: list[str]) -> list[dict]:
    """
    Fetch live quotes for multiple tickers efficiently.
    """
    results = []
    for ticker in tickers:
        quote = fetch_live_quote(ticker)
        results.append(quote)
    return results


def fetch_batch_history(tickers: list[str], period: str = "6mo") -> dict[str, pd.DataFrame]:
    """
    Fetch historical data for multiple tickers.
    
    Returns:
        Dict mapping ticker -> DataFrame
    """
    result = {}
    try:
        data = yf.download(tickers, period=period, group_by="ticker", progress=False)
        for ticker in tickers:
            try:
                if len(tickers) == 1:
                    df = data.copy()
                else:
                    df = data[ticker].copy()
                df = df.dropna(how="all")
                if not df.empty:
                    result[ticker] = df
            except (KeyError, Exception) as e:
                logger.warning(f"No batch data for {ticker}: {e}")
    except Exception as e:
        logger.error(f"Batch download failed: {e}")
        # Fallback to individual downloads
        for ticker in tickers:
            df = fetch_stock_history(ticker, period=period)
            if not df.empty:
                result[ticker] = df
    return result
