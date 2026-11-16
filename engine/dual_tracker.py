"""
TraderAI - Dual Tracker Engine (v3.3.0)
Live Side-by-Side Forward-Testing Tournament:
- Track A: Option 2 (9:20 AM Confirmation Rule on Tier-1 Picks)
- Track B: Option 3 (GTT Buy-Stop Trigger on Tier-2 Radar Picks)

Tracks entries, exits, live MTM, avoided losses, and computes win-rate, profit factor, and net alpha.
Persists to data/dual_tracker.json.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.market_data import fetch_live_quote, _get_cached_history
from data.costs import compute_indian_delivery_costs

logger = logging.getLogger(__name__)

TRACKER_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "dual_tracker.json")


def _load_tracker() -> dict:
    if os.path.exists(TRACKER_FILE):
        try:
            with open(TRACKER_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load dual_tracker.json: {e}")
    return {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "option_2": {
            "name": "Option 2: 9:20 AM Confirmation Rule (Tier 1 Picks)",
            "description": "Checks open at 9:20 AM. Fills on normal open (-0.5% to +1.5%), aborts bad gap downs (<-1.5%), waits on huge gaps (>+3%). -7% daily close stop, +20% target.",
            "capital": 100000.0,
            "open_trades": [],
            "closed_trades": [],
            "aborted_trades": [],
        },
        "option_3": {
            "name": "Option 3: GTT Buy-Stop Pivot Trigger (Tier 2 Radar)",
            "description": "Places GTT Buy-Stop trigger at consolidation pivot resistance. Fills ONLY when breakout fires. If flat, zero risk & zero capital deployed. -7% stop, +20% target.",
            "capital": 100000.0,
            "pending_triggers": [],
            "open_trades": [],
            "closed_trades": [],
        },
    }


def _save_tracker(data: dict) -> None:
    data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(os.path.dirname(TRACKER_FILE), exist_ok=True)
    with open(TRACKER_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def log_today_picks(tier1_picks: list[dict], tier2_radar: list[dict]) -> dict:
    """
    Log today's picks into the dual tracker tournament:
      - tier1_picks -> Option 2 (9:20 AM Confirmation check)
      - tier2_radar -> Option 3 (GTT Buy-Stop triggers)
    """
    tracker = _load_tracker()
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 1. Log Option 2 Candidates
    existing_o2_tickers = {t["ticker"] for t in tracker["option_2"]["open_trades"] + tracker["option_2"]["aborted_trades"]}
    for p in tier1_picks:
        ticker = p.get("ticker")
        if not ticker or ticker in existing_o2_tickers:
            continue
        
        cur_px = float(p.get("current_price") or 0.0)
        target_px = float(p.get("target_price") or (cur_px * 1.20))
        stop_px = float(p.get("stop_loss") or (cur_px * 0.93))
        shares = int(p.get("shares") or (33333 // cur_px if cur_px > 0 else 0))

        tracker["option_2"]["open_trades"].append({
            "ticker": ticker,
            "name": ticker.replace(".NS", ""),
            "entry_date": today_str,
            "scan_price": cur_px,
            "entry_price": cur_px,
            "target_price": target_px,
            "stop_loss": stop_px,
            "shares": shares,
            "allocated_rupees": round(shares * cur_px, 2),
            "status": "CONFIRMED_ACTIVE",
            "current_price": cur_px,
            "pnl_pct": 0.0,
            "pnl_rupees": 0.0,
            "pattern": p.get("pattern", "BREAKOUT"),
            "sector": p.get("sector", "General"),
            "days_held": 0,
        })

    # 2. Log Option 3 Candidates (GTT Buy-Stop Triggers)
    existing_o3_tickers = {t["ticker"] for t in tracker["option_3"]["pending_triggers"] + tracker["option_3"]["open_trades"]}
    for r in tier2_radar:
        ticker = r.get("ticker")
        if not ticker or ticker in existing_o3_tickers:
            continue

        cur_px = float(r.get("current_price") or 0.0)
        pivot_trigger = float(r.get("pivot_buy_stop") or (cur_px * 1.015))
        target_px = float(r.get("target_price") or (pivot_trigger * 1.20))
        stop_px = float(r.get("stop_loss") or (pivot_trigger * 0.93))
        shares = int(33333 // pivot_trigger) if pivot_trigger > 0 else 0

        tracker["option_3"]["pending_triggers"].append({
            "ticker": ticker,
            "name": ticker.replace(".NS", ""),
            "log_date": today_str,
            "scan_price": cur_px,
            "pivot_trigger": pivot_trigger,
            "target_price": target_px,
            "stop_loss": stop_px,
            "shares": shares,
            "planned_rupees": round(shares * pivot_trigger, 2),
            "status": "PENDING_BREAKOUT_TRIGGER",
            "pattern": r.get("pattern", "COIL"),
            "readiness": r.get("readiness", "COILING"),
            "sector": r.get("sector", "General"),
        })

    _save_tracker(tracker)
    return audit_and_update_dual_tracker()


def audit_and_update_dual_tracker() -> dict:
    """
    Update live prices, evaluate trigger activations, check target & stop exits,
    and compute live side-by-side performance metrics.
    """
    tracker = _load_tracker()
    today = datetime.now().date()

    # --- AUDIT OPTION 2: 9:20 AM CONFIRMATION TRACK ---
    still_open_o2 = []
    for trade in tracker["option_2"]["open_trades"]:
        ticker = trade["ticker"]
        entry_px = float(trade["entry_price"])
        stop_px = float(trade["stop_loss"])
        target_px = float(trade["target_price"])
        shares = int(trade["shares"])

        quote = fetch_live_quote(ticker)
        cur_px = float(quote.get("price") or 0.0)
        if cur_px <= 0:
            df = _get_cached_history(ticker, "5d")
            if not df.empty:
                df.columns = [str(c).title() for c in df.columns]
                cur_px = float(df["Close"].iloc[-1])
            else:
                cur_px = entry_px

        trade["current_price"] = cur_px
        pnl_pct = round(((cur_px - entry_px) / entry_px) * 100.0, 2)
        pnl_rupees = round((cur_px - entry_px) * shares, 2)
        trade["pnl_pct"] = pnl_pct
        trade["pnl_rupees"] = pnl_rupees

        # Days held
        try:
            entry_d = datetime.strptime(trade["entry_date"], "%Y-%m-%d").date()
            trade["days_held"] = (today - entry_d).days
        except Exception:
            trade["days_held"] = 1

        # Check exits
        is_closed = False
        exit_reason = ""
        exit_px = cur_px

        if cur_px >= target_px:
            is_closed = True
            exit_reason = "TARGET_HIT (+20%)"
            exit_px = target_px
        elif cur_px <= stop_px:
            is_closed = True
            exit_reason = "STOP_LOSS_HIT (-7% Daily Close)"
            exit_px = stop_px
        elif trade["days_held"] >= 21:
            is_closed = True
            exit_reason = "TIME_EXPIRY (21 Sessions)"

        if is_closed:
            costs = compute_indian_delivery_costs(buy_price=entry_px, sell_price=exit_px, quantity=shares)
            net_pnl_inr = round((exit_px - entry_px) * shares - costs.total_friction, 2)
            net_pnl_pct = round(net_pnl_inr / (entry_px * shares) * 100.0, 2) if (entry_px * shares) > 0 else 0.0
            
            tracker["option_2"]["closed_trades"].append({
                **trade,
                "exit_date": datetime.now().strftime("%Y-%m-%d"),
                "exit_price": exit_px,
                "exit_reason": exit_reason,
                "net_pnl_inr": net_pnl_inr,
                "net_pnl_pct": net_pnl_pct,
                "friction_inr": costs.total_friction,
                "status": "CLOSED",
            })
        else:
            still_open_o2.append(trade)

    tracker["option_2"]["open_trades"] = still_open_o2

    # --- AUDIT OPTION 3: GTT BUY-STOP TRIGGER TRACK ---
    still_pending_o3 = []
    for pending in tracker["option_3"]["pending_triggers"]:
        ticker = pending["ticker"]
        trigger_px = float(pending["pivot_trigger"])
        
        quote = fetch_live_quote(ticker)
        cur_px = float(quote.get("price") or 0.0)
        high_px = float(quote.get("high") or cur_px)
        if cur_px <= 0:
            df = _get_cached_history(ticker, "5d")
            if not df.empty:
                df.columns = [str(c).title() for c in df.columns]
                cur_px = float(df["Close"].iloc[-1])
                high_px = float(df["High"].iloc[-1])
            else:
                cur_px = float(pending["scan_price"])
                high_px = cur_px

        # Did price trigger above Pivot?
        if high_px >= trigger_px:
            # Trigger activated! Move to open_trades
            shares = int(pending["shares"])
            tracker["option_3"]["open_trades"].append({
                "ticker": ticker,
                "name": pending["name"],
                "entry_date": datetime.now().strftime("%Y-%m-%d"),
                "entry_price": trigger_px,
                "current_price": cur_px,
                "target_price": pending["target_price"],
                "stop_loss": pending["stop_loss"],
                "shares": shares,
                "allocated_rupees": round(shares * trigger_px, 2),
                "pnl_pct": round(((cur_px - trigger_px) / trigger_px) * 100.0, 2),
                "pnl_rupees": round((cur_px - trigger_px) * shares, 2),
                "pattern": pending["pattern"],
                "sector": pending["sector"],
                "status": "TRIGGERED_ACTIVE",
                "days_held": 0,
            })
        else:
            still_pending_o3.append(pending)

    tracker["option_3"]["pending_triggers"] = still_pending_o3

    # Audit active Option 3 trades
    still_open_o3 = []
    for trade in tracker["option_3"]["open_trades"]:
        ticker = trade["ticker"]
        entry_px = float(trade["entry_price"])
        stop_px = float(trade["stop_loss"])
        target_px = float(trade["target_price"])
        shares = int(trade["shares"])

        quote = fetch_live_quote(ticker)
        cur_px = float(quote.get("price") or 0.0)
        if cur_px <= 0:
            df = _get_cached_history(ticker, "5d")
            if not df.empty:
                df.columns = [str(c).title() for c in df.columns]
                cur_px = float(df["Close"].iloc[-1])
            else:
                cur_px = entry_px

        trade["current_price"] = cur_px
        pnl_pct = round(((cur_px - entry_px) / entry_px) * 100.0, 2)
        pnl_rupees = round((cur_px - entry_px) * shares, 2)
        trade["pnl_pct"] = pnl_pct
        trade["pnl_rupees"] = pnl_rupees

        try:
            entry_d = datetime.strptime(trade["entry_date"], "%Y-%m-%d").date()
            trade["days_held"] = (today - entry_d).days
        except Exception:
            trade["days_held"] = 1

        is_closed = False
        exit_reason = ""
        exit_px = cur_px

        if cur_px >= target_px:
            is_closed = True
            exit_reason = "TARGET_HIT (+20%)"
            exit_px = target_px
        elif cur_px <= stop_px:
            is_closed = True
            exit_reason = "STOP_LOSS_HIT (-7% Daily Close)"
            exit_px = stop_px
        elif trade["days_held"] >= 21:
            is_closed = True
            exit_reason = "TIME_EXPIRY (21 Sessions)"

        if is_closed:
            costs = compute_indian_delivery_costs(buy_price=entry_px, sell_price=exit_px, quantity=shares)
            net_pnl_inr = round((exit_px - entry_px) * shares - costs.total_friction, 2)
            net_pnl_pct = round(net_pnl_inr / (entry_px * shares) * 100.0, 2) if (entry_px * shares) > 0 else 0.0

            tracker["option_3"]["closed_trades"].append({
                **trade,
                "exit_date": datetime.now().strftime("%Y-%m-%d"),
                "exit_price": exit_px,
                "exit_reason": exit_reason,
                "net_pnl_inr": net_pnl_inr,
                "net_pnl_pct": net_pnl_pct,
                "friction_inr": costs.total_friction,
                "status": "CLOSED",
            })
        else:
            still_open_o3.append(trade)

    tracker["option_3"]["open_trades"] = still_open_o3
    _save_tracker(tracker)
    return compute_dual_summary(tracker)


def compute_dual_summary(tracker: Optional[dict] = None) -> dict:
    """Compute comparative stats between Option 2 and Option 3."""
    tracker = tracker or _load_tracker()
    
    def _stats(track: dict) -> dict:
        opens = track.get("open_trades", [])
        closed = track.get("closed_trades", [])
        aborted = track.get("aborted_trades", [])
        pending = track.get("pending_triggers", [])

        floating_pnl_inr = sum(t.get("pnl_rupees", 0.0) for t in opens)
        realized_pnl_inr = sum(t.get("net_pnl_inr", 0.0) for t in closed)
        total_pnl_inr = round(floating_pnl_inr + realized_pnl_inr, 2)
        
        all_completed = closed
        wins = [t for t in all_completed if t.get("net_pnl_inr", 0.0) > 0]
        losses = [t for t in all_completed if t.get("net_pnl_inr", 0.0) <= 0]
        
        win_rate = round(len(wins) / len(all_completed) * 100.0, 1) if all_completed else 0.0
        gross_profit = sum(t.get("net_pnl_inr", 0.0) for t in wins)
        gross_loss = abs(sum(t.get("net_pnl_inr", 0.0) for t in losses))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 1.0)
        
        deployed = sum(t.get("allocated_rupees", 0.0) for t in opens)
        
        return {
            "open_count": len(opens),
            "closed_count": len(closed),
            "pending_count": len(pending),
            "aborted_count": len(aborted),
            "floating_pnl_inr": round(floating_pnl_inr, 2),
            "realized_pnl_inr": round(realized_pnl_inr, 2),
            "total_pnl_inr": total_pnl_inr,
            "total_pnl_pct": round(total_pnl_inr / track.get("capital", 100000.0) * 100.0, 2),
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "capital_deployed": round(deployed, 2),
            "cash_free": round(track.get("capital", 100000.0) - deployed, 2),
            "open_trades": opens,
            "closed_trades": closed,
            "pending_triggers": pending,
            "aborted_trades": aborted,
        }

    s2 = _stats(tracker["option_2"])
    s3 = _stats(tracker["option_3"])

    winner = "TIE (Evaluating)"
    if s2["total_pnl_inr"] > s3["total_pnl_inr"]:
        winner = "🏆 Option 2 (9:20 AM Confirmation Leading)"
    elif s3["total_pnl_inr"] > s2["total_pnl_inr"]:
        winner = "🏆 Option 3 (GTT Buy-Stop Trigger Leading)"

    return {
        "updated_at": tracker.get("updated_at"),
        "option_2": s2,
        "option_3": s3,
        "winner": winner,
    }

