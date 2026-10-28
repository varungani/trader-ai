"""
Check recommendations in daily_scores table and run screener for today.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from data.db import get_connection

conn = get_connection()
cursor = conn.cursor()

print("--- RECENT DAILY SCORES IN DB ---")
cursor.execute("SELECT DISTINCT date FROM daily_scores ORDER BY date DESC LIMIT 5")
dates = [r[0] for r in cursor.fetchall()]
for d in dates:
    cursor.execute("SELECT ticker, action, final_score, reasoning FROM daily_scores WHERE date = ? AND action = 'BUY' ORDER BY final_score DESC", (d,))
    buys = cursor.fetchall()
    print(f"Date {d}: {len(buys)} BUY recommendations")
    for b in buys[:3]:
        print(f"   • {b[0]:<12}: Score {b[2]:.1f} | {b[3][:70]}")
