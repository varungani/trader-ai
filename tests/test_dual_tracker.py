"""
Tests for Dual Forward-Tracker Tournament Engine (Option 2 vs Option 3).
Verifies pick logging, trigger activations, stop/target exits, and summary metrics.
"""
import copy
import os
import sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine.dual_tracker import (
    _load_tracker,
    log_today_picks,
    compute_dual_summary,
    audit_and_update_dual_tracker,
)


@pytest.fixture
def sample_picks():
    t1_picks = [
        {
            "ticker": "TEST1.NS",
            "name": "TEST1",
            "current_price": 1000.0,
            "target_price": 1200.0,
            "stop_loss": 930.0,
            "shares": 33,
            "pattern": "BREAKOUT",
            "sector": "IT",
        }
    ]
    t2_radar = [
        {
            "ticker": "TEST2.NS",
            "name": "TEST2",
            "current_price": 500.0,
            "pivot_buy_stop": 510.0,
            "target_price": 612.0,
            "stop_loss": 474.3,
            "readiness": "COILING",
            "pattern": "COIL",
            "sector": "Infra",
        }
    ]
    return t1_picks, t2_radar


def test_tracker_structure():
    """Verify default tracker data structure."""
    data = _load_tracker()
    assert "option_2" in data
    assert "option_3" in data
    assert "open_trades" in data["option_2"]
    assert "pending_triggers" in data["option_3"]


def test_compute_dual_summary_empty():
    """Verify compute_dual_summary executes without division by zero on empty trades."""
    empty_data = {
        "updated_at": "2026-11-16 10:00:00",
        "option_2": {
            "capital": 100000.0,
            "open_trades": [],
            "closed_trades": [],
            "aborted_trades": [],
        },
        "option_3": {
            "capital": 100000.0,
            "pending_triggers": [],
            "open_trades": [],
            "closed_trades": [],
        },
    }
    summary = compute_dual_summary(empty_data)
    assert summary["option_2"]["win_rate"] == 0.0
    assert summary["option_2"]["profit_factor"] == 1.0
    assert summary["option_3"]["win_rate"] == 0.0
    assert summary["option_3"]["profit_factor"] == 1.0
    assert "winner" in summary


def test_compute_dual_summary_with_closed_trades():
    """Verify metrics calculation when closed trades are present."""
    data = {
        "updated_at": "2026-11-16 10:00:00",
        "option_2": {
            "capital": 100000.0,
            "open_trades": [],
            "closed_trades": [
                {"ticker": "WIN.NS", "net_pnl_inr": 5000.0},
                {"ticker": "LOSS.NS", "net_pnl_inr": -2000.0},
            ],
            "aborted_trades": [],
        },
        "option_3": {
            "capital": 100000.0,
            "pending_triggers": [],
            "open_trades": [],
            "closed_trades": [
                {"ticker": "WIN3.NS", "net_pnl_inr": 6000.0},
            ],
        },
    }
    summary = compute_dual_summary(data)
    # Option 2: 1 win, 1 loss = 50% win rate
    assert summary["option_2"]["win_rate"] == 50.0
    # PF = 5000 / 2000 = 2.5
    assert summary["option_2"]["profit_factor"] == 2.5
    assert summary["option_2"]["total_pnl_inr"] == 3000.0

    # Option 3: 1 win, 0 loss = 100% win rate
    assert summary["option_3"]["win_rate"] == 100.0
    assert summary["option_3"]["total_pnl_inr"] == 6000.0
    assert "Option 3" in summary["winner"]


def test_can_trigger_breakout_market_rules():
    """Verify that GTT breakout triggers strictly simulate Indian market hours."""
    from engine.dual_tracker import _can_trigger_breakout
    from datetime import datetime, timedelta

    # 1. Force market open override (used in testing/simulation)
    can_exec, ts = _can_trigger_breakout("2026-11-16", force_market_open=True)
    assert can_exec is True
    assert len(ts) >= 10

    # 2. Same-day evening scan (shortlisted today) cannot trigger when market is closed
    today_str = datetime.now().strftime("%Y-%m-%d")
    # Outside market hours, a stock shortlisted today should not trigger
    # Note: If test runs outside market hours, this returns False
    from data.market_calendar import get_market_status
    mkt = get_market_status()
    if not mkt.get("is_open"):
        can_exec_today, _ = _can_trigger_breakout(today_str, force_market_open=False)
        assert can_exec_today is False


def test_log_today_picks_sets_shortlist_and_fill_dates(sample_picks):
    """Verify that logging picks establishes shortlist_date and fill_date."""
    t1_picks, t2_radar = sample_picks
    summary = log_today_picks(t1_picks, t2_radar)
    
    tracker = _load_tracker()
    # Track A active trades have shortlist_date and fill_date
    for t in tracker["option_2"]["open_trades"]:
        assert "shortlist_date" in t
        assert "fill_date" in t

    # Track B pending triggers have shortlist_date
    for p in tracker["option_3"]["pending_triggers"]:
        assert "shortlist_date" in p


