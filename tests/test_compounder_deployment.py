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


def test_weekly_10w_ema_only_triggers_at_friday_close(monkeypatch):
    """Verify intraday Friday dips do not exit Weekly 10W EMA before 15:15 IST close."""
    from zoneinfo import ZoneInfo
    import engine.strategies.implementations as impl_mod

    strat = default_registry.get("track_apex_compounder")
    assert strat is not None

    # Create synthetic 1y weekly falling below 10W EMA at current price 90
    dates = pd.bdate_range("2025-11-01", "2026-11-26")
    df_1y = pd.DataFrame(
        {"Open": 110.0, "High": 112.0, "Low": 108.0, "Close": 110.0, "Volume": 100000.0},
        index=dates,
    )
    monkeypatch.setattr(impl_mod, "fetch_live_quote", lambda t: {"price": 95.0, "day_high": 100.0, "day_low": 94.5})
    monkeypatch.setattr(impl_mod, "fetch_stock_history", lambda t, period="1y", force_live=True: df_1y.copy())

    acc = PortfolioAccount(name="Test Friday", capital=100000.0, max_slots=3, slot_capital=33333.33)
    acc.positions.append(
        Position(
            ticker="RUNNER.NS",
            shortlist_date="2026-11-01",
            fill_date="2026-11-02 09:30",
            entry_date="2026-11-02",
            entry_price=90.0,
            current_price=95.0,
            target_price=999.0,
            stop_loss=83.7,  # Hard stop not hit (94.5 > 83.7)
            shares=300,
            allocated_rupees=27000.0,
            days_held=15,
        )
    )

    tz = ZoneInfo("Asia/Kolkata")
    friday_date = date(2026, 11, 27)  # Friday

    # 1. At 10:30 IST Friday morning: must NOT exit on Weekly 10W EMA intraday dip
    monkeypatch.setattr(impl_mod, "get_ist_now", lambda: datetime(2026, 11, 27, 10, 30, tzinfo=tz))
    strat.audit_open_positions(acc, "2026-11-27", friday_date)
    assert len(acc.positions) == 1

    # 2. At 15:20 IST Friday close: MUST exit on Weekly 10W EMA close below EMA
    monkeypatch.setattr(impl_mod, "get_ist_now", lambda: datetime(2026, 11, 27, 15, 20, tzinfo=tz))
    strat.audit_open_positions(acc, "2026-11-27", friday_date)
    assert len(acc.positions) == 0
    assert "WEEKLY_10W_EMA_TRAIL" in acc.closed_trades[0]["exit_reason"]


def test_pyramid_alert_payload_and_persistence(monkeypatch):
    """Verify pyramiding sets persistent pyramid_stage=1 and calls Telegram notifier cleanly without TypeError."""
    from zoneinfo import ZoneInfo
    import engine.strategies.implementations as impl_mod
    from bot.telegram_notifier import TelegramNotifier

    strat = default_registry.get("track_apex_compounder")
    assert strat is not None

    dates = pd.bdate_range("2026-05-01", "2026-11-25")
    df_6m = pd.DataFrame(
        {"Open": 100.0, "High": 120.0, "Low": 98.0, "Close": 115.0, "Volume": 100000.0},
        index=dates,
    )
    monkeypatch.setattr(impl_mod, "fetch_live_quote", lambda t: {"price": 130.0, "day_high": 131.0, "day_low": 125.0, "volume": 200000.0})
    monkeypatch.setattr(impl_mod, "fetch_stock_history", lambda t, period="6mo", force_live=True: df_6m.copy())
    monkeypatch.setattr(impl_mod, "get_ist_now", lambda: datetime(2026, 11, 25, 11, 0, tzinfo=ZoneInfo("Asia/Kolkata")))

    acc = PortfolioAccount(name="Test Pyramid", capital=100000.0, max_slots=3, slot_capital=33333.33)
    acc.positions.append(
        Position(
            ticker="PYR.NS",
            shortlist_date="2026-10-20",
            fill_date="2026-10-25 09:30",
            entry_date="2026-10-25",
            entry_price=100.0,
            current_price=130.0,
            target_price=999.0,
            stop_loss=93.0,
            shares=300,
            allocated_rupees=30000.0,
            days_held=20,
        )
    )

    notifier = TelegramNotifier(enabled=True, bot_token="tok", chat_id="123")
    captured = []
    monkeypatch.setattr(notifier, "send_message", lambda txt: captured.append(txt) or True)

    def cb(alert_type, **kw):
        assert alert_type == "breakeven_lock"
        notifier.notify_breakeven_lock(**kw)

    strat.audit_open_positions(acc, "2026-11-25", date(2026, 11, 25), alert_callback=cb)
    assert acc.positions[0].pyramid_stage == 1
    assert acc.positions[0].shares == 405  # 300 + 35% (105)
    assert len(captured) == 1
    assert "PYR" in captured[0]

    # Verify round-trip persistence preserves pyramid_stage
    reloaded = PortfolioAccount.from_dict(acc.to_dict())
    assert reloaded.positions[0].pyramid_stage == 1


def test_rs_priority_slot_auction_beats_fifo(monkeypatch):
    """Verify stronger Composite RS leader wins free slot ahead of weaker older pending ticker at index 0."""
    from zoneinfo import ZoneInfo
    import engine.strategies.base as base_mod

    strat = default_registry.get("track_apex_1slot")  # 1-slot rocket
    assert strat is not None

    monkeypatch.setattr(base_mod, "fetch_live_quote", lambda t: {"price": 105.0, "day_high": 106.0, "day_low": 99.0, "open": 101.0})
    monkeypatch.setattr(base_mod, "get_ist_now", lambda: datetime(2026, 11, 25, 10, 30, tzinfo=ZoneInfo("Asia/Kolkata")))

    acc = PortfolioAccount(name="Test Auction", capital=100000.0, max_slots=1, slot_capital=100000.0)
    # Old weaker stock placed FIRST (index 0)
    acc.pending_triggers.append(GTTOrder(ticker="WEAK_OLD.NS", shortlist_date="2026-11-24", pivot_trigger=100.0, composite_rs=8.0))
    # Newer monster RS leader placed SECOND (index 1)
    acc.pending_triggers.append(GTTOrder(ticker="MONSTER_RS.NS", shortlist_date="2026-11-25", pivot_trigger=100.0, composite_rs=42.5))

    strat.audit_pending(acc, "2026-11-25", date(2026, 11, 25), force_market_open=False)
    assert len(acc.positions) == 1
    assert acc.positions[0].ticker == "MONSTER_RS.NS", "Highest Composite RS rocket must win slot auction over FIFO index 0!"


def test_stale_pending_trigger_expires_after_5_trading_days(monkeypatch):
    """Verify untriggered pending orders older than 5 NSE trading days expire automatically."""
    from zoneinfo import ZoneInfo
    import engine.strategies.base as base_mod

    strat = default_registry.get("track_apex_compounder")
    assert strat is not None

    monkeypatch.setattr(base_mod, "fetch_live_quote", lambda t: {"price": 90.0, "day_high": 91.0, "day_low": 89.0})
    monkeypatch.setattr(base_mod, "get_ist_now", lambda: datetime(2026, 11, 25, 10, 30, tzinfo=ZoneInfo("Asia/Kolkata")))

    acc = PortfolioAccount(name="Test Expiry", capital=100000.0, max_slots=3, slot_capital=33333.33)
    # Shortlisted Nov 12 -> 8+ trading days old by Nov 25 (> 5 days)
    acc.pending_triggers.append(GTTOrder(ticker="STALE.NS", shortlist_date="2026-11-12", pivot_trigger=100.0))
    # Fresh Nov 23 -> < 5 trading days old (remember Nov 24 was holiday, so 1 trading day!)
    acc.pending_triggers.append(GTTOrder(ticker="FRESH.NS", shortlist_date="2026-11-23", pivot_trigger=100.0))

    strat.audit_pending(acc, "2026-11-25", date(2026, 11, 25), force_market_open=False)
    remaining = [t.ticker for t in acc.pending_triggers]
    assert "STALE.NS" not in remaining
    assert "FRESH.NS" in remaining


def test_clv_filter_blocks_upper_wick_trap(monkeypatch):
    """Verify EDA-B1 CLV >= 0.65 filter blocks fake intraday wick spikes that collapse back down."""
    from zoneinfo import ZoneInfo
    import engine.strategies.base as base_mod

    strat = default_registry.get("track_apex_compounder")
    assert strat is not None

    # Stock spiked to high=110 (trigger=100), dropped back to price=96 (low=95 -> CLV = 1/15 = 0.067 < 0.65)
    monkeypatch.setattr(base_mod, "fetch_live_quote", lambda t: {"price": 96.0, "day_high": 110.0, "day_low": 95.0, "open": 100.5})
    monkeypatch.setattr(base_mod, "get_ist_now", lambda: datetime(2026, 11, 25, 11, 0, tzinfo=ZoneInfo("Asia/Kolkata")))
    monkeypatch.setattr(strat, "_resolve_live_breadth", lambda orders: 60.0)

    acc = PortfolioAccount(name="Test CLV", capital=100000.0, max_slots=3, slot_capital=33333.33)
    acc.pending_triggers.append(GTTOrder(ticker="WICK.NS", shortlist_date="2026-11-23", pivot_trigger=100.0, composite_rs=25.0))

    strat.audit_pending(acc, "2026-11-25", date(2026, 11, 25), force_market_open=False)
    assert len(acc.positions) == 0
    assert acc.pending_triggers[0].status == "PENDING_CLV_CONFIRMATION"


def test_breadth_shield_blocks_entry_below_45_pct(monkeypatch):
    """Verify Universe Breadth Gate (<45%) shields compounder tracks in weak markets."""
    from zoneinfo import ZoneInfo
    import engine.strategies.base as base_mod

    strat = default_registry.get("track_apex_compounder")
    assert strat is not None

    monkeypatch.setattr(base_mod, "fetch_live_quote", lambda t: {"price": 105.0, "day_high": 106.0, "day_low": 99.0, "open": 101.0})
    monkeypatch.setattr(base_mod, "get_ist_now", lambda: datetime(2026, 11, 25, 11, 0, tzinfo=ZoneInfo("Asia/Kolkata")))
    monkeypatch.setattr(strat, "_resolve_live_breadth", lambda orders: 38.0)  # Weak breadth < 45%

    acc = PortfolioAccount(name="Test Breadth", capital=100000.0, max_slots=3, slot_capital=33333.33)
    acc.pending_triggers.append(GTTOrder(ticker="BEAR.NS", shortlist_date="2026-11-23", pivot_trigger=100.0, composite_rs=20.0))

    strat.audit_pending(acc, "2026-11-25", date(2026, 11, 25), force_market_open=False)
    assert len(acc.positions) == 0
    assert acc.pending_triggers[0].status == "PENDING_BREADTH_SHIELD"


def test_registry_has_18_ab_paired_tracks_and_muted_legacy():
    """Verify full 18-track A/B matrix (9 Tech B EDA + 9 Tech A Legacy) with all Legacy tracks Telegram-muted."""
    all_strats = default_registry.all()
    assert len(all_strats) == 18

    b_tracks = [s for s in all_strats if not s.legacy_mode]
    a_tracks = [s for s in all_strats if s.legacy_mode]
    assert len(b_tracks) == 9
    assert len(a_tracks) == 9

    for b_s in b_tracks:
        a_s = default_registry.get(f"{b_s.key}_legacy")
        assert a_s is not None, f"Missing legacy twin for {b_s.key}"
        assert a_s.is_silent is True, f"Telegram noise control requires {a_s.key} to be silent!"
        assert a_s.shortlist_mode == "legacy"
        assert b_s.shortlist_mode == "eda"
        assert a_s.prioritize_by_composite_rs is False
        assert b_s.prioritize_by_composite_rs is True


def test_declumped_group_b_strategies_route_distinct_dna_pools():
    """Verify Group B tracks route to genuinely distinct strategy pools rather than cloning identical stocks."""
    sample_picks = [
        {"ticker": "BLAST1.NS", "current_price": 500.0, "pivot_buy_stop": 505.0, "pattern": "ULTRA_ALPHA_LEADER", "rvol": 5.5, "composite_rs": 25.0, "clv": 0.92, "vol_asym_20": 2.2, "dist_ema200_pct": 18.0, "final_score": 88.0, "sector_status": "LEADING"},
        {"ticker": "ROCKET1.NS", "current_price": 800.0, "pivot_buy_stop": 810.0, "pattern": "PRE_IGNITION_COIL", "rvol": 1.1, "composite_rs": 38.0, "clv": 0.85, "vol_asym_20": 4.2, "dist_ema200_pct": 34.0, "final_score": 82.0, "sector_status": "NEUTRAL"},
    ]
    sample_radar = [
        {"ticker": "COIL1.NS", "current_price": 300.0, "pivot_buy_stop": 304.0, "pattern": "PRE_IGNITION_COIL", "rvol": 1.2, "composite_rs": 22.0, "clv": 0.78, "vol_asym_20": 3.5, "dist_ema200_pct": 14.0, "final_score": 76.0, "sector_status": "LEADING"},
        {"ticker": "IGN1.NS", "current_price": 400.0, "pivot_buy_stop": 405.0, "pattern": "INSTITUTIONAL_BLAST", "rvol": 3.8, "composite_rs": 18.0, "clv": 0.88, "vol_asym_20": 2.1, "dist_ema200_pct": 10.0, "final_score": 80.0, "sector_status": "NEUTRAL"},
    ]

    def _picked_tickers(key: str) -> set[str]:
        s = default_registry.get(key)
        acc = PortfolioAccount(name=s.name, capital=100000.0, max_slots=s.max_slots, slot_capital=s.slot_capital)
        s.log_picks(acc, sample_picks, sample_radar, "2026-11-26", True, datetime(2026, 11, 26, 16, 0).time())
        return {t.ticker for t in (acc.pending_triggers + acc.pending_confirmations)}

    t1 = _picked_tickers("track_algo4")            # Quiet coils (ROCKET1 excluded by dist>30, blasters excluded by rvol>1.8)
    t2 = _picked_tickers("option_3")               # High-RVOL ignitions (BLAST1, IGN1)
    t3 = _picked_tickers("track_algo5")            # Pure blasts (BLAST1, IGN1)
    t4 = _picked_tickers("option_2")               # VCP tight coils (ROCKET1, COIL1)
    t6 = _picked_tickers("track_apex_compounder")  # High-extension rockets (ROCKET1 >= 20% 200EMA)
    t9 = _picked_tickers("track_monthly_swing")    # Moderate-extension 5-25% accumulation swings (BLAST1 ineligible rvol>=2.5, COIL1 eligible)

    assert t1 == {"COIL1.NS"}
    assert t2 == {"BLAST1.NS", "IGN1.NS"}
    assert t3 == {"BLAST1.NS", "IGN1.NS"}
    assert t4 == {"ROCKET1.NS", "COIL1.NS"}
    assert t6 == {"ROCKET1.NS"}
    assert t9 == {"COIL1.NS"}
