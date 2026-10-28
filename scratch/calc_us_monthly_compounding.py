"""
Calculate 1-10 Year Compounding Projection for US Equities:
Monthly Inflow: $104 USD (approx Rs 9,000 / month)
Scenarios:
1. Conservative Swing: 22% CAGR (S&P outperformance)
2. Realistic Tested: 31.8% CAGR (10 EMA Trail)
3. Optimized Bullet: 38.4% CAGR (15 EMA Wide Runner)
"""
import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

monthly_inflow = 104.0
usd_inr = 86.50

def project(cagr, years=10):
    monthly_rate = (1.0 + cagr) ** (1.0 / 12.0) - 1.0
    balance = 0.0
    history = []
    total_deposited = 0.0
    
    for yr in range(1, years + 1):
        for m in range(12):
            balance += monthly_inflow
            total_deposited += monthly_inflow
            balance *= (1.0 + monthly_rate)
        history.append({
            "year": yr,
            "deposited_usd": total_deposited,
            "deposited_inr": total_deposited * usd_inr,
            "balance_usd": balance,
            "balance_inr": balance * usd_inr,
            "profit_usd": balance - total_deposited,
            "profit_inr": (balance - total_deposited) * usd_inr,
        })
    return history

print("--- $104/MONTH US SWING COMPOUNDING PROJECTION ---")
scenarios = [
    ("Conservative (22% CAGR)", 0.22),
    ("Tested 10 EMA (31.8% CAGR)", 0.318),
    ("Optimized Bullet (38.4% CAGR)", 0.384)
]

for label, cagr in scenarios:
    h = project(cagr)
    print(f"\n>>> {label}:")
    for row in [h[0], h[2], h[4], h[9]]:  # Year 1, 3, 5, 10
        print(f"  Year {row['year']:>2}: Deposited ${row['deposited_usd']:>6,.0f} (Rs {row['deposited_inr']:>9,.0f}) | Portfolio: ${row['balance_usd']:>8,.0f} (Rs {row['balance_inr']:>11,.0f}) | Net Profit: +${row['profit_usd']:>8,.0f} (+Rs {row['profit_inr']:>11,.0f})")
