import pandas as pd
import io

csv_data = """
Ticker,Action,Entry Date,Entry Price,Current Price,Stop-Loss (-7%),Target (+15%),Qty,Unrealized P&L,PnL_pct
FEDERALBNK.NS,BUY,2026-10-18,338.00,348.45,321.61,378.56,7,73.15,3.09
BBOX.NS,BUY,2026-10-18,907.25,916.40,852.81,1016.12,2,18.30,1.01
KOTAKBANK.NS,BUY,2026-10-17,447.40,443.55,428.92,501.09,5,-19.25,-0.86
MPHASIS.NS,BUY,2026-10-11,2360.00,2488.10,2194.80,2714.00,1,128.10,5.43
COFORGE.NS,BUY,2026-10-11,1867.90,1948.90,1745.74,2148.09,1,81.00,4.34
COFORGE.NS,BUY,2026-10-11,1867.90,1948.90,1745.74,2148.09,1,81.00,4.34
AXISBANK.NS,BUY,2026-10-10,1259.10,1242.20,1170.96,1447.96,1,-16.90,-1.34
MPHASIS.NS,BUY,2026-10-10,2360.00,2488.10,2194.80,2714.00,1,128.10,5.43
KOTAKBANK.NS,BUY,2026-10-10,441.00,443.55,410.13,507.15,7,17.85,0.58
MON100.NS,BUY,2026-10-10,325.15,313.10,302.39,373.92,7,-84.35,-3.71
AXISBANK.NS,BUY,2026-10-10,1259.10,1242.20,1170.96,1447.96,2,-33.80,-1.34
KOTAKBANK.NS,BUY,2026-10-10,441.00,443.55,410.13,507.15,5,12.75,0.58
MPHASIS.NS,BUY,2026-10-10,2360.00,2488.10,2194.80,2714.00,1,128.10,5.43
MON100.NS,BUY,2026-10-10,325.15,313.10,302.39,373.92,8,-96.40,-3.71
MPHASIS.NS,BUY,2026-10-10,2360.00,2488.10,2194.80,2714.00,1,128.10,5.43
COFORGE.NS,BUY,2026-10-10,1867.90,1948.90,1737.15,2148.09,1,81.00,4.34
COFORGE.NS,BUY,2026-10-10,1867.90,1948.90,1737.15,2148.09,1,81.00,4.34
COFORGE.NS,BUY,2026-10-10,1867.90,1948.90,1737.15,2148.09,1,81.00,4.34
KOTAKBANK.NS,BUY,2026-10-10,441.00,443.55,410.13,507.15,5,12.75,0.58
"""

df = pd.read_csv(io.StringIO(csv_data.strip()))

tot_invested = (df['Entry Price'] * df['Qty']).sum()
tot_current = (df['Current Price'] * df['Qty']).sum()
tot_pnl = df['Unrealized P&L'].sum()
tot_pnl_pct = (tot_pnl / tot_invested) * 100
wins = df[df['Unrealized P&L'] > 0]
losses = df[df['Unrealized P&L'] < 0]
win_rate = len(wins) / len(df) * 100

print("=" * 80)
print("AUDITED PAPER TRADING LEDGER PERFORMANCE (FROM EXCEL)")
print("=" * 80)
print(f"Total Logged Entries:     {len(df)}")
print(f"Total Capital Simulated:  Rs {tot_invested:,.2f}")
print(f"Current Value:            Rs {tot_current:,.2f}")
print(f"Net Floating Profit:      Rs {tot_pnl:+,.2f} ({tot_pnl_pct:+.2f}%)")
print(f"Active Win Rate:          {len(wins)} / {len(df)} ({win_rate:.1f}%)")
print("=" * 80)

# Unique symbols
symbols = df['Ticker'].unique()
print("\nCONSOLIDATED PORTFOLIO BY ASSET:")
print("-" * 80)

for sym in symbols:
    sub = df[df['Ticker'] == sym]
    qty = sub['Qty'].sum()
    invested = (sub['Entry Price'] * sub['Qty']).sum()
    cur_val = (sub['Current Price'] * sub['Qty']).sum()
    pnl = sub['Unrealized P&L'].sum()
    pnl_pct = (pnl / invested) * 100
    cur_p = sub['Current Price'].iloc[-1]
    sl_p = sub['Stop-Loss (-7%)'].iloc[-1]
    tp_p = sub['Target (+15%)'].iloc[-1]
    cushion = (cur_p - sl_p) / cur_p * 100
    dist_tp = (tp_p - cur_p) / cur_p * 100
    status = "PROFIT (+5%+)" if pnl_pct >= 5.0 else ("GREEN" if pnl_pct > 0 else "RED (Near Stop)" if pnl_pct < -3.0 else "MILD LOSS")
    
    print(f"{sym:14s} | Qty: {qty:2d} | Cost: Rs {invested:8,.1f} | MTM: Rs {pnl:+7.2f} ({pnl_pct:+5.2f}%) | Stop Cushion: {cushion:4.1f}% | To Target: {dist_tp:4.1f}% | [{status}]")

print("-" * 80)
