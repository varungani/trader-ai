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
from data.market_calendar import get_market_status, is_trading_day, get_ist_now, count_trading_days

logger = logging.getLogger(__name__)


def can_trigger_breakout(shortlist_date_str: str, force_market_open: bool = False) -> Tuple[bool, str]:
    """
    Determines whether a pending GTT breakout trigger is allowed to execute based on NSE/BSE trading rules.
    Breakouts may ONLY fire while the exchange is actively open (09:15 - 15:30 IST on a trading day).
    Returns: (can_execute, fill_timestamp_str)
    """
    if force_market_open:
        return True, get_ist_now().strftime("%Y-%m-%d %H:%M")

    now = get_ist_now()
    mkt = get_market_status(now)

    # Strict Ground Truth Guard:
    # A GTT trigger can ONLY execute during continuous live NSE hours (09:15-15:30 IST).
    # Never trigger fills post-close (e.g. 17:30 or 19:00 IST from a queued cron).
    if mkt.get("is_open", False):
        return True, now.strftime("%Y-%m-%d %H:%M")

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

    # Empirical Upgrades (Group B: Quant EDA Shortlist; Legacy Group A twins override via legacy_mode=True)
    shortlist_mode: str = "eda"
    prioritize_by_composite_rs: bool = False
    stale_expiry_days: int = 0
    min_breadth_gate: float = 0.0
    min_entry_clv: float = 0.0

    def __init__(self, legacy_mode: bool = False):
        self.legacy_mode = legacy_mode
        if legacy_mode:
            orig_id = self.track_id
            orig_title = self.name.split(":", 1)[-1].strip() if ":" in self.name else self.name
            self.shortlist_mode = "legacy"
            self.track_id = 10 + orig_id
            self.key = f"{self.key}_legacy"
            self.name = f"Track {orig_id}A (Legacy): {orig_title} [Silent]"
            self.description = f"[Technique A - Legacy RVOL/FIFO Shortlist | Muted] {self.description}"
            self.is_silent = True
            self.prioritize_by_composite_rs = False
            self.stale_expiry_days = 0
            self.min_breadth_gate = 0.0
            self.min_entry_clv = 0.0
        else:
            self.shortlist_mode = "eda"
            self.prioritize_by_composite_rs = True
            self.stale_expiry_days = 5
            self.min_breadth_gate = 45.0

    def _prepare_shortlist_pool(
        self,
        account: PortfolioAccount,
        candidates: List[Dict[str, Any]],
        fallback_pool: Optional[List[Dict[str, Any]]] = None,
        legacy_limit: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Shared shortlist funnel selector:
          - Legacy mode (Group A): preserves original candidate ordering capped at legacy_limit.
          - EDA mode (Group B): refreshes live Composite RS / breadth metadata on existing triggers,
            sorts candidates by Composite RS descending, and widens radar staging up to 12-16 leaders.
        """
        pool_src = list(candidates) if candidates else list(fallback_pool or [])
        cand_map = {c.get("ticker"): c for c in pool_src if c.get("ticker")}

        if self.shortlist_mode == "eda":
            for pend in account.pending_triggers:
                src = cand_map.get(pend.ticker)
                if src:
                    pend.composite_rs = float(src.get("composite_rs", pend.composite_rs))
                    pend.clv = float(src.get("clv", pend.clv))
                    pend.vol_asym = float(src.get("vol_asym_20", pend.vol_asym))
                    pend.market_breadth_pct = float(src.get("market_breadth_pct", pend.market_breadth_pct))

        existing = (
            {t.ticker for t in account.pending_triggers}
            | {t.ticker for t in account.pending_confirmations}
            | {p.ticker for p in account.positions}
        )
        filtered = [r for r in pool_src if r.get("ticker") and r.get("ticker") not in existing]
        if self.shortlist_mode == "eda":
            filtered.sort(
                key=lambda x: (
                    1 if x.get("is_compounder_rocket") else 0,
                    float(x.get("composite_rs", 0.0)),
                    float(x.get("rs_vs_nifty", 0.0)),
                    float(x.get("final_score", 0.0)),
                ),
                reverse=True,
            )
            return filtered[: max(12, self.max_slots * 4)]

        return filtered[:legacy_limit]

    @staticmethod
    def _build_gtt_order(
        item: Dict[str, Any],
        today_str: str,
        pivot_trigger: float,
        target_price: float,
        stop_loss: float,
        breakeven_lock: float,
        shares: int,
        default_pattern: str,
        default_readiness: str,
        scheduled_date: str = "",
        fill_date: str = "",
        status: str = "PENDING_BREAKOUT_TRIGGER",
    ) -> GTTOrder:
        ticker = str(item.get("ticker", ""))
        cur_px = float(item.get("current_price") or 0.0)
        return GTTOrder(
            ticker=ticker,
            name=ticker.replace(".NS", ""),
            shortlist_date=today_str,
            log_date=today_str,
            scheduled_date=scheduled_date,
            fill_date=fill_date,
            scan_price=cur_px,
            pivot_trigger=pivot_trigger,
            target_price=target_price,
            stop_loss=stop_loss,
            breakeven_lock=breakeven_lock,
            shares=shares,
            planned_rupees=round(shares * pivot_trigger, 2),
            status=status,
            pattern=item.get("pattern", item.get("setup_pattern", default_pattern)),
            readiness=item.get("readiness", default_readiness),
            sector=item.get("sector", "General"),
            composite_rs=float(item.get("composite_rs", item.get("rs_vs_nifty", 0.0))),
            clv=float(item.get("clv", 0.5)),
            vol_asym=float(item.get("vol_asym_20", 1.0)),
            market_breadth_pct=float(item.get("market_breadth_pct", 50.0)),
        )

    def get_slot_allocation(self, rank_idx: int, active_slots: int, total_capital: float) -> float:
        """Default equal slot allocation; subclasses may override for 40/30/30 conviction weighting."""
        return self.slot_capital

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

    def _resolve_live_breadth(self, pending_orders: List[GTTOrder]) -> float:
        """Resolve latest universe breadth % from latest_scan.json or pending metadata; defaults to 50.0 if unknown."""
        try:
            import json
            import os
            root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            scan_path = os.path.join(root, "data", "latest_scan.json")
            if os.path.exists(scan_path):
                with open(scan_path, "r", encoding="utf-8") as f:
                    val = json.load(f).get("market_breadth_pct")
                    if val is not None:
                        return float(val)
        except Exception:
            pass
        for t in pending_orders:
            val = getattr(t, "market_breadth_pct", 50.0)
            if val and val != 50.0:
                return float(val)
        return 50.0

    def audit_pending(
        self,
        account: PortfolioAccount,
        today_str: str,
        today: date,
        force_market_open: bool = False,
        alert_callback: Optional[Callable[..., Any]] = None,
    ) -> None:
        """
        GTT Buy-Stop trigger evaluation.
        When prioritize_by_composite_rs=True, evaluates candidates in descending Composite RS order
        so top leaders win free slots ahead of older FIFO watchlist items, and enforces stale expiry,
        breadth shield, and CLV breakout quality.
        """
        still_pending: List[GTTOrder] = []

        ordered_pending = list(account.pending_triggers)
        if self.prioritize_by_composite_rs and ordered_pending:
            ordered_pending.sort(
                key=lambda x: (
                    float(getattr(x, "composite_rs", 0.0)),
                    float(getattr(x, "vol_asym", 1.0)),
                    str(x.shortlist_date or ""),
                ),
                reverse=True,
            )

        breadth_val = self._resolve_live_breadth(ordered_pending) if (self.min_breadth_gate > 0 and not force_market_open) else 50.0
        breadth_blocked = bool(self.min_breadth_gate > 0 and not force_market_open and breadth_val < self.min_breadth_gate)

        for pending in ordered_pending:
            ticker = pending.ticker
            trigger_px = float(pending.pivot_trigger)
            shortlist_d = pending.shortlist_date or pending.log_date or today_str

            # 0. Auto-expire stale setups older than stale_expiry_days trading sessions
            if self.stale_expiry_days > 0 and not force_market_open and shortlist_d:
                try:
                    age_days = count_trading_days(shortlist_d, today)
                    if age_days > self.stale_expiry_days:
                        logger.info(f"🧹 [Expired Stale GTT] {ticker} untriggered for {age_days} trading days (> {self.stale_expiry_days}). Pruning.")
                        continue
                except Exception:
                    pass

            quote = fetch_live_quote(ticker)
            cur_px = float(quote.get("price") or 0.0)
            high_px = float(quote.get("day_high") or quote.get("high") or cur_px)
            low_px = float(quote.get("day_low") or quote.get("low") or 0.0)
            if cur_px <= 0:
                df = _get_cached_history(ticker, "5d")
                if not df.empty:
                    df.columns = [str(c).title() for c in df.columns]
                    cur_px = float(df["Close"].iloc[-1])
                    high_px = float(df["High"].iloc[-1])
                    low_px = float(df["Low"].iloc[-1]) if "Low" in df.columns else 0.0
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

                # 2. Universe Market Breadth Gate (EDA: <45% stays in cash shield)
                if breadth_blocked:
                    logger.info(f"🛡️ [Breadth Shield] Market breadth {breadth_val:.1f}% < {self.min_breadth_gate:.1f}%. Holding {ticker} in cash.")
                    pending.status = "PENDING_BREADTH_SHIELD"
                    still_pending.append(pending)
                    continue

                # 3. CLV Breakout Quality Check (EDA-B1: skip intraday collapsed wick breakouts when intraday range available)
                if self.min_entry_clv > 0 and not force_market_open and low_px > 0 and high_px > low_px:
                    live_clv = (cur_px - low_px) / (high_px - low_px)
                    if live_clv < self.min_entry_clv:
                        logger.info(f"⏳ [CLV Guard] {ticker} intraday CLV {live_clv:.2f} < {self.min_entry_clv:.2f} (wick trap). Holding pending.")
                        pending.status = "PENDING_CLV_CONFIRMATION"
                        still_pending.append(pending)
                        continue

                can_fill, fill_reason = account.can_fill_trade()
                if not can_fill:
                    logger.info(f"⏳ [{self.name} Slot Queued] {ticker} awaiting slot: {fill_reason}")
                    pending.status = "PENDING_SLOT_CAPACITY"
                    still_pending.append(pending)
                    continue

                fill_price = round(trigger_px * (1.0 + self.slippage_pct), 2)
                cash_free = account.get_free_cash()
                active_cnt = len(account.positions)
                target_alloc = self.get_slot_allocation(active_cnt, active_cnt, account.capital)
                slot_budget = min(target_alloc, cash_free)
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
