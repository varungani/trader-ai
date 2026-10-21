import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.trade_policy import evaluate_trade_exit

print("=== 1. TESTING MOMENTUM STAGNATION EXIT (DAY 10) ===")
# Stagnant trade: entry 100, current 100.5 (+0.5%), held for 10 sessions
res_stag = evaluate_trade_exit(
    entry_price=100.0,
    current_price=100.5,
    stop_loss=93.0,
    target_price=115.0,
    days_held=10
)
print("Stagnant Trade (Day 10, +0.5%):")
print(f"  Closed: {res_stag.is_closed}, Reason: {res_stag.exit_reason}")
assert res_stag.is_closed == True
assert "MOMENTUM_STAGNATION_EXIT" in res_stag.exit_reason

# Active runner trade: entry 100, current 108.0 (+8%), held for 10 sessions
res_active = evaluate_trade_exit(
    entry_price=100.0,
    current_price=108.0,
    stop_loss=93.0,
    target_price=115.0,
    days_held=10
)
print("\nActive Trending Trade (Day 10, +8.0%):")
print(f"  Closed: {res_active.is_closed}, Reason: {res_active.exit_reason}")
assert res_active.is_closed == False

print("\n=== 2. TESTING PARTIAL PROFIT TRIGGER (+7% / +1.5R) ===")
res_partial = evaluate_trade_exit(
    entry_price=100.0,
    current_price=107.5,
    stop_loss=95.0, # risk is 5. 1.5R is 7.5 -> 107.5
    target_price=115.0,
    days_held=5
)
print("Partial Profit (+7.5%):")
print(f"  Partial Booked: {res_partial.is_partial_booked}")
assert res_partial.is_partial_booked == True

print("\n[SUCCESS] ALL PROFIT-BOOSTING VERIFICATIONS PASSED!")
