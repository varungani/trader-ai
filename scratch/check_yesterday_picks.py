import sqlite3
import pandas as pd

conn = sqlite3.connect('trader_ai.db')
query = """
SELECT ticker, final_score, action, stop_loss, target_price, reasoning
FROM daily_scores
WHERE date = '2026-11-12' AND ticker IN ('TECHM.NS', 'HCLTECH.NS', 'HAL.NS', 'INDHOTEL.NS', 'NIFTYBEES.NS')
ORDER BY final_score DESC
"""
df = pd.read_sql_query(query, conn)
for _, row in df.iterrows():
    print(f"[{row['ticker']}] Score: {row['final_score']} | SL: {row['stop_loss']} | Target: {row['target_price']}")
    print(f"Reasoning: {row['reasoning']}\n")
