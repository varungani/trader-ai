import sys
import os
import sqlite3
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.market_data import fetch_live_quote

conn = sqlite3.connect("trader_ai.db")
cursor = conn.cursor()

# Query the 5 active open trades
cursor.execute("SELECT id, ticker, entry_date, entry_price, quantity, stop_loss, target_price FROM paper_trades WHERE status = 'OPEN'")
open_rows = cursor.fetchall()

portfolio_data = []
for row_id, ticker, entry_date, entry_price, qty, sl, tp in open_rows:
    q = fetch_live_quote(ticker)
    ltp = q.get("price") or q.get("current_price") or entry_price
    if ltp == 0:
        ltp = entry_price
    
    pnl = (ltp - entry_price) * qty
    pnl_pct = ((ltp - entry_price) / entry_price) * 100
    
    cursor.execute("""
        UPDATE paper_trades
        SET exit_price = ?,
            pnl = ?,
            pnl_percent = ?
        WHERE id = ?
    """, (ltp, pnl, pnl_pct, row_id))
    
    portfolio_data.append({
        "ID": row_id,
        "Ticker": ticker,
        "Entry Date": entry_date,
        "Shares": qty,
        "Buy Price": f"Rs. {entry_price:,.2f}",
        "Current LTP": f"Rs. {ltp:,.2f}",
        "Invested": entry_price * qty,
        "Current Val": ltp * qty,
        "P&L (Rs)": round(pnl, 2),
        "P&L (%)": round(pnl_pct, 2),
        "Stop Loss": f"Rs. {sl:,.2f}",
        "Target": f"Rs. {tp:,.2f}"
    })

conn.commit()
conn.close()

df = pd.DataFrame(portfolio_data)
print("=== DEDUPLICATED ACTIVE 5-STOCK PORTFOLIO (Rs 10,000 ALLOCATION) ===")
print(df.to_string(index=False))

total_inv = df["Invested"].sum()
total_curr = df["Current Val"].sum()
net_pnl = df["P&L (Rs)"].sum()
net_pct = (net_pnl / total_inv) * 100

print("\n=== SUMMARY ===")
print(f"Total Invested:   Rs. {total_inv:,.2f}")
print(f"Current Value:    Rs. {total_curr:,.2f}")
print(f"Net Floating P&L: Rs. {net_pnl:+,.2f} ({net_pct:+.2f}%)")
