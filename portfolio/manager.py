"""
TraderAI - Portfolio Manager
Local JSON portfolio + optional Kotak Neo sync (read-only).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import PORTFOLIO_PATH, SECTOR_MAP, TICKER_TO_SECTOR

logger = logging.getLogger(__name__)


def _empty_portfolio() -> dict:
    return {
        "updated_at": datetime.now().isoformat(),
        "source": "local",
        "cash": 0.0,
        "holdings": [],
    }


def load_portfolio() -> dict:
    """Load portfolio from disk; create empty file if missing."""
    os.makedirs(os.path.dirname(PORTFOLIO_PATH), exist_ok=True)
    if not os.path.exists(PORTFOLIO_PATH):
        data = _empty_portfolio()
        save_portfolio(data)
        return data
    try:
        with open(PORTFOLIO_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load portfolio: {e}")
        return _empty_portfolio()


def save_portfolio(data: dict) -> None:
    """Persist portfolio JSON."""
    os.makedirs(os.path.dirname(PORTFOLIO_PATH), exist_ok=True)
    data["updated_at"] = datetime.now().isoformat()
    with open(PORTFOLIO_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def upsert_holding(
    ticker: str,
    quantity: int,
    avg_price: float,
    current_price: Optional[float] = None,
    timeframe: str = "short_term",
    purchase_date: Optional[str] = None,
) -> dict:
    """Add or update a local holding with timeframe bucket and purchase date."""
    data = load_portfolio()
    holdings = data.get("holdings", [])
    cur_px = current_price if current_price is not None else avg_price
    pnl = round((cur_px - avg_price) * quantity, 2)
    pnl_pct = round(((cur_px - avg_price) / avg_price * 100), 2) if avg_price else 0.0
    found = False
    for h in holdings:
        if h["symbol"] == ticker:
            h["quantity"] = quantity
            h["avg_price"] = avg_price
            h["current_price"] = cur_px
            h["market_value"] = round(cur_px * quantity, 2)
            h["pnl"] = pnl
            h["pnl_percent"] = pnl_pct
            if timeframe:
                h["timeframe"] = timeframe
            if purchase_date:
                h["purchase_date"] = purchase_date
            found = True
            break
    if not found:
        holdings.append(
            {
                "symbol": ticker,
                "quantity": quantity,
                "avg_price": avg_price,
                "current_price": cur_px,
                "market_value": round(cur_px * quantity, 2),
                "pnl": pnl,
                "pnl_percent": pnl_pct,
                "timeframe": timeframe or "short_term",
                "purchase_date": purchase_date or datetime.now().strftime("%Y-%m-%d"),
                "exchange": "NSE",
                "sector": TICKER_TO_SECTOR.get(ticker, "Unknown"),
            }
        )
    data["holdings"] = holdings
    data["source"] = data.get("source", "local")
    save_portfolio(data)
    return data


def remove_holding(ticker: str) -> dict:
    data = load_portfolio()
    data["holdings"] = [h for h in data.get("holdings", []) if h["symbol"] != ticker]
    save_portfolio(data)
    return data


def sync_from_kotak(totp: Optional[str] = None, prompt: bool = False) -> dict:
    """
    Connect to Kotak Neo (read-only) and replace local holdings with broker holdings.
    Preserves any existing timeframe bucket classifications previously set by user.
    """
    from data.broker import connect_broker, get_broker_portfolio_summary, is_configured

    if not is_configured():
        return {"ok": False, "error": "Kotak credentials missing in .env"}

    if not connect_broker(totp=totp, prompt=prompt):
        return {"ok": False, "error": "Broker login failed (check TOTP / credentials)"}

    # Preserve user's custom timeframe assignments for existing holdings
    existing_tfs = {
        h.get("symbol"): h.get("timeframe")
        for h in load_portfolio().get("holdings", [])
        if h.get("timeframe")
    }

    summary = get_broker_portfolio_summary()
    holdings = summary.get("holdings") or []
    enriched = []
    for h in holdings:
        item = dict(h)
        sym = h.get("symbol", "")
        item["sector"] = TICKER_TO_SECTOR.get(sym, "Unknown")
        item["timeframe"] = existing_tfs.get(sym, "short_term")
        enriched.append(item)

    data = {
        "updated_at": datetime.now().isoformat(),
        "source": "kotak_neo",
        "cash": 0.0,
        "broker_summary": {
            "total_invested": summary.get("total_invested"),
            "total_current_value": summary.get("total_current_value"),
            "total_pnl": summary.get("total_pnl"),
            "total_pnl_percent": summary.get("total_pnl_percent"),
            "holdings_count": summary.get("holdings_count"),
        },
        "holdings": enriched,
    }
    save_portfolio(data)
    return {"ok": True, "portfolio": data}


def portfolio_summary(data: Optional[dict] = None) -> dict:
    """Compute invested value, sector mix, timeframe distribution, concentration flags."""
    data = data or load_portfolio()
    holdings = data.get("holdings") or []
    if not holdings:
        return {
            "holdings_count": 0,
            "total_invested": 0,
            "total_current_value": 0,
            "total_pnl": 0,
            "total_pnl_percent": 0,
            "sector_weights": {},
            "timeframe_weights": {"long_term": 0.0, "mid_term": 0.0, "short_term": 0.0},
            "timeframe_values": {"long_term": 0.0, "mid_term": 0.0, "short_term": 0.0},
            "concentration_flags": [],
        }

    invested = 0.0
    current = 0.0
    sector_value = {}
    timeframe_value = {"long_term": 0.0, "mid_term": 0.0, "short_term": 0.0}

    for h in holdings:
        qty = float(h.get("quantity") or 0)
        avg = float(h.get("avg_price") or 0)
        px = float(h.get("current_price") or avg)
        inv = avg * qty
        cur = px * qty
        invested += inv
        current += cur
        sector = h.get("sector") or TICKER_TO_SECTOR.get(h.get("symbol", ""), "Unknown")
        sector_value[sector] = sector_value.get(sector, 0) + cur
        tf = h.get("timeframe") or "short_term"
        if tf in timeframe_value:
            timeframe_value[tf] += cur
        else:
            timeframe_value["short_term"] += cur

    pnl = current - invested
    sector_weights = {
        s: round(v / current * 100, 1) for s, v in sector_value.items() if current > 0
    }
    timeframe_weights = {
        k: round(v / current * 100, 1) for k, v in timeframe_value.items() if current > 0
    }

    flags = []
    for h in holdings:
        px = float(h.get("current_price") or h.get("avg_price") or 0)
        qty = float(h.get("quantity") or 0)
        weight = (px * qty / current * 100) if current else 0
        if weight > 10:
            flags.append(f"{h.get('symbol')} is {weight:.1f}% of portfolio (>10% cap)")
    for s, w in sector_weights.items():
        if w > 30:
            flags.append(f"Sector {s} is {w:.1f}% of portfolio (>30% cap)")

    return {
        "holdings_count": len(holdings),
        "total_invested": round(invested, 2),
        "total_current_value": round(current, 2),
        "total_pnl": round(pnl, 2),
        "total_pnl_percent": round(pnl / invested * 100, 2) if invested else 0,
        "sector_weights": sector_weights,
        "timeframe_weights": timeframe_weights,
        "timeframe_values": {k: round(v, 2) for k, v in timeframe_value.items()},
        "concentration_flags": flags,
        "source": data.get("source", "local"),
        "updated_at": data.get("updated_at"),
        "holdings": holdings,
    }


def held_tickers() -> list[str]:
    return [h["symbol"] for h in load_portfolio().get("holdings", []) if h.get("symbol")]
