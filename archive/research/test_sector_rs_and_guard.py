"""
Test Script: Verify Sector Relative Strength (RS) Engine & 20 EMA Over-Extension Guard
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import RISK_CONFIG, TICKER_TO_SECTOR
from analysis.sector_rs import compute_sector_rs, refresh_sector_relative_strengths
from engine.scorer import score_stock
from engine.recommender import build_recommendation

print("=" * 60)
print("TEST 1: Config Min Score to Buy")
print("=" * 60)
print(f"RISK_CONFIG['min_score_to_buy'] = {RISK_CONFIG['min_score_to_buy']} (Expected: 70)")
assert RISK_CONFIG["min_score_to_buy"] == 70, "min_score_to_buy should be 70"

print("\n" + "=" * 60)
print("TEST 2: Sector Relative Strength (RS) Engine")
print("=" * 60)
it_rs = compute_sector_rs("IT")
auto_rs = compute_sector_rs("Auto")
bank_rs = compute_sector_rs("Banking")

print(f"IT RS: {it_rs['relative_strength_pct']:+.2f}%, Status: {it_rs['status']}, Bonus: {it_rs['bonus_points']:+.1f}")
print(f"Auto RS: {auto_rs['relative_strength_pct']:+.2f}%, Status: {auto_rs['status']}, Bonus: {auto_rs['bonus_points']:+.1f}")
print(f"Bank RS: {bank_rs['relative_strength_pct']:+.2f}%, Status: {bank_rs['status']}, Bonus: {bank_rs['bonus_points']:+.1f}")

assert it_rs["bonus_points"] > 0, "IT should have positive bonus today"
assert auto_rs["bonus_points"] < 0, "Auto should have negative penalty today"

print("\n" + "=" * 60)
print("TEST 3: Stock Scoring with Sector RS & EMA Guard")
print("=" * 60)
# Score Coforge (IT)
s_coforge = score_stock("COFORGE.NS")
r_coforge = build_recommendation(s_coforge)
print(f"COFORGE.NS: Sector={s_coforge.get('sector')}, FinalScore={s_coforge['final_score']}, Action={r_coforge['action']}")

# Score Karur Vysya (Over-extended bank)
s_kvb = score_stock("KARURVYSYA.NS")
r_kvb = build_recommendation(s_kvb)
dev_kvb = (s_kvb.get("technical") or {}).get("indicators", {}).get("ema_20", {}).get("deviation_pct", 0)
print(f"KARURVYSYA.NS: Deviation from EMA20={dev_kvb:+.2f}%, Action={r_kvb['action']}, Rationale={r_kvb.get('action_rationale')}")

print("\n" + "=" * 60)
print("ALL ASSERTIONS PASSED CLEANLY!")
print("=" * 60)
