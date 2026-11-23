"""
TraderAI Base Strategy Interface
Polymorphic strategy base class providing standard execution, T1 harvest,
friction deduction, and risk management across all parallel tournament tracks.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import date, datetime, time as dtime
from typing import Dict, Any, List, Optional, Callable, Tuple

from engine.domain.models import PortfolioAccount, GTTOrder, Position
from data.market_data import fetch_live_quote, _get_cached_history
from data.market_calendar import get_market_status, is_trading_day, get_ist_now

logger = logging.getLogger(__name__)


def can_trigger_breakout(shortlist_date_str: str, force_market_open: bool = False) -> Tuple[bool, str]:
    """
    Determines whether a pending GTT breakout trigger is allowed to execute based on NSE/BSE trading rules.
    Returns: (can_execute, fill_timestamp_str)
    """
    if force_market_open:
        return True, get_ist_now().strftime("%Y-%m-%d %H:%M")

    now = get_ist_now()
    today_str = now.strftime("%Y-%m-%d")
    mkt = get_market_status(now)

    # 1. Market is live and trading right now (09:15-15:30 IST)
    if mkt.get("is_open", False):
        return True, now.strftime("%Y-%m-%d %H:%M")

    # 2. Market is currently closed: verify if today was a trading day and the session has concluded
    # A GTT trigger can NEVER execute before market opens at 09:15 AM IST!
    is_td, _ = is_trading_day(now.date())
    if is_td and shortlist_date_str and str(shortlist_date_str) < today_str:
        if now.time() >= dtime(15, 30):
            return True, f"{today_str} (Market Hours)"

    return False, ""


class BaseStrategy(ABC):
    """Abstract Base Class for all tournament strategies (OCP-compliant)."""
    track_id: int = 1
    key: str = "track_algo"
    name: str = "Base Strategy"
    description: str = ""
    is_silent: bool = False

    target_pct: float = 0.12
    stop_loss_pct: float = 0.04
    breakeven_trigger_pct: float = 0.05
    breakeven_lock_pct: float = 0.006
    slippage_pct: float = 0.0025
    slot_capital: float = 20000.0
    max_slots: int = 5
    anti_fomo_max_gap_pct: float = 0.025
    enable_velocity_kill: bool = True
    velocity_kill_days: int = 3
    velocity_kill_min_pnl: float = 1.5
    max_holding_days: int = 7

    @abstractmethod
    def log_picks(
        self,
        account: PortfolioAccount,
        tier1_picks: List[Dict[str, Any]],
        tier2_radar: List[Dict[str, Any]],
        today_str: str,
        is_td: bool,
        now_time: dtime,
    ) -> None:
        """Route shortlisted radar/picks into this strategy's pending orders."""
        pass

    def audit(
        self,
        account: PortfolioAccount,
        today_str: str,
        today: date,
        force_market_open: bool = False,
        alert_callback: Optional[Callable[..., Any]] = None,
    ) -> None:
        """Standard audit cycle: audit pending orders, check fills, audit active positions."""
        self.audit_pending(account, today_str, today, force_market_open, alert_callback)
        self.audit_open_positions(account, today_str, today, alert_callback)

    def audit_pending(
        self,
        account: PortfolioAccount,
        today_str: str,
        today: date,
        force_market_open: bool = False,
        alert_callback: Optional[Callable[..., Any]] = None,
    ) -> None:
        """Default GTT Buy-Stop trigger evaluation for breakout strategies."""
        still_pending = []
        for pending in account.pending_triggers:
            ticker = pending.ticker
            trigger_px = float(pending.pivot_trigger)
            shortlist_d = pending.shortlist_date or pending.log_date or today_str

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
                    cur_px = float(pending.scan_price)
                    high_px = cur_px

            can_exec, fill_ts = can_trigger_breakout(shortlist_d, force_market_open)

            # Trigger only during market hours when price hit or crossed pivot resistance
            if can_exec and high_px >= trigger_px:
                # 1. Anti-FOMO Gap Ceiling: Never chase if opened > +2.5% above trigger
                open_px = float(quote.get("open") or quote.get("price") or 0.0)
                if open_px > 0 and open_px > trigger_px * (1.0 + self.anti_fomo_max_gap_pct):
                    logger.info(f"🚫 [Anti-FOMO Abort] {ticker} opened @ ₹{open_px:.2f} (> +{self.anti_fomo_max_gap_pct*100}% above trigger). Aborting chase.")
                    pending.status = "FOMO_GAP_ABORTED"
                    d_abort = pending.to_dict()
                    d_abort.update({
                        "abort_date": today_str,
                        "abort_price": open_px,
                        "abort_reason": f"Runaway Gap-Up FOMO ceiling breached (> +{self.anti_fomo_max_gap_pct*100}%)",
                    })
                    account.aborted_trades.append(d_abort)
                    continue

                can_fill, fill_reason = account.can_fill_trade()
                if not can_fill:
                    logger.info(f"⏳ [{self.name} Slot Queued] {ticker} awaiting slot: {fill_reason}")
                    pending.status = "PENDING_SLOT_CAPACITY"
                    still_pending.append(pending)
                    continue

                fill_price = round(trigger_px * (1.0 + self.slippage_pct), 2)
                cash_free = account.get_free_cash()
                slot_budget = min(self.slot_capital, cash_free)
                shares = int(slot_budget // fill_price)
                if shares <= 0:
                    pending.status = "PENDING_SLOT_CAPACITY"
                    still_pending.append(pending)
                    continue

                allocated_rupees = round(shares * fill_price, 2)
                target_px = round(fill_price * (1.0 + self.target_pct), 2)
                stop_px = round(fill_price * (1.0 - self.stop_loss_pct), 2)
                be_lock_px = round(fill_price * (1.0 + self.breakeven_trigger_pct), 2)

                pos = Position(
                    ticker=ticker,
                    name=pending.name,
                    shortlist_date=shortlist_d,
                    fill_date=fill_ts,
                    entry_date=fill_ts[:10],
                    entry_price=fill_price,
                    current_price=cur_px,
                    target_price=target_px,
                    stop_loss=stop_px,
                    breakeven_lock=be_lock_px,
                    shares=shares,
                    allocated_rupees=allocated_rupees,
                    pattern=pending.pattern or "BREAKOUT",
                    sector=pending.sector or "General",
                    status="TRIGGERED_ACTIVE",
                    days_held=0,
                )
                account.positions.append(pos)

                if alert_callback and not self.is_silent:
                    alert_callback(
                        "breakout_fill",
                        ticker=ticker,
                        fill_price=fill_price,
                        target_price=target_px,
                        stop_loss=stop_px,
                        shares=shares,
                        strategy_track=self.name,
                        sector=pending.sector,
                        pattern=pending.pattern,
                    )
            else:
                pending.shortlist_date = shortlist_d
                still_pending.append(pending)

        account.pending_triggers = still_pending

    def audit_open_positions(
        self,
        account: PortfolioAccount,
        today_str: str,
        today: date,
        alert_callback: Optional[Callable[..., Any]] = None,
    ) -> None:
        """Audits open positions: updates live quotes, processes T1 harvests, and conservative stop-first exits."""
        still_open = []
        for pos in account.positions:
            ticker = pos.ticker
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
                    cur_px = pos.entry_price
                    high_px = pos.entry_price
                    low_px = pos.entry_price

            pos.update_quote(cur_px, high_px, low_px, today)

            # Check T1 Partial Profit Harvest (+5.0% gain)
            harvest_meta = pos.process_t1_harvest(
                high_px=high_px,
                cur_px=cur_px,
                slippage_pct=self.slippage_pct,
                breakeven_lock_pct=self.breakeven_lock_pct,
            )
            if harvest_meta and alert_callback and not self.is_silent:
                alert_callback(
                    "t1_harvest",
                    strategy_track=self.name,
                    **harvest_meta,
                )

            # Evaluate Conservative Stop-First Exits
            is_closed, exit_reason, exit_px = pos.evaluate_exit(
                high_px=high_px,
                low_px=low_px,
                cur_px=cur_px,
                slippage_pct=self.slippage_pct,
                enable_velocity_kill=self.enable_velocity_kill,
                velocity_kill_days=self.velocity_kill_days,
                velocity_kill_min_pnl=self.velocity_kill_min_pnl,
                max_holding_days=self.max_holding_days,
            )

            if is_closed:
                closed_d = pos.close(exit_px, exit_reason, exit_date=today_str)
                account.closed_trades.append(closed_d)

                if alert_callback and not self.is_silent:
                    net_pnl = closed_d.get("net_pnl_inr", 0.0)
                    net_pct = closed_d.get("net_pnl_pct", 0.0)
                    if "TARGET_HIT" in exit_reason:
                        alert_callback("target_hit", ticker=ticker, entry_price=pos.entry_price, exit_price=exit_px, pnl_rupees=net_pnl, pnl_pct=net_pct, strategy_track=self.name)
                    elif "VELOCITY_KILL" in exit_reason:
                        alert_callback("velocity_kill", ticker=ticker, entry_price=pos.entry_price, exit_price=exit_px, days_held=pos.days_held, pnl_pct=net_pct, freed_capital_inr=pos.shares * exit_px, strategy_track=self.name)
                    elif "STOP_LOSS" in exit_reason or "BREAKEVEN_LOCK_HIT" in exit_reason:
                        alert_callback("stop_loss_hit", ticker=ticker, entry_price=pos.entry_price, exit_price=exit_px, loss_inr=net_pnl, loss_pct=net_pct, is_breakeven=pos.is_breakeven_locked, strategy_track=self.name)
            else:
                still_open.append(pos)

        account.positions = still_open
