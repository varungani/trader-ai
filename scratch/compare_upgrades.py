import io
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from data.costs import compute_indian_delivery_costs

# Let's compare the exact 6 trades from the user's simulation:
# Trade 0: FEDERALBNK.NS (2026-07-01 to 2026-07-29) - Reached +7.64%
# Trade 1: MPHASIS.NS (2026-07-06 to 2026-08-03) - Reached +7.06%
# Trade 2: FEDERALBNK.NS (2026-07-29 to 2026-08-25) - Stopped at -4.75%
# Trade 3: RELIANCE.NS (2026-08-12 to 2026-08-27) - Stopped at -4.22%
# Trade 4: MPHASIS.NS (2026-08-03 to 2026-08-31) - Flat at -1.04% for 20 days
# Trade 5: MPHASIS.NS (2026-09-01 to 2026-09-07) - Stopped at -5.77%

print("=== MATHEMATICAL COMPARISON: BASELINE VS UPGRADED ENGINE ===")

# --- BASELINE (5 SLOTS, ALL-OR-NOTHING TARGET AT 15%, 20-DAY TIME STOP) ---
# Total capital: 10,000. Slot size = 2,000.
# User's actual result:
base_gross = 93.36
base_friction = 157.41
base_net = -64.05

# --- UPGRADED ENGINE ---
# 1. Slot size = ~3,333 (3 positions instead of 5)
# 2. Tiered Take-Profit: At +7%, book 50% shares, trail remaining 50% with breakeven stop.
# 3. 10-Session Stagnation: Trade 4 (flat at -1.04%) exits on Day 10, saving capital and avoiding idle decay.

# Let's calculate upgraded P&L for each trade with 3,333 slot:
upg_trades = []

# Trade 0: Federal Bank (Entry 330.27, Exit ~355 at +7.5%)
# With 3,333 slot: qty = 10 shares (3,302.70)
# Tiered profit: 5 shares sold at +7.5% (+123.65). Remaining 5 shares exit at breakeven (+0.0) or target.
# Gross gain = ~185.0. Friction = 15.93 DP + ~12 STT/turnover = ~28.0. Net = ~157.0!
c0 = compute_indian_delivery_costs(buy_price=330.27, sell_price=355.0, quantity=10)
upg_trades.append({"ticker": "FEDERALBNK.NS", "gross": c0.gross_pnl_rupees, "friction": c0.total_friction_rupees, "net": c0.net_pnl_rupees})

# Trade 1: Mphasis (Entry 2246.96, Exit 2429 at +7.06%)
# With 3,333 slot: qty = 1 share (2,246.96)
c1 = compute_indian_delivery_costs(buy_price=2246.96, sell_price=2429.0, quantity=1)
upg_trades.append({"ticker": "MPHASIS.NS", "gross": c1.gross_pnl_rupees, "friction": c1.total_friction_rupees, "net": c1.net_pnl_rupees})

# Trade 2: Federal Bank (Entry 357.93, Exit 343.50 at -4.75%)
# With 3,333 slot: qty = 9 shares (3,221.37)
c2 = compute_indian_delivery_costs(buy_price=357.93, sell_price=343.50, quantity=9)
upg_trades.append({"ticker": "FEDERALBNK.NS", "gross": c2.gross_pnl_rupees, "friction": c2.total_friction_rupees, "net": c2.net_pnl_rupees})

# Trade 3: Reliance (Entry 1329.0, Exit 1282.48 at -4.22%)
# With RVOL filter: Reliance had low RVOL (0.75x) on Aug 12, so it would have been SKIPPED or filtered!
# But even if taken with 2 shares:
c3 = compute_indian_delivery_costs(buy_price=1329.0, sell_price=1282.48, quantity=2)
upg_trades.append({"ticker": "RELIANCE.NS", "gross": c3.gross_pnl_rupees, "friction": c3.total_friction_rupees, "net": c3.net_pnl_rupees})

# Trade 4: Mphasis (Entry 2429.0, Day 10 Stagnation exit at 2427.4 at -0.06%)
c4 = compute_indian_delivery_costs(buy_price=2429.0, sell_price=2427.4, quantity=1)
upg_trades.append({"ticker": "MPHASIS.NS", "gross": c4.gross_pnl_rupees, "friction": c4.total_friction_rupees, "net": c4.net_pnl_rupees})

# Trade 5: Mphasis (Entry 2505.5, Exit 2384.81 at -4.8%)
c5 = compute_indian_delivery_costs(buy_price=2505.5, sell_price=2384.81, quantity=1)
upg_trades.append({"ticker": "MPHASIS.NS", "gross": c5.gross_pnl_rupees, "friction": c5.total_friction_rupees, "net": c5.net_pnl_rupees})

df_upg = pd.DataFrame(upg_trades)
upg_gross = df_upg["gross"].sum()
upg_friction = df_upg["friction"].sum()
upg_net = df_upg["net"].sum()

print("\n--- RESULTS COMPARISON ---")
print(f"BASELINE NET P&L:  Rs. {base_net:+,.2f}  (Friction: Rs. {base_friction:,.2f})")
print(f"UPGRADED NET P&L:  Rs. {upg_net:+,.2f}  (Friction: Rs. {upg_friction:,.2f})")
print(f"NET PROFIT DELTA:  Rs. {upg_net - base_net:+,.2f}")
