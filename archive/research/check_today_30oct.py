import os, sys
sys.path.insert(0, os.getcwd())
from data.db import get_connection, get_open_paper_trades
from engine.paper_week import mark_to_market
from engine.us_engine import fetch_us_realtime_data, sync_us_paper_trades, get_us_market_status

print("=== 1. AUDITING INDIAN PAPER TRADES (30 OCT CLOSE) ===")
mtm = mark_to_market()
conn = get_connection()
try:
    open_trades = get_open_paper_trades(conn)
    marks_map = {m['trade_id']: m for m in (mtm.get('marks') or [])}
    tot_inv = 0
    tot_val = 0
    for t in open_trades:
        m = marks_map.get(t['id'], {})
        sym = t['ticker']
        entry_px = float(t.get('entry_price') or 0.0)
        cur_px = float(m.get('last') or entry_px)
        qty = int(t.get('quantity') or 1)
        pnl = float(m.get('unrealized_pnl') or ((cur_px - entry_px) * qty))
        pnl_pct = ((cur_px - entry_px) / entry_px * 100.0) if entry_px > 0 else 0.0
        stop_px = float(t.get('stop_loss') or 0.0)
        target_px = float(t.get('target_price') or 0.0)
        inv = entry_px * qty
        val = cur_px * qty
        tot_inv += inv
        tot_val += val
        print(f"{sym:<14} | Qty: {qty:2d} | Entry: Rs {entry_px:8.2f} | Close: Rs {cur_px:8.2f} | PnL: Rs {pnl:+7.2f} ({pnl_pct:+6.2f}%) | Stop: Rs {stop_px:.2f}")
    if tot_inv > 0:
        print(f"Total Invested: Rs {tot_inv:,.2f} | Current Value: Rs {tot_val:,.2f} | Net Floating PnL: Rs {tot_val-tot_inv:+,.2f} ({(tot_val-tot_inv)/tot_inv*100:+.2f}%)")
finally:
    conn.close()

print("\n=== 2. AUDITING US PAPER TRADES ===")
stat = get_us_market_status()
print("US Market Status:", stat['badge'])
u_data = fetch_us_realtime_data()
u_sync = sync_us_paper_trades(u_data)
for ut in u_sync.get('open_trades', []):
    print(f"{ut['symbol']:<6} | Shares: {ut['shares']:.4f} | Entry: ${ut['entry_price_usd']:.2f} | Close: ${ut['current_price_usd']:.2f} | PnL: ${ut['unrealized_pnl_usd']:+.2f} ({ut['unrealized_pnl_pct']:+.2f}%)")
print(f"Tot Floating USD: ${u_sync.get('tot_floating_pnl_usd', 0):+.2f} | INR: Rs {u_sync.get('tot_floating_pnl_inr', 0):+.2f}")
