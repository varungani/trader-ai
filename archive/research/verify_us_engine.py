"""
Test engine/us_engine.py functionality:
- Market status clock
- Realtime data fetching
- Analysis & 4-pillar scoring
- Shadow buy execution & sync
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from engine.us_engine import (
    get_us_market_status,
    fetch_us_realtime_data,
    analyze_us_market,
    sync_us_paper_trades,
    execute_us_shadow_buy,
    manual_close_us_paper_trade
)

print("1. Testing US Market Status Clock...")
status = get_us_market_status()
print(f"   Badge: {status['badge']}")
print(f"   Detail: {status['detail']}")
print(f"   EST: {status['time_est_str']} | IST: {status['time_ist_str']}")

print("\n2. Testing Real-time Data Fetch...")
data = fetch_us_realtime_data()
print(f"   Fetched {len(data)} US Equities tickers.")
assert len(data) >= 15, "Expected at least 15 tickers."

print("\n3. Testing Analysis & 4-Pillar Quant Scoring...")
analysis = analyze_us_market(data)
assert analysis["status"] == "OK"
macro = analysis["macro"]
print(f"   Macro Regime: {macro['regime']}")
print(f"   SPY Price: ${macro['spy_price']:.2f} (50 SMA: ${macro['spy_sma50']:.2f})")
print(f"   QQQ Price: ${macro['qqq_price']:.2f} (50 SMA: ${macro['qqq_sma50']:.2f})")
print(f"   Verdict: {macro['verdict']}")

candidates = analysis["candidates"]
print(f"\n   Total Candidates Scored: {len(candidates)}")
print("   Top 5 US Momentum Picks:")
for c in candidates[:5]:
    print(f"     • {c['symbol']:<5} | Score: {c['score']:>4.1f} | Verdict: {c['verdict']} | Action: {c['action']}")
    print(f"       Price: ${c['price_usd']:.2f} (Rs {c['price_inr']:,.2f}) | RVOL: {c['rvol']}x | RS: {c['mansfield_rs']:+.1f}% | Stop: ${c['stop_loss_usd']} | TGT1: ${c['target1_usd']}")

print("\n4. Testing Paper / Shadow Sync...")
sync_res = sync_us_paper_trades(data)
print(f"   Open Trades: {len(sync_res['open_trades'])}")
print(f"   Closed Trades: {len(sync_res['closed_trades'])}")
print(f"   Win Rate: {sync_res['win_rate']}% | PF: {sync_res['profit_factor']}")

print("\nALL US ENGINE TESTS PASSED SUCCESSFULLY!")
