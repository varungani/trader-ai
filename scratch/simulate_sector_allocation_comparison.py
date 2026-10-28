import sys
import sqlite3
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
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
    rs_val = float(sector_info.get("relative_strength_pct") or 0.0)
    status = sector_info.get("status", "NEUTRAL")
    
    # Capital weight multiplier for sector
    if status == "LEADING" or rs_val >= 2.0:
        weight_mult = 1.35
    elif status == "OUTPERFORMING" or rs_val >= 0.75:
        weight_mult = 1.15
    elif status == "NEUTRAL" or rs_val >= -0.75:
        weight_mult = 1.00
    elif status == "LAGGING" or rs_val >= -1.75:
        weight_mult = 0.80
    else:
        weight_mult = 0.60

    enriched.append({
        "ticker": ticker,
        "final_score": float(c.get("final_score") or 50.0),
        "entry_price": entry_px,
        "current_price": cur_px,
        "sector": sector,
        "rs": rs_val,
        "status": status,
        "weight_mult": weight_mult,
        "sector_boosted_score": float(c.get("final_score") or 50.0) + (rs_val * 1.5),
    })

def simulate_portfolio(name: str, stocks: list[dict], corpus: float = 20000.0, use_sector_weighting: bool = False):
    if not stocks:
        return
    n = len(stocks)
    if use_sector_weighting:
        tot_mult = sum(s["weight_mult"] for s in stocks)
        weights = [s["weight_mult"] / tot_mult for s in stocks]
    else:
        weights = [1.0 / n for _ in range(n)]

    tot_inv = 0.0
    tot_pnl = 0.0
    tot_fric = 0.0
    pos_res = []

    for s, w in zip(stocks, weights):
        alloc = corpus * w
        px = s["entry_price"]
        cur_px = s["current_price"]
        qty = int(alloc // px)
        if qty <= 0 and px <= corpus:
            qty = 1
        if qty <= 0:
            continue
        inv = qty * px
        cur_val = qty * cur_px
        c = compute_indian_delivery_costs(buy_price=px, sell_price=cur_px, quantity=qty)
        tot_inv += inv
        tot_pnl += c.net_pnl_rupees
        tot_fric += c.total_friction_rupees
        pos_res.append(f"{s['ticker']} ({s['sector']}, {s['status']}, {w*100:.1f}%): qty={qty}, inv=₹{inv:.0f}, net=₹{c.net_pnl_rupees:+.2f}")

    print(f"\n=== {name} ===")
    print(f"Total Invested: ₹{tot_inv:.2f} | Net P&L: ₹{tot_pnl:+.2f} ({(tot_pnl/tot_inv)*100:+.2f}%) | Friction: ₹{tot_fric:.2f}")
    for p in pos_res:
        print("  -", p)

# 1. Old naive Top 3 (sorted by final_score only, no sector cap)
s_old = sorted(enriched, key=lambda x: x["final_score"], reverse=True)[:3]
simulate_portfolio("Option 0: Old Naive Top 3 (Flat Equal Weight)", s_old, 20000.0, use_sector_weighting=False)

# 2. Sector-Diverse Top 3 (Max 1 per sector, sorted by final_score, flat equal weight)
s_diverse = []
seen_sec = set()
for s in sorted(enriched, key=lambda x: x["final_score"], reverse=True):
    if s["sector"] not in seen_sec:
        seen_sec.add(s["sector"])
        s_diverse.append(s)
        if len(s_diverse) >= 3:
            break
simulate_portfolio("Option 1: Sector-Diverse Top 3 (Max 1 Per Sector, Flat Equal Weight)", s_diverse, 20000.0, use_sector_weighting=False)

# 3. Sector-Diverse Top 3 + Dynamic Leading Sector Weighting
simulate_portfolio("Option 2: Sector-Diverse Top 3 + Dynamic Leading Sector Capital Boost", s_diverse, 20000.0, use_sector_weighting=True)

# 4. Sector-Boosted Score Ranking + Max 1 Per Sector + Dynamic Leading Sector Capital Boost
s_boosted = []
seen_sec = set()
for s in sorted(enriched, key=lambda x: x["sector_boosted_score"], reverse=True):
    if s["sector"] not in seen_sec:
        seen_sec.add(s["sector"])
        s_boosted.append(s)
        if len(s_boosted) >= 3:
            break
simulate_portfolio("Option 3: Sector-Momentum Ranked + Max 1 Per Sector + Leading Sector Boost", s_boosted, 20000.0, use_sector_weighting=True)
