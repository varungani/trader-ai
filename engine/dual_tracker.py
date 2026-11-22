"""
TraderAI - 3-Way Parallel Tournament Tracker (v3.4.0)
Live Side-by-Side Forward-Testing Tournament across 3 Parallel Execution Models:
  - Track A: Option 2 (9:20 AM Confirmation Rule on Tier-1 Picks)
  - Track B: Option 3 (GTT Buy-Stop Trigger on Tier-2 Radar Picks with +20% Target)
  - Track C: Benchmark Velocity Sniper (GTT Pivot Trigger with Expanded +25% Target & 72h Velocity Gate)

Tracks entries, exits, live MTM, avoided losses, and computes win-rate, profit factor, and net alpha.
Persists to data/dual_tracker.json.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, time as dtime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.market_data import fetch_live_quote, _get_cached_history
from data.costs import compute_indian_delivery_costs
from data.market_calendar import get_market_status, is_trading_day, get_ist_now, get_next_trading_day, count_trading_days
from config import TOURNAMENT_CONFIG

logger = logging.getLogger(__name__)

TRACKER_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "dual_tracker.json")

# Unified Tournament & High-Velocity Architecture Constants (5 Slots @ ₹20,000)
MAX_SLOTS: int = int(TOURNAMENT_CONFIG.get("max_slots", 5))
SLOT_CAPITAL: float = float(TOURNAMENT_CONFIG.get("slot_capital", 20000.0))
TOTAL_CAPITAL: float = float(TOURNAMENT_CONFIG.get("total_capital", 100000.0))
SLIPPAGE_PCT: float = float(TOURNAMENT_CONFIG.get("slippage_pct", 0.0025))
TARGET_PCT: float = float(TOURNAMENT_CONFIG.get("target_pct", 0.12))
STOP_LOSS_PCT: float = float(TOURNAMENT_CONFIG.get("stop_loss_pct", 0.04))
BREAKEVEN_TRIGGER_PCT: float = float(TOURNAMENT_CONFIG.get("breakeven_trigger_pct", 0.05))
BREAKEVEN_LOCK_PCT: float = float(TOURNAMENT_CONFIG.get("breakeven_lock_pct", 0.006))
T1_HARVEST_PCT: float = float(TOURNAMENT_CONFIG.get("t1_harvest_pct", 0.05))
T1_HARVEST_FRACTION: float = float(TOURNAMENT_CONFIG.get("t1_harvest_fraction", 0.50))
ANTI_FOMO_MAX_GAP_PCT: float = float(TOURNAMENT_CONFIG.get("anti_fomo_max_gap_pct", 0.025))
IGNITION_MIN_RVOL: float = float(TOURNAMENT_CONFIG.get("ignition_min_rvol", 1.8))
VELOCITY_KILL_DAYS: int = int(TOURNAMENT_CONFIG.get("velocity_kill_days", 3))
VELOCITY_KILL_MIN_PNL: float = float(TOURNAMENT_CONFIG.get("velocity_kill_min_pnl", 1.5))
MAX_HOLDING_DAYS: int = int(TOURNAMENT_CONFIG.get("max_holding_days", 7))


def _get_free_cash(track: dict) -> float:
    """Computes pure available cash: starting capital + closed PnL + partial harvest PnL - deployed."""
    total_cap = float(track.get("capital", TOTAL_CAPITAL))
    realized_closed = sum(float(t.get("net_pnl_inr", 0.0)) for t in track.get("closed_trades", []))
    realized_partial = sum(float(t.get("realized_pnl_inr", 0.0)) for t in track.get("open_trades", []))
    deployed = sum(float(t.get("allocated_rupees", 0.0)) for t in track.get("open_trades", []))
    return round(total_cap + realized_closed + realized_partial - deployed, 2)


def _can_fill_trade(track: dict, slot_capital: float = SLOT_CAPITAL, max_slots: int = MAX_SLOTS) -> tuple[bool, str]:
    """Strictly enforces slot capacity (max 5) and non-negative cash cushion (zero leverage)."""
    open_trades = track.get("open_trades", [])
    if len(open_trades) >= max_slots:
        return False, f"All {max_slots} slots full ({len(open_trades)} active)."
    
    cash_free = _get_free_cash(track)
    if cash_free < 5000.0:
        return False, f"Insufficient free cash (Free: ₹{cash_free:.2f}, Min: ₹5,000.00)."
    return True, ""


def _send_telegram_alert(alert_type: str, **kwargs):
    """Safely trigger Telegram alert if enabled, without interrupting trading execution."""
    try:
        from bot.telegram_notifier import default_telegram_notifier
        if alert_type == "breakout_fill":
            default_telegram_notifier.notify_breakout_fill(**kwargs)
        elif alert_type == "breakeven_lock":
            default_telegram_notifier.notify_breakeven_lock(**kwargs)
        elif alert_type == "target_hit":
            default_telegram_notifier.notify_target_hit(**kwargs)
        elif alert_type == "stop_loss_hit":
            default_telegram_notifier.notify_stop_loss_hit(**kwargs)
        elif alert_type == "velocity_kill":
            default_telegram_notifier.notify_velocity_kill(**kwargs)
    except Exception as e:
        logger.debug(f"Telegram alert dispatch error: {e}")


# Backward-compatibility alias
_send_telegram_alert = _send_telegram_alert


def _default_tracker_state() -> dict:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "created_at": now_str,
        "updated_at": now_str,
        "option_2": {
            "name": "Track A: Algo 2 - Minervini VCP Squeeze (9:20 AM Confirmation)",
            "description": "Checks open at 9:20 AM after VCP volatility contraction. Fills on normal open (-0.5% to +1.5%), aborts bad gap downs (<-1.5%). Banks 50% at +5% T1, locks rest at breakeven + friction (+0.6%), Target +12%.",
            "capital": TOTAL_CAPITAL,
            "max_slots": MAX_SLOTS,
            "pending_confirmations": [],
            "open_trades": [],
            "closed_trades": [],
            "aborted_trades": [],
        },
        "option_3": {
            "name": "Track B: Algo 1 - Morning Ignition Thrust (GTT Buy-Stop + T1 Profit Lock)",
            "description": "GTT Buy-Stop trigger at consolidation pivot resistance with 09:30 AM volume run-rate check. Fills on breakout. Sells 50% at +5% T1 profit target, locks rest at breakeven + friction (+0.6%), trails runner with +12% target.",
            "capital": TOTAL_CAPITAL,
            "max_slots": MAX_SLOTS,
            "pending_triggers": [],
            "open_trades": [],
            "closed_trades": [],
            "aborted_trades": [],
        },
        "track_c": {
            "name": "Track C: Algo 3 - Benchmark Velocity Sniper (52W / High-RS Leader Breakout)",
            "description": "GTT Pivot Breakout entry on Top High-RS leaders. Sells 50% at +5% T1, locks rest at breakeven, trails runner with +12% target, 72h Velocity Kill (< +1.5% after 3 days).",
            "capital": TOTAL_CAPITAL,
            "max_slots": MAX_SLOTS,
            "pending_triggers": [],
            "open_trades": [],
            "closed_trades": [],
            "aborted_trades": [],
        },
    }


def _load_tracker() -> dict:
    default_state = _default_tracker_state()
    if os.path.exists(TRACKER_FILE):
        try:
            with open(TRACKER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "track_c" not in data:
                    data["track_c"] = default_state["track_c"]
                if "pending_confirmations" not in data.get("option_2", {}):
                    data.setdefault("option_2", {})["pending_confirmations"] = []
                # Migration: ensure shortlist_date & fill_date exist on all trades
                for trk in ["option_2", "option_3", "track_c"]:
                    if trk in data:
                        for t in data[trk].get("open_trades", []):
                            if "shortlist_date" not in t:
                                t["shortlist_date"] = t.get("entry_date", "2026-11-16")
                            if "fill_date" not in t:
                                t["fill_date"] = t.get("entry_date", "2026-11-16")
                        for t in data[trk].get("pending_triggers", []):
                            if "shortlist_date" not in t:
                                t["shortlist_date"] = t.get("log_date", "2026-11-16")
                        for t in data[trk].get("closed_trades", []):
                            if "shortlist_date" not in t:
                                t["shortlist_date"] = t.get("entry_date", "2026-11-16")
                            if "fill_date" not in t:
                                t["fill_date"] = t.get("entry_date", "2026-11-16")
                return data
        except Exception as e:
            logger.warning(f"Failed to load dual_tracker.json: {e}")
    return default_state


def _save_tracker(data: dict) -> None:
    data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(os.path.dirname(TRACKER_FILE), exist_ok=True)
    with open(TRACKER_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def _can_trigger_breakout(shortlist_date_str: str, force_market_open: bool = False) -> tuple[bool, str]:
    """
    Determines whether a pending GTT breakout trigger is allowed to execute based on NSE/BSE trading rules.
    Returns: (can_execute, fill_timestamp_str)
    
    Strict Indian Market Execution Rules:
      1. force_market_open=True: Manual force/unit test override.
      2. Market is OPEN (09:15 - 15:30 IST on a trading day):
         - Breakouts are executed live in real-time as prices cross triggers.
         - fill_timestamp = current live timestamp (e.g. '2026-11-17 11:45').
      3. Market is CLOSED:
         - A pending trigger CANNOT execute if it was shortlisted today after market hours (it is pending for tomorrow's session).
         - It CAN only be confirmed as triggered if:
           a) Today was a trading day.
           b) The stock was shortlisted on a previous day (shortlist_date_str < today_str).
           c) fill_timestamp = today_str + ' (Intraday)' (triggered during today's market session).
    """
    if force_market_open:
        return True, datetime.now().strftime("%Y-%m-%d %H:%M")

    now = get_ist_now()
    today_str = now.strftime("%Y-%m-%d")
    mkt = get_market_status(now)
    
    # 1. Market is live and trading right now
    if mkt.get("is_open", False):
        return True, now.strftime("%Y-%m-%d %H:%M")
        
    # 2. Market is currently closed: verify if today was a trading day and order was pre-placed
    is_td, _ = is_trading_day(now.date())
    if is_td and shortlist_date_str and str(shortlist_date_str) < today_str:
        return True, f"{today_str} (Market Hours)"
        
    return False, ""


def log_today_picks(tier1_picks: list[dict], tier2_radar: list[dict]) -> dict:
    """
    Log today's picks into all 3 parallel tournament tracks:
      - Track A (Option 2): tier1_picks with 9:20 AM Confirmation check
      - Track B (Option 3): tier2_radar with GTT Buy-Stop triggers (+20% target, -7% stop)
      - Track C (Benchmark Sniper): Top 2 highest-RS rockets (+25% target, -6% stop, 72h gate)
    """
    tracker = _load_tracker()
    now = get_ist_now()
    today_date = now.date()
    today_str = now.strftime("%Y-%m-%d")
    is_td, _ = is_trading_day(today_date)

    # 1. Option 2 Candidates (Track A: 9:20 AM Confirmation Rule)
    # If today is a trading day and current time < 09:20 AM, scheduled for today's 09:20 AM open.
    # Otherwise (scanned after 09:20 AM, evening scan, weekend, or holiday), scheduled for next trading day's open.
    if is_td and now.time() < dtime(9, 20):
        scheduled_date = today_date
    else:
        scheduled_date, _ = get_next_trading_day(today_date)
    scheduled_str = scheduled_date.strftime("%Y-%m-%d")
    scheduled_disp = scheduled_date.strftime("%d %b")

    existing_o2_tickers = {
        t["ticker"] for t in (
            tracker["option_2"].get("pending_confirmations", []) +
            tracker["option_2"]["open_trades"] +
            tracker["option_2"]["aborted_trades"]
        )
    }
    for p in tier1_picks:
        ticker = p.get("ticker")
        if not ticker or ticker in existing_o2_tickers:
            continue
        
        cur_px = float(p.get("current_price") or 0.0)
        target_px = float(p.get("target_price") or round(cur_px * (1.0 + TARGET_PCT), 2))
        stop_px = float(p.get("stop_loss") or round(cur_px * (1.0 - STOP_LOSS_PCT), 2))
        be_lock_px = float(p.get("breakeven_lock") or round(cur_px * (1.0 + BREAKEVEN_TRIGGER_PCT), 2))
        shares = int(p.get("shares") or (SLOT_CAPITAL // cur_px if cur_px > 0 else 0))

        tracker["option_2"].setdefault("pending_confirmations", []).append({
            "ticker": ticker,
            "name": ticker.replace(".NS", ""),
            "shortlist_date": today_str,
            "scheduled_date": scheduled_str,
            "fill_date": f"Awaiting {scheduled_disp} 09:20",
            "scan_price": cur_px,
            "entry_price": cur_px,
            "target_price": target_px,
            "stop_loss": stop_px,
            "breakeven_lock": be_lock_px,
            "shares": shares,
            "planned_rupees": round(shares * cur_px, 2),
            "status": "AWAITING_920_OPEN",
            "current_price": cur_px,
            "pnl_pct": 0.0,
            "pnl_rupees": 0.0,
            "pattern": p.get("pattern", "BREAKOUT"),
            "sector": p.get("sector", "General"),
            "days_held": 0,
        })

    # 2. Log Option 3 Candidates (GTT Buy-Stop Triggers: Target +12%, Stop -4%, Breakeven Lock +5%)
    existing_o3_tickers = {t["ticker"] for t in tracker["option_3"]["pending_triggers"] + tracker["option_3"]["open_trades"]}
    for r in tier2_radar:
        ticker = r.get("ticker")
        if not ticker or ticker in existing_o3_tickers:
            continue

        cur_px = float(r.get("current_price") or 0.0)
        pivot_trigger = float(r.get("pivot_buy_stop") or (cur_px * 1.002))
        target_px = round(pivot_trigger * (1.0 + TARGET_PCT), 2)
        if "stop_loss_pct" in r:
            stop_px = round(pivot_trigger * (1.0 - float(r["stop_loss_pct"]) / 100.0), 2)
        elif "stop_loss" in r and float(r["stop_loss"]) > cur_px:
            stop_px = float(r["stop_loss"])
        else:
            stop_px = round(pivot_trigger * (1.0 - STOP_LOSS_PCT), 2)
        be_lock_px = float(r.get("breakeven_lock") or round(pivot_trigger * (1.0 + BREAKEVEN_TRIGGER_PCT), 2))
        shares = int(SLOT_CAPITAL // pivot_trigger) if pivot_trigger > 0 else 0

        tracker["option_3"]["pending_triggers"].append({
            "ticker": ticker,
            "name": ticker.replace(".NS", ""),
            "shortlist_date": today_str,
            "log_date": today_str,
            "scan_price": cur_px,
            "pivot_trigger": pivot_trigger,
            "target_price": target_px,
            "stop_loss": stop_px,
            "breakeven_lock": be_lock_px,
            "shares": shares,
            "planned_rupees": round(shares * pivot_trigger, 2),
            "status": "PENDING_BREAKOUT_TRIGGER",
            "pattern": r.get("pattern", "COIL"),
            "readiness": r.get("readiness", "COILING"),
            "sector": r.get("sector", "General"),
        })

    # 3. Log Track C Candidates (Benchmark Velocity Sniper: Target +12%, Stop -4%, 72h Gate)
    if "track_c" not in tracker:
        tracker["track_c"] = _default_tracker_state()["track_c"]
    existing_c_tickers = {t["ticker"] for t in tracker["track_c"]["pending_triggers"] + tracker["track_c"]["open_trades"]}
    
    # Pick top 3 coiled setups with highest readiness
    c_candidates = [r for r in tier2_radar if r.get("ticker") not in existing_c_tickers][:3]
    if not c_candidates and tier1_picks:
        c_candidates = [p for p in tier1_picks if p.get("ticker") not in existing_c_tickers][:3]

    for c in c_candidates:
        ticker = c.get("ticker")
        if not ticker or ticker in existing_c_tickers:
            continue
        cur_px = float(c.get("current_price") or 0.0)
        pivot_trigger = float(c.get("pivot_buy_stop") or cur_px)
        target_12 = round(pivot_trigger * (1.0 + TARGET_PCT), 2)
        if "stop_loss_pct" in c:
            stop_4 = round(pivot_trigger * (1.0 - float(c["stop_loss_pct"]) / 100.0), 2)
        elif "stop_loss" in c and float(c["stop_loss"]) > cur_px:
            stop_4 = float(c["stop_loss"])
        else:
            stop_4 = round(pivot_trigger * (1.0 - STOP_LOSS_PCT), 2)
        be_lock_px = float(c.get("breakeven_lock") or round(pivot_trigger * (1.0 + BREAKEVEN_TRIGGER_PCT), 2))
        shares = int(SLOT_CAPITAL // pivot_trigger) if pivot_trigger > 0 else 0

        tracker["track_c"]["pending_triggers"].append({
            "ticker": ticker,
            "name": ticker.replace(".NS", ""),
            "shortlist_date": today_str,
            "log_date": today_str,
            "scan_price": cur_px,
            "pivot_trigger": pivot_trigger,
            "target_price": target_12,
            "stop_loss": stop_4,
            "breakeven_lock": be_lock_px,
            "shares": shares,
            "planned_rupees": round(shares * pivot_trigger, 2),
            "status": "PENDING_BREAKOUT_TRIGGER",
            "pattern": "BENCHMARK_SNIPER",
            "readiness": c.get("readiness", "COILING"),
            "sector": c.get("sector", "General"),
        })

    _save_tracker(tracker)
    return audit_and_update_dual_tracker()


def audit_and_update_dual_tracker(force_market_open: bool = False) -> dict:
    """
    Update live prices, evaluate trigger activations, check target & stop exits,
    and compute live 3-way side-by-side performance metrics.
    Strictly simulates Indian market hours (09:15-15:30 IST) for trigger executions.
    """
    tracker = _load_tracker()
    now = get_ist_now()
    today = now.date()
    today_str = now.strftime("%Y-%m-%d")
    is_td, _ = is_trading_day(today)

    # --- AUDIT TRACK A: OPTION 2 (9:20 AM CONFIRMATION) ---
    # 1. Audit pending 9:20 AM confirmations
    can_evaluate_920 = force_market_open or (is_td and now.time() >= dtime(9, 20))
    still_pending_o2 = []
    for pend in tracker["option_2"].get("pending_confirmations", []):
        sched_d_str = pend.get("scheduled_date", pend.get("shortlist_date", today_str))
        try:
            sched_d = datetime.strptime(sched_d_str, "%Y-%m-%d").date()
        except Exception:
            sched_d = today

        if can_evaluate_920 and (today >= sched_d or force_market_open):
            ticker = pend["ticker"]
            scan_px = float(pend["scan_price"])
            quote = fetch_live_quote(ticker)
            open_px = float(quote.get("open") or quote.get("price") or scan_px)
            if open_px <= 0:
                df = _get_cached_history(ticker, "5d")
                if not df.empty:
                    df.columns = [str(c).title() for c in df.columns]
                    open_px = float(df["Open"].iloc[-1])
                else:
                    open_px = scan_px

            gap_pct = ((open_px - scan_px) / scan_px) * 100.0 if scan_px > 0 else 0.0

            # Abort bad gap down (<-1.5%)
            if gap_pct < -1.5:
                logger.info(f"🚫 [Track A Aborted] {ticker}: Gap down {gap_pct:.2f}% (Scan: ₹{scan_px:.2f}, Open: ₹{open_px:.2f})")
                tracker["option_2"]["aborted_trades"].append({
                    **pend,
                    "abort_date": today_str,
                    "open_price": open_px,
                    "gap_pct": round(gap_pct, 2),
                    "status": "ABORTED_GAP_DOWN",
                    "reason": f"Bad gap down ({gap_pct:.2f}% < -1.5%). Capital preserved.",
                })
            elif gap_pct > 2.5:
                logger.info(f"🚫 [Track A Aborted] {ticker}: Gapped up {gap_pct:+.2f}% beyond buy zone (+2.5% max). Chasing avoided.")
                tracker["option_2"]["aborted_trades"].append({
                    **pend,
                    "abort_date": today_str,
                    "open_price": open_px,
                    "gap_pct": round(gap_pct, 2),
                    "status": "ABORTED_EXTENDED_GAP",
                    "reason": f"Extended beyond +2.5% buy zone (gapped {gap_pct:+.2f}%). Avoided chasing peak.",
                })
            else:
                fill_ts = f"{today_str} 09:20"
                can_fill, fill_reason = _can_fill_trade(tracker["option_2"])
                if not can_fill:
                    logger.info(f"⏳ [Track A Slot Queued] {ticker} @ ₹{open_px:.2f} awaiting free slot: {fill_reason}")
                    pend["status"] = "PENDING_SLOT_CAPACITY"
                    still_pending_o2.append(pend)
                    continue

                # Apply slippage on entry
                fill_px = round(open_px * (1.0 + SLIPPAGE_PCT), 2)
                cash_free_o2 = _get_free_cash(tracker["option_2"])
                slot_budget_o2 = min(SLOT_CAPITAL, cash_free_o2)
                shares = int(slot_budget_o2 // fill_px)
                if shares <= 0:
                    pend["status"] = "PENDING_SLOT_CAPACITY"
                    still_pending_o2.append(pend)
                    continue

                allocated_rupees = round(shares * fill_px, 2)
                stop_loss_px = round(fill_px * (1.0 - STOP_LOSS_PCT), 2)
                target_px = round(fill_px * (1.0 + TARGET_PCT), 2)
                be_lock_px = round(fill_px * (1.0 + BREAKEVEN_TRIGGER_PCT), 2)

                logger.info(f"✅ [Track A Filled] {ticker} @ ₹{fill_px:.2f} (Gap: {gap_pct:+.2f}%, Slippage: {SLIPPAGE_PCT*100:.2f}%) on {fill_ts}")
                tracker["option_2"]["open_trades"].append({
                    **pend,
                    "entry_date": today_str,
                    "fill_date": fill_ts,
                    "entry_price": fill_px,
                    "target_price": target_px,
                    "stop_loss": stop_loss_px,
                    "breakeven_lock": be_lock_px,
                    "shares": shares,
                    "allocated_rupees": allocated_rupees,
                    "status": "CONFIRMED_ACTIVE",
                    "current_price": fill_px,
                    "gap_pct": round(gap_pct, 2),
                })
                _send_telegram_alert(
                    "breakout_fill",
                    ticker=ticker,
                    fill_price=fill_px,
                    target_price=target_px,
                    stop_loss=stop_loss_px,
                    shares=shares,
                    strategy_track="Track A (9:20 AM Open)",
                    sector=pend.get("sector", "General"),
                    pattern=pend.get("pattern", "9:20_OPEN_CONFIRMATION"),
                )
        else:
            still_pending_o2.append(pend)
    tracker["option_2"]["pending_confirmations"] = still_pending_o2

    # 2. Audit open trades
    still_open_o2 = []
    for trade in tracker["option_2"]["open_trades"]:
        ticker = trade["ticker"]
        entry_px = float(trade["entry_price"])
        stop_px = float(trade["stop_loss"])
        target_px = float(trade["target_price"])
        shares = int(trade["shares"])
        
        # Ensure dates exist
        if "shortlist_date" not in trade:
            trade["shortlist_date"] = trade.get("entry_date", today_str)
        if "fill_date" not in trade:
            trade["fill_date"] = trade.get("entry_date", today_str)

        quote = fetch_live_quote(ticker)
        cur_px = float(quote.get("price") or 0.0)
        high_px = float(quote.get("day_high") or quote.get("high") or cur_px)
        low_px = float(quote.get("day_low") or quote.get("low") or cur_px)
        if cur_px <= 0:
            df = _get_cached_history(ticker, "5d")
            if not df.empty:
                df.columns = [str(c).title() for c in df.columns]
                cur_px = float(df["Close"].iloc[-1])
                high_px = float(df["High"].iloc[-1])
                low_px = float(df["Low"].iloc[-1]) if "Low" in df.columns else cur_px
            else:
                cur_px = entry_px
                high_px = entry_px
                low_px = entry_px

        trade["current_price"] = cur_px
        trade["pnl_pct"] = round(((cur_px - entry_px) / entry_px) * 100.0, 2) if entry_px > 0 else 0.0
        trade["pnl_rupees"] = round((cur_px - entry_px) * shares, 2)

        try:
            entry_d = datetime.strptime(trade["entry_date"][:10], "%Y-%m-%d").date()
            trade["days_held"] = count_trading_days(entry_d, today)
        except Exception:
            trade["days_held"] = 1

        is_closed = False
        exit_reason = ""
        exit_px = cur_px

        # Active Breakeven Lock & T1 Partial Profit Harvest (+5.0% gain)
        be_lock = float(trade.get("breakeven_lock") or round(entry_px * (1.0 + BREAKEVEN_TRIGGER_PCT), 2))
        if (high_px >= be_lock or cur_px >= be_lock):
            if not trade.get("t1_harvested") and shares >= 2:
                orig_shares = int(trade.get("orig_shares") or shares)
                trade["orig_shares"] = orig_shares
                harvest_shares = shares // 2
                rem_shares = shares - harvest_shares
                
                t1_exit_px = round(be_lock * (1.0 - SLIPPAGE_PCT), 2)
                t1_costs = compute_indian_delivery_costs(buy_price=entry_px, sell_price=t1_exit_px, quantity=harvest_shares)
                t1_pnl_inr = round((t1_exit_px - entry_px) * harvest_shares - t1_costs.total_friction_rupees, 2)
                
                trade["realized_pnl_inr"] = round(trade.get("realized_pnl_inr", 0.0) + t1_pnl_inr, 2)
                trade["t1_friction_inr"] = round(trade.get("t1_friction_inr", 0.0) + t1_costs.total_friction_rupees, 2)
                trade["shares"] = rem_shares
                trade["allocated_rupees"] = round(rem_shares * entry_px, 2)
                trade["t1_harvested"] = True
                trade["t1_exit_price"] = t1_exit_px
                trade["t1_pnl_inr"] = t1_pnl_inr
                shares = rem_shares
                
                stop_px = round(entry_px * (1.0 + BREAKEVEN_LOCK_PCT), 2)
                trade["stop_loss"] = stop_px
                trade["is_breakeven_locked"] = True
                
                if not trade.get("alert_be_lock_sent"):
                    trade["alert_be_lock_sent"] = True
                    _send_telegram_alert(
                        "breakeven_lock",
                        ticker=ticker,
                        entry_price=entry_px,
                        current_price=cur_px,
                        pnl_pct=trade.get("pnl_pct", 5.0),
                        new_stop_loss=stop_px,
                    )
            elif stop_px < entry_px:
                stop_px = round(entry_px * (1.0 + BREAKEVEN_LOCK_PCT), 2)
                trade["stop_loss"] = stop_px
                trade["is_breakeven_locked"] = True

        # 1. Stop Loss Hit / Breakeven Lock Hit (Conservative Stop-First Ordering)
        if low_px <= stop_px or cur_px <= stop_px:
            is_closed = True
            exit_reason = "BREAKEVEN_LOCK_HIT (Zero Loss)" if trade.get("is_breakeven_locked") else "STOP_LOSS_HIT (-4% Base Floor)"
            exit_px = round(stop_px * (1.0 - SLIPPAGE_PCT), 2)
        # 2. Target Hit (+12% Velocity)
        elif high_px >= target_px or cur_px >= target_px:
            is_closed = True
            exit_reason = "TARGET_HIT (+12% Velocity)"
            exit_px = round(target_px * (1.0 - SLIPPAGE_PCT), 2)
        elif trade["days_held"] >= VELOCITY_KILL_DAYS and trade.get("pnl_pct", 0.0) < VELOCITY_KILL_MIN_PNL:
            is_closed = True
            exit_reason = "72H_VELOCITY_KILL (Dead Money)"
            exit_px = round(cur_px * (1.0 - SLIPPAGE_PCT), 2)
        elif trade["days_held"] >= MAX_HOLDING_DAYS:
            is_closed = True
            exit_reason = "TIME_EXPIRY (7 Sessions)"
            exit_px = round(cur_px * (1.0 - SLIPPAGE_PCT), 2)

        if is_closed:
            curr_shares = int(trade.get("shares", 0))
            if curr_shares > 0:
                costs = compute_indian_delivery_costs(buy_price=entry_px, sell_price=exit_px, quantity=curr_shares)
                rem_pnl_inr = round((exit_px - entry_px) * curr_shares - costs.total_friction_rupees, 2)
                friction_inr = round(costs.total_friction_rupees + trade.get("t1_friction_inr", 0.0), 2)
            else:
                rem_pnl_inr = 0.0
                friction_inr = trade.get("t1_friction_inr", 0.0)
                
            total_net_pnl_inr = round(trade.get("realized_pnl_inr", 0.0) + rem_pnl_inr, 2)
            net_pnl_inr = total_net_pnl_inr
            orig_shares = int(trade.get("orig_shares") or curr_shares)
            orig_deployed = entry_px * orig_shares
            net_pnl_pct = round(total_net_pnl_inr / orig_deployed * 100.0, 2) if orig_deployed > 0 else 0.0
            
            tracker["option_2"]["closed_trades"].append({
                **trade,
                "exit_date": datetime.now().strftime("%Y-%m-%d"),
                "exit_price": exit_px,
                "exit_reason": exit_reason,
                "net_pnl_inr": total_net_pnl_inr,
                "net_pnl_pct": net_pnl_pct,
                "friction_inr": friction_inr,
                "status": "CLOSED",
            })

            # Send Telegram alert for closed trade
            if "TARGET_HIT" in exit_reason:
                _send_telegram_alert("target_hit", ticker=ticker, entry_price=entry_px, exit_price=exit_px, pnl_rupees=net_pnl_inr, pnl_pct=net_pnl_pct)
            elif "VELOCITY_KILL" in exit_reason:
                _send_telegram_alert("velocity_kill", ticker=ticker, entry_price=entry_px, exit_price=exit_px, days_held=trade["days_held"], pnl_pct=net_pnl_pct, freed_capital_inr=shares * exit_px)
            elif "STOP_LOSS" in exit_reason or "BREAKEVEN_LOCK_HIT" in exit_reason:
                _send_telegram_alert("stop_loss_hit", ticker=ticker, entry_price=entry_px, exit_price=exit_px, loss_inr=net_pnl_inr, loss_pct=net_pnl_pct, is_breakeven=trade.get("is_breakeven_locked", False))
        else:
            still_open_o2.append(trade)

    tracker["option_2"]["open_trades"] = still_open_o2

    # --- AUDIT TRACK B: OPTION 3 (GTT BUY-STOP TRIGGER) ---
    still_pending_o3 = []
    for pending in tracker["option_3"]["pending_triggers"]:
        ticker = pending["ticker"]
        trigger_px = float(pending["pivot_trigger"])
        shortlist_d = pending.get("shortlist_date") or pending.get("log_date") or today_str
        
        quote = fetch_live_quote(ticker)
        cur_px = float(quote.get("price") or 0.0)
        high_px = float(quote.get("day_high") or quote.get("high") or cur_px)
        if cur_px <= 0:
            df = _get_cached_history(ticker, "5d")
            if not df.empty:
                df.columns = [str(c).title() for c in df.columns]
                cur_px = float(df["Close"].iloc[-1])
                high_px = float(df["High"].iloc[-1])
            else:
                cur_px = float(pending.get("scan_price", 0.0))
                high_px = cur_px

        can_exec, fill_timestamp = _can_trigger_breakout(shortlist_d, force_market_open)

        # Trigger ONLY during market hours when price hit or crossed pivot resistance
        if can_exec and high_px >= trigger_px:
            # 1. Anti-FOMO Gap Ceiling: Never chase if stock opened with a runaway gap > +2.5% above pivot trigger
            open_px = float(quote.get("open") or 0.0)
            if open_px > 0 and open_px > trigger_px * (1.0 + ANTI_FOMO_MAX_GAP_PCT):
                logger.info(f"🚫 [Anti-FOMO Abort] {ticker} opened @ ₹{open_px:.2f} (> +{ANTI_FOMO_MAX_GAP_PCT*100}% above trigger ₹{trigger_px:.2f}). Aborting chase.")
                pending["status"] = "FOMO_GAP_ABORTED"
                tracker["option_3"].setdefault("aborted_trades", []).append({
                    **pending,
                    "abort_date": today_str,
                    "abort_price": open_px,
                    "abort_reason": f"Runaway Gap-Up FOMO ceiling breached (> +{ANTI_FOMO_MAX_GAP_PCT*100}%)",
                })
                continue

            can_fill, fill_reason = _can_fill_trade(tracker["option_3"])
            if not can_fill:
                logger.info(f"⏳ [Track B Slot Queued] {ticker} @ trigger ₹{trigger_px:.2f} awaiting slot: {fill_reason}")
                pending["status"] = "PENDING_SLOT_CAPACITY"
                still_pending_o3.append(pending)
                continue

            fill_price = round(trigger_px * (1.0 + SLIPPAGE_PCT), 2)
            cash_free_o3 = _get_free_cash(tracker["option_3"])
            slot_budget_o3 = min(SLOT_CAPITAL, cash_free_o3)
            shares = int(slot_budget_o3 // fill_price)
            if shares <= 0:
                pending["status"] = "PENDING_SLOT_CAPACITY"
                still_pending_o3.append(pending)
                continue

            allocated_rupees = round(shares * fill_price, 2)
            target_px = round(fill_price * (1.0 + TARGET_PCT), 2)
            stop_px = round(fill_price * (1.0 - STOP_LOSS_PCT), 2)
            be_lock_px = round(fill_price * (1.0 + BREAKEVEN_TRIGGER_PCT), 2)

            t_entry = {
                "ticker": ticker,
                "name": pending["name"],
                "shortlist_date": shortlist_d,
                "fill_date": fill_timestamp,
                "entry_date": fill_timestamp[:10],
                "entry_price": fill_price,
                "current_price": cur_px,
                "target_price": target_px,
                "stop_loss": stop_px,
                "breakeven_lock": be_lock_px,
                "shares": shares,
                "allocated_rupees": allocated_rupees,
                "pnl_pct": round(((cur_px - fill_price) / fill_price) * 100.0, 2) if fill_price > 0 else 0.0,
                "pnl_rupees": round((cur_px - fill_price) * shares, 2),
                "pattern": pending.get("pattern", "COIL"),
                "sector": pending.get("sector", "General"),
                "status": "TRIGGERED_ACTIVE",
                "days_held": 0,
            }
            tracker["option_3"]["open_trades"].append(t_entry)
            _send_telegram_alert(
                "breakout_fill",
                ticker=ticker,
                fill_price=fill_price,
                target_price=target_px,
                stop_loss=stop_px,
                shares=shares,
                strategy_track="Track B (GTT Breakout)",
                sector=pending.get("sector", "General"),
                pattern=pending.get("pattern", "COIL"),
            )
        else:
            pending["shortlist_date"] = shortlist_d
            still_pending_o3.append(pending)

    tracker["option_3"]["pending_triggers"] = still_pending_o3

    still_open_o3 = []
    for trade in tracker["option_3"]["open_trades"]:
        ticker = trade["ticker"]
        entry_px = float(trade["entry_price"])
        stop_px = float(trade["stop_loss"])
        target_px = float(trade["target_price"])
        shares = int(trade["shares"])
        
        # Ensure dates exist
        if "shortlist_date" not in trade:
            trade["shortlist_date"] = trade.get("log_date") or trade.get("entry_date", today_str)
        if "fill_date" not in trade:
            trade["fill_date"] = trade.get("entry_date", today_str)

        quote = fetch_live_quote(ticker)
        cur_px = float(quote.get("price") or 0.0)
        high_px = float(quote.get("day_high") or quote.get("high") or cur_px)
        low_px = float(quote.get("day_low") or quote.get("low") or cur_px)
        if cur_px <= 0:
            df = _get_cached_history(ticker, "5d")
            if not df.empty:
                df.columns = [str(c).title() for c in df.columns]
                cur_px = float(df["Close"].iloc[-1])
                high_px = float(df["High"].iloc[-1])
                low_px = float(df["Low"].iloc[-1]) if "Low" in df.columns else cur_px
            else:
                cur_px = entry_px
                high_px = entry_px
                low_px = entry_px

        trade["current_price"] = cur_px
        trade["pnl_pct"] = round(((cur_px - entry_px) / entry_px) * 100.0, 2) if entry_px > 0 else 0.0
        trade["pnl_rupees"] = round((cur_px - entry_px) * shares, 2)

        try:
            entry_d = datetime.strptime(trade["entry_date"][:10], "%Y-%m-%d").date()
            trade["days_held"] = count_trading_days(entry_d, today)
        except Exception:
            trade["days_held"] = 1

        is_closed = False
        exit_reason = ""
        exit_px = cur_px

        # Active Breakeven Lock & T1 Partial Profit Harvest (+5.0% gain)
        be_lock = float(trade.get("breakeven_lock") or round(entry_px * (1.0 + BREAKEVEN_TRIGGER_PCT), 2))
        if (high_px >= be_lock or cur_px >= be_lock):
            if not trade.get("t1_harvested") and shares >= 2:
                orig_shares = int(trade.get("orig_shares") or shares)
                trade["orig_shares"] = orig_shares
                harvest_shares = shares // 2
                rem_shares = shares - harvest_shares
                
                t1_exit_px = round(be_lock * (1.0 - SLIPPAGE_PCT), 2)
                t1_costs = compute_indian_delivery_costs(buy_price=entry_px, sell_price=t1_exit_px, quantity=harvest_shares)
                t1_pnl_inr = round((t1_exit_px - entry_px) * harvest_shares - t1_costs.total_friction_rupees, 2)
                
                trade["realized_pnl_inr"] = round(trade.get("realized_pnl_inr", 0.0) + t1_pnl_inr, 2)
                trade["t1_friction_inr"] = round(trade.get("t1_friction_inr", 0.0) + t1_costs.total_friction_rupees, 2)
                trade["shares"] = rem_shares
                trade["allocated_rupees"] = round(rem_shares * entry_px, 2)
                trade["t1_harvested"] = True
                trade["t1_exit_price"] = t1_exit_px
                trade["t1_pnl_inr"] = t1_pnl_inr
                shares = rem_shares
                
                stop_px = round(entry_px * (1.0 + BREAKEVEN_LOCK_PCT), 2)
                trade["stop_loss"] = stop_px
                trade["is_breakeven_locked"] = True
                
                if not trade.get("alert_be_lock_sent"):
                    trade["alert_be_lock_sent"] = True
                    _send_telegram_alert(
                        "breakeven_lock",
                        ticker=ticker,
                        entry_price=entry_px,
                        current_price=cur_px,
                        pnl_pct=trade.get("pnl_pct", 5.0),
                        new_stop_loss=stop_px,
                    )
            elif stop_px < entry_px:
                stop_px = round(entry_px * (1.0 + BREAKEVEN_LOCK_PCT), 2)
                trade["stop_loss"] = stop_px
                trade["is_breakeven_locked"] = True

        # 1. Stop Loss Hit / Breakeven Lock Hit (Conservative Stop-First Ordering)
        if low_px <= stop_px or cur_px <= stop_px:
            is_closed = True
            exit_reason = "BREAKEVEN_LOCK_HIT (Zero Loss)" if trade.get("is_breakeven_locked") else "STOP_LOSS_HIT (-4% Base Floor)"
            exit_px = round(stop_px * (1.0 - SLIPPAGE_PCT), 2)
        # 2. Target Hit (+12% Velocity)
        elif high_px >= target_px or cur_px >= target_px:
            is_closed = True
            exit_reason = "TARGET_HIT (+12% Velocity)"
            exit_px = round(target_px * (1.0 - SLIPPAGE_PCT), 2)
        elif trade["days_held"] >= VELOCITY_KILL_DAYS and trade.get("pnl_pct", 0.0) < VELOCITY_KILL_MIN_PNL:
            is_closed = True
            exit_reason = "72H_VELOCITY_KILL (Dead Money)"
            exit_px = round(cur_px * (1.0 - SLIPPAGE_PCT), 2)
        elif trade["days_held"] >= MAX_HOLDING_DAYS:
            is_closed = True
            exit_reason = "TIME_EXPIRY (7 Sessions)"
            exit_px = round(cur_px * (1.0 - SLIPPAGE_PCT), 2)

        if is_closed:
            curr_shares = int(trade.get("shares", 0))
            if curr_shares > 0:
                costs = compute_indian_delivery_costs(buy_price=entry_px, sell_price=exit_px, quantity=curr_shares)
                rem_pnl_inr = round((exit_px - entry_px) * curr_shares - costs.total_friction_rupees, 2)
                friction_inr = round(costs.total_friction_rupees + trade.get("t1_friction_inr", 0.0), 2)
            else:
                rem_pnl_inr = 0.0
                friction_inr = trade.get("t1_friction_inr", 0.0)
                
            total_net_pnl_inr = round(trade.get("realized_pnl_inr", 0.0) + rem_pnl_inr, 2)
            net_pnl_inr = total_net_pnl_inr
            orig_shares = int(trade.get("orig_shares") or curr_shares)
            orig_deployed = entry_px * orig_shares
            net_pnl_pct = round(total_net_pnl_inr / orig_deployed * 100.0, 2) if orig_deployed > 0 else 0.0

            tracker["option_3"]["closed_trades"].append({
                **trade,
                "exit_date": datetime.now().strftime("%Y-%m-%d"),
                "exit_price": exit_px,
                "exit_reason": exit_reason,
                "net_pnl_inr": total_net_pnl_inr,
                "net_pnl_pct": net_pnl_pct,
                "friction_inr": friction_inr,
                "status": "CLOSED",
            })

            # Send Telegram alert for closed trade
            if "TARGET_HIT" in exit_reason:
                _send_telegram_alert("target_hit", ticker=ticker, entry_price=entry_px, exit_price=exit_px, pnl_rupees=net_pnl_inr, pnl_pct=net_pnl_pct)
            elif "VELOCITY_KILL" in exit_reason:
                _send_telegram_alert("velocity_kill", ticker=ticker, entry_price=entry_px, exit_price=exit_px, days_held=trade["days_held"], pnl_pct=net_pnl_pct, freed_capital_inr=shares * exit_px)
            elif "STOP_LOSS" in exit_reason or "BREAKEVEN_LOCK_HIT" in exit_reason:
                _send_telegram_alert("stop_loss_hit", ticker=ticker, entry_price=entry_px, exit_price=exit_px, loss_inr=net_pnl_inr, loss_pct=net_pnl_pct, is_breakeven=trade.get("is_breakeven_locked", False))
        else:
            still_open_o3.append(trade)

    tracker["option_3"]["open_trades"] = still_open_o3

    # --- AUDIT TRACK C: BENCHMARK VELOCITY SNIPER ---
    if "track_c" in tracker:
        still_pending_c = []
        for pending in tracker["track_c"].get("pending_triggers", []):
            ticker = pending["ticker"]
            trigger_px = float(pending["pivot_trigger"])
            shortlist_d = pending.get("shortlist_date") or pending.get("log_date") or today_str

            quote = fetch_live_quote(ticker)
            cur_px = float(quote.get("price") or 0.0)
            high_px = float(quote.get("day_high") or quote.get("high") or cur_px)
            if cur_px <= 0:
                df = _get_cached_history(ticker, "5d")
                if not df.empty:
                    df.columns = [str(c).title() for c in df.columns]
                    cur_px = float(df["Close"].iloc[-1])
                    high_px = float(df["High"].iloc[-1])
                else:
                    cur_px = float(pending.get("scan_price", 0.0))
                    high_px = cur_px

            can_exec, fill_timestamp = _can_trigger_breakout(shortlist_d, force_market_open)

            # Trigger ONLY during market hours when price hit or crossed pivot resistance
            if can_exec and high_px >= trigger_px:
                # 1. Anti-FOMO Gap Ceiling: Never chase if stock opened with a runaway gap > +2.5% above pivot trigger
                open_px = float(quote.get("open") or 0.0)
                if open_px > 0 and open_px > trigger_px * (1.0 + ANTI_FOMO_MAX_GAP_PCT):
                    logger.info(f"🚫 [Anti-FOMO Abort] {ticker} opened @ ₹{open_px:.2f} (> +{ANTI_FOMO_MAX_GAP_PCT*100}% above trigger ₹{trigger_px:.2f}). Aborting chase.")
                    pending["status"] = "FOMO_GAP_ABORTED"
                    tracker["track_c"].setdefault("aborted_trades", []).append({
                        **pending,
                        "abort_date": today_str,
                        "abort_price": open_px,
                        "abort_reason": f"Runaway Gap-Up FOMO ceiling breached (> +{ANTI_FOMO_MAX_GAP_PCT*100}%)",
                    })
                    continue

                can_fill, fill_reason = _can_fill_trade(tracker["track_c"])
                if not can_fill:
                    logger.info(f"⏳ [Track C Slot Queued] {ticker} @ trigger ₹{trigger_px:.2f} awaiting slot: {fill_reason}")
                    pending["status"] = "PENDING_SLOT_CAPACITY"
                    still_pending_c.append(pending)
                    continue

                fill_price = round(trigger_px * (1.0 + SLIPPAGE_PCT), 2)
                cash_free_c = _get_free_cash(tracker["track_c"])
                slot_budget_c = min(SLOT_CAPITAL, cash_free_c)
                shares = int(slot_budget_c // fill_price)
                if shares <= 0:
                    pending["status"] = "PENDING_SLOT_CAPACITY"
                    still_pending_c.append(pending)
                    continue

                allocated_rupees = round(shares * fill_price, 2)
                target_px = round(fill_price * (1.0 + TARGET_PCT), 2)
                stop_px = round(fill_price * (1.0 - STOP_LOSS_PCT), 2)
                be_lock_px = round(fill_price * (1.0 + BREAKEVEN_TRIGGER_PCT), 2)

                tracker["track_c"].setdefault("open_trades", []).append({
                    "ticker": ticker,
                    "name": pending["name"],
                    "shortlist_date": shortlist_d,
                    "fill_date": fill_timestamp,
                    "entry_date": fill_timestamp[:10],
                    "entry_price": fill_price,
                    "current_price": cur_px,
                    "target_price": target_px,
                    "stop_loss": stop_px,
                    "breakeven_lock": be_lock_px,
                    "shares": shares,
                    "allocated_rupees": allocated_rupees,
                    "pnl_pct": round(((cur_px - fill_price) / fill_price) * 100.0, 2) if fill_price > 0 else 0.0,
                    "pnl_rupees": round((cur_px - fill_price) * shares, 2),
                    "pattern": pending.get("pattern", "SNIPER"),
                    "sector": pending.get("sector", "General"),
                    "status": "TRIGGERED_ACTIVE",
                    "days_held": 0,
                })
                _send_telegram_alert(
                    "breakout_fill",
                    ticker=ticker,
                    fill_price=fill_price,
                    target_price=target_px,
                    stop_loss=stop_px,
                    shares=shares,
                    strategy_track="Track C (Benchmark Sniper)",
                    sector=pending.get("sector", "General"),
                    pattern=pending.get("pattern", "SNIPER"),
                )
            else:
                pending["shortlist_date"] = shortlist_d
                still_pending_c.append(pending)
        tracker["track_c"]["pending_triggers"] = still_pending_c

        still_open_c = []
        for trade in tracker["track_c"].get("open_trades", []):
            ticker = trade["ticker"]
            entry_px = float(trade["entry_price"])
            stop_px = float(trade["stop_loss"])
            target_px = float(trade["target_price"])
            shares = int(trade["shares"])
            
            # Ensure dates exist
            if "shortlist_date" not in trade:
                trade["shortlist_date"] = trade.get("log_date") or trade.get("entry_date", today_str)
            if "fill_date" not in trade:
                trade["fill_date"] = trade.get("entry_date", today_str)

            quote = fetch_live_quote(ticker)
            cur_px = float(quote.get("price") or 0.0)
            high_px = float(quote.get("day_high") or quote.get("high") or cur_px)
            low_px = float(quote.get("day_low") or quote.get("low") or cur_px)
            if cur_px <= 0:
                df = _get_cached_history(ticker, "5d")
                if not df.empty:
                    df.columns = [str(c).title() for c in df.columns]
                    cur_px = float(df["Close"].iloc[-1])
                    high_px = float(df["High"].iloc[-1])
                    low_px = float(df["Low"].iloc[-1]) if "Low" in df.columns else cur_px
                else:
                    cur_px = entry_px
                    high_px = entry_px
                    low_px = entry_px

            trade["current_price"] = cur_px
            trade["pnl_pct"] = round(((cur_px - entry_px) / entry_px) * 100.0, 2) if entry_px > 0 else 0.0
            trade["pnl_rupees"] = round((cur_px - entry_px) * shares, 2)

            try:
                entry_d = datetime.strptime(trade["entry_date"][:10], "%Y-%m-%d").date()
                trade["days_held"] = count_trading_days(entry_d, today)
            except Exception:
                trade["days_held"] = 1

            is_closed = False
            exit_reason = ""
            exit_px = cur_px

            # Active Breakeven Lock & T1 Partial Profit Harvest (+5.0% gain)
            be_lock = float(trade.get("breakeven_lock") or round(entry_px * (1.0 + BREAKEVEN_TRIGGER_PCT), 2))
            if (high_px >= be_lock or cur_px >= be_lock):
                if not trade.get("t1_harvested") and shares >= 2:
                    orig_shares = int(trade.get("orig_shares") or shares)
                    trade["orig_shares"] = orig_shares
                    harvest_shares = shares // 2
                    rem_shares = shares - harvest_shares
                    
                    t1_exit_px = round(be_lock * (1.0 - SLIPPAGE_PCT), 2)
                    t1_costs = compute_indian_delivery_costs(buy_price=entry_px, sell_price=t1_exit_px, quantity=harvest_shares)
                    t1_pnl_inr = round((t1_exit_px - entry_px) * harvest_shares - t1_costs.total_friction_rupees, 2)
                    
                    trade["realized_pnl_inr"] = round(trade.get("realized_pnl_inr", 0.0) + t1_pnl_inr, 2)
                    trade["t1_friction_inr"] = round(trade.get("t1_friction_inr", 0.0) + t1_costs.total_friction_rupees, 2)
                    trade["shares"] = rem_shares
                    trade["allocated_rupees"] = round(rem_shares * entry_px, 2)
                    trade["t1_harvested"] = True
                    trade["t1_exit_price"] = t1_exit_px
                    trade["t1_pnl_inr"] = t1_pnl_inr
                    shares = rem_shares
                    
                    stop_px = round(entry_px * (1.0 + BREAKEVEN_LOCK_PCT), 2)
                    trade["stop_loss"] = stop_px
                    trade["is_breakeven_locked"] = True
                    
                    if not trade.get("alert_be_lock_sent"):
                        trade["alert_be_lock_sent"] = True
                        _send_telegram_alert(
                            "breakeven_lock",
                            ticker=ticker,
                            entry_price=entry_px,
                            current_price=cur_px,
                            pnl_pct=trade.get("pnl_pct", 5.0),
                            new_stop_loss=stop_px,
                        )
                elif stop_px < entry_px:
                    stop_px = round(entry_px * (1.0 + BREAKEVEN_LOCK_PCT), 2)
                    trade["stop_loss"] = stop_px
                    trade["is_breakeven_locked"] = True

            # 1. Stop Loss Hit / Breakeven Lock Hit (Conservative Stop-First Ordering)
            if low_px <= stop_px or cur_px <= stop_px:
                is_closed = True
                exit_reason = "BREAKEVEN_LOCK_HIT (Zero Loss)" if trade.get("is_breakeven_locked") else "STOP_LOSS_HIT (-4% Base Floor)"
                exit_px = round(stop_px * (1.0 - SLIPPAGE_PCT), 2)
            # 2. Target Hit (+12% Velocity)
            elif high_px >= target_px or cur_px >= target_px:
                is_closed = True
                exit_reason = "TARGET_HIT (+12% Velocity)"
                exit_px = round(target_px * (1.0 - SLIPPAGE_PCT), 2)
            # 3. 72-Hour Velocity Gate: If 3 sessions pass and gain < +1.5%, kill trade flat
            elif trade["days_held"] >= VELOCITY_KILL_DAYS and trade.get("pnl_pct", 0.0) < VELOCITY_KILL_MIN_PNL:
                is_closed = True
                exit_reason = "72H_VELOCITY_KILL (Dead Money)"
                exit_px = round(cur_px * (1.0 - SLIPPAGE_PCT), 2)
            elif trade["days_held"] >= MAX_HOLDING_DAYS:
                is_closed = True
                exit_reason = "TIME_EXPIRY (7 Sessions)"
                exit_px = round(cur_px * (1.0 - SLIPPAGE_PCT), 2)

            if is_closed:
                curr_shares = int(trade.get("shares", 0))
                if curr_shares > 0:
                    costs = compute_indian_delivery_costs(buy_price=entry_px, sell_price=exit_px, quantity=curr_shares)
                    rem_pnl_inr = round((exit_px - entry_px) * curr_shares - costs.total_friction_rupees, 2)
                    friction_inr = round(costs.total_friction_rupees + trade.get("t1_friction_inr", 0.0), 2)
                else:
                    rem_pnl_inr = 0.0
                    friction_inr = trade.get("t1_friction_inr", 0.0)
                    
                total_net_pnl_inr = round(trade.get("realized_pnl_inr", 0.0) + rem_pnl_inr, 2)
                net_pnl_inr = total_net_pnl_inr
                orig_shares = int(trade.get("orig_shares") or curr_shares)
                orig_deployed = entry_px * orig_shares
                net_pnl_pct = round(total_net_pnl_inr / orig_deployed * 100.0, 2) if orig_deployed > 0 else 0.0

                tracker["track_c"]["closed_trades"].append({
                    **trade,
                    "exit_date": datetime.now().strftime("%Y-%m-%d"),
                    "exit_price": exit_px,
                    "exit_reason": exit_reason,
                    "net_pnl_inr": total_net_pnl_inr,
                    "net_pnl_pct": net_pnl_pct,
                    "friction_inr": friction_inr,
                    "status": "CLOSED",
                })

                # Send Telegram alert for closed trade
                if "TARGET_HIT" in exit_reason:
                    _send_telegram_alert("target_hit", ticker=ticker, entry_price=entry_px, exit_price=exit_px, pnl_rupees=net_pnl_inr, pnl_pct=net_pnl_pct)
                elif "VELOCITY_KILL" in exit_reason:
                    _send_telegram_alert("velocity_kill", ticker=ticker, entry_price=entry_px, exit_price=exit_px, days_held=trade["days_held"], pnl_pct=net_pnl_pct, freed_capital_inr=shares * exit_px)
                elif "STOP_LOSS" in exit_reason or "BREAKEVEN_LOCK_HIT" in exit_reason:
                    _send_telegram_alert("stop_loss_hit", ticker=ticker, entry_price=entry_px, exit_price=exit_px, loss_inr=net_pnl_inr, loss_pct=net_pnl_pct, is_breakeven=trade.get("is_breakeven_locked", False))
            else:
                still_open_c.append(trade)

        tracker["track_c"]["open_trades"] = still_open_c

    _save_tracker(tracker)
    return compute_dual_summary(tracker)


def compute_dual_summary(tracker: Optional[dict] = None) -> dict:
    """Compute comparative stats between Track A (Option 2), Track B (Option 3), and Track C (Benchmark Sniper)."""
    tracker = tracker or _load_tracker()
    
    def _stats(track: dict) -> dict:
        if not track:
            return {
                "open_count": 0, "closed_count": 0, "pending_count": 0, "aborted_count": 0,
                "floating_pnl_inr": 0.0, "realized_pnl_inr": 0.0, "total_pnl_inr": 0.0,
                "total_pnl_pct": 0.0, "win_rate": 0.0, "profit_factor": 1.0,
                "capital_deployed": 0.0, "cash_free": 100000.0,
                "open_trades": [], "closed_trades": [], "pending_triggers": [], "aborted_trades": [],
            }
        opens = track.get("open_trades", [])
        closed = track.get("closed_trades", [])
        aborted = track.get("aborted_trades", [])
        pending = track.get("pending_triggers", [])
        pending_conf = track.get("pending_confirmations", [])
        total_pending = len(pending) + len(pending_conf)

        floating_pnl_inr = sum(t.get("pnl_rupees", 0.0) for t in opens)
        realized_partial_pnl = sum(t.get("realized_pnl_inr", 0.0) for t in opens)
        realized_closed_pnl = sum(t.get("net_pnl_inr", 0.0) for t in closed)
        realized_pnl_inr = round(realized_closed_pnl + realized_partial_pnl, 2)
        total_pnl_inr = round(floating_pnl_inr + realized_pnl_inr, 2)
        
        all_completed = closed
        wins = [t for t in all_completed if t.get("net_pnl_inr", 0.0) > 0]
        losses = [t for t in all_completed if t.get("net_pnl_inr", 0.0) <= 0]
        
        win_rate = round(len(wins) / len(all_completed) * 100.0, 1) if all_completed else 0.0
        gross_profit = sum(t.get("net_pnl_inr", 0.0) for t in wins) + realized_partial_pnl
        gross_loss = abs(sum(t.get("net_pnl_inr", 0.0) for t in losses))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 1.0)
        
        deployed = sum(t.get("allocated_rupees", 0.0) for t in opens)
        roc_deployed_pct = round(total_pnl_inr / deployed * 100.0, 2) if deployed > 0 else 0.0
        
        return {
            "open_count": len(opens),
            "closed_count": len(closed),
            "pending_count": total_pending,
            "aborted_count": len(aborted),
            "floating_pnl_inr": round(floating_pnl_inr, 2),
            "realized_pnl_inr": round(realized_pnl_inr, 2),
            "total_pnl_inr": total_pnl_inr,
            "total_pnl_pct": round(total_pnl_inr / track.get("capital", TOTAL_CAPITAL) * 100.0, 2),
            "roc_deployed_pct": roc_deployed_pct,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "capital_deployed": round(deployed, 2),
            "cash_free": _get_free_cash(track),
            "open_trades": opens,
            "closed_trades": closed,
            "pending_triggers": pending,
            "pending_confirmations": pending_conf,
            "aborted_trades": aborted,
        }

    s2 = _stats(tracker.get("option_2", {}))
    s3 = _stats(tracker.get("option_3", {}))
    sc = _stats(tracker.get("track_c", {}))

    total_closed = s2["closed_count"] + s3["closed_count"] + sc["closed_count"]
    winner = "TIE (Evaluating)"
    pnl_scores = [("Track A: Option 2", s2["total_pnl_inr"]), ("Track B: Option 3", s3["total_pnl_inr"]), ("Track C: Benchmark Sniper", sc["total_pnl_inr"])]
    best = max(pnl_scores, key=lambda x: x[1])
    if best[1] != 0:
        if total_closed == 0:
            winner = f"⚖️ Forward-Testing (MTM Leader: {best[0]} at ₹{best[1]:+,.2f})"
        else:
            winner = f"🏆 {best[0]} Leading ({total_closed} closed trades)"

    return {
        "updated_at": tracker.get("updated_at"),
        "option_2": s2,
        "option_3": s3,
        "track_c": sc,
        "winner": winner,
    }
