"""
Verify Crypto Paper Trading, Scoring, Verdicts, and Shadow Tracking.
"""
import sys, os
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.crypto_engine import (
    fetch_crypto_realtime_data,
    analyze_crypto_market,
    sync_crypto_paper_trades,
    execute_crypto_shadow_buy,
    manual_close_crypto_paper_trade
)
from data.db import get_connection, get_open_crypto_paper_trades, get_closed_crypto_paper_trades

print("1. Fetching live crypto data...")
data = fetch_crypto_realtime_data()
print(f"Loaded {len(data)} assets: {list(data.keys())}")

print("\n2. Analyzing crypto market (4-Pillar Scoring & Verdicts)...")
analysis = analyze_crypto_market(data)
assert analysis["status"] == "OK"
btc = analysis["btc_macro"]
print(f"BTC Price: ${btc['price_usd']:,.2f} | Regime: {btc['regime']} | Entries Allowed: {btc['entries_allowed']}")

print("\n3. Inspecting Top 5 Candidates:")
for c in analysis["candidates"][:5]:
    print(f"  {c['name']} ({c['symbol']}): Score={c['score']}/100 | Verdict={c['verdict']} | Action={c['action']} | RVOL={c['rvol']}x | RS={c['mansfield_rs']}%")

print("\n4. Testing Shadow Buy Execution...")
top_cand = analysis["candidates"][0]
res = execute_crypto_shadow_buy(top_cand["symbol"], top_cand, allocated_inr=1500.0)
print(f"Shadow Buy Result: {res}")

print("\n5. Syncing Crypto Paper Trades...")
ledger = sync_crypto_paper_trades(data)
print(f"Open Positions Count: {len(ledger['open_positions'])}")
for p in ledger['open_positions']:
    print(f"  Trade ID #{p['id']}: {p['symbol']} | Qty: {p['quantity_tokens']} | Alloc: Rs {p['allocated_inr']} | MTM P&L: Rs {p.get('unrealized_pnl_inr', 0):+.2f} ({p.get('unrealized_pnl_pct', 0):+.2f}%)")

print("\n6. Testing Manual Close...")
if ledger['open_positions']:
    t_id = ledger['open_positions'][0]['id']
    curr_px = ledger['open_positions'][0]['current_price_usd']
    c_res = manual_close_crypto_paper_trade(t_id, curr_px)
    print(f"Manual Close Result for #{t_id}: {c_res}")

print("\n7. Final Closed Trades Count:")
conn = get_connection()
closed = get_closed_crypto_paper_trades(conn)
conn.close()
print(f"Closed Trades Count: {len(closed)}")
for c in closed:
    print(f"  Closed ID #{c['id']}: {c['symbol']} | Realized P&L: Rs {c['pnl_inr']:+.2f} ({c['pnl_pct']:+.2f}%) | TDS Paid: Rs {c['tds_inr']} | Reason: {c['exit_reason']}")

print("\nALL VERIFICATIONS PASSED SUCCESSFULLY!")
