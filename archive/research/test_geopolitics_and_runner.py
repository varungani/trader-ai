"""
Test script to verify outer-world news, geopolitical tailwinds,
and uncapped runner profit strategy across the stack.
"""
import sys
import os

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))

from analysis.event_risk import classify_events, compute_event_risk_score
from engine.trade_policy import calculate_trade_levels, evaluate_trade_exit
from llm.analyst import analyze_recommendation

def test_geopolitics_and_runner():
    print("=== 1. Testing Geopolitical Event Classification ===")
    mock_articles = [
        {
            "headline": "Cabinet approves mega defense indigenisation order for fighter jet engines and indigenous radar",
            "summary": "Major boost for domestic defense manufacturers with massive multi-year capital budget allocation."
        },
        {
            "headline": "Global supply chain shift boosts Indian electronics manufacturing and contract exports",
            "summary": "China+1 diversification accelerates with high capex expansion."
        },
        {
            "headline": "Brent crude drops below $70, expanding downstream margins for paints and aviation",
            "summary": "Crude oil softening provides margin relief."
        }
    ]

    tagged = classify_events(mock_articles)
    print(f"Classified {len(tagged)} articles:")
    for a in tagged:
        print(f" - [{', '.join(a['event_categories'])}] Impact: {a['event_impact']} | {a['headline'][:60]}...")
    assert len(tagged) == 3, f"Expected 3 tagged articles, got {len(tagged)}"

    event_res = compute_event_risk_score(mock_articles, ticker="HAL.NS")
    print(f"Event/Geopolitical Score: {event_res['score']}/100, Signal: {event_res['signal']}")
    assert event_res["score"] >= 60, f"Expected elevated score for positive catalysts, got {event_res['score']}"
    print("-> Geopolitical Event Engine: PASSED [OK]")

    print("\n=== 2. Testing Multi-Stage Profit Tiers (T1, T2, T3) ===")
    entry_price = 1000.0
    levels = calculate_trade_levels(entry_price, atr=25.0, timeframe="short_term")
    print(f"Entry Price: Rs. {entry_price:.2f}")
    print(f"Base Target T1: Rs. {levels.target_price:.2f} (+{levels.target_pct:.1f}%)")
    print(f"Extended Target T2: Rs. {levels.extended_target_price:.2f} (+{levels.extended_target_pct:.1f}%)")
    print(f"Runner Target T3: Rs. {levels.runner_target_price:.2f} (+{levels.runner_target_pct:.1f}%)")
    print(f"Planned Stop: Rs. {levels.stop_loss:.2f} (-{levels.stop_loss_pct:.1f}%)")
    
    assert levels.extended_target_price > levels.target_price, "Extended target must exceed base target"
    assert levels.runner_target_price > levels.extended_target_price, "Runner target must exceed extended target"
    assert levels.target_pct >= 12.0, "Base target must be at least 12%"
    assert levels.extended_target_pct >= 25.0, "Extended target must be at least 25%"
    assert levels.runner_target_pct >= 50.0, "Runner target must be at least 50%"
    print("-> Multi-Tier Profit Levels: PASSED [OK]")

    print("\n=== 3. Testing Uncapped Runner Exit Logic ===")
    # When allow_runner is False, hitting T1 exits with TARGET_HIT
    res_no_runner = evaluate_trade_exit(
        entry_price=1000.0,
        current_price=1140.0, # +14% (hits T1)
        stop_loss=levels.stop_loss,
        target_price=levels.target_price,
        days_held=5,
        peak_price=1140.0,
        high_price=1140.0,
        low_price=1130.0,
        atr=25.0,
        allow_runner=False
    )
    print(f"Standard Mode at +14%: should_exit={res_no_runner.is_closed}, reason={res_no_runner.exit_reason}")
    assert res_no_runner.is_closed is True
    assert "TARGET_HIT" in res_no_runner.exit_reason

    # When allow_runner is True, hitting T1 ratchets stop to lock in +8% and DOES NOT EXIT!
    res_runner_1 = evaluate_trade_exit(
        entry_price=1000.0,
        current_price=1140.0, # +14%
        stop_loss=levels.stop_loss,
        target_price=levels.target_price,
        days_held=5,
        peak_price=1140.0,
        high_price=1140.0,
        low_price=1130.0,
        atr=25.0,
        allow_runner=True
    )
    print(f"Runner Mode at +14%: should_exit={res_runner_1.is_closed}, stop_updated_to={res_runner_1.effective_stop}")
    assert res_runner_1.is_closed is False, "Runner mode must not exit at T1; it should let winner run!"
    assert res_runner_1.effective_stop >= 1080.0, f"Expected profit floor >= 1080, got {res_runner_1.effective_stop}"

    # Stock surges to +35% (1350)
    res_runner_2 = evaluate_trade_exit(
        entry_price=1000.0,
        current_price=1350.0,
        stop_loss=res_runner_1.effective_stop,
        target_price=levels.target_price,
        days_held=10,
        peak_price=1350.0,
        high_price=1350.0,
        low_price=1330.0,
        atr=25.0,
        allow_runner=True,
        is_runner=True
    )
    print(f"Runner Mode at +35%: should_exit={res_runner_2.is_closed}, trailing_stop={res_runner_2.effective_stop}")
    assert res_runner_2.is_closed is False
    assert res_runner_2.effective_stop > 1250.0, "Trailing stop must advance with peak price"

    # Stock pulls back from peak (1350) below trailing stop
    pullback_px = res_runner_2.effective_stop - 5.0
    res_runner_exit = evaluate_trade_exit(
        entry_price=1000.0,
        current_price=pullback_px,
        stop_loss=res_runner_2.effective_stop,
        target_price=levels.target_price,
        days_held=12,
        peak_price=1350.0,
        high_price=1350.0,
        low_price=pullback_px,
        atr=25.0,
        allow_runner=True,
        is_runner=True
    )
    print(f"Runner Pullback Exit: should_exit={res_runner_exit.is_closed}, reason={res_runner_exit.exit_reason}, price={pullback_px:.2f} (+{(pullback_px-1000)/10:.1f}%)")
    assert res_runner_exit.is_closed is True
    assert "TRAILING_STOP" in res_runner_exit.exit_reason
    print("-> Uncapped Runner Engine: PASSED [OK]")

    print("\n=== 4. Testing AI Analyst Geopolitics & Runner Synthesis ===")
    mock_rec = {
        "ticker": "BEL.NS",
        "action": "BUY",
        "final_score": 74.5,
        "technical_score": 78.0,
        "sentiment_score": 70.0,
        "event_risk_score": 72.0,
        "macro_score": 68.0,
        "current_price": 310.0,
        "stop_loss": 294.5,
        "target_price": 352.0,
        "extended_target_price": 395.0,
        "runner_target_price": 465.0,
        "is_runner_candidate": True,
        "target_pct": 13.5,
        "stop_loss_pct": 5.0,
        "reward_risk": 2.7,
        "sector": "Defense",
        "key_events": mock_articles,
    }
    analysis = analyze_recommendation(mock_rec)
    print(f"Summary: {analysis.get('summary')}")
    print(f"Geopolitical/Macro Catalyst: {analysis.get('geopolitical_and_macro_catalyst')}")
    print(f"Runner Strategy: {analysis.get('runner_strategy')}")
    assert "geopolitical_and_macro_catalyst" in analysis
    assert "runner_strategy" in analysis
    assert analysis["runner_strategy"]["is_runner_candidate"] is True
    print("-> Analyst Geopolitics & Runner Synthesis: PASSED [OK]")

    print("\nALL GEOPOLITICAL & UNCAPPED RUNNER TESTS PASSED SUCCESSFULLY! [100% OK]")

if __name__ == "__main__":
    test_geopolitics_and_runner()
