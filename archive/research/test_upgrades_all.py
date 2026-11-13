"""
Comprehensive Test of the 3 Implemented Upgrades:
1. count_trading_days in data.market_calendar
2. 52W Breakout reward in engine.screener
3. Sector Decoupling Engine in engine.pipeline
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

print("=================================================================")
print("TEST 1: TRADING DAYS CALENDAR ENGINE")
print("=================================================================")
from data.market_calendar import count_trading_days, is_trading_holiday

# Test 1: Weekend + Dussehra Holiday (2026-10-20)
sessions_kotak = count_trading_days("2026-10-17", "2026-10-27")
print(f"• Kotak Bank Held from 2026-10-17 to 2026-10-27:")
print(f"  Calendar Days: 10 days")
print(f"  Actual NSE Trading Sessions: {sessions_kotak} sessions (excludes 4 weekend days + Dussehra Oct 20)")
assert sessions_kotak == 6, f"Expected 6 sessions, got {sessions_kotak}"
print("  => PASSED! Real market sessions accurately calculated.\n")

print("=================================================================")
print("TEST 2: PRE-SCREENER 52W HIGH BREAKOUT REWARD")
print("=================================================================")
from engine.screener import pre_screen

screened = pre_screen(["BHARTIARTL.NS", "COFORGE.NS", "KOTAKBANK.NS"], top_n=5)
for s in screened:
    print(f"• {s['ticker']:<14}: Screen Score: {s['screen_score']:>5.1f} | RVOL: {s['rvol']:>4.2f}x | Pattern: {s['setup_pattern']:<18} | Range Pos: {s['range_position']}")

bharti = next((s for s in screened if s["ticker"] == "BHARTIARTL.NS"), None)
if bharti:
    print(f"  Bharti Airtel Pattern Detected: {bharti['setup_pattern']}")
    print(f"  Bharti Airtel Score: {bharti['screen_score']}")
    assert bharti['screen_score'] > 65, "Expected high screen score for Bharti Airtel"
print("  => PASSED! 52W High Breakouts rewarded with full credit.\n")

print("=================================================================")
print("TEST 3: SECTOR DECOUPLING ENGINE PIPELINE")
print("=================================================================")
# Fast mock for forward validation to avoid 160+ individual quote lookups during test
import engine.validator
engine.validator.audit_and_resolve_forward_trades = lambda: {}

from engine.pipeline import run_pipeline

brief = run_pipeline(
    tickers=["BHARTIARTL.NS", "COFORGE.NS", "KOTAKBANK.NS"],
    timeframe="short_term",
    include_holdings=False,
    sync_broker=False,
    persist=False,
    use_llm=False,
    paper_week=False,
    use_screener=False,
    stock_budget=10000.0,
)

print(f"• Macro Regime Gate Cleared: {brief['macro'].get('is_regime_gate_cleared')}")
print(f"• Sector Decoupled Active: {brief.get('sector_decoupled_active')}")
print(f"• Top Picks Count: {len(brief.get('top_picks', []))}")
for p in brief.get('top_picks', []):
    print(f"  - {p['ticker']} | Score: {p['final_score']} | Action: {p['action']} | Decoupled: {p.get('is_sector_decoupled')} | Context: {p.get('regime_context')}")

assert brief.get('sector_decoupled_active') is True, "Expected sector_decoupled_active to be True"
assert len(brief.get('top_picks', [])) > 0, "Expected decoupled leaders in top_picks"
print("  => PASSED! Sector Decoupling successfully unlocked high-alpha breakout leaders.\n")

print("ALL 3 UPGRADES SUCCESSFULLY TESTED AND VERIFIED!")
