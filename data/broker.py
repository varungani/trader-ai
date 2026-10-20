"""
TraderAI - Kotak Neo Broker Integration (Read-Only)
Reads portfolio holdings and positions. NEVER places orders.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    KOTAK_CONSUMER_KEY,
    KOTAK_CONSUMER_SECRET,
    KOTAK_MOBILE,
    KOTAK_UCC,
    KOTAK_MPIN,
    KOTAK_TOTP_SECRET,
)

logger = logging.getLogger(__name__)
_client = None


def is_configured() -> bool:
    """Check if Kotak Neo credentials are configured."""
    return bool(KOTAK_CONSUMER_KEY and KOTAK_MOBILE and KOTAK_UCC and KOTAK_MPIN)


def _generate_totp(secret: str) -> str:
    """Generate current TOTP from authenticator secret (open-source pyotp)."""
    import pyotp

    return pyotp.TOTP(secret.replace(" ", "").strip()).now()


def connect_broker(totp: Optional[str] = None, prompt: bool = True) -> bool:
    """
    Authenticate with Kotak Neo API (read-only session).

    Auth order for TOTP:
      1. Explicit `totp` argument
      2. KOTAK_TOTP_SECRET in .env (preferred for automation)
      3. Interactive prompt if prompt=True

    Returns:
        True if connection successful
    """
    global _client

    if not is_configured():
        logger.warning(
            "Kotak Neo not configured. Set KOTAK_CONSUMER_KEY, KOTAK_MOBILE, "
            "KOTAK_UCC, KOTAK_MPIN in .env"
        )
        return False

    code = (totp or "").strip()
    if not code and KOTAK_TOTP_SECRET:
        try:
            code = _generate_totp(KOTAK_TOTP_SECRET)
            logger.info("Generated TOTP from KOTAK_TOTP_SECRET")
        except Exception as e:
            logger.error(f"Failed to generate TOTP from secret: {e}")
            return False

    if not code and prompt:
        try:
            code = input("Enter Kotak Neo TOTP (Authenticator app): ").strip()
        except EOFError:
            code = ""

    if not code:
        logger.error(
            "TOTP required. Pass totp=, set KOTAK_TOTP_SECRET, or run interactively."
        )
        return False

    try:
        from neo_api_client import NeoAPI

        kwargs = {"environment": "prod", "consumer_key": KOTAK_CONSUMER_KEY}
        if KOTAK_CONSUMER_SECRET:
            kwargs["consumer_secret"] = KOTAK_CONSUMER_SECRET

        _client = NeoAPI(**kwargs)
        _client.totp_login(
            mobile_number=KOTAK_MOBILE,
            ucc=KOTAK_UCC,
            totp=code,
        )
        _client.totp_validate(mpin=KOTAK_MPIN)
        logger.info("Connected to Kotak Neo (read-only)")
        return True
    except ImportError:
        logger.error(
            "neo_api_client not installed. Run: pip install kotakneoapi"
        )
        return False
    except Exception as e:
        logger.error(f"Failed to connect to Kotak Neo: {e}")
        _client = None
        return False


def disconnect_broker():
    """Clear the broker client session."""
    global _client
    _client = None


def _normalize_symbol(raw: str) -> str:
    """Map broker symbol to yfinance NSE ticker when possible."""
    if not raw:
        return ""
    symbol = str(raw).strip().upper()
    # Strip exchange suffixes Kotak sometimes returns
    for suffix in ("-EQ", " EQ", ".NSE", ".BSE"):
        if symbol.endswith(suffix):
            symbol = symbol[: -len(suffix)].strip()
    if symbol.endswith(".NS") or symbol.endswith(".BO"):
        return symbol
    return f"{symbol}.NS"


def fetch_holdings() -> list[dict]:
    """Fetch current stock holdings from demat account."""
    if _client is None:
        logger.warning("Broker not connected. Call connect_broker() first.")
        return []

    try:
        response = _client.holdings()
        if isinstance(response, dict):
            holdings_data = (
                response.get("data")
                or response.get("data", {}).get("holdings")
                or response.get("holdings")
                or []
            )
            if isinstance(holdings_data, dict):
                holdings_data = holdings_data.get("holdings", [])
        elif isinstance(response, list):
            holdings_data = response
        else:
            holdings_data = []

        results = []
        for h in holdings_data or []:
            if not isinstance(h, dict):
                continue
            qty = int(float(h.get("quantity") or h.get("qty") or h.get("holdingQty") or 0))
            if qty <= 0:
                continue
            avg = float(h.get("averagePrice") or h.get("avgPrice") or h.get("avg_price") or 0)
            ltp = float(h.get("ltp") or h.get("lastTradedPrice") or h.get("mktPrice") or 0)
            mkt = float(h.get("mktValue") or h.get("marketValue") or (ltp * qty))
            pnl = float(h.get("pnl") or h.get("profitAndLoss") or (mkt - avg * qty))
            pnl_pct = float(
                h.get("pnlPercentage")
                or h.get("pnlPercent")
                or ((pnl / (avg * qty) * 100) if avg * qty else 0)
            )
            raw_sym = h.get("displaySymbol") or h.get("tradingSymbol") or h.get("symbol") or ""
            results.append(
                {
                    "symbol": _normalize_symbol(raw_sym),
                    "raw_symbol": raw_sym,
                    "quantity": qty,
                    "avg_price": round(avg, 2),
                    "current_price": round(ltp, 2),
                    "market_value": round(mkt, 2),
                    "pnl": round(pnl, 2),
                    "pnl_percent": round(pnl_pct, 2),
                    "exchange": h.get("exchange", "NSE"),
                }
            )
        return results
    except Exception as e:
        logger.error(f"Error fetching holdings: {e}")
        return []


def fetch_positions() -> list[dict]:
    """Fetch current open positions (intraday/delivery)."""
    if _client is None:
        logger.warning("Broker not connected. Call connect_broker() first.")
        return []

    try:
        response = _client.positions()
        if isinstance(response, dict):
            positions_data = response.get("data") or response.get("positions") or []
        elif isinstance(response, list):
            positions_data = response
        else:
            positions_data = []

        results = []
        for p in positions_data or []:
            if not isinstance(p, dict):
                continue
            raw_sym = p.get("displaySymbol") or p.get("tradingSymbol") or p.get("symbol") or ""
            results.append(
                {
                    "symbol": _normalize_symbol(raw_sym),
                    "raw_symbol": raw_sym,
                    "product": p.get("product", ""),
                    "quantity": int(float(p.get("quantity") or p.get("qty") or 0)),
                    "buy_price": float(p.get("buyPrice") or p.get("avgBuyPrice") or 0),
                    "sell_price": float(p.get("sellPrice") or p.get("avgSellPrice") or 0),
                    "ltp": float(p.get("ltp") or 0),
                    "pnl": float(p.get("pnl") or p.get("netPnl") or 0),
                    "exchange": p.get("exchange", "NSE"),
                }
            )
        return results
    except Exception as e:
        logger.error(f"Error fetching positions: {e}")
        return []


def fetch_order_history() -> list[dict]:
    """Fetch past order book for analysis (read-only)."""
    if _client is None:
        logger.warning("Broker not connected. Call connect_broker() first.")
        return []

    try:
        # Prefer order_report; fall back to order_history naming across SDK versions
        if hasattr(_client, "order_report"):
            response = _client.order_report()
        elif hasattr(_client, "order_history"):
            response = _client.order_history()
        else:
            return []

        if isinstance(response, dict):
            orders_data = response.get("data") or response.get("orders") or []
        elif isinstance(response, list):
            orders_data = response
        else:
            orders_data = []

        results = []
        for o in orders_data or []:
            if not isinstance(o, dict):
                continue
            raw_sym = o.get("displaySymbol") or o.get("tradingSymbol") or o.get("symbol") or ""
            results.append(
                {
                    "order_id": o.get("orderId") or o.get("nOrdNo") or "",
                    "symbol": _normalize_symbol(raw_sym),
                    "side": o.get("transactionType") or o.get("trnsTp") or o.get("side") or "",
                    "quantity": int(float(o.get("quantity") or o.get("qty") or 0)),
                    "price": float(o.get("price") or o.get("prc") or 0),
                    "status": o.get("orderStatus") or o.get("ordSt") or o.get("status") or "",
                    "timestamp": o.get("orderTimestamp") or o.get("ordDtTm") or o.get("time") or "",
                    "exchange": o.get("exchange", "NSE"),
                }
            )
        return results
    except Exception as e:
        logger.error(f"Error fetching order history: {e}")
        return []


def get_broker_portfolio_summary() -> dict:
    """Consolidated broker portfolio summary."""
    holdings = fetch_holdings()
    if not holdings:
        return {"connected": _client is not None, "holdings_count": 0, "holdings": []}

    total_invested = sum(h["avg_price"] * h["quantity"] for h in holdings)
    total_current = sum(h["market_value"] for h in holdings)
    total_pnl = total_current - total_invested

    return {
        "connected": True,
        "holdings_count": len(holdings),
        "total_invested": round(total_invested, 2),
        "total_current_value": round(total_current, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_percent": round((total_pnl / total_invested * 100), 2) if total_invested else 0,
        "holdings": holdings,
    }
