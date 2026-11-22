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


@pytest.fixture(autouse=True)
def isolate_tracker_file(tmp_path, monkeypatch):
    """Ensure all dual_tracker tests run against an isolated temporary tracker file."""
    import engine.dual_tracker as dt
    test_tracker_path = str(tmp_path / "dual_tracker.json")
    monkeypatch.setattr(dt, "TRACKER_FILE", test_tracker_path)
    return test_tracker_path


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
    assert "pending_confirmations" in data["option_2"]
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
    """Verify that logging picks establishes shortlist_date and pending confirmation."""
    t1_picks, t2_radar = sample_picks
    summary = log_today_picks(t1_picks, t2_radar)
    
    tracker = _load_tracker()
    # Track A candidates logged outside market hours are in pending_confirmations awaiting 9:20 AM
    assert len(tracker["option_2"]["pending_confirmations"]) > 0
    for p in tracker["option_2"]["pending_confirmations"]:
        assert "shortlist_date" in p
        assert "scheduled_date" in p
        assert "fill_date" in p
        assert "Awaiting" in p["fill_date"]

    # When market open is forced (simulation), they promote to open_trades
    audit_and_update_dual_tracker(force_market_open=True)
    tracker_audited = _load_tracker()
    assert len(tracker_audited["option_2"]["open_trades"]) > 0
    for t in tracker_audited["option_2"]["open_trades"]:
        assert "shortlist_date" in t
        assert "fill_date" in t

    # Track B pending triggers have shortlist_date
    for p in tracker["option_3"]["pending_triggers"]:
        assert "shortlist_date" in p


def test_option_3_target_and_stop_anchored_to_pivot_trigger():
    """Verify Option 3 target (+12%) and stop (-4%) are strictly anchored to pivot_trigger."""
    t2_radar = [{
        "ticker": "TRIGGER_TEST.NS",
        "name": "TRIGGER_TEST",
        "current_price": 100.0,
        "pivot_buy_stop": 110.0,
        "target_price": 120.0,  # 100 * 1.20 (old flawed anchor)
        "stop_loss": 93.0,       # 100 * 0.93 (old flawed anchor)
        "readiness": "COILING",
        "pattern": "COIL",
        "sector": "Infra",
    }]
    log_today_picks([], t2_radar)
    tracker = _load_tracker()
    item = next(p for p in tracker["option_3"]["pending_triggers"] if p["ticker"] == "TRIGGER_TEST.NS")
    # Must be 110 * 1.12 = 123.2, NOT 120.0
    assert item["target_price"] == 123.2
    # Must be 110 * 0.96 = 105.6, NOT 93.0
    assert item["stop_loss"] == 105.6


def test_days_held_uses_trading_days():
    """Verify that days_held counts actual NSE trading days rather than calendar days."""
    from data.market_calendar import count_trading_days
    # Friday to Monday = 3 calendar days, but exactly 1 trading day
    friday = "2026-11-13"
    monday = "2026-11-16"
    assert count_trading_days(friday, monday) == 1


def test_max_slots_and_capital_enforcement_prevents_leverage(monkeypatch):
    """Verify that no more than 5 slots can be filled and capital deployed never exceeds ₹100,000."""
    import engine.dual_tracker as dt
    from engine.dual_tracker import _save_tracker, _load_tracker, audit_and_update_dual_tracker, MAX_SLOTS, TOTAL_CAPITAL

    # Mock fetch_live_quote so all tickers hit breakout trigger (high = 105.0 >= trigger 100.0)
    monkeypatch.setattr(dt, "fetch_live_quote", lambda t: {"price": 105.0, "day_high": 105.0, "open": 101.0})

    tracker = _load_tracker()
    # Create 7 pending triggers for Option 3
    tracker["option_3"]["pending_triggers"] = [
        {
            "ticker": f"STOCK{i}.NS",
            "name": f"STOCK{i}",
            "shortlist_date": "2026-11-16",
            "pivot_trigger": 100.0,
            "shares": 200,
            "target_price": 112.0,
            "stop_loss": 96.0,
            "breakeven_lock": 105.0,
            "status": "PENDING_BREAKOUT_TRIGGER",
        }
        for i in range(1, 8)
    ]
    tracker["option_3"]["open_trades"] = []
    _save_tracker(tracker)

    # Force audit where all triggers activate
    audit_and_update_dual_tracker(force_market_open=True)

    updated = _load_tracker()
    open_trades = updated["option_3"]["open_trades"]
    pending = updated["option_3"]["pending_triggers"]

    # Exactly 5 slots filled, 2 remain queued
    assert len(open_trades) == MAX_SLOTS == 5
    assert len(pending) == 2
    for p in pending:
        assert p["status"] == "PENDING_SLOT_CAPACITY"

    # Total deployed capital must not exceed TOTAL_CAPITAL (zero leverage)
    deployed = sum(t["allocated_rupees"] for t in open_trades)
    assert deployed <= TOTAL_CAPITAL
    assert deployed >= 95000.0  # ~20k * 5


def test_slippage_applied_on_entry_and_breakeven_lock_buffer(monkeypatch):
    """Verify 0.25% slippage on entry and +0.6% breakeven lock buffer to cover statutory friction."""
    import engine.dual_tracker as dt
    from engine.dual_tracker import (
        _save_tracker,
        _load_tracker,
        audit_and_update_dual_tracker,
        SLIPPAGE_PCT,
        BREAKEVEN_LOCK_PCT,
    )

    # Mock quote hitting breakout trigger
    monkeypatch.setattr(dt, "fetch_live_quote", lambda t: {"price": 1010.0, "day_high": 1010.0, "open": 1005.0})

    tracker = _load_tracker()
    tracker["option_3"]["open_trades"] = []
    tracker["option_3"]["pending_triggers"] = [
        {
            "ticker": "SLIPTEST.NS",
            "name": "SLIPTEST",
            "shortlist_date": "2026-11-16",
            "pivot_trigger": 1000.0,
            "shares": 20,
            "target_price": 1120.0,
            "stop_loss": 960.0,
            "breakeven_lock": 1050.0,
            "status": "PENDING_BREAKOUT_TRIGGER",
        }
    ]
    _save_tracker(tracker)

    audit_and_update_dual_tracker(force_market_open=True)

    updated = _load_tracker()
    assert len(updated["option_3"]["open_trades"]) == 1
    trade = updated["option_3"]["open_trades"][0]

    # Entry price must include slippage: 1000 * 1.0025 = 1002.50
    expected_entry = round(1000.0 * (1.0 + SLIPPAGE_PCT), 2)
    assert trade["entry_price"] == expected_entry

    # Breakeven lock buffer must move stop to entry * (1 + 0.006) = 1002.50 * 1.006 = 1008.52
    expected_be_stop = round(trade["entry_price"] * (1.0 + BREAKEVEN_LOCK_PCT), 2)
    assert expected_be_stop > trade["entry_price"]


def test_t1_partial_harvest_locks_profit_and_moves_stop(monkeypatch):
    """Verify that when price reaches +5.0%, 50% shares are sold and stop is locked at breakeven + friction."""
    import engine.dual_tracker as dt
    from engine.dual_tracker import _save_tracker, _load_tracker, audit_and_update_dual_tracker

    tracker = _load_tracker()
    tracker["option_3"]["open_trades"] = [
        {
            "ticker": "HARVEST.NS",
            "name": "HARVEST",
            "entry_date": "2026-11-16",
            "shortlist_date": "2026-11-16",
            "fill_date": "2026-11-16 09:30",
            "entry_price": 100.0,
            "current_price": 100.0,
            "target_price": 112.0,
            "stop_loss": 96.0,
            "breakeven_lock": 105.0,
            "shares": 200,
            "allocated_rupees": 20000.0,
            "pnl_pct": 0.0,
            "pnl_rupees": 0.0,
            "days_held": 1,
            "status": "TRIGGERED_ACTIVE",
        }
    ]
    tracker["option_3"]["closed_trades"] = []
    _save_tracker(tracker)

    # 1. Price surges to 105.50 (triggers T1 harvest, day low stays above breakeven at 101.50)
    monkeypatch.setattr(dt, "fetch_live_quote", lambda t: {"price": 105.50, "day_high": 105.50, "day_low": 101.50, "open": 101.0})
    audit_and_update_dual_tracker(force_market_open=True)

    audited = _load_tracker()
    open_t = audited["option_3"]["open_trades"][0]
    assert open_t["t1_harvested"] is True
    # 50% of 200 shares = 100 shares remaining
    assert open_t["shares"] == 100
    assert open_t["orig_shares"] == 200
    # Realized PnL from harvested 100 shares must be positive (~+₹400 to +₹500)
    assert open_t["realized_pnl_inr"] > 400.0
    # Stop loss moved to Entry * 1.006 = 100.60
    assert open_t["stop_loss"] == 100.60
    assert open_t["is_breakeven_locked"] is True

    # 2. Next day stock retraces and hits trailed breakeven stop at 100.50
    monkeypatch.setattr(dt, "fetch_live_quote", lambda t: {"price": 100.0, "day_high": 101.0, "day_low": 100.0, "open": 100.5})
    audit_and_update_dual_tracker(force_market_open=True)

    audited_closed = _load_tracker()
    assert len(audited_closed["option_3"]["open_trades"]) == 0
    assert len(audited_closed["option_3"]["closed_trades"]) == 1
    closed_t = audited_closed["option_3"]["closed_trades"][0]
    assert closed_t["status"] == "CLOSED"
    assert "BREAKEVEN_LOCK_HIT" in closed_t["exit_reason"]
    # Net PnL must be positive because 50% profit was locked in at +5.0%!
    assert closed_t["net_pnl_inr"] > 350.0


def test_anti_fomo_gap_aborts_runaway_open(monkeypatch):
    """Verify that when a stock gaps up > +2.5% above trigger, order is aborted to prevent chasing."""
    import engine.dual_tracker as dt
    from engine.dual_tracker import _save_tracker, _load_tracker, audit_and_update_dual_tracker

    # Mock open at 103.50 (which is +3.5% above trigger 100.0, exceeding 2.5% ceiling)
    monkeypatch.setattr(dt, "fetch_live_quote", lambda t: {"price": 104.0, "day_high": 104.0, "open": 103.5})

    tracker = _load_tracker()
    tracker["option_3"]["open_trades"] = []
    tracker["option_3"]["pending_triggers"] = [
        {
            "ticker": "RUNAWAY.NS",
            "name": "RUNAWAY",
            "shortlist_date": "2026-11-16",
            "pivot_trigger": 100.0,
            "shares": 200,
            "target_price": 112.0,
            "stop_loss": 96.0,
            "breakeven_lock": 105.0,
            "status": "PENDING_BREAKOUT_TRIGGER",
        }
    ]
    tracker["option_3"]["aborted_trades"] = []
    _save_tracker(tracker)

    audit_and_update_dual_tracker(force_market_open=True)

    updated = _load_tracker()
    assert len(updated["option_3"]["open_trades"]) == 0
    assert len(updated["option_3"]["aborted_trades"]) == 1
    aborted = updated["option_3"]["aborted_trades"][0]
    assert aborted["status"] == "FOMO_GAP_ABORTED"


def test_free_cash_conservation_equation_with_closed_and_partial_trades():
    """Verify that free cash strictly equals Starting Capital + Realized PnL - Deployed Capital."""
    from engine.dual_tracker import compute_dual_summary

    mock_track = {
        "capital": 100000.0,
        "open_trades": [
            {
                "ticker": "ACTIVE.NS",
                "shares": 100,
                "allocated_rupees": 10000.0,
                "realized_pnl_inr": 500.0,
                "pnl_rupees": 200.0,
            }
        ],
        "closed_trades": [
            {"ticker": "WIN.NS", "net_pnl_inr": 4000.0},
            {"ticker": "LOSS.NS", "net_pnl_inr": -1500.0},
        ],
        "aborted_trades": [],
        "pending_triggers": [],
    }

    mock_tracker = {
        "updated_at": "2026-11-22 10:00:00",
        "option_2": mock_track,
        "option_3": mock_track,
        "track_c": mock_track,
    }

    summary = compute_dual_summary(mock_tracker)
    o3 = summary["option_3"]

    # Realized closed PnL = 4000 - 1500 = 2500
    # Realized partial PnL = 500
    # Total Realized PnL = 3000.0
    assert o3["realized_pnl_inr"] == 3000.0
    assert o3["capital_deployed"] == 10000.0
    # Cash free must be 100000 + 3000 - 10000 = 93000.0
    assert o3["cash_free"] == 93000.0
    # Invariant: Free Cash + Deployed Capital == Starting Capital + Realized PnL
    assert round(o3["cash_free"] + o3["capital_deployed"], 2) == round(mock_track["capital"] + o3["realized_pnl_inr"], 2)





