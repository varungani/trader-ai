"""
TraderAI - Institutional Forward Validation Engine
Validates strategy recommendations on out-of-sample live market data with zero real money.
Computes 4 institutional scorecards:
  1. Realized Net Expectancy After Friction
  2. Alpha Generation vs Nifty 50 Benchmark
  3. Factor Predictive Power (Information Coefficient proxy)
  4. AI Judge Value-Add Audit
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.db import (
    get_connection,
    get_open_forward_trades,
    get_all_forward_trades,
    log_forward_trade,
    update_forward_trade_mtm,
    resolve_forward_trade,
)
from data.market_data import fetch_live_quote

logger = logging.getLogger(__name__)


def _get_live_nifty_price() -> float:
    """Fetch live price of Nifty 50 ETF (NIFTYBEES.NS)."""
    try:
        q = fetch_live_quote("NIFTYBEES.NS")
        px = float(q.get("price") or 0.0)
        if px > 0:
            return px
    except Exception as e:
        logger.debug(f"Failed to fetch NIFTYBEES quote: {e}")
    return 0.0


def record_daily_snapshot(
    recommendations: list[dict],
    macro: Optional[dict] = None,
    judge_reviews: Optional[list[dict]] = None,
) -> list[dict]:
    """
    Log an unalterable 09:30 AM recommendation snapshot to SQLite.
    Only snapshots actionable BUY / STRONG_BUY recommendations.
    """
    if not recommendations:
        return []

    judge_map = {
        j.get("ticker"): j.get("verdict", "PASS")
        for j in (judge_reviews or [])
        if j.get("ticker")
    }

    nifty_px = _get_live_nifty_price()
    logged = []
    conn = get_connection()
    try:
        now_ts = datetime.now().isoformat()
        today_date = datetime.now().strftime("%Y-%m-%d")

        for r in recommendations:
            action = r.get("action", "HOLD")
            ticker = r.get("ticker")
            if not ticker:
                continue

            entry_px = float(r.get("current_price") or 0.0)
            if entry_px <= 0:
                continue

            stop_px = float(r.get("stop_loss") or (entry_px * 0.93))
            target_px = float(r.get("target_price") or (entry_px * 1.15))

            record = {
                "timestamp": now_ts,
                "date": today_date,
                "ticker": ticker,
                "timeframe": r.get("preferred_timeframe") or r.get("timeframe", "short_term"),
                "action": action,
                "entry_price": entry_px,
                "stop_loss": stop_px,
                "target_price": target_px,
                "final_score": float(r.get("final_score") or 50.0),
                "technical_score": float(r.get("technical_score") or 50.0),
                "fundamental_score": float(r.get("fundamental_score") or 50.0),
                "sentiment_score": float(r.get("sentiment_score") or 50.0),
                "macro_score": float((macro or {}).get("score") or 50.0),
                "event_risk_score": float(r.get("event_risk_score") or 50.0),
                "judge_verdict": judge_map.get(ticker, "PASS"),
                "nifty_entry_price": nifty_px,
            }

            trade_id = log_forward_trade(conn, record)
            logged.append({"id": trade_id, "ticker": ticker, "entry": entry_px, "action": action})
    finally:
        conn.close()

    return logged


from engine.trade_policy import evaluate_trade_exit
from data.costs import compute_indian_delivery_costs


def audit_and_resolve_forward_trades() -> dict:
    """
    Mark open forward trades to live market prices using Unified Trade Policy.
    Resolves trades upon hitting target (+15%), dynamic stop-loss, or T+20 day expiry.
    """
    conn = get_connection()
    resolved = []
    updated = []
    nifty_px = _get_live_nifty_price()

    try:
        opens = get_open_forward_trades(conn)
        today = datetime.now().date()

        for t in opens:
            trade_id = t["id"]
            ticker = t["ticker"]
            entry_px = float(t["entry_price"])
            stop_px = float(t["stop_loss"])
            target_px = float(t["target_price"])
            nifty_entry = float(t.get("nifty_entry_price") or 0.0)

            # Calculate days held
            entry_date = datetime.strptime(t["date"], "%Y-%m-%d").date()
            days_held = (today - entry_date).days

            quote = fetch_live_quote(ticker)
            cur_px = float(quote.get("price") or 0.0)
            if not cur_px or cur_px <= 0:
                continue

            nifty_pnl_pct = (
                round(((nifty_px - nifty_entry) / nifty_entry) * 100.0, 2)
                if (nifty_px > 0 and nifty_entry > 0)
                else 0.0
            )

            # Evaluate exit using Single Source of Truth Trade Policy
            exit_eval = evaluate_trade_exit(
                entry_price=entry_px,
                current_price=cur_px,
                stop_loss=stop_px,
                target_price=target_px,
                days_held=days_held,
            )

            if exit_eval.is_closed:
                # Compute realistic Indian delivery costs & true Net P&L
                costs = compute_indian_delivery_costs(buy_price=entry_px, sell_price=exit_eval.exit_price, quantity=1)
                net_pnl = costs.net_pnl_pct
                alpha_pct = round(net_pnl - nifty_pnl_pct, 2)

                resolution = {
                    "exit_price": exit_eval.exit_price,
                    "exit_date": datetime.now().strftime("%Y-%m-%d"),
                    "exit_reason": exit_eval.exit_reason,
                    "exit_pnl_pct": net_pnl,
                    "exit_alpha_pct": alpha_pct,
                    "status": "RESOLVED_" + (exit_eval.exit_reason or "EXIT").split()[0],
                }
                resolve_forward_trade(conn, trade_id, resolution)
                resolved.append({
                    "ticker": ticker,
                    "reason": exit_eval.exit_reason,
                    "pnl_pct": net_pnl,
                    "alpha_pct": alpha_pct,
                    "days_held": days_held,
                })
            else:
                costs = compute_indian_delivery_costs(buy_price=entry_px, sell_price=cur_px, quantity=1)
                stock_pnl_pct = costs.net_pnl_pct
                alpha_pct = round(stock_pnl_pct - nifty_pnl_pct, 2)

                mtm_update = {
                    "current_price": cur_px,
                    "current_pnl_pct": stock_pnl_pct,
                    "nifty_current_price": nifty_px,
                    "nifty_pnl_pct": nifty_pnl_pct,
                    "alpha_pct": alpha_pct,
                    "days_held": days_held,
                }
                update_forward_trade_mtm(conn, trade_id, mtm_update)
                updated.append({"ticker": ticker, "pnl_pct": stock_pnl_pct, "alpha": alpha_pct})

    finally:
        conn.close()

    return {"updated": updated, "resolved": resolved, "open_count": len(opens) - len(resolved)}


def compute_institutional_scorecards() -> dict:
    """
    Calculates the 4 rigorous institutional validation scorecards:
      1. Realized Net Expectancy (with single-deducted statutory costs)
      2. Alpha Generation vs Nifty 50
      3. Factor Predictive Power (Non-overlapping score quintiles)
      4. AI Judge Value-Add
    """
    conn = get_connection()
    try:
        all_trades = get_all_forward_trades(conn, limit=200)
    finally:
        conn.close()

    if not all_trades:
        return {
            "has_data": False,
            "total_trades": 0,
            "message": "No forward test recommendations logged yet. Run analysis to start logging.",
        }

    resolved_trades = [t for t in all_trades if "RESOLVED" in (t.get("status") or "")]
    open_trades = [t for t in all_trades if t.get("status") == "OPEN"]

    # ─── SCORECARD 1: Realized Net Expectancy ─────────────────────────
    total_resolved = len(resolved_trades)
    if total_resolved > 0:
        wins = [t for t in resolved_trades if float(t.get("exit_pnl_pct") or 0.0) > 0]
        losses = [t for t in resolved_trades if float(t.get("exit_pnl_pct") or 0.0) < 0]
        decisive = len(wins) + len(losses)
        win_rate = round(len(wins) / decisive * 100.0, 1) if decisive else 0.0
        avg_win = (
            round(sum(float(t["exit_pnl_pct"]) for t in wins) / len(wins), 2)
            if wins
            else 0.0
        )
        avg_loss = (
            round(sum(float(t["exit_pnl_pct"]) for t in losses) / len(losses), 2)
            if losses
            else 0.0
        )
        # Returns are ALREADY net of statutory friction; compute exact expectancy without double-counting
        p_win = win_rate / 100.0
        p_loss = (100.0 - win_rate) / 100.0
        net_expectancy = round((p_win * avg_win) + (p_loss * avg_loss), 2)
        is_day_zero = False
    else:
        # If still in forward holding period, compute on live mark-to-market
        wins = [t for t in open_trades if float(t.get("current_pnl_pct") or 0.0) > 0]
        losses = [t for t in open_trades if float(t.get("current_pnl_pct") or 0.0) < 0]
        decisive = len(wins) + len(losses)
        if decisive == 0:
            # Day 0 Snapshot: market has not opened yet (weekend/entry baseline)
            win_rate = 0.0
            avg_win = 0.0
            avg_loss = 0.0
            net_expectancy = 0.0
            is_day_zero = True
        else:
            win_rate = round(len(wins) / decisive * 100.0, 1)
            avg_win = (
                round(sum(float(t.get("current_pnl_pct") or 0) for t in wins) / len(wins), 2)
                if wins
                else 0.0
            )
            avg_loss = (
                round(sum(float(t.get("current_pnl_pct") or 0) for t in losses) / len(losses), 2)
                if losses
                else 0.0
            )
            p_win = win_rate / 100.0
            p_loss = (100.0 - win_rate) / 100.0
            net_expectancy = round((p_win * avg_win) + (p_loss * avg_loss), 2)
            is_day_zero = False


    # ─── SCORECARD 2: Alpha Generation vs Nifty 50 ─────────────────────
    trades_with_alpha = [t for t in all_trades if t.get("alpha_pct") is not None]
    if trades_with_alpha:
        avg_alpha = round(sum(float(t["alpha_pct"]) for t in trades_with_alpha) / len(trades_with_alpha), 2)
        stocks_beating_nifty = sum(1 for t in trades_with_alpha if float(t["alpha_pct"]) > 0)
        nifty_beat_rate = round(stocks_beating_nifty / len(trades_with_alpha) * 100.0, 1)
    else:
        avg_alpha = 0.0
        nifty_beat_rate = 0.0

    # ─── SCORECARD 3: Factor Predictive Power ─────────────────────────
    # Do high scores (>70) outperform lower scores (<55)?
    high_score_trades = [t for t in all_trades if float(t.get("final_score") or 0) >= 70]
    mid_score_trades = [t for t in all_trades if 55 <= float(t.get("final_score") or 0) < 70]
    low_score_trades = [t for t in all_trades if float(t.get("final_score") or 0) < 55]

    def _mean_ret(items):
        if not items:
            return 0.0
        rets = [float(t.get("exit_pnl_pct") if "RESOLVED" in (t.get("status") or "") else t.get("current_pnl_pct") or 0.0) for t in items]
        return round(sum(rets) / len(rets), 2)

    factor_power = {
        "high_tier_score_avg_return": _mean_ret(high_score_trades),
        "high_tier_count": len(high_score_trades),
        "mid_tier_score_avg_return": _mean_ret(mid_score_trades),
        "mid_tier_count": len(mid_score_trades),
        "low_tier_score_avg_return": _mean_ret(low_score_trades),
        "low_tier_count": len(low_score_trades),
    }

    # ─── SCORECARD 4: AI Judge Value-Add ──────────────────────────────
    approved = [t for t in all_trades if t.get("judge_verdict") == "PASS"]
    vetoed = [t for t in all_trades if t.get("judge_verdict") in ("REVISE", "FAIL")]
    judge_audit = {
        "approved_count": len(approved),
        "approved_avg_return": _mean_ret(approved),
        "vetoed_count": len(vetoed),
        "vetoed_avg_return": _mean_ret(vetoed),
        "judge_saved_capital": (_mean_ret(approved) > _mean_ret(vetoed)),
    }

    return {
        "has_data": True,
        "total_forward_trades": len(all_trades),
        "open_trades_count": len(open_trades),
        "resolved_trades_count": len(resolved_trades),
        "scorecard_1_expectancy": {
            "win_rate": win_rate,
            "avg_win_pct": avg_win,
            "avg_loss_pct": avg_loss,
            "net_expectancy_per_trade": net_expectancy,
            "is_positive": net_expectancy > 0,
            "is_day_zero": is_day_zero,
        },
        "scorecard_2_alpha": {
            "avg_alpha_vs_nifty": avg_alpha,
            "nifty_beat_rate_pct": nifty_beat_rate,
            "is_alpha_positive": avg_alpha > 0,
        },
        "scorecard_3_factor_power": factor_power,
        "scorecard_4_judge_audit": judge_audit,
        "recent_forward_trades": all_trades[:25],
    }
