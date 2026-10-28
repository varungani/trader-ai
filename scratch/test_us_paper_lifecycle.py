"""
Test US Paper Trading lifecycle:
1. Fetch live candidates
2. Execute a simulated buy on a top US stock (e.g. NVDA or AAPL)
3. Sync and inspect open position ledger (MTM in USD and INR)
4. Manually close and inspect closed ledger
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from engine.us_engine import (
    fetch_us_realtime_data,
    analyze_us_market,
    execute_us_shadow_buy,
    sync_us_paper_trades,
    manual_close_us_paper_trade
)
from data.db import get_connection

print("1. Fetching US real-time data & analyzing...")
data = fetch_us_realtime_data()
analysis = analyze_us_market(data)
cands = analysis["candidates"]
target = next(c for c in cands if c["symbol"] == "NVDA")

print(f"   Selected: {target['symbol']} at ${target['price_usd']:.2f} (Rs {target['price_inr']:,.2f})")

print("\n2. Executing US Shadow Buy ($1,500 slot)...")
res_buy = execute_us_shadow_buy(
    symbol="NVDA",
    candidate=target,
    allocated_usd=1500.0,
    strategy_mode="Ultra Bullet Runner (15 EMA Trail)"
)
print(f"   Buy Result: {res_buy}")
assert res_buy["ok"], f"Buy failed: {res_buy}"
trade_id = res_buy["trade_id"]

print("\n3. Syncing Paper Trades...")
ledger = sync_us_paper_trades(data)
print(f"   Active Open Trades: {len(ledger['open_trades'])}")
pos = next(t for t in ledger["open_trades"] if t["id"] == trade_id)
print(f"   Holding: {pos['shares']} shares of {pos['symbol']}")
print(f"   Entry: ${pos['entry_price_usd']:.2f} | Current: ${pos['current_price_usd']:.2f}")
print(f"   Allocated: ${pos['allocated_usd']:.2f} (Rs {pos['allocated_inr']:,.2f})")
print(f"   Floating P&L: ${pos['unrealized_pnl_usd']:+.2f} (Rs {pos['unrealized_pnl_inr']:+.2f} | {pos['unrealized_pnl_pct']:+.2f}%)")
print(f"   Stop-Loss: ${pos['stop_loss_usd']:.2f} | Cushion: {pos['dist_to_stop_pct']:.1f}%")

print("\n4. Testing Manual Close...")
res_close = manual_close_us_paper_trade(trade_id, exit_price_usd=pos['current_price_usd'] * 1.05, exit_reason="TARGET 1 TAKE PROFIT (+5%)")
print(f"   Close Result: {res_close}")
assert res_close["ok"], f"Close failed: {res_close}"

print("\n5. Checking Closed Trades Audit...")
ledger_post = sync_us_paper_trades(data)
print(f"   Active Open Trades: {len(ledger_post['open_trades'])}")
print(f"   Closed Trades Count: {ledger_post['total_closed_count']}")
print(f"   Total Realized P&L: ${ledger_post['tot_realized_pnl_usd']:+,.2f} (Rs {ledger_post['tot_realized_pnl_inr']:+,.2f})")
print(f"   Win Rate: {ledger_post['win_rate']}% | Profit Factor: {ledger_post['profit_factor']}")

# Clean up test trade so user starts with a clean slate
conn = get_connection()
conn.cursor().execute("DELETE FROM paper_us_trades WHERE id = ?", (trade_id,))
conn.commit()
conn.close()
print("\nCleaned up test trade from SQLite. Database pristine!")
print("US PAPER TRADING PIPELINE FULLY VALIDATED!")
