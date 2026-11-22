"""
Tests for Modular OOP Architecture
Verifies domain models (Position, GTTOrder, PortfolioAccount),
polymorphic strategy registration, and tournament execution service.
"""
from datetime import date, datetime
import pytest

from engine.domain.models import Position, GTTOrder, PortfolioAccount
from engine.strategies.base import BaseStrategy
from engine.strategies.registry import StrategyRegistry
from engine.execution.tournament_service import TournamentService


def test_position_domain_t1_harvest_and_conservative_stop_exit():
    """Verify Position domain model encapsulates T1 partial harvest and conservative stop-first exit."""
    pos = Position(
        ticker="TATAMOTORS.NS",
        name="TATAMOTORS",
        entry_date="2026-11-15",
        shortlist_date="2026-11-15",
        fill_date="2026-11-15 09:30",
        entry_price=1000.0,
        current_price=1000.0,
        target_price=1120.0,
        stop_loss=960.0,
        breakeven_lock=1050.0,
        shares=20,
        orig_shares=20,
        allocated_rupees=20000.0,
    )

    # 1. Update quote
    today = date(2026, 11, 17)
    pos.update_quote(cur_px=1055.0, high_px=1060.0, low_px=995.0, today=today)
    assert pos.pnl_pct == 5.5
    assert pos.pnl_rupees == 1100.0
    assert pos.days_held >= 1

    # 2. Process T1 harvest at +5%
    harvest_meta = pos.process_t1_harvest(high_px=1060.0, cur_px=1055.0, slippage_pct=0.0025, breakeven_lock_pct=0.006)
    assert harvest_meta is not None
    assert pos.t1_harvested is True
    assert pos.shares == 10  # 50% sold
    assert pos.orig_shares == 20
    assert pos.is_breakeven_locked is True
    # Stop loss moved to breakeven + friction cushion (1000 * 1.006 = 1006.0)
    assert pos.stop_loss == 1006.0
    assert pos.realized_pnl_inr > 0.0

    # 3. Conservative stop-first ordering:
    # If a volatile bar hits both trailed stop (1006.0) and target (1120.0), stop exit must trigger first
    is_closed, reason, exit_px = pos.evaluate_exit(
        high_px=1150.0,
        low_px=1000.0,
        cur_px=1050.0,
        slippage_pct=0.0025,
    )
    assert is_closed is True
    assert "BREAKEVEN_LOCK_HIT" in reason
    assert exit_px == round(1006.0 * (1.0 - 0.0025), 2)

    # 4. Close position
    closed_dict = pos.close(exit_price=exit_px, exit_reason=reason, exit_date="2026-11-17")
    assert closed_dict["status"] == "CLOSED"
    assert closed_dict["friction_inr"] > 0.0
    assert "net_pnl_inr" in closed_dict


def test_portfolio_account_cash_conservation_equation():
    """Verify PortfolioAccount strictly enforces cash conservation and slot limits."""
    account = PortfolioAccount(
        name="Test Strategy",
        capital=100000.0,
        max_slots=5,
        slot_capital=20000.0,
    )

    # Add 2 open positions
    account.positions.append(Position(ticker="T1.NS", entry_price=100.0, shares=100, allocated_rupees=10000.0, realized_pnl_inr=500.0))
    account.positions.append(Position(ticker="T2.NS", entry_price=200.0, shares=50, allocated_rupees=10000.0, realized_pnl_inr=0.0))

    # Add closed trades: Net PnL = +3000 - 1000 = +2000
    account.closed_trades.append({"ticker": "C1.NS", "net_pnl_inr": 3000.0})
    account.closed_trades.append({"ticker": "C2.NS", "net_pnl_inr": -1000.0})

    # Total realized PnL = +2000 (closed) + 500 (partial) = +2500
    # Total deployed = 10000 + 10000 = 20000
    # Free Cash = 100000 + 2500 - 20000 = 82500.0
    free_cash = account.get_free_cash()
    assert free_cash == 82500.0

    # Invariant check: Free Cash + Deployed Capital == Starting Capital + Total Realized PnL
    deployed = sum(p.allocated_rupees for p in account.positions)
    total_realized = sum(t["net_pnl_inr"] for t in account.closed_trades) + sum(p.realized_pnl_inr for p in account.positions)
    assert round(free_cash + deployed, 2) == round(account.capital + total_realized, 2)

    # Slot check
    can_fill, _ = account.can_fill_trade()
    assert can_fill is True

    # Fill all 5 slots
    for i in range(3, 6):
        account.positions.append(Position(ticker=f"T{i}.NS", entry_price=100.0, shares=100, allocated_rupees=10000.0))
    assert len(account.positions) == 5
    can_fill_5, reason = account.can_fill_trade()
    assert can_fill_5 is False
    assert "full" in reason


def test_extensible_polymorphic_strategy_subclassing():
    """Verify that any new strategy can be cleanly registered without touching core audit loops."""
    class CustomAlphaStrategy(BaseStrategy):
        track_id = 99
        key = "track_custom"
        name = "Track 99: Custom Institutional Algo"
        is_silent = False

        def log_picks(self, account, tier1_picks, tier2_radar, today_str, is_td, now_time):
            account.pending_triggers.append(
                GTTOrder(
                    ticker="CUSTOM.NS",
                    name="CUSTOM",
                    pivot_trigger=500.0,
                    target_price=560.0,
                    stop_loss=480.0,
                    shares=40,
                )
            )

    registry = StrategyRegistry()
    custom_strat = CustomAlphaStrategy()
    registry.register(custom_strat)

    service = TournamentService(registry)
    service.initialize_default()
    assert "track_custom" in service.accounts

    # Route picks
    service.log_today_picks([], [])
    acc = service.accounts["track_custom"]
    assert len(acc.pending_triggers) == 1
    assert acc.pending_triggers[0].ticker == "CUSTOM.NS"
