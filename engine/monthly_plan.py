"""
TraderAI - Monthly investment plan
Default: INR 10,000 stocks + INR 10,000 mutual funds (SIP-style).
Scales when monthly capital increases later.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    MONTHLY_STOCK_BUDGET,
    MONTHLY_MF_BUDGET,
    MF_SCHEME_CODES,
    RISK_CONFIG,
    SMALL_CAPITAL_CONFIG,
)
from data.mutual_fund_data import calculate_mf_returns, fetch_mf_details, fetch_mf_nav_history

logger = logging.getLogger(__name__)


def build_monthly_plan(
    recommendations: list[dict],
    deploy_plan: list[dict],
    stock_budget: Optional[float] = None,
    mf_budget: Optional[float] = None,
    mf_codes: Optional[list[str]] = None,
) -> dict:
    """
    Allocate this month's fresh capital across stocks + MFs.
    Designed for ~10k/10k but accepts any budgets.
    """
    stock_budget = float(stock_budget if stock_budget is not None else MONTHLY_STOCK_BUDGET)
    mf_budget = float(mf_budget if mf_budget is not None else MONTHLY_MF_BUDGET)
    mf_codes = mf_codes if mf_codes is not None else list(MF_SCHEME_CODES)

    max_names = SMALL_CAPITAL_CONFIG["max_new_stock_names_per_month"]
    min_ticket = SMALL_CAPITAL_CONFIG["min_stock_ticket"]
    max_per_name = min(
        stock_budget * SMALL_CAPITAL_CONFIG["max_pct_per_name"],
        stock_budget,
    )

    # Prefer judge-approved / BUY deploys; fall back to best HOLD with high stability for SIP
    candidates = list(deploy_plan or [])
    if not candidates:
        candidates = [
            {
                "ticker": r.get("ticker"),
                "action": "SIP_CANDIDATE",
                "sleeve": r.get("sleeve"),
                "preferred_timeframe": r.get("preferred_timeframe"),
                "final_score": r.get("final_score"),
                "stability_score": r.get("stability_score"),
                "opportunity_score": r.get("opportunity_score"),
                "reward_risk": r.get("reward_risk"),
                "stop_loss": r.get("stop_loss"),
                "target_price": r.get("target_price"),
                "current_price": r.get("current_price"),
                "risk_level": r.get("risk_level"),
            }
            for r in recommendations
            if r.get("action") in ("BUY", "STRONG_BUY", "HOLD")
            and float(r.get("final_score") or 0) >= 48
            and (r.get("risk_level") != "HIGH" or float(r.get("stability_score") or 0) >= 45)
        ]
        # Budget-Adaptive Candidate Sorting:
        # If stock_budget is small (<= 25k), prioritize quality setups where the user can afford >= 2 shares
        # (allowing partial profit taking and avoiding 1-share lock-in), while still keeping high-priced
        # stocks as secondary candidates if no low-priced setups qualify.
        slot_size = stock_budget / max_names if max_names > 0 else stock_budget

        def _candidate_rank(c):
            base_score = (
                float(c.get("stability_score") or 0) * 0.5
                + float(c.get("final_score") or 0) * 0.5
            )
            px = float(c.get("current_price") or 0)
            if stock_budget <= 25000 and px > 0 and slot_size > 0:
                affordable_qty = int(slot_size // px)
                multi_share_boost = 15.0 if affordable_qty >= 2 else (5.0 if affordable_qty == 1 else -20.0)
                return base_score + multi_share_boost
            return base_score

        candidates.sort(key=_candidate_rank, reverse=True)

    stock_allocs = []
    remaining = stock_budget
    for c in candidates:
        if len(stock_allocs) >= max_names or remaining < min_ticket:
            break
        import math
        try:
            price = float(c.get("current_price") or 0)
        except Exception:
            price = 0.0
        if not price or math.isnan(price) or price <= 0:
            # deploy plan may only have rupees/qty
            qty_hint = int(c.get("qty") or 0)
            rupees_hint = float(c.get("rupees") or 0)
            price = (rupees_hint / qty_hint) if qty_hint else 0.0
        if not price or math.isnan(price) or price <= 0:
            continue

        # Size: equal-ish split of remaining slots, capped
        slots_left = max_names - len(stock_allocs)
        target_rupees = min(max_per_name, remaining / slots_left, remaining)
        if target_rupees < min_ticket:
            break

        qty = int(target_rupees // price)
        if qty <= 0:
            # Share too expensive for this month's slice — skip or note
            if price <= remaining and price <= max_per_name * 1.2:
                # allow 1 share if within budget
                qty = 1
            else:
                stock_allocs.append(
                    {
                        "ticker": c.get("ticker"),
                        "status": "SKIP_TOO_EXPENSIVE",
                        "price": round(price, 2),
                        "note": f"1 share costs INR {price:.0f}; monthly slice too small — wait or use MF/ETF.",
                    }
                )
                continue

        rupees = round(qty * price, 2)
        stop = c.get("stop_loss")
        risk = round(qty * (price - float(stop)), 2) if stop and price > float(stop) else None
        remaining -= rupees
        stock_allocs.append(
            {
                "ticker": c.get("ticker"),
                "status": "ALLOCATE",
                "sleeve": c.get("sleeve"),
                "preferred_timeframe": c.get("preferred_timeframe"),
                "qty": qty,
                "price": round(price, 2),
                "rupees": rupees,
                "stop_loss": stop,
                "target_price": c.get("target_price"),
                "reward_risk": c.get("reward_risk"),
                "final_score": c.get("final_score"),
                "stability_score": c.get("stability_score"),
                "risk_rupees": risk,
                "action": c.get("action"),
            }
        )

    mf_allocs = _allocate_mfs(mf_budget, mf_codes)

    invested_stocks = sum(a["rupees"] for a in stock_allocs if a.get("status") == "ALLOCATE")
    invested_mf = sum(a["rupees"] for a in mf_allocs if a.get("status") == "ALLOCATE")

    guidance = [
        f"This month: INR {stock_budget:,.0f} stocks + INR {mf_budget:,.0f} mutual funds "
        f"(total SIP INR {stock_budget + mf_budget:,.0f}).",
        f"Stock deploy: INR {invested_stocks:,.0f} across "
        f"{sum(1 for a in stock_allocs if a.get('status')=='ALLOCATE')} names; "
        f"cash kept in stock budget: INR {remaining:,.0f}.",
        f"MF deploy: INR {invested_mf:,.0f} across {sum(1 for a in mf_allocs if a.get('status')=='ALLOCATE')} schemes.",
        "Universe is NOT limited to Nifty 50 — screener ranks a wider NSE set, then deep-scores top hits.",
        "As capital grows, raise MONTHLY_STOCK_BUDGET / MONTHLY_MF_BUDGET in .env — plan scales automatically.",
    ]
    if remaining >= min_ticket:
        guidance.append(
            "Leftover stock cash is fine — do not force weak names just to spend the budget."
        )

    return {
        "stock_budget": stock_budget,
        "mf_budget": mf_budget,
        "total_monthly": stock_budget + mf_budget,
        "stock_allocations": stock_allocs,
        "mf_allocations": mf_allocs,
        "stock_invested": round(invested_stocks, 2),
        "mf_invested": round(invested_mf, 2),
        "stock_cash_left": round(remaining, 2),
        "guidance": guidance,
    }


def _allocate_mfs(mf_budget: float, codes: list[str]) -> list[dict]:
    if mf_budget <= 0:
        return []
    if not codes:
        return [
            {
                "status": "NEED_CODES",
                "note": "Set MF_SCHEME_CODES in .env (AMFI codes). Budget reserved but unallocated.",
                "rupees": mf_budget,
            }
        ]

    # Equal-weight SIP across configured schemes (simple, robust for small SIPs)
    per = mf_budget / len(codes)
    out = []
    for code in codes:
        details = fetch_mf_details(code)
        nav_hist = fetch_mf_nav_history(code)
        rets = calculate_mf_returns(nav_hist) if not nav_hist.empty else {}
        if details.get("error"):
            out.append({"scheme_code": code, "status": "ERROR", "error": details["error"], "rupees": 0})
            continue
        nav = float(details.get("latest_nav") or 0)
        units = round(per / nav, 3) if nav > 0 else 0
        out.append(
            {
                "status": "ALLOCATE",
                "scheme_code": code,
                "scheme_name": details.get("scheme_name"),
                "category": details.get("scheme_category"),
                "fund_house": details.get("fund_house"),
                "nav": nav,
                "nav_date": details.get("nav_date"),
                "rupees": round(per, 2),
                "approx_units": units,
                "returns": {
                    k: rets.get(k)
                    for k in ("return_1m", "return_3m", "return_1y", "return_3y")
                    if rets.get(k) is not None
                },
            }
        )
    return out
