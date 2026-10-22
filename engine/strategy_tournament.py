"""
TraderAI - Multi-Strategy Forward Tournament Engine
Tracks all BUY recommendations across the full scored universe and compares
parallel diversification strategies (e.g. Top 3 vs Top 5 vs All Buys) on a configurable corpus (default ₹20,000).
Incorporates Sector Relative Strength (RS) diversification caps and dynamic leading sector capital boosting.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
import pandas as pd

from data.db import get_connection
from data.market_data import fetch_live_quote
from data.costs import compute_indian_delivery_costs
from analysis.sector_rs import compute_sector_rs
from config import (
    TICKER_TO_SECTOR,
    SECTOR_ALLOCATION_MULTIPLIERS,
    MIN_DELIVERY_TICKET_RUPEES,
)

logger = logging.getLogger(__name__)


def get_all_scored_buy_candidates(conn: sqlite3.Connection, limit: int = 25) -> list[dict]:
    """
    Fetch the latest distinct BUY / STRONG_BUY recommendations from the database.
    De-duplicates tickers to get the latest signal per stock.
    Joins with forward_test_log to retrieve snapshot entry_price if available.
    """
    cursor = conn.cursor()
    # Query latest recommendations from daily_scores, joining with forward_test_log for entry_price
    cursor.execute("""
        SELECT d.ticker, d.date, d.final_score, d.technical_score, d.fundamental_score,
               d.sentiment_score, d.stop_loss, d.target_price, d.action,
               f.entry_price
        FROM daily_scores d
        LEFT JOIN (
            SELECT ticker, entry_price, MAX(id) as max_id
            FROM forward_test_log
            WHERE action LIKE '%BUY%'
            GROUP BY ticker
        ) f ON d.ticker = f.ticker
        WHERE d.action IN ('BUY', 'STRONG_BUY')
        ORDER BY d.date DESC, d.final_score DESC
    """)
    rows = cursor.fetchall()
    
    seen = set()
    buys = []
    for r in rows:
        d = dict(r)
        ticker = d["ticker"]
        if ticker in seen:
            continue
        seen.add(ticker)
        buys.append(d)
        if len(buys) >= limit:
            break

    # If daily_scores is sparse, supplement with forward_test_log BUYs
    if len(buys) < 5:
        cursor.execute("""
            SELECT ticker, date, final_score, technical_score, fundamental_score,
                   sentiment_score, stop_loss, target_price, action, entry_price
            FROM forward_test_log
            WHERE action LIKE '%BUY%'
            ORDER BY date DESC, id DESC
        """)
        for r in cursor.fetchall():
            d = dict(r)
            ticker = d["ticker"]
            if ticker in seen:
                continue
            seen.add(ticker)
            buys.append(d)
            if len(buys) >= limit:
                break

    return buys


def select_diversified_candidates(
    candidates: list[dict],
    target_slots: int,
    max_per_sector: int = 1,
) -> list[dict]:
    """
    Selects top candidates prioritizing sector-momentum boosted score,
    while enforcing a hard cap on the number of stocks from any single sector.
    Prevents single-sector overconcentration traps (e.g. 67% in Banking).
    """
    # Sort candidates by sector-momentum boosted score (final_score + sector_rs * 1.5)
    ranked = sorted(
        candidates,
        key=lambda x: x.get("sector_boosted_score", x.get("final_score", 50.0)),
        reverse=True,
    )
    selected = []
    sector_counts: dict[str, int] = {}

    for c in ranked:
        sec = c.get("sector", "General")
        curr_cnt = sector_counts.get(sec, 0)
        if curr_cnt < max_per_sector:
            selected.append(c)
            sector_counts[sec] = curr_cnt + 1
            if len(selected) >= target_slots:
                break

    # Fallback: if slots not completely filled due to tight sector caps, fill remaining with highest scores
    if len(selected) < target_slots:
        for c in ranked:
            if c not in selected:
                selected.append(c)
                if len(selected) >= target_slots:
                    break

    return selected


def simulate_tournament(
    corpus: float = 20000.0,
    top_n_candidates: int = 15,
) -> dict:
    """
    Simulate a live forward tournament comparing 3 diversification strategies:
      1. Strategy A: 'Concentrated 3' (Top 3 sector-diversified picks, leading sector capital boosted)
      2. Strategy B: 'Diversified 5' (Top 5 sector-diversified picks, leading sector capital boosted)
      3. Strategy C: 'All Scored BUYs' (Equal-weighted basket across all active BUY signals)
    """
    conn = get_connection()
    try:
        candidates = get_all_scored_buy_candidates(conn, limit=top_n_candidates)
    finally:
        conn.close()

    if not candidates:
        return {"error": "No active BUY recommendations found in the database. Run an analysis scan first."}

    # Fetch live quotes and enrich with Sector Relative Strength data
    enriched_candidates = []
    for c in candidates:
        ticker = c["ticker"]
        q = fetch_live_quote(ticker)
        entry_px = float(c.get("entry_price") or q.get("previous_close") or q.get("price") or 100.0)
        cur_px = float(q.get("price") or entry_px)
        if entry_px <= 0:
            continue

        raw_gain_pct = round(((cur_px - entry_px) / entry_px) * 100.0, 2)
        sl_px = float(c.get("stop_loss") or (entry_px * 0.93))
        tp_px = float(c.get("target_price") or (entry_px * 1.15))

        sector = TICKER_TO_SECTOR.get(ticker, "General")
        rs_data = compute_sector_rs(sector)
        rs_pct = float(rs_data.get("relative_strength_pct") or 0.0)
        rs_status = rs_data.get("status", "NEUTRAL")

        # Dynamic capital multiplier based on sector relative strength
        weight_mult = SECTOR_ALLOCATION_MULTIPLIERS.get(rs_status, 1.0)
        # Sector-boosted conviction score (rewards stocks with institutional tailwinds)
        sector_boosted_score = float(c.get("final_score") or 50.0) + (rs_pct * 1.5)

        enriched_candidates.append({
            "ticker": ticker,
            "action": c.get("action", "BUY"),
            "date": c.get("date", datetime.now().strftime("%Y-%m-%d")),
            "final_score": float(c.get("final_score") or 50.0),
            "sector_boosted_score": round(sector_boosted_score, 2),
            "sector": sector,
            "sector_rs_pct": rs_pct,
            "sector_status": rs_status,
            "weight_mult": weight_mult,
            "entry_price": entry_px,
            "current_price": cur_px,
            "stop_loss": sl_px,
            "target_price": tp_px,
            "raw_gain_pct": raw_gain_pct,
        })

    # Sort candidates by sector-momentum boosted score descending
    enriched_candidates.sort(key=lambda x: x["sector_boosted_score"], reverse=True)

    def _build_strategy_portfolio(
        name: str,
        selected_stocks: list[dict],
        target_slots: int,
        dynamic_sector_weighting: bool = True,
    ) -> dict:
        if not selected_stocks:
            return {
                "name": name,
                "target_slots": target_slots,
                "positions_count": 0,
                "invested": 0.0,
                "current_val": 0.0,
                "net_pnl": 0.0,
                "friction": 0.0,
                "net_return_pct": 0.0,
                "win_rate": 0.0,
                "sector_breakdown": {},
                "min_ticket_warnings": 0,
                "positions": [],
            }

        # Calculate capital weights: dynamic sector boost vs flat equal
        if dynamic_sector_weighting and selected_stocks:
            tot_mult = sum(s.get("weight_mult", 1.0) for s in selected_stocks)
            weights = [
                s.get("weight_mult", 1.0) / tot_mult for s in selected_stocks
            ] if tot_mult > 0 else [1.0 / len(selected_stocks)] * len(selected_stocks)
        else:
            weights = [1.0 / target_slots] * len(selected_stocks)

        positions = []
        tot_invested = 0.0
        tot_curr_val = 0.0
        tot_net_pnl = 0.0
        tot_friction = 0.0
        wins = 0
        min_ticket_warnings = 0
        sector_breakdown: dict[str, dict] = {}

        for s, w in zip(selected_stocks, weights):
            target_capital = corpus * w
            px = s["entry_price"]
            cur_px = s["current_price"]

            qty = int(target_capital // px)
            if qty <= 0:
                # If stock price > slot capital, allow 1 share if affordable within corpus
                qty = 1 if px <= corpus else 0
            if qty <= 0:
                continue

            invested = qty * px
            curr_val = qty * cur_px
            costs = compute_indian_delivery_costs(buy_price=px, sell_price=cur_px, quantity=qty)
            net_pnl = costs.net_pnl_rupees
            friction = costs.total_friction_rupees

            if net_pnl > 0:
                wins += 1

            if invested < MIN_DELIVERY_TICKET_RUPEES:
                min_ticket_warnings += 1

            tot_invested += invested
            tot_curr_val += curr_val
            tot_net_pnl += net_pnl
            tot_friction += friction

            sec = s.get("sector", "General")
            if sec not in sector_breakdown:
                sector_breakdown[sec] = {
                    "sector": sec,
                    "status": s.get("sector_status", "NEUTRAL"),
                    "rs_pct": s.get("sector_rs_pct", 0.0),
                    "invested": 0.0,
                    "stock_count": 0,
                }
            sector_breakdown[sec]["invested"] = round(sector_breakdown[sec]["invested"] + invested, 2)
            sector_breakdown[sec]["stock_count"] += 1

            positions.append({
                "ticker": s["ticker"],
                "sector": sec,
                "sector_status": s.get("sector_status", "NEUTRAL"),
                "sector_rs_pct": s.get("sector_rs_pct", 0.0),
                "weight_mult": s.get("weight_mult", 1.0),
                "target_weight_pct": round(w * 100.0, 1),
                "shares": qty,
                "buy_price": px,
                "current_price": cur_px,
                "invested": round(invested, 2),
                "current_val": round(curr_val, 2),
                "gain_pct": s["raw_gain_pct"],
                "net_pnl": round(net_pnl, 2),
                "friction": round(friction, 2),
            })

        net_ret_pct = round((tot_net_pnl / tot_invested * 100.0), 2) if tot_invested > 0 else 0.0
        win_rate = round((wins / len(positions) * 100.0), 1) if positions else 0.0

        return {
            "name": name,
            "target_slots": target_slots,
            "positions_count": len(positions),
            "invested": round(tot_invested, 2),
            "current_val": round(tot_curr_val, 2),
            "net_pnl": round(tot_net_pnl, 2),
            "friction": round(tot_friction, 2),
            "net_return_pct": net_ret_pct,
            "win_rate": win_rate,
            "sector_breakdown": sector_breakdown,
            "min_ticket_warnings": min_ticket_warnings,
            "dynamic_sector_weighted": dynamic_sector_weighting,
            "positions": positions,
        }

    # Strategy A: Concentrated Top 3 (Strictly Max 1 per sector, Leading Sector Boosted)
    strat_top3_stocks = select_diversified_candidates(enriched_candidates, target_slots=3, max_per_sector=1)
    strat_top3 = _build_strategy_portfolio(
        "Strategy A: Concentrated Top 3 (Sector-Diversified, Leading Boost)",
        strat_top3_stocks,
        target_slots=3,
        dynamic_sector_weighting=True,
    )

    # Strategy B: Balanced Core 5 (Max 2 per sector, Leading Sector Boosted)
    strat_top5_stocks = select_diversified_candidates(enriched_candidates, target_slots=5, max_per_sector=2)
    strat_top5 = _build_strategy_portfolio(
        "Strategy B: Balanced Core 5 (Sector-Diversified, Leading Boost)",
        strat_top5_stocks,
        target_slots=5,
        dynamic_sector_weighting=True,
    )

    # Strategy C: All Recommended BUYs (Equal-weighted basket across full universe)
    strat_all = _build_strategy_portfolio(
        f"Strategy C: All Recommended BUYs ({len(enriched_candidates)} Stocks, Equal Basket)",
        enriched_candidates,
        target_slots=len(enriched_candidates),
        dynamic_sector_weighting=False,
    )

    # Identify best performing strategy
    all_strats = [strat_top3, strat_top5, strat_all]
    best_strat = max(all_strats, key=lambda x: x["net_return_pct"])

    return {
        "corpus": corpus,
        "best_strategy": best_strat["name"],
        "strategies": {
            "top3": strat_top3,
            "top5": strat_top5,
            "all_buys": strat_all,
        },
        "all_candidates": enriched_candidates,
    }
