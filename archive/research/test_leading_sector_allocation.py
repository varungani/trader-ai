import sqlite3
import pandas as pd
from engine.strategy_tournament import get_all_scored_buy_candidates
from data.db import get_connection
from data.market_data import fetch_live_quote
from data.costs import compute_indian_delivery_costs
from analysis.sector_rs import compute_sector_rs
from config import TICKER_TO_SECTOR

conn = get_connection()
candidates = get_all_scored_buy_candidates(conn, limit=15)
conn.close()

enriched = []
for c in candidates:
    ticker = c["ticker"]
    q = fetch_live_quote(ticker)
    entry_px = float(c.get("entry_price") or q.get("previous_close") or q.get("price") or 100.0)
    cur_px = float(q.get("price") or entry_px)
    if entry_px <= 0:
        continue
    sector = TICKER_TO_SECTOR.get(ticker, "General")
    sector_info = compute_sector_rs(sector)
    raw_gain_pct = round(((cur_px - entry_px) / entry_px) * 100.0, 2)
    enriched.append({
        "ticker": ticker,
        "final_score": float(c.get("final_score") or 50.0),
        "entry_price": entry_px,
        "current_price": cur_px,
        "raw_gain_pct": raw_gain_pct,
        "sector": sector,
        "sector_rs": sector_info.get("relative_strength_pct", 0.0),
        "sector_status": sector_info.get("status", "NEUTRAL"),
    })

enriched.sort(key=lambda x: x["final_score"], reverse=True)
print("--- ALL CANDIDATES ---")
for x in enriched:
    print(f"{x['ticker']:<15} Sector: {x['sector']:<10} Score: {x['final_score']:<5} Gain: {x['raw_gain_pct']:+6.2f}% RS: {x['sector_rs']:+5.2f}% ({x['sector_status']})")
