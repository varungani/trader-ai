import sqlite3
import pandas as pd

conn = sqlite3.connect("trader_ai.db")
query = """
SELECT id, date, ticker, action, entry_price, current_price, current_pnl_pct, status, exit_reason
FROM forward_test_log
WHERE action LIKE '%BUY%'
ORDER BY date DESC, id DESC
"""
df = pd.read_sql(query, conn)
print("=== ALL RECORDED FORWARD BUY RECOMMENDATIONS ===")
print(df.to_string())
