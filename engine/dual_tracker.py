"""
TraderAI - 5-Way Parallel Tournament Tracker (v3.5.0 - Clean OOP Architecture)
Modular, Object-Oriented facade delegating to typed domain models and polymorphic strategies.
Maintains 100% backward-compatibility across all existing endpoints and tests:
  - Track 1: Algo 4 (Confirmed 20-EMA Bounce Pivot) [Alpha Leader - Alerts Active]
  - Track 2: Algo 1 (Morning Ignition Thrust) [Alpha Rocket - Alerts Active]
  - Track 3: Algo 5 (High-RS 52W Breakaway Blast) [Momentum Runner - Alerts Active]
  - Track 4: Algo 2 (Minervini VCP Squeeze) [Silent Benchmark - Muted Alerts]
  - Track 5: Algo 3 (Benchmark Velocity Sniper) [Silent Benchmark - Muted Alerts]
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from typing import Optional, Dict, Any, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import TOURNAMENT_CONFIG
from data.market_data import fetch_live_quote, _get_cached_history
from engine.domain.models import PortfolioAccount, GTTOrder, Position
from engine.strategies.base import can_trigger_breakout
from engine.strategies.registry import StrategyRegistry, default_registry
from engine.execution.tournament_service import TournamentService

logger = logging.getLogger(__name__)

TRACKER_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "dual_tracker.json")

# Tournament Constants (5 Slots @ ₹20,000)
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
    """Computes available unallocated cash via domain model."""
    account = PortfolioAccount.from_dict(track)
    return account.get_free_cash()


def _can_fill_trade(track: dict, slot_capital: float = SLOT_CAPITAL, max_slots: int = MAX_SLOTS) -> Tuple[bool, str]:
    """Strictly enforces slot capacity (max 5) and non-negative cash cushion."""
    account = PortfolioAccount.from_dict(track)
    account.max_slots = max_slots
    account.slot_capital = slot_capital
    return account.can_fill_trade()


def _can_trigger_breakout(shortlist_date_str: str, force_market_open: bool = False) -> Tuple[bool, str]:
    """Determines whether a pending GTT breakout trigger is allowed to execute based on NSE trading rules."""
    return can_trigger_breakout(shortlist_date_str, force_market_open)


def _send_telegram_alert(alert_type: str, **kwargs):
    """Safely trigger Telegram alert if enabled and within NSE live window (09:15-15:40 IST)."""
    try:
        from datetime import time as dtime
        from data.market_calendar import get_ist_now, is_trading_day
        now = get_ist_now()
        is_td, _ = is_trading_day(now.date())
        if not is_td or not (dtime(9, 15) <= now.time() <= dtime(15, 40)):
            logger.info(f"🔇 Suppressed {alert_type} Telegram alert outside market hours ({now.strftime('%H:%M IST')}).")
            return

        from bot.telegram_notifier import default_telegram_notifier
        if alert_type == "breakout_fill":
            default_telegram_notifier.notify_breakout_fill(**kwargs)
        elif alert_type == "breakeven_lock":
            default_telegram_notifier.notify_breakeven_lock(**kwargs)
        elif alert_type == "t1_harvest":
            default_telegram_notifier.notify_t1_harvest(**kwargs)
        elif alert_type == "target_hit":
            default_telegram_notifier.notify_target_hit(**kwargs)
        elif alert_type == "stop_loss_hit":
            default_telegram_notifier.notify_stop_loss_hit(**kwargs)
        elif alert_type == "velocity_kill":
            default_telegram_notifier.notify_velocity_kill(**kwargs)
    except Exception as e:
        logger.debug(f"Telegram alert dispatch error: {e}")


def _default_tracker_state() -> dict:
    """Returns initial state dictionary for all 5 tracks."""
    service = TournamentService(default_registry)
    service.initialize_default()
    return service.to_dict()


def _load_tracker() -> dict:
    """Loads tracker data from TRACKER_FILE into service and serializes back with schema migrations."""
    service = TournamentService(default_registry)
    if os.path.exists(TRACKER_FILE):
        try:
            with open(TRACKER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            service.load_from_dict(data)
            return service.to_dict()
        except Exception as e:
            logger.warning(f"Failed to load {TRACKER_FILE}: {e}")
    service.initialize_default()
    return service.to_dict()


def _save_tracker(data: dict) -> None:
    """Persists tracker state to TRACKER_FILE and syncs per-algo state files."""
    service = TournamentService(default_registry)
    service.load_from_dict(data)
    service.save_to_files(TRACKER_FILE)


def log_today_picks(tier1_picks: list[dict], tier2_radar: list[dict]) -> dict:
    """Route today's picks into all 5 parallel tournament tracks and perform audit."""
    service = TournamentService(default_registry)
    current_data = _load_tracker()
    service.load_from_dict(current_data)
    service.log_today_picks(tier1_picks, tier2_radar)
    service.save_to_files(TRACKER_FILE)
    return audit_and_update_dual_tracker()


def audit_and_update_dual_tracker(force_market_open: bool = False) -> dict:
    """
    Audits pending orders, evaluates trigger activations, processes T1 harvests,
    and updates live MTM across all 5 strategies using clean domain models.
    """
    import engine.strategies.base as base_mod
    import engine.strategies.implementations as impl_mod
    base_mod.fetch_live_quote = fetch_live_quote
    base_mod._get_cached_history = _get_cached_history
    impl_mod.fetch_live_quote = fetch_live_quote
    impl_mod._get_cached_history = _get_cached_history

    service = TournamentService(default_registry)
    current_data = _load_tracker()
    service.load_from_dict(current_data)
    service.audit_all(force_market_open=force_market_open, alert_callback=_send_telegram_alert)
    service.save_to_files(TRACKER_FILE)
    return service.compute_summary()


def compute_dual_summary(tracker: Optional[dict] = None) -> dict:
    """Computes comparative stats across all 5 tracks via TournamentService."""
    service = TournamentService(default_registry)
    if tracker is not None:
        service.load_from_dict(tracker)
    else:
        current_data = _load_tracker()
        service.load_from_dict(current_data)
    return service.compute_summary()
