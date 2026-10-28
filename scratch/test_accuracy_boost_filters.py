import sys
import os
import sqlite3
import pandas as pd
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

conn = sqlite3.connect("trader_ai.db")
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Query all forward test log entries
cursor.execute("""
    SELECT ticker, date, action, entry_price, current_price, current_pnl_pct,
           final_score, technical_score, fundamental_score, event_risk_score, status
    FROM forward_test_log
    WHERE action LIKE '%BUY%'
    ORDER BY id ASC
""")
rows = [dict(r) for r in cursor.fetchall()]
conn.close()

print(f"Total Logged Forward BUYs in DB: {len(rows)}")

df = pd.DataFrame(rows)
if df.empty:
    print("No forward BUY rows found in database.")
    sys.exit(0)

# Calculate outcome: Win if current_pnl_pct > 0 or status == 'TARGET'
df['is_win'] = df['current_pnl_pct'] > 0

print("\n=== BASELINE ACCURACY (ALL BUY SIGNALS) ===")
tot = len(df)
wins = df['is_win'].sum()
print(f"Total BUYs: {tot} | Wins: {wins} | Accuracy: {(wins/tot)*100:.1f}% | Avg PnL: {df['current_pnl_pct'].mean():+.2f}%")

# Test Filter 1: Score >= 70
f1 = df[df['final_score'] >= 70]
if len(f1):
    w1 = f1['is_win'].sum()
    print(f"\nFilter 1 (Score >= 70): {len(f1)} trades | Wins: {w1} | Accuracy: {(w1/len(f1))*100:.1f}% | Avg PnL: {f1['current_pnl_pct'].mean():+.2f}%")

# Test Filter 2: Score >= 72
f2 = df[df['final_score'] >= 72]
if len(f2):
    w2 = f2['is_win'].sum()
    print(f"Filter 2 (Score >= 72): {len(f2)} trades | Wins: {w2} | Accuracy: {(w2/len(f2))*100:.1f}% | Avg PnL: {f2['current_pnl_pct'].mean():+.2f}%")

# Test Filter 3: Score >= 74
f3 = df[df['final_score'] >= 74]
if len(f3):
    w3 = f3['is_win'].sum()
    print(f"Filter 3 (Score >= 74): {len(f3)} trades | Wins: {w3} | Accuracy: {(w3/len(f3))*100:.1f}% | Avg PnL: {f3['current_pnl_pct'].mean():+.2f}%")

# Test Filter 4: Technical Score >= 75
f4 = df[df['technical_score'] >= 75]
if len(f4):
    w4 = f4['is_win'].sum()
    print(f"Filter 4 (Technical Score >= 75): {len(f4)} trades | Wins: {w4} | Accuracy: {(w4/len(f4))*100:.1f}% | Avg PnL: {f4['current_pnl_pct'].mean():+.2f}%")
