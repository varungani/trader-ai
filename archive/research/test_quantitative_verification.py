import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from data.costs import compute_indian_delivery_costs
from engine.trade_policy import calculate_trade_levels, evaluate_trade_exit
from engine.balancer import position_size
from analysis.macro import compute_macro_score

print("=== 1. INDIAN STATUTORY COSTS & TAXES TEST ===")
costs = compute_indian_delivery_costs(buy_price=1000.0, sell_price=1120.0, quantity=10)
print(f"Buy: ₹10,000 | Sell: ₹11,200 | Gross Gain: ₹{costs.gross_pnl_rupees}")
print(f"Total Friction (STT, Stamp, NSE, SEBI, GST, DP, Slippage): ₹{costs.total_friction_rupees}")
print(f"Pre-Tax Net PnL: ₹{costs.net_pnl_rupees} ({costs.net_pnl_pct}%)")
print(f"20% STCG Tax (Finance Act 2024): ₹{costs.stcg_tax_rupees}")
print(f"Net Post-Tax PnL: ₹{costs.net_post_tax_pnl_rupees} ({costs.net_post_tax_pnl_pct}%)")
assert costs.stcg_tax_rupees > 0, "STCG tax should be positive on profitable trade"
assert costs.dp_charges_rupees == 15.93, "CDSL DP charge should be 15.93"

print("\n=== 2. POSITION SIZING & BINDING CONSTRAINT TEST ===")
size_result = position_size(capital=50000.0, price=2000.0, stop=1900.0, profile={})
print(f"Capital: ₹50,000 | Price: ₹2,000 | Stop: ₹1,900 (-5.0%)")
print(f"Qty: {size_result['qty']} shares | Invested: ₹{size_result['rupees']} | Risk: ₹{size_result['risk_rupees']}")
print(f"Binding Constraint: {size_result['binding_constraint']} | Planned Risk: {size_result['planned_risk_pct']}% of Capital")
assert size_result["binding_constraint"] == "CAPITAL_CAP (20%)", "20% Capital Cap should bind before 2% risk"
assert size_result["rupees"] <= 10000.0, "Position should not exceed 20% cap (₹10,000)"

print("\n=== 3. DYNAMIC ATR LEVELS & EXITS TEST ===")
levels = calculate_trade_levels(entry_price=1000.0, atr=25.0)  # ATR = 2.5% -> 2*ATR = 5.0%
print(f"Entry: ₹{levels.entry_price} | Planned Stop: ₹{levels.stop_loss} (-{levels.stop_loss_pct}%) | Target: ₹{levels.target_price} (+{levels.target_pct}%)")
print(f"Breakeven Level (+1R): ₹{levels.breakeven_price} | Partial Target (+1.5R): ₹{levels.partial_target_price}")
assert levels.stop_loss_pct == 5.0, "Stop should be 5.0%"
assert levels.reward_risk >= 2.0, "R:R should be >= 2.0"

# Gap-down realism
res_gap = evaluate_trade_exit(entry_price=1000.0, current_price=920.0, stop_loss=950.0, target_price=1120.0, days_held=2, low_price=915.0)
print(f"Gap-Down Exit: Fill at ₹{res_gap.exit_price} (Reason: {res_gap.exit_reason})")
assert res_gap.exit_price <= 920.0, "Gap-down fill must fill at market/low price, not stop trigger!"

# Breakeven move at +1R
res_be = evaluate_trade_exit(entry_price=1000.0, current_price=1010.0, stop_loss=950.0, target_price=1120.0, days_held=5, peak_price=1055.0, low_price=998.0)
print(f"Breakeven Stop Hit: Exit fill at ₹{res_be.exit_price} (Reason: {res_be.exit_reason})")
assert res_be.is_closed and "BREAKEVEN" in str(res_be.exit_reason), "Stop should ratchet to breakeven after +1R peak"

# Time stop at day 15
res_time = evaluate_trade_exit(entry_price=1000.0, current_price=1020.0, stop_loss=950.0, target_price=1120.0, days_held=15)
print(f"Time Stop Exit: {res_time.exit_reason} at ₹{res_time.exit_price}")
assert res_time.is_closed and "TIME" in str(res_time.exit_reason), "Day 15 time stop should trigger"

print("\n=== 4. HARD MARKET REGIME GATE TEST ===")
macro = compute_macro_score()
print(f"Regime: {macro.get('regime')} (Score: {macro.get('score')})")
print(f"Regime Gate Status: {macro.get('regime_gate_status')}")
print(f"Regime Gate Cleared: {macro.get('is_regime_gate_cleared')}")
print(f"No Trade Today: {macro.get('no_trade_today')}")
print(f"Reason: {macro.get('regime_gate_reason')}")

print("\nALL QUANTITATIVE VERIFICATION TESTS PASSED SUCCESSFULLY!")
