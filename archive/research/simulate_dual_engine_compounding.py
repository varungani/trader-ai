"""
Simulate 1-Year (and 4-Year) Dual-Engine Compounding with User Inflow Schedule.
Engine 1: Core NSE Equities (Rs 30k start + Rs 20k/mo M1-4 + Rs 50k/mo M5-48)
Engine 2: Crypto Alpha Satellite (Rs 3k start + Rs 3k/mo M1-4 + Rs 6k/mo M5-48)
"""
import sys
import pandas as pd
import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

def run_monthly_projection(
    stock_start=30000.0,
    stock_inflow_early=20000.0, # M1-M4
    stock_inflow_late=50000.0,  # M5-M48
    stock_annual_cagr=0.26,     # 26% net CAGR (empirical 10y backtest baseline)
    
    crypto_start=3000.0,
    crypto_inflow_early=3000.0, # M1-M4
    crypto_inflow_late=6000.0,  # M5-M48
    crypto_annual_cagr=0.28,    # 28% net CAGR (5y backtest multi-week swing baseline)
    
    months=48
):
    stock_monthly_r = (1.0 + stock_annual_cagr) ** (1.0 / 12.0) - 1.0
    crypto_monthly_r = (1.0 + crypto_annual_cagr) ** (1.0 / 12.0) - 1.0
    
    stock_balance = stock_start
    stock_injected = stock_start
    
    crypto_balance = crypto_start
    crypto_injected = crypto_start
    
    records = []
    
    for m in range(1, months + 1):
        # Determine inflows
        s_in = stock_inflow_early if m <= 4 else stock_inflow_late
        c_in = crypto_inflow_early if m <= 4 else crypto_inflow_late
        
        # Add inflow at start of month
        stock_balance += s_in
        stock_injected += s_in
        
        crypto_balance += c_in
        crypto_injected += c_in
        
        # Compound for the month
        stock_balance *= (1.0 + stock_monthly_r)
        crypto_balance *= (1.0 + crypto_monthly_r)
        
        stock_profit = stock_balance - stock_injected
        crypto_profit = crypto_balance - crypto_injected
        
        total_balance = stock_balance + crypto_balance
        total_injected = stock_injected + crypto_injected
        total_profit = total_balance - total_injected
        
        records.append({
            'month': m,
            'year': (m - 1) // 12 + 1,
            'stock_injected': stock_injected,
            'stock_balance': stock_balance,
            'stock_profit': stock_profit,
            'crypto_injected': crypto_injected,
            'crypto_balance': crypto_balance,
            'crypto_profit': crypto_profit,
            'total_injected': total_injected,
            'total_balance': total_balance,
            'total_profit': total_profit
        })
        
    return pd.DataFrame(records)

df = run_monthly_projection()

print("="*90)
print("DUAL-ENGINE COMPOUNDING PROJECTION (STOCKS + CRYPTO SATELLITE)")
print("Core Stocks: Rs 30k start | Rs 20k/mo (M1-4) -> Rs 50k/mo (M5-48) @ 26% CAGR")
print("Crypto Sat:  Rs 3k start  | Rs 3k/mo (M1-4)  -> Rs 6k/mo (M5-48)  @ 28% CAGR")
print("="*90)

for yr in range(1, 5):
    m_end = yr * 12
    row = df[df['month'] == m_end].iloc[0]
    print(f"\n>> END OF YEAR {yr} (Month {m_end}):")
    print(f"   -------------------------------------------------------------------------")
    print(f"   [1. CORE NSE EQUITIES (90%)]: ")
    print(f"       Raw Capital Injected: Rs {row['stock_injected']:10,.0f} ({row['stock_injected']/100000:4.2f} Lakhs)")
    print(f"       Account Balance:      Rs {row['stock_balance']:10,.0f} ({row['stock_balance']/100000:4.2f} Lakhs)")
    print(f"       Pure Stock Profit:    Rs {row['stock_profit']:+10,.0f} ({row['stock_profit']/100000:+4.2f} Lakhs)")
    print(f"   [2. CRYPTO ALPHA SATELLITE (10%)]: ")
    print(f"       Raw Capital Injected: Rs {row['crypto_injected']:10,.0f} ({row['crypto_injected']/100000:4.2f} Lakhs)")
    print(f"       Account Balance:      Rs {row['crypto_balance']:10,.0f} ({row['crypto_balance']/100000:4.2f} Lakhs)")
    print(f"       Pure Crypto Profit:   Rs {row['crypto_profit']:+10,.0f} ({row['crypto_profit']/100000:+4.2f} Lakhs)")
    print(f"   -------------------------------------------------------------------------")
    print(f"   [TOTAL COMBINED WEALTH]:")
    print(f"       Total Cash Injected:  Rs {row['total_injected']:10,.0f} ({row['total_injected']/100000:4.2f} Lakhs)")
    print(f"       TOTAL PORTFOLIO NET:  Rs {row['total_balance']:10,.0f} ({row['total_balance']/100000:4.2f} Lakhs)")
    print(f"       TOTAL PURE PROFIT:    Rs {row['total_profit']:+10,.0f} ({row['total_profit']/100000:+4.2f} Lakhs)")

# Also print monthly progression for Year 1 specifically
print("\n" + "="*90)
print("DETAILED MONTH-BY-MONTH PROGRESSION FOR YEAR 1:")
print("="*90)
print(f"{'Month':5s} | {'Stock Bal':12s} | {'Stock P&L':10s} | {'Crypto Bal':12s} | {'Crypto P&L':10s} | {'Total Net':12s}")
print("-"*90)
for m in range(1, 13):
    r = df[df['month'] == m].iloc[0]
    print(f"M{m:02d}   | Rs {r['stock_balance']:9,.0f} | Rs {r['stock_profit']:+7,.0f} | Rs {r['crypto_balance']:9,.0f} | Rs {r['crypto_profit']:+7,.0f} | Rs {r['total_balance']:9,.0f}")
print("="*90)
