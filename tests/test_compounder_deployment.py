"""
tests/test_compounder_deployment.py

Unit and Integration Tests for the Newly Deployed Compounder Strategies:
- Track 6: Apex 3-Slot Compounder (40/30/30, Weekly 10W Trail, Pyramiding)
- Track 7: 2-Slot Conviction Compounder (50/50, Weekly 10W Trail)
- Track 8: 1-Slot Apex Leader Rocket (100% Capital, 1 Slot)
- Track 9: Active 1-to-2 Month Swing Engine (4 Slots, Day 21 Stagnation Cutoff)
"""

import pytest
import pandas as pd
from datetime import date, datetime, time as dtime
from engine.strategies.registry import default_registry
from engine.execution.tournament_service import TournamentService
from engine.domain.models import PortfolioAccount, GTTOrder, Position


def test_registry_contains_all_nine_tracks():
    keys = [s.key for s in default_registry.all()]
    expected = [
        "track_algo4", "option_3", "track_algo5", "option_2", "track_c",
        "track_apex_compounder", "track_conviction_2slot", "track_apex_1slot", "track_monthly_swing"
    ]
    for exp in expected:
        assert exp in keys, f"Missing strategy {exp} from default registry"


def test_slot_capacities_and_capital():
    service = TournamentService(default_registry)
    service.initialize_default()
    
    # Track 6: Apex 3-Slot
    acc6 = service.accounts["track_apex_compounder"]
    assert acc6.max_slots == 3
    
    # Track 7: 2-Slot
    acc7 = service.accounts["track_conviction_2slot"]
    assert acc7.max_slots == 2
    
    # Track 8: 1-Slot
    acc8 = service.accounts["track_apex_1slot"]
    assert acc8.max_slots == 1
    
    # Track 9: 4-Slot Monthly Swing
    acc9 = service.accounts["track_monthly_swing"]
    assert acc9.max_slots == 4


def test_apex_compounder_pyramiding_and_stop():
    strat = default_registry.get("track_apex_compounder")
    assert strat is not None
    
    acc = PortfolioAccount(name="Test Apex", capital=100000.0, max_slots=3, slot_capital=33333.33)
    pos = Position(
        ticker="TATAMOTORS.NS",
        name="TATAMOTORS",
        shortlist_date="2026-11-01",
        fill_date="2026-11-01 09:15",
        entry_date="2026-11-01",
        entry_price=100.0,
        current_price=130.0,  # Up +30%
        target_price=999.0,
        stop_loss=93.0,       # Initial -7%
        shares=300,
        allocated_rupees=30000.0,
        days_held=20,
    )
    acc.positions.append(pos)
    
    # Test audit_open_positions does not exit while above stop and Friday weekly ema is satisfied
    strat.audit_open_positions(acc, "2026-11-23", date(2026, 11, 23))
    assert len(acc.positions) == 1
    assert acc.positions[0].stop_loss >= 93.0


def test_monthly_swing_day21_stagnation_cutoff(monkeypatch):
    strat = default_registry.get("track_monthly_swing")
    assert strat is not None

    import engine.strategies.implementations as impl_mod
    monkeypatch.setattr(impl_mod, "fetch_live_quote", lambda t: {"price": 101.0, "day_high": 101.5, "day_low": 100.5})
    monkeypatch.setattr(impl_mod, "_get_cached_history", lambda t, p: pd.DataFrame())

    acc = PortfolioAccount(name="Test Swing", capital=100000.0, max_slots=4, slot_capital=25000.0)
    # Stagnant position: held 22 days, only +1% gain (< +3%)
    pos = Position(
        ticker="INFY.NS",
        name="INFY",
        shortlist_date="2026-10-01",
        fill_date="2026-10-01 09:15",
        entry_date="2026-10-01",
        entry_price=100.0,
        current_price=101.0,
        target_price=999.0,
        stop_loss=93.0,
        shares=200,
        allocated_rupees=20000.0,
        days_held=22,
    )
    acc.positions.append(pos)

    strat.audit_open_positions(acc, "2026-11-23", date(2026, 11, 23))
    # Must be closed due to Day 21 Stagnation Cutoff
    assert len(acc.positions) == 0
    assert len(acc.closed_trades) == 1
    assert "DAY21_STAGNATION_CUTOFF" in acc.closed_trades[0]["exit_reason"]


def test_tournament_summary_includes_new_tracks():
    service = TournamentService(default_registry)
    service.initialize_default()
    summary = service.compute_summary()
    
    assert "track_apex_compounder" in summary["tracks"]
    assert "track_conviction_2slot" in summary["tracks"]
    assert "track_apex_1slot" in summary["tracks"]
    assert "track_monthly_swing" in summary["tracks"]
    assert "track_6" in summary
    assert "track_7" in summary
    assert "track_8" in summary
    assert "track_9" in summary
