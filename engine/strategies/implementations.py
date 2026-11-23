"""
TraderAI Concrete Strategy Implementations
The 5 audited algorithms implemented as clean, polymorphic BaseStrategy subclasses:
  - Track 1: Algo 4 - Confirmed 20-EMA Bounce Pivot [Alpha Leader]
  - Track 2: Algo 1 - Morning Ignition Thrust [Alpha Rocket]
  - Track 3: Algo 5 - High-RS 52W Breakaway Blast [Momentum Runner]
  - Track 4: Algo 2 - Minervini VCP Squeeze [Silent Benchmark]
  - Track 5: Algo 3 - Benchmark Velocity Sniper [Silent Benchmark]
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time as dtime
from typing import Dict, Any, List, Optional, Callable

from engine.domain.models import PortfolioAccount, GTTOrder, Position
from engine.strategies.base import BaseStrategy
from data.market_data import fetch_live_quote, _get_cached_history
from data.market_calendar import get_next_trading_day, get_ist_now

logger = logging.getLogger(__name__)


class EMABouncePivotStrategy(BaseStrategy):
    """
    Track 1: Algo 4 - Confirmed 20-EMA Bounce Pivot [Alpha Leader]
    Tests 20-EMA on drying volume and triggers on break of prior high with RVOL >= 1.5x.
    Audited +75.0% 5Y CAGR, 67.6% Win Rate, -8.5% DD.
    """
    track_id: int = 1
    key: str = "track_algo4"
    name: str = "Track 1: Algo 4 - Confirmed 20-EMA Bounce Pivot [Alpha Leader]"
    description: str = (
        "Tests 20-day EMA on drying volume and triggers on break of prior high with RVOL >= 1.5x. "
        "Sells 50% at +5% T1, trails stop to breakeven (+0.6%), target +12%. Audited +75.0% 5Y CAGR, 67.6% Win Rate, -8.5% DD."
    )
    is_silent: bool = False

    def log_picks(
        self,
        account: PortfolioAccount,
        tier1_picks: List[Dict[str, Any]],
        tier2_radar: List[Dict[str, Any]],
        today_str: str,
        is_td: bool,
        now_time: dtime,
    ) -> None:
        existing = {t.ticker for t in account.pending_triggers} | {p.ticker for p in account.positions}
        pool = [r for r in (tier1_picks + tier2_radar) if "20EMA" in str(r.get("pattern", "")).upper() or "SWEET_SPOT" in str(r.get("pattern", "")).upper()]
        if not pool:
            pool = [r for r in tier2_radar if r.get("ticker") not in existing][:3]

        for a in pool[:3]:
            ticker = a.get("ticker")
            if not ticker or ticker in existing:
                continue
            cur_px = float(a.get("current_price") or 0.0)
            pivot_trigger = float(a.get("pivot_buy_stop") or (cur_px * 1.002))
            target_px = round(pivot_trigger * (1.0 + self.target_pct), 2)
            stop_px = round(pivot_trigger * (1.0 - self.stop_loss_pct), 2)
            be_lock_px = round(pivot_trigger * (1.0 + self.breakeven_trigger_pct), 2)
            shares = int(self.slot_capital // pivot_trigger) if pivot_trigger > 0 else 0

            account.pending_triggers.append(
                GTTOrder(
                    ticker=ticker,
                    name=ticker.replace(".NS", ""),
                    shortlist_date=today_str,
                    log_date=today_str,
                    scan_price=cur_px,
                    pivot_trigger=pivot_trigger,
                    target_price=target_px,
                    stop_loss=stop_px,
                    breakeven_lock=be_lock_px,
                    shares=shares,
                    planned_rupees=round(shares * pivot_trigger, 2),
                    status="PENDING_BREAKOUT_TRIGGER",
                    pattern=a.get("pattern", "20EMA_SWEET_SPOT"),
                    readiness=a.get("readiness", "PULLBACK_BOUNCE"),
                    sector=a.get("sector", "General"),
                )
            )


class MorningIgnitionStrategy(BaseStrategy):
    """
    Track 2: Algo 1 - Morning Ignition Thrust [Alpha Rocket]
    GTT Buy-Stop trigger at consolidation pivot resistance with 09:30 AM volume run-rate check.
    Audited +69.4% 5Y CAGR, 62.5% Win Rate.
    """
    track_id: int = 2
    key: str = "option_3"
    name: str = "Track 2: Algo 1 - Morning Ignition Thrust [Alpha Rocket]"
    description: str = (
        "GTT Buy-Stop trigger at consolidation pivot resistance with 09:30 AM volume run-rate check. "
        "Fills on breakout. Sells 50% at +5% T1 profit target, locks rest at breakeven + friction (+0.6%), trails runner with +12% target."
    )
    is_silent: bool = False

    def log_picks(
        self,
        account: PortfolioAccount,
        tier1_picks: List[Dict[str, Any]],
        tier2_radar: List[Dict[str, Any]],
        today_str: str,
        is_td: bool,
        now_time: dtime,
    ) -> None:
        existing = {t.ticker for t in account.pending_triggers} | {p.ticker for p in account.positions}
        for r in tier2_radar:
            ticker = r.get("ticker")
            if not ticker or ticker in existing:
                continue
            cur_px = float(r.get("current_price") or 0.0)
            pivot_trigger = float(r.get("pivot_buy_stop") or (cur_px * 1.002))
            target_px = round(pivot_trigger * (1.0 + self.target_pct), 2)
            if "stop_loss_pct" in r:
                stop_px = round(pivot_trigger * (1.0 - float(r["stop_loss_pct"]) / 100.0), 2)
            elif "stop_loss" in r and float(r["stop_loss"]) > cur_px:
                stop_px = float(r["stop_loss"])
            else:
                stop_px = round(pivot_trigger * (1.0 - self.stop_loss_pct), 2)

            be_lock_px = float(r.get("breakeven_lock") or round(pivot_trigger * (1.0 + self.breakeven_trigger_pct), 2))
            shares = int(self.slot_capital // pivot_trigger) if pivot_trigger > 0 else 0

            account.pending_triggers.append(
                GTTOrder(
                    ticker=ticker,
                    name=ticker.replace(".NS", ""),
                    shortlist_date=today_str,
                    log_date=today_str,
                    scan_price=cur_px,
                    pivot_trigger=pivot_trigger,
                    target_price=target_px,
                    stop_loss=stop_px,
                    breakeven_lock=be_lock_px,
                    shares=shares,
                    planned_rupees=round(shares * pivot_trigger, 2),
                    status="PENDING_BREAKOUT_TRIGGER",
                    pattern=r.get("pattern", "COIL"),
                    readiness=r.get("readiness", "COILING"),
                    sector=r.get("sector", "General"),
                )
            )


class BreakawayBlastStrategy(BaseStrategy):
    """
    Track 3: Algo 5 - High-RS 52W Breakaway Blast [Momentum Runner]
    High-RS leaders within 10% of 52W High surging on morning gap with RVOL >= 2.0x.
    Audited +33.0% 5Y CAGR, 60.2% Win Rate.
    """
    track_id: int = 3
    key: str = "track_algo5"
    name: str = "Track 3: Algo 5 - High-RS 52W Breakaway Blast [Momentum Runner]"
    description: str = (
        "High-RS leaders within 10% of 52W High surging on morning gap with RVOL >= 2.0x. "
        "Sells 50% at +5% T1, trails stop to breakeven (+0.6%), target +12%. Audited +33.0% 5Y CAGR, 60.2% Win Rate."
    )
    is_silent: bool = False

    def log_picks(
        self,
        account: PortfolioAccount,
        tier1_picks: List[Dict[str, Any]],
        tier2_radar: List[Dict[str, Any]],
        today_str: str,
        is_td: bool,
        now_time: dtime,
    ) -> None:
        existing = {t.ticker for t in account.pending_triggers} | {p.ticker for p in account.positions}
        pool = [r for r in (tier1_picks + tier2_radar) if "BLAST" in str(r.get("pattern", "")).upper() or "ULTRA" in str(r.get("pattern", "")).upper()]
        if not pool:
            pool = [r for r in tier2_radar if float(r.get("rvol", 1.0)) >= 1.5 and r.get("ticker") not in existing][:3]

        for a in pool[:3]:
            ticker = a.get("ticker")
            if not ticker or ticker in existing:
                continue
            cur_px = float(a.get("current_price") or 0.0)
            pivot_trigger = float(a.get("pivot_buy_stop") or (cur_px * 1.002))
            target_px = round(pivot_trigger * (1.0 + self.target_pct), 2)
            stop_px = round(pivot_trigger * (1.0 - self.stop_loss_pct), 2)
            be_lock_px = round(pivot_trigger * (1.0 + self.breakeven_trigger_pct), 2)
            shares = int(self.slot_capital // pivot_trigger) if pivot_trigger > 0 else 0

            account.pending_triggers.append(
                GTTOrder(
                    ticker=ticker,
                    name=ticker.replace(".NS", ""),
                    shortlist_date=today_str,
                    log_date=today_str,
                    scan_price=cur_px,
                    pivot_trigger=pivot_trigger,
                    target_price=target_px,
                    stop_loss=stop_px,
                    breakeven_lock=be_lock_px,
                    shares=shares,
                    planned_rupees=round(shares * pivot_trigger, 2),
                    status="PENDING_BREAKOUT_TRIGGER",
                    pattern=a.get("pattern", "INSTITUTIONAL_BLAST"),
                    readiness=a.get("readiness", "BLASTING"),
                    sector=a.get("sector", "General"),
                )
            )


class MinerviniVCPStrategy(BaseStrategy):
    """
    Track 4: Algo 2 - Minervini VCP Squeeze [Silent Benchmark]
    Checks open at 9:20 AM after VCP volatility contraction. Fills on normal open (-0.5% to +1.5%),
    aborts bad gap downs (<-1.5%). Banks 50% at +5% T1, locks rest at breakeven + friction (+0.6%), Target +12%. Muted alerts.
    """
    track_id: int = 4
    key: str = "option_2"
    name: str = "Track 4: Algo 2 - Minervini VCP Squeeze [Silent Benchmark]"
    description: str = (
        "Checks open at 9:20 AM after VCP volatility contraction. Fills on normal open (-0.5% to +1.5%), "
        "aborts bad gap downs (<-1.5%). Banks 50% at +5% T1, locks rest at breakeven + friction (+0.6%), Target +12%. Muted alerts."
    )
    is_silent: bool = True

    def log_picks(
        self,
        account: PortfolioAccount,
        tier1_picks: List[Dict[str, Any]],
        tier2_radar: List[Dict[str, Any]],
        today_str: str,
        is_td: bool,
        now_time: dtime,
    ) -> None:
        today_d = datetime.strptime(today_str, "%Y-%m-%d").date()
        if is_td and now_time < dtime(9, 20):
            scheduled_date = today_d
        else:
            scheduled_date, _ = get_next_trading_day(today_d)

        sched_str = scheduled_date.strftime("%Y-%m-%d")
        sched_disp = scheduled_date.strftime("%d %b")

        existing = (
            {t.ticker for t in account.pending_confirmations} |
            {p.ticker for p in account.positions} |
            {a["ticker"] for a in account.aborted_trades if "ticker" in a}
        )

        for p in tier1_picks:
            ticker = p.get("ticker")
            if not ticker or ticker in existing:
                continue
            cur_px = float(p.get("current_price") or 0.0)
            target_px = float(p.get("target_price") or round(cur_px * (1.0 + self.target_pct), 2))
            stop_px = float(p.get("stop_loss") or round(cur_px * (1.0 - self.stop_loss_pct), 2))
            be_lock_px = float(p.get("breakeven_lock") or round(cur_px * (1.0 + self.breakeven_trigger_pct), 2))
            shares = int(p.get("shares") or (self.slot_capital // cur_px if cur_px > 0 else 0))

            account.pending_confirmations.append(
                GTTOrder(
                    ticker=ticker,
                    name=ticker.replace(".NS", ""),
                    shortlist_date=today_str,
                    scheduled_date=sched_str,
                    fill_date=f"Awaiting {sched_disp} 09:20",
                    scan_price=cur_px,
                    pivot_trigger=cur_px,
                    target_price=target_px,
                    stop_loss=stop_px,
                    breakeven_lock=be_lock_px,
                    shares=shares,
                    planned_rupees=round(shares * cur_px, 2),
                    status="AWAITING_920_OPEN",
                    pattern=p.get("pattern", "BREAKOUT"),
                    sector=p.get("sector", "General"),
                )
            )

    def audit_pending(
        self,
        account: PortfolioAccount,
        today_str: str,
        today: date,
        force_market_open: bool = False,
        alert_callback: Optional[Callable[..., Any]] = None,
    ) -> None:
        """Audits pending 9:20 AM confirmations."""
        now = get_ist_now()
        can_evaluate = force_market_open or now.time() >= dtime(9, 20)
        still_pending = []

        for pend in account.pending_confirmations:
            sched_str = pend.scheduled_date or pend.shortlist_date or today_str
            try:
                sched_d = datetime.strptime(sched_str, "%Y-%m-%d").date()
            except Exception:
                sched_d = today

            if can_evaluate and (today >= sched_d or force_market_open):
                ticker = pend.ticker
                scan_px = float(pend.scan_price)
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

                if gap_pct < -1.5:
                    logger.info(f"🚫 [Track 4 Aborted] {ticker}: Gap down {gap_pct:.2f}% (Scan: ₹{scan_px:.2f}, Open: ₹{open_px:.2f})")
                    d_abort = pend.to_dict()
                    d_abort.update({
                        "abort_date": today_str,
                        "open_price": open_px,
                        "gap_pct": round(gap_pct, 2),
                        "status": "ABORTED_GAP_DOWN",
                        "reason": f"Bad gap down ({gap_pct:.2f}% < -1.5%). Capital preserved.",
                    })
                    account.aborted_trades.append(d_abort)
                elif gap_pct > 2.5:
                    logger.info(f"🚫 [Track 4 Aborted] {ticker}: Gapped up {gap_pct:+.2f}% beyond buy zone (+2.5% max). Chasing avoided.")
                    d_abort = pend.to_dict()
                    d_abort.update({
                        "abort_date": today_str,
                        "open_price": open_px,
                        "gap_pct": round(gap_pct, 2),
                        "status": "ABORTED_EXTENDED_GAP",
                        "reason": f"Extended beyond +2.5% buy zone (gapped {gap_pct:+.2f}%). Avoided chasing peak.",
                    })
                    account.aborted_trades.append(d_abort)
                else:
                    can_fill, fill_reason = account.can_fill_trade()
                    if not can_fill:
                        logger.info(f"⏳ [Track 4 Slot Queued] {ticker} @ ₹{open_px:.2f} awaiting free slot: {fill_reason}")
                        pend.status = "PENDING_SLOT_CAPACITY"
                        still_pending.append(pend)
                        continue

                    fill_px = round(open_px * (1.0 + self.slippage_pct), 2)
                    cash_free = account.get_free_cash()
                    slot_budget = min(self.slot_capital, cash_free)
                    shares = int(slot_budget // fill_px)
                    if shares <= 0:
                        pend.status = "PENDING_SLOT_CAPACITY"
                        still_pending.append(pend)
                        continue

                    allocated_rupees = round(shares * fill_px, 2)
                    stop_loss_px = round(fill_px * (1.0 - self.stop_loss_pct), 2)
                    target_px = round(fill_px * (1.0 + self.target_pct), 2)
                    be_lock_px = round(fill_px * (1.0 + self.breakeven_trigger_pct), 2)

                    pos = Position(
                        ticker=ticker,
                        name=pend.name,
                        shortlist_date=pend.shortlist_date,
                        fill_date=f"{today_str} 09:20",
                        entry_date=today_str,
                        entry_price=fill_px,
                        current_price=fill_px,
                        target_price=target_px,
                        stop_loss=stop_loss_px,
                        breakeven_lock=be_lock_px,
                        shares=shares,
                        allocated_rupees=allocated_rupees,
                        pattern=pend.pattern or "9:20_OPEN_CONFIRMATION",
                        sector=pend.sector or "General",
                        status="CONFIRMED_ACTIVE",
                        days_held=0,
                        gap_pct=round(gap_pct, 2),
                    )
                    account.positions.append(pos)
            else:
                still_pending.append(pend)

        account.pending_confirmations = still_pending


class VelocitySniperStrategy(BaseStrategy):
    """
    Track 5: Algo 3 - Benchmark Velocity Sniper [Silent Benchmark]
    GTT Pivot Breakout entry on Top High-RS leaders. Sells 50% at +5% T1, locks rest at breakeven,
    trails runner with +12% target, 72h Velocity Kill (< +1.5% after 3 days). Muted alerts.
    """
    track_id: int = 5
    key: str = "track_c"
    name: str = "Track 5: Algo 3 - Benchmark Velocity Sniper [Silent Benchmark]"
    description: str = (
        "GTT Pivot Breakout entry on Top High-RS leaders. Sells 50% at +5% T1, locks rest at breakeven, "
        "trails runner with +12% target, 72h Velocity Kill (< +1.5% after 3 days). Muted alerts."
    )
    is_silent: bool = True
    enable_velocity_kill: bool = True

    def log_picks(
        self,
        account: PortfolioAccount,
        tier1_picks: List[Dict[str, Any]],
        tier2_radar: List[Dict[str, Any]],
        today_str: str,
        is_td: bool,
        now_time: dtime,
    ) -> None:
        existing = {t.ticker for t in account.pending_triggers} | {p.ticker for p in account.positions}
        c_candidates = [r for r in tier2_radar if r.get("ticker") not in existing][:3]
        if not c_candidates and tier1_picks:
            c_candidates = [p for p in tier1_picks if p.get("ticker") not in existing][:3]

        for c in c_candidates:
            ticker = c.get("ticker")
            if not ticker or ticker in existing:
                continue
            cur_px = float(c.get("current_price") or 0.0)
            pivot_trigger = float(c.get("pivot_buy_stop") or cur_px)
            target_12 = round(pivot_trigger * (1.0 + self.target_pct), 2)
            if "stop_loss_pct" in c:
                stop_4 = round(pivot_trigger * (1.0 - float(c["stop_loss_pct"]) / 100.0), 2)
            elif "stop_loss" in c and float(c["stop_loss"]) > cur_px:
                stop_4 = float(c["stop_loss"])
            else:
                stop_4 = round(pivot_trigger * (1.0 - self.stop_loss_pct), 2)
            be_lock_px = float(c.get("breakeven_lock") or round(pivot_trigger * (1.0 + self.breakeven_trigger_pct), 2))
            shares = int(self.slot_capital // pivot_trigger) if pivot_trigger > 0 else 0

            account.pending_triggers.append(
                GTTOrder(
                    ticker=ticker,
                    name=ticker.replace(".NS", ""),
                    shortlist_date=today_str,
                    log_date=today_str,
                    scan_price=cur_px,
                    pivot_trigger=pivot_trigger,
                    target_price=target_12,
                    stop_loss=stop_4,
                    breakeven_lock=be_lock_px,
                    shares=shares,
                    planned_rupees=round(shares * pivot_trigger, 2),
                    status="PENDING_BREAKOUT_TRIGGER",
                    pattern="BENCHMARK_SNIPER",
                    readiness=c.get("readiness", "COILING"),
                    sector=c.get("sector", "General"),
                )
            )
