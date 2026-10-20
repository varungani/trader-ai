"""
TraderAI - Paper Week (shadow trading)
Run recommendations for N days with ZERO real money.
Tracks PnL, judge pass rate, and gates real investing until week passes.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    PAPER_WEEK_DAYS,
    PAPER_WEEK_MIN_TRADES,
    PAPER_WEEK_MIN_TRUST,
    PAPER_WEEK_PATH,
    REAL_MONEY_ENABLED,
)
from data.db import (
    close_paper_trade,
    create_paper_trade,
    get_connection,
    get_open_paper_trades,
    get_paper_trade_stats,
    update_paper_trade_stop,
)
from data.market_data import fetch_live_quote

logger = logging.getLogger(__name__)


def _empty_state() -> dict:
    return {
        "started_at": None,
        "ends_at": None,
        "days_required": PAPER_WEEK_DAYS,
        "status": "NOT_STARTED",  # NOT_STARTED | RUNNING | PASSED | FAILED | EXTENDED
        "real_money_unlocked": False,
        "daily_logs": [],
        "metrics": {},
        "notes": [],
    }


def load_paper_week() -> dict:
    os.makedirs(os.path.dirname(PAPER_WEEK_PATH), exist_ok=True)
    if not os.path.exists(PAPER_WEEK_PATH):
        state = _empty_state()
        save_paper_week(state)
        return state
    with open(PAPER_WEEK_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_paper_week(state: dict) -> None:
    os.makedirs(os.path.dirname(PAPER_WEEK_PATH), exist_ok=True)
    with open(PAPER_WEEK_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)


def start_paper_week(force: bool = False) -> dict:
    state = load_paper_week()
    if state.get("status") == "RUNNING" and not force:
        return state
    now = datetime.now()
    state = _empty_state()
    state["started_at"] = now.isoformat()
    state["ends_at"] = (now + timedelta(days=PAPER_WEEK_DAYS)).isoformat()
    state["status"] = "RUNNING"
    state["notes"].append(
        f"Paper week started. No real money until {PAPER_WEEK_DAYS} days pass gates."
    )
    save_paper_week(state)
    return state


def real_money_allowed() -> dict:
    """Hard gate — real investing stays locked until paper week PASSES."""
    state = load_paper_week()
    if REAL_MONEY_ENABLED and state.get("real_money_unlocked") and state.get("status") == "PASSED":
        return {"allowed": True, "reason": "Paper week PASSED and REAL_MONEY_ENABLED=true"}
    reasons = []
    if not REAL_MONEY_ENABLED:
        reasons.append("REAL_MONEY_ENABLED is false")
    if state.get("status") != "PASSED":
        reasons.append(f"paper week status={state.get('status')}")
    if not state.get("real_money_unlocked"):
        reasons.append("real_money_unlocked=false")
    return {"allowed": False, "reason": "; ".join(reasons), "paper_week": state}


def open_paper_from_deploys(
    deploy_plan: list[dict],
    judged: list[dict],
    timeframe: str = "short_term",
) -> list[dict]:
    """
    Open paper trades only for deploys the judge allowed.
    """
    allow_map = {
        j.get("ticker"): j
        for j in judged
        if j.get("allow_paper_trade") and j.get("verdict") in ("PASS", "REVISE")
    }
    # Stricter: only PASS by default for opening; REVISE only if allow_paper_trade true
    opened = []
    conn = get_connection()
    try:
        existing_opens = {o["ticker"] for o in get_open_paper_trades(conn)}
        for d in deploy_plan:
            ticker = d.get("ticker")
            if ticker in existing_opens:
                continue
            if len(existing_opens) >= 5:
                break
            verdict = allow_map.get(ticker)
            if not verdict:
                continue
            if verdict.get("verdict") == "FAIL":
                continue
            if not verdict.get("allow_paper_trade"):
                continue
            qty = int(d.get("qty") or 0)
            price = float(d.get("rupees") or 0) / qty if qty else 0
            # Prefer live-ish price from deploy weight fields — use stop/target from plan
            # Re-read price via size if present
            entry = None
            # deploy has rupees/qty; derive entry
            if qty and d.get("rupees"):
                entry = float(d["rupees"]) / qty
            if not entry or entry <= 0:
                continue
            trade_id = create_paper_trade(
                conn,
                {
                    "ticker": ticker,
                    "timeframe": d.get("preferred_timeframe") or timeframe,
                    "action": "BUY",
                    "entry_price": round(entry, 2),
                    "quantity": qty,
                    "stop_loss": d.get("stop_loss"),
                    "target_price": d.get("target_price"),
                    "notes": json.dumps(
                        {
                            "sleeve": d.get("sleeve"),
                            "judge_verdict": verdict.get("verdict"),
                            "judge_trust": verdict.get("overall_trust"),
                            "reward_risk": d.get("reward_risk"),
                            "paper_week": True,
                        }
                    ),
                },
            )
            opened.append({"trade_id": trade_id, "ticker": ticker, "qty": qty, "entry": entry})
            existing_opens.add(ticker)
    finally:
        conn.close()
    return opened


def mark_to_market() -> dict:
    """Update open paper trades vs live quotes; auto-close on stop/target."""
    conn = get_connection()
    closed = []
    marks = []
    try:
        opens = get_open_paper_trades(conn)
        for t in opens:
            ticker = t["ticker"]
            quote = fetch_live_quote(ticker)
            px = float(quote.get("price") or 0)
            if not px:
                continue
            marks.append(
                {
                    "trade_id": t["id"],
                    "ticker": ticker,
                    "entry": t["entry_price"],
                    "last": px,
                    "unrealized_pnl": round((px - t["entry_price"]) * t["quantity"], 2)
                    if t["action"] == "BUY"
                    else round((t["entry_price"] - px) * t["quantity"], 2),
                }
            )
            stop = float(t.get("stop_loss") or 0)
            target = float(t.get("target_price") or 0)
            entry = float(t.get("entry_price") or 0)

            # --- Trailing Stop-Loss Protection (Profit Never Turns To Loss) ---
            if t.get("action") == "BUY" and entry > 0:
                gain_pct = ((px - entry) / entry) * 100.0
                # If gain >= +5.0%, elevate stop to Breakeven so capital is protected
                if gain_pct >= 5.0 and stop < entry:
                    stop = round(entry, 2)
                    update_paper_trade_stop(conn, t["id"], stop)
                    logger.info(f"Trailing Stop updated for {ticker}: moved to BREAKEVEN (Rs. {stop})")
                # If gain >= +10.0%, lock in at least +5% profit floor
                if gain_pct >= 10.0:
                    profit_lock = round(entry * 1.05, 2)
                    if stop < profit_lock:
                        stop = profit_lock
                        update_paper_trade_stop(conn, t["id"], stop)
                        logger.info(f"Trailing Stop updated for {ticker}: locked at +5% (Rs. {stop})")

            if stop and px <= float(stop):
                exit_reason = "BREAKEVEN_STOP" if abs(px - entry) <= (entry * 0.005) else ("TRAILING_STOP" if px > entry else "STOP_LOSS")
                close_paper_trade(conn, t["id"], px, exit_reason=exit_reason)
                closed.append({"ticker": ticker, "reason": exit_reason, "price": px})
            elif target and px >= float(target):
                close_paper_trade(conn, t["id"], px, exit_reason="TARGET")
                closed.append({"ticker": ticker, "reason": "TARGET", "price": px})
        stats = get_paper_trade_stats(conn)
    finally:
        conn.close()
    return {"marks": marks, "closed": closed, "stats": stats}


def record_daily_review(
    brief_summary: str,
    judge_results: list[dict],
    opened: list[dict],
) -> dict:
    """Append a day to the paper-week log and recompute pass/fail readiness."""
    state = load_paper_week()
    if state.get("status") not in ("RUNNING", "EXTENDED"):
        state = start_paper_week()

    trusts = [float(j.get("overall_trust") or 0) for j in judge_results if j]
    halls = [float(j.get("hallucination_score") or 0) for j in judge_results if j]
    passes = sum(1 for j in judge_results if (j or {}).get("verdict") == "PASS")
    fails = sum(1 for j in judge_results if (j or {}).get("verdict") == "FAIL")

    mtm = mark_to_market()
    day = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "summary": brief_summary,
        "judge_pass": passes,
        "judge_fail": fails,
        "judge_count": len(judge_results),
        "avg_trust": round(sum(trusts) / len(trusts), 1) if trusts else None,
        "avg_hallucination": round(sum(halls) / len(halls), 1) if halls else None,
        "paper_opened": opened,
        "mtm": mtm,
    }
    logs = state.get("daily_logs") or []
    # replace same-day entry
    logs = [d for d in logs if d.get("date") != day["date"]]
    logs.append(day)
    state["daily_logs"] = logs

    state["metrics"] = _compute_metrics(state, mtm.get("stats") or {})
    state = _evaluate_gate(state)
    save_paper_week(state)
    return state


def _compute_metrics(state: dict, trade_stats: dict) -> dict:
    logs = state.get("daily_logs") or []
    days_done = len(logs)
    avg_trust = None
    avg_hall = None
    if logs:
        trusts = [d["avg_trust"] for d in logs if d.get("avg_trust") is not None]
        halls = [d["avg_hallucination"] for d in logs if d.get("avg_hallucination") is not None]
        avg_trust = round(sum(trusts) / len(trusts), 1) if trusts else None
        avg_hall = round(sum(halls) / len(halls), 1) if halls else None
    total_judge = sum(d.get("judge_count") or 0 for d in logs)
    total_pass = sum(d.get("judge_pass") or 0 for d in logs)
    return {
        "days_logged": days_done,
        "days_required": state.get("days_required") or PAPER_WEEK_DAYS,
        "avg_judge_trust": avg_trust,
        "avg_hallucination_score": avg_hall,
        "judge_pass_rate": round(total_pass / total_judge * 100, 1) if total_judge else None,
        "paper_trade_stats": trade_stats,
        "closed_trades": trade_stats.get("total_trades", 0),
        "win_rate": trade_stats.get("win_rate"),
        "total_pnl": trade_stats.get("total_pnl"),
    }


def _evaluate_gate(state: dict) -> dict:
    metrics = state.get("metrics") or {}
    days_ok = metrics.get("days_logged", 0) >= (state.get("days_required") or PAPER_WEEK_DAYS)
    trust = metrics.get("avg_judge_trust")
    trust_ok = trust is not None and trust >= PAPER_WEEK_MIN_TRUST
    trades = int((metrics.get("paper_trade_stats") or {}).get("total_trades") or 0)
    open_n = 0
    try:
        conn = get_connection()
        open_n = len(get_open_paper_trades(conn))
        conn.close()
    except Exception:
        pass
    sample_ok = (trades + open_n) >= PAPER_WEEK_MIN_TRADES
    hall = metrics.get("avg_hallucination_score")
    hall_ok = hall is None or hall <= 35

    if not days_ok:
        state["status"] = "RUNNING"
        state["real_money_unlocked"] = False
        state["gate_detail"] = "Waiting for full paper week duration."
        return state

    if trust_ok and sample_ok and hall_ok:
        state["status"] = "PASSED"
        state["real_money_unlocked"] = True
        state["gate_detail"] = (
            "Paper week PASSED. Set REAL_MONEY_ENABLED=true only if you accept the risk. "
            "Kotak remains read-only unless you intentionally add order code later."
        )
    else:
        state["status"] = "FAILED"
        state["real_money_unlocked"] = False
        missing = []
        if not trust_ok:
            missing.append(f"avg trust {trust} < {PAPER_WEEK_MIN_TRUST}")
        if not sample_ok:
            missing.append(f"trades {trades + open_n} < {PAPER_WEEK_MIN_TRADES}")
        if not hall_ok:
            missing.append(f"hallucination {hall} > 35")
        state["gate_detail"] = "Paper week FAILED gates: " + "; ".join(missing)
        state["notes"] = list(state.get("notes") or []) + [
            "Extend another week with --paper-week-extend after fixing issues."
        ]
    return state


def extend_paper_week(extra_days: int = 7) -> dict:
    state = load_paper_week()
    state["days_required"] = int(state.get("days_required") or PAPER_WEEK_DAYS) + extra_days
    ends = state.get("ends_at")
    try:
        base = datetime.fromisoformat(ends) if ends else datetime.now()
    except Exception:
        base = datetime.now()
    state["ends_at"] = (base + timedelta(days=extra_days)).isoformat()
    state["status"] = "EXTENDED"
    state["real_money_unlocked"] = False
    state["notes"] = list(state.get("notes") or []) + [f"Extended by {extra_days} days."]
    save_paper_week(state)
    return state
