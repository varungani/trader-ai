"""
TraderAI Domain Models
Clean, strongly-typed, object-oriented domain representations for:
  - GTT Orders & Breakout Triggers
  - Open Positions & Intraday MTM / T1 Profit Harvesting / Exits
  - Portfolio Account & Zero-Leverage Cash Conservation Invariants
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Optional, Dict, Any, List, Tuple

from data.costs import compute_indian_delivery_costs
from data.market_calendar import count_trading_days

logger = logging.getLogger(__name__)


@dataclass
class GTTOrder:
    """Represents a pending GTT Buy-Stop trigger or 9:20 AM confirmation candidate."""
    ticker: str
    name: str = ""
    shortlist_date: str = ""
    log_date: str = ""
    scheduled_date: str = ""
    fill_date: str = ""
    scan_price: float = 0.0
    pivot_trigger: float = 0.0
    target_price: float = 0.0
    stop_loss: float = 0.0
    breakeven_lock: float = 0.0
    shares: int = 0
    planned_rupees: float = 0.0
    status: str = "PENDING_BREAKOUT_TRIGGER"
    pattern: str = ""
    readiness: str = ""
    sector: str = "General"

    def __post_init__(self):
        if not self.name:
            self.name = self.ticker.replace(".NS", "")
        if not self.log_date:
            self.log_date = self.shortlist_date
        if not self.planned_rupees and self.shares > 0:
            px = self.pivot_trigger if self.pivot_trigger > 0 else self.scan_price
            self.planned_rupees = round(self.shares * px, 2)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if not d.get("scheduled_date"):
            d.pop("scheduled_date", None)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GTTOrder:
        known_keys = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in known_keys}
        return cls(**filtered)


@dataclass
class Position:
    """
    Represents an active CNC Cash Equity position.
    Encapsulates MTM computation, T1 partial profit harvest (+5%),
    breakeven stop locking (+0.6%), and conservative stop-first exits.
    """
    ticker: str
    name: str = ""
    shortlist_date: str = ""
    fill_date: str = ""
    entry_date: str = ""
    entry_price: float = 0.0
    current_price: float = 0.0
    target_price: float = 0.0
    stop_loss: float = 0.0
    breakeven_lock: float = 0.0
    is_breakeven_locked: bool = False
    shares: int = 0
    orig_shares: int = 0
    allocated_rupees: float = 0.0
    pnl_pct: float = 0.0
    pnl_rupees: float = 0.0
    pattern: str = "BREAKOUT"
    sector: str = "General"
    status: str = "TRIGGERED_ACTIVE"
    days_held: int = 0
    t1_harvested: bool = False
    t1_exit_price: float = 0.0
    t1_pnl_inr: float = 0.0
    t1_friction_inr: float = 0.0
    realized_pnl_inr: float = 0.0
    alert_be_lock_sent: bool = False
    gap_pct: float = 0.0

    def __post_init__(self):
        if not self.name:
            self.name = self.ticker.replace(".NS", "")
        if self.shares > 0 and self.orig_shares <= 0:
            self.orig_shares = self.shares
        if not self.allocated_rupees and self.shares > 0 and self.entry_price > 0:
            self.allocated_rupees = round(self.shares * self.entry_price, 2)

    def update_quote(self, cur_px: float, high_px: float, low_px: float, today: date) -> None:
        """Update live quote and mark-to-market calculations."""
        self.current_price = cur_px
        if self.entry_price > 0:
            self.pnl_pct = round(((cur_px - self.entry_price) / self.entry_price) * 100.0, 2)
            self.pnl_rupees = round((cur_px - self.entry_price) * self.shares, 2)
        try:
            entry_d = datetime.strptime(self.entry_date[:10], "%Y-%m-%d").date()
            self.days_held = count_trading_days(entry_d, today)
        except Exception:
            self.days_held = 1

    def process_t1_harvest(
        self,
        high_px: float,
        cur_px: float,
        slippage_pct: float = 0.0025,
        breakeven_lock_pct: float = 0.006,
    ) -> Optional[Dict[str, Any]]:
        """
        Processes T1 Partial Profit Harvest (+5.0% trigger).
        Banks 50% shares, locks stop at breakeven + friction cushion (+0.6%),
        and returns alert metadata if an alert should be dispatched.
        """
        be_trigger = self.breakeven_lock
        if high_px < be_trigger and cur_px < be_trigger:
            return None

        # Case 1: First time touching +5.0% and has at least 2 shares to split
        if not self.t1_harvested and self.shares >= 2:
            orig = self.orig_shares or self.shares
            self.orig_shares = orig
            harvest_shares = self.shares // 2
            rem_shares = self.shares - harvest_shares

            t1_exit = round(be_trigger * (1.0 - slippage_pct), 2)
            costs = compute_indian_delivery_costs(
                buy_price=self.entry_price,
                sell_price=t1_exit,
                quantity=harvest_shares,
            )
            t1_pnl = round((t1_exit - self.entry_price) * harvest_shares - costs.total_friction_rupees, 2)

            self.realized_pnl_inr = round(self.realized_pnl_inr + t1_pnl, 2)
            self.t1_friction_inr = round(self.t1_friction_inr + costs.total_friction_rupees, 2)
            self.shares = rem_shares
            self.allocated_rupees = round(rem_shares * self.entry_price, 2)
            self.t1_harvested = True
            self.t1_exit_price = t1_exit
            self.t1_pnl_inr = t1_pnl

            # Move stop to breakeven + friction cushion (+0.6%)
            self.stop_loss = round(self.entry_price * (1.0 + breakeven_lock_pct), 2)
            self.is_breakeven_locked = True

            if not self.alert_be_lock_sent:
                self.alert_be_lock_sent = True
                return {
                    "ticker": self.ticker,
                    "entry_price": self.entry_price,
                    "harvest_price": t1_exit,
                    "sold_shares": harvest_shares,
                    "rem_shares": rem_shares,
                    "realized_pnl": t1_pnl,
                    "new_stop": self.stop_loss,
                }
        elif self.stop_loss < self.entry_price:
            # Trailed stop already harvested or 1 share: just ensure stop is at breakeven
            self.stop_loss = round(self.entry_price * (1.0 + breakeven_lock_pct), 2)
            self.is_breakeven_locked = True

        return None

    def evaluate_exit(
        self,
        high_px: float,
        low_px: float,
        cur_px: float,
        slippage_pct: float = 0.0025,
        enable_velocity_kill: bool = True,
        velocity_kill_days: int = 3,
        velocity_kill_min_pnl: float = 1.5,
        max_holding_days: int = 7,
    ) -> Tuple[bool, str, float]:
        """
        Conservative Stop-First Intrabar Exit Evaluation.
        Returns: (is_closed, exit_reason, exit_price)
        """
        # 1. Stop Loss Hit / Breakeven Lock Hit (Conservative Stop-First Ordering)
        if low_px <= self.stop_loss or cur_px <= self.stop_loss:
            reason = "BREAKEVEN_LOCK_HIT (Zero Loss)" if self.is_breakeven_locked else "STOP_LOSS_HIT (-4% Base Floor)"
            exit_px = round(self.stop_loss * (1.0 - slippage_pct), 2)
            return True, reason, exit_px

        # 2. Target Hit (+12% Velocity)
        if high_px >= self.target_price or cur_px >= self.target_price:
            reason = "TARGET_HIT (+12% Velocity)"
            exit_px = round(self.target_price * (1.0 - slippage_pct), 2)
            return True, reason, exit_px

        # 3. 72-Hour Velocity Gate: If dead money for 3 trading sessions
        if enable_velocity_kill and self.days_held >= velocity_kill_days and self.pnl_pct < velocity_kill_min_pnl:
            reason = "72H_VELOCITY_KILL (Dead Money)"
            exit_px = round(cur_px * (1.0 - slippage_pct), 2)
            return True, reason, exit_px

        # 4. Max Holding Duration Expiry (7 Sessions)
        if self.days_held >= max_holding_days:
            reason = "TIME_EXPIRY (7 Sessions)"
            exit_px = round(cur_px * (1.0 - slippage_pct), 2)
            return True, reason, exit_px

        return False, "", 0.0

    def close(self, exit_price: float, exit_reason: str, exit_date: str) -> Dict[str, Any]:
        """
        Computes remaining delivery friction, realized PnL, and closes position.
        """
        curr_shares = self.shares
        if curr_shares > 0:
            costs = compute_indian_delivery_costs(
                buy_price=self.entry_price,
                sell_price=exit_price,
                quantity=curr_shares,
            )
            rem_pnl_inr = round((exit_price - self.entry_price) * curr_shares - costs.total_friction_rupees, 2)
            friction_inr = round(costs.total_friction_rupees + self.t1_friction_inr, 2)
        else:
            rem_pnl_inr = 0.0
            friction_inr = self.t1_friction_inr

        total_net_pnl_inr = round(self.realized_pnl_inr + rem_pnl_inr, 2)
        orig = self.orig_shares or curr_shares
        orig_deployed = self.entry_price * orig
        net_pnl_pct = round(total_net_pnl_inr / orig_deployed * 100.0, 2) if orig_deployed > 0 else 0.0

        d = self.to_dict()
        d.update({
            "exit_date": exit_date,
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "net_pnl_inr": total_net_pnl_inr,
            "net_pnl_pct": net_pnl_pct,
            "friction_inr": friction_inr,
            "status": "CLOSED",
        })
        return d

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Position:
        known_keys = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in known_keys}
        return cls(**filtered)


@dataclass
class PortfolioAccount:
    """
    Manages a single strategy's cash corpus, slot capacity, active positions,
    and guarantees the fundamental cash conservation invariant:
        Free Cash = Starting Capital + Realized Closed PnL + Realized Partial PnL - Deployed Capital
    """
    name: str = ""
    description: str = ""
    capital: float = 100000.0
    max_slots: int = 5
    slot_capital: float = 20000.0
    positions: List[Position] = field(default_factory=list)
    closed_trades: List[Dict[str, Any]] = field(default_factory=list)
    pending_triggers: List[GTTOrder] = field(default_factory=list)
    pending_confirmations: List[GTTOrder] = field(default_factory=list)
    aborted_trades: List[Dict[str, Any]] = field(default_factory=list)

    def get_free_cash(self) -> float:
        """Computes available unallocated cash without leverage."""
        realized_closed = sum(float(t.get("net_pnl_inr", 0.0)) for t in self.closed_trades)
        realized_partial = sum(p.realized_pnl_inr for p in self.positions)
        deployed = sum(p.allocated_rupees for p in self.positions)
        return round(self.capital + realized_closed + realized_partial - deployed, 2)

    def can_fill_trade(self) -> Tuple[bool, str]:
        """Validates that slot capacity and cash cushion exist."""
        if len(self.positions) >= self.max_slots:
            return False, f"All {self.max_slots} slots full ({len(self.positions)} active)."
        cash = self.get_free_cash()
        if cash < 5000.0:
            return False, f"Insufficient free cash (Free: ₹{cash:.2f}, Min: ₹5,000.00)."
        return True, ""

    def to_dict(self) -> Dict[str, Any]:
        """Exports state matching exact dual_tracker JSON structure."""
        return {
            "name": self.name,
            "description": self.description,
            "capital": self.capital,
            "max_slots": self.max_slots,
            "pending_triggers": [p.to_dict() for p in self.pending_triggers],
            "pending_confirmations": [p.to_dict() for p in self.pending_confirmations],
            "open_trades": [p.to_dict() for p in self.positions],
            "closed_trades": self.closed_trades,
            "aborted_trades": self.aborted_trades,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PortfolioAccount:
        acc = cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            capital=float(data.get("capital", 100000.0)),
            max_slots=int(data.get("max_slots", 5)),
            slot_capital=float(data.get("slot_capital", 20000.0)),
            closed_trades=data.get("closed_trades", []),
            aborted_trades=data.get("aborted_trades", []),
        )
        acc.positions = [Position.from_dict(t) for t in data.get("open_trades", [])]
        acc.pending_triggers = [GTTOrder.from_dict(t) for t in data.get("pending_triggers", [])]
        acc.pending_confirmations = [GTTOrder.from_dict(t) for t in data.get("pending_confirmations", [])]
        return acc
