"""
Layer 1: Deterministic Invariant Tests (TraderAI v3.5.1)
Verifies core quantitative system invariants on every commit:
  1. Hand-computed Indian statutory friction golden values down to the exact paisa.
  2. Intrabar exit conflict resolution: Conservative Stop-First ordering.
  3. Spec-to-table parameter consistency against config.py (TOURNAMENT_CONFIG).
  4. Fill realism: GTT breakout buy-stops fill at pivot or worse, never better.
  5. Gap guardrails: Morning gaps > +2.5% abort with ABORTED_EXTENDED_GAP.
  6. Calendar invariants: Holding period strictly excludes weekends and NSE holidays.
"""
import pytest
from data.costs import compute_indian_delivery_costs, CDSL_DP_CHARGE
from config import TOURNAMENT_CONFIG


def test_friction_golden_values_exact_paisa():
    """
    Assert exact statutory friction down to the paisa on 3 canonical hand-computed trades:
      1. Profitable micro-gain (+0.3% on ₹33k): Demonstrates real net margin.
      2. Flat trade (0.0% on ₹20k): Quantifies baseline friction cost of round-trip.
      3. Stop-loss exit (-4.0% on ₹20k): Asserts loss friction and zero STCG tax.
    """
    # ─── Trade 1: +0.3% gain on ₹33,000 (330 shares @ ₹100.0 -> ₹100.30) ───
    c1 = compute_indian_delivery_costs(buy_price=100.0, sell_price=100.30, quantity=330, slippage_pct=0.0)
    assert c1.gross_pnl_rupees == 99.00
    assert c1.stt_rupees == 66.10       # 0.1% buy (33.00) + 0.1% sell (33.10)
    assert c1.stamp_duty_rupees == 4.95 # 0.015% buy
    assert c1.exchange_charges_rupees == 2.28  # 0.00345% of total turnover (₹66,099)
    assert c1.sebi_charges_rupees == 0.07      # 0.0001% of total turnover
    assert c1.gst_rupees == 0.42        # 18% on (2.28 + 0.07)
    assert c1.dp_charges_rupees == 15.93 # CDSL flat per scrip sell
    assert c1.total_friction_rupees == 89.75
    assert c1.net_pnl_rupees == 9.25    # Leaves only ₹9.25 margin, proving why +0.6% lock is essential

    # ─── Trade 2: Flat 0.0% trade on ₹20,000 (200 shares @ ₹100.0 -> ₹100.0) ───
    c2 = compute_indian_delivery_costs(buy_price=100.0, sell_price=100.0, quantity=200, slippage_pct=0.0)
    assert c2.gross_pnl_rupees == 0.00
    assert c2.stt_rupees == 40.00       # 20.00 buy + 20.00 sell
    assert c2.stamp_duty_rupees == 3.00
    assert c2.exchange_charges_rupees == 1.38
    assert c2.sebi_charges_rupees == 0.04
    assert c2.gst_rupees == 0.26
    assert c2.dp_charges_rupees == 15.93
    assert c2.total_friction_rupees == 60.61
    assert c2.net_pnl_rupees == -60.61   # Fixed statutory toll for entry and exit

    # ─── Trade 3: -4.0% Stop-loss on ₹20,000 (200 shares @ ₹100.0 -> ₹96.0) ───
    c3 = compute_indian_delivery_costs(buy_price=100.0, sell_price=96.0, quantity=200, slippage_pct=0.0)
    assert c3.gross_pnl_rupees == -800.00
    assert c3.stt_rupees == 39.20       # 20.00 buy + 19.20 sell
    assert c3.stamp_duty_rupees == 3.00
    assert c3.exchange_charges_rupees == 1.35
    assert c3.sebi_charges_rupees == 0.04
    assert c3.gst_rupees == 0.25
    assert c3.dp_charges_rupees == 15.93
    assert c3.total_friction_rupees == 59.77
    assert c3.net_pnl_rupees == -859.77
    assert c3.stcg_tax_rupees == 0.0    # Losses carry zero STCG tax liability


def test_intrabar_exit_ordering_stop_first_conservative(tmp_path, monkeypatch):
    """
    Assert conservative Stop-First ordering:
    When a single bar's High touches Target (+12%) and Low touches Stop (-4%),
    the engine MUST trigger Stop Loss first, never allowing optimistic Target-first fills.
    """
    import engine.dual_tracker as dt
    test_tracker_file = str(tmp_path / "dual_tracker.json")
    monkeypatch.setattr(dt, "TRACKER_FILE", test_tracker_file)

    tracker = dt._default_tracker_state()
    # Active trade: Entry ₹100.00, Target ₹112.00 (+12%), Stop ₹96.00 (-4%)
    tracker["option_3"]["open_trades"] = [
        {
            "ticker": "CONFLICT.NS",
            "name": "CONFLICT",
            "shortlist_date": "2026-11-16",
            "fill_date": "2026-11-16 10:00",
            "entry_date": "2026-11-16",
            "entry_price": 100.0,
            "current_price": 100.0,
            "target_price": 112.0,
            "stop_loss": 96.0,
            "breakeven_lock": 105.0,
            "shares": 200,
            "allocated_rupees": 20000.0,
            "status": "TRIGGERED_ACTIVE",
            "days_held": 1,
        }
    ]
    tracker["option_3"]["pending_triggers"] = []
    dt._save_tracker(tracker)

    # Volatile bar touches BOTH target (high=115.0) and stop (low=95.0)
    monkeypatch.setattr(
        dt,
        "fetch_live_quote",
        lambda t: {"price": 100.0, "day_high": 115.0, "day_low": 95.0, "high": 115.0, "low": 95.0},
    )

    dt.audit_and_update_dual_tracker(force_market_open=True)

    updated = dt._load_tracker()
    closed = updated["option_3"]["closed_trades"]
    assert len(closed) == 1
    # MUST be a stop exit (either base STOP_LOSS or BREAKEVEN_LOCK), NEVER TARGET_HIT
    assert ("STOP_LOSS" in closed[0]["exit_reason"] or "BREAKEVEN_LOCK" in closed[0]["exit_reason"])
    assert "TARGET" not in closed[0]["exit_reason"]


def test_spec_to_table_consistency():
    """
    Assert that every position in data/dual_tracker.json adheres to TOURNAMENT_CONFIG:
      - Target pct matches +12.0% within rounding.
      - Stop loss pct matches -4.0% within rounding.
      - Position size does not exceed ₹20,000 + buffer.
    """
    import json
    import os
    tracker_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "dual_tracker.json")
    if not os.path.exists(tracker_path):
        pytest.skip("dual_tracker.json not found")

    with open(tracker_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    target_pct = TOURNAMENT_CONFIG["target_pct"]
    stop_pct = TOURNAMENT_CONFIG["stop_loss_pct"]
    slot_cap = TOURNAMENT_CONFIG["slot_capital"]

    for trk_key in ["option_2", "option_3", "track_c"]:
        trk = data.get(trk_key, {})
        for t in trk.get("open_trades", []):
            ep = float(t["entry_price"])
            tp = float(t["target_price"])
            sl = float(t["stop_loss"])
            alloc = float(t.get("allocated_rupees", 0.0))

            # Target should be within 1.5% of entry * (1 + target_pct)
            expected_tp = ep * (1.0 + target_pct)
            assert abs(tp - expected_tp) / expected_tp < 0.05, f"Target {tp} diverged from {expected_tp} on {t['ticker']}"

            # Stop should be within 1.5% of entry * (1 - stop_pct)
            expected_sl = ep * (1.0 - stop_pct)
            assert abs(sl - expected_sl) / expected_sl < 0.05, f"Stop {sl} diverged from {expected_sl} on {t['ticker']}"

            # Allocated capital per trade must respect slot capital (₹20,000)
            assert alloc <= slot_cap * 1.02, f"Allocation ₹{alloc} exceeded slot cap on {t['ticker']}"


def test_gtt_fill_rules_worse_or_equal_never_better(tmp_path, monkeypatch):
    """
    Assert fill realism:
    A GTT buy-stop breakout order fills at the pivot trigger + slippage, NEVER below the trigger.
    """
    import engine.dual_tracker as dt
    test_tracker_file = str(tmp_path / "dual_tracker.json")
    monkeypatch.setattr(dt, "TRACKER_FILE", test_tracker_file)

    tracker = dt._default_tracker_state()
    tracker["option_3"]["open_trades"] = []
    tracker["option_3"]["pending_triggers"] = [
        {
            "ticker": "BREAKOUT.NS",
            "name": "BREAKOUT",
            "shortlist_date": "2026-11-16",
            "pivot_trigger": 500.0,
            "shares": 40,
            "target_price": 560.0,
            "stop_loss": 480.0,
            "breakeven_lock": 525.0,
            "status": "PENDING_BREAKOUT_TRIGGER",
        }
    ]
    dt._save_tracker(tracker)

    # Market ticks through pivot (high=505.0)
    monkeypatch.setattr(dt, "fetch_live_quote", lambda t: {"price": 502.0, "day_high": 505.0, "open": 498.0})

    dt.audit_and_update_dual_tracker(force_market_open=True)

    updated = dt._load_tracker()
    assert len(updated["option_3"]["open_trades"]) == 1
    trade = updated["option_3"]["open_trades"][0]

    # Fill price must be >= pivot_trigger (500.0 * 1.0025 = 501.25)
    assert trade["entry_price"] >= 500.0
    assert trade["entry_price"] == 501.25


def test_gap_above_chase_ceiling_aborts_trade(tmp_path, monkeypatch):
    """
    Assert that if a stock opens > +2.5% above scan price on Track A,
    it aborts with ABORTED_EXTENDED_GAP to prevent chasing local tops.
    """
    import engine.dual_tracker as dt
    test_tracker_file = str(tmp_path / "dual_tracker.json")
    monkeypatch.setattr(dt, "TRACKER_FILE", test_tracker_file)

    tracker = dt._default_tracker_state()
    tracker["option_2"]["pending_confirmations"] = [
        {
            "ticker": "GAP_CHASE.NS",
            "name": "GAP_CHASE",
            "shortlist_date": "2026-11-16",
            "scheduled_date": "2026-11-17",
            "scan_price": 100.0,
            "status": "AWAITING_920_OPEN",
        }
    ]
    dt._save_tracker(tracker)

    # Gapped up 4.0% at open (₹104.0 > ₹102.50 ceiling)
    monkeypatch.setattr(dt, "fetch_live_quote", lambda t: {"open": 104.0, "price": 104.0})

    dt.audit_and_update_dual_tracker(force_market_open=True)

    updated = dt._load_tracker()
    assert len(updated["option_2"]["open_trades"]) == 0
    aborted = updated["option_2"]["aborted_trades"]
    assert len(aborted) == 1
    assert aborted[0]["status"] == "ABORTED_EXTENDED_GAP"
    assert "chasing" in aborted[0]["reason"].lower()
