"""
Inspect Indian market status, daily scores, and paper trades for 2026-10-27.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from data.db import get_connection

conn = get_connection()
cursor = conn.cursor()

print("=== 1. DAILY SCORES IN DB FOR TODAY (2026-10-27) ===")
cursor.execute("SELECT ticker, action, final_score, technical_score, fundamental_score, reasoning FROM daily_scores WHERE date = ?", ('2026-10-27',))
rows = cursor.fetchall()
print(f"Total scores for 2026-10-27: {len(rows)}")
for r in rows:
    print(f"• {r[0]:<12}: Action: {r[1]:<6} | Score: {r[2]:.1f} | Tech: {r[3]} | Reason: {r[5][:80]}")

if not rows:
    cursor.execute("SELECT DISTINCT date FROM daily_scores ORDER BY date DESC LIMIT 5")
    print("Recent dates in daily_scores:", [r[0] for r in cursor.fetchall()])

print("\n=== 2. OPEN PAPER TRADES ===")
cursor.execute("SELECT * FROM paper_trades WHERE status = 'OPEN'")
open_trades = [dict(r) for r in cursor.fetchall()]
print(f"Total open paper trades: {len(open_trades)}")
for t in open_trades:
    print(f"• ID #{t['id']}: {t['ticker']} | Entry: Rs {t['entry_price']:,.2f} on {t['entry_date']} | Qty: {t['quantity']} | Stop: Rs {t['stop_loss']} | Target: Rs {t['target_price']}")

print("\n=== 3. CLOSED PAPER TRADES (RECENT) ===")
cursor.execute("SELECT * FROM paper_trades WHERE status = 'CLOSED' ORDER BY id DESC LIMIT 5")
closed_trades = [dict(r) for r in cursor.fetchall()]
for t in closed_trades:
    print(f"• ID #{t['id']}: {t['ticker']} | Exit Date: {t['exit_date']} | PnL: Rs {t['pnl']} ({t['pnl_percent']}%) | Reason: {t['exit_reason']}")

print("\n=== 4. FORWARD TEST LOG (RECENT) ===")
cursor.execute("SELECT ticker, date, action, entry_price, current_price, current_pnl_pct, status, exit_reason FROM forward_test_log ORDER BY id DESC LIMIT 5")
fwd = cursor.fetchall()
for f in fwd:
    print(f"• {f[0]} ({f[1]}): {f[2]} | Entry: Rs {f[3]} | Curr: Rs {f[4]} | PnL: {f[5]}% | Status: {f[6]} | ExitReason: {f[7]}")
