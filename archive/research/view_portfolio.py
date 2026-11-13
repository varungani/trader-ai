import sqlite3
import pandas as pd

conn = sqlite3.connect("trader_ai.db")
query = """
SELECT id, ticker, entry_date, entry_price, quantity, stop_loss, target_price, exit_price, pnl, pnl_percent, status
FROM paper_trades
WHERE status = 'OPEN'
ORDER BY id ASC
"""
df = pd.read_sql(query, conn)
print("=== ACTIVE OPEN POSITIONS (EXACTLY 5) ===")
print(df.to_string(index=False))

total_inv = (df['entry_price'] * df['quantity']).sum()
print("\n=== TOTALS ===")
print(f"Total Invested: Rs. {total_inv:,.2f}")

# Also check live quote updates if possible
from data.market_data import fetch_live_quote

quotes = {}
curr_vals = []
pnls = []
pnl_pcts = []

for _, row in df.iterrows():
    q = fetch_live_quote(row['ticker'])
    ltp = q.get('current_price') or row['entry_price']
    invested = row['entry_price'] * row['quantity']
    curr_val = ltp * row['quantity']
    pnl = curr_val - invested
    pct = (pnl / invested) * 100
    quotes[row['ticker']] = ltp
    curr_vals.append(curr_val)
    pnls.append(pnl)
    pnl_pcts.append(pct)

df['live_ltp'] = [quotes[t] for t in df['ticker']]
df['current_val'] = curr_vals
df['live_pnl'] = pnls
df['live_pnl_pct'] = pnl_pcts

print("\n=== LIVE PORTFOLIO WITH REAL-TIME PRICES ===")
print(df[['ticker', 'entry_date', 'entry_price', 'quantity', 'live_ltp', 'stop_loss', 'target_price', 'live_pnl', 'live_pnl_pct']].to_string(index=False))

total_current_val = sum(curr_vals)
total_pnl = sum(pnls)
net_pnl_pct = (total_pnl / total_inv) * 100 if total_inv > 0 else 0

print(f"\nTotal Capital Allocated: Rs. {total_inv:,.2f}")
print(f"Current Value:           Rs. {total_current_val:,.2f}")
print(f"Total Net Floating P&L:  Rs. {total_pnl:+,.2f} ({net_pnl_pct:+.2f}%)")
