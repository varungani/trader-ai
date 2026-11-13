"""
Simulate Combined Multi-Asset Barbell Compounding:
1. Indian Equities: Rs 30,000 initial + Rs 11,000/mo inflow @ 45% CAGR (conservative from 51.6% audited)
2. US Equities: $104 initial (Rs 9,000) + $104/mo inflow (Rs 9,000) @ 38.4% CAGR (audited 10y)
3. Crypto Satellite: Rs 3,000 initial + Rs 3,000 in Feb @ 65% CAGR (conservative from 127%-154% cycle run)

Compare against traditional benchmarks:
- Bank FD (7%)
- Nifty Index Mutual Fund (13%)
"""
import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Monthly rates
r_in = (1.0 + 0.45) ** (1.0 / 12.0) - 1.0
r_us = (1.0 + 0.384) ** (1.0 / 12.0) - 1.0
r_cr = (1.0 + 0.65) ** (1.0 / 12.0) - 1.0
r_mf = (1.0 + 0.13) ** (1.0 / 12.0) - 1.0
r_fd = (1.0 + 0.07) ** (1.0 / 12.0) - 1.0

# Capital tracking
bal_in = 30000.0
bal_us = 9000.0  # $104
bal_cr = 3000.0
bal_mf = 42000.0
bal_fd = 42000.0

total_deposited = 42000.0
monthly_records = []

for m in range(1, 121):  # 120 months = 10 years
    # Inflows
    inflow_in = 11000.0
    inflow_us = 9000.0
    inflow_cr = 3000.0 if m == 4 else 0.0  # Feb scaling
    total_inflow = inflow_in + inflow_us + inflow_cr
    total_deposited += total_inflow
    
    # Growth
    bal_in = (bal_in + inflow_in) * (1.0 + r_in)
    bal_us = (bal_us + inflow_us) * (1.0 + r_us)
    bal_cr = (bal_cr + inflow_cr) * (1.0 + r_cr)
    
    bal_mf = (bal_mf + total_inflow) * (1.0 + r_mf)
    bal_fd = (bal_fd + total_inflow) * (1.0 + r_fd)
    
    tot_trader_ai = bal_in + bal_us + bal_cr
    tot_profit = tot_trader_ai - total_deposited
    monthly_profit = tot_trader_ai - (tot_trader_ai / (1.0 + ((bal_in*r_in + bal_us*r_us + bal_cr*r_cr)/tot_trader_ai)))
    
    if m in [1, 3, 6, 12, 24, 36, 60, 120]:
        monthly_records.append({
            "month": m,
            "year": m // 12 if m % 12 == 0 else m / 12.0,
            "deposited": total_deposited,
            "indian": bal_in,
            "us": bal_us,
            "crypto": bal_cr,
            "total": tot_trader_ai,
            "profit": tot_profit,
            "monthly_run_rate": bal_in * r_in + bal_us * r_us + bal_cr * r_cr,
            "mf_balance": bal_mf,
            "fd_balance": bal_fd,
        })

print(f"{'Milestone':<10} | {'Total Deposited':<15} | {'TraderAI Total':<16} | {'Net Profit':<14} | {'Monthly Earnings':<16} | {'Index MF':<14} | {'Bank FD':<12}")
print("-" * 105)
for r in monthly_records:
    lbl = f"Month {r['month']}" if r['month'] < 12 else f"Year {int(r['year'])}"
    print(f"{lbl:<10} | Rs {r['deposited']:>11,.0f} | Rs {r['total']:>12,.0f} | +Rs {r['profit']:>10,.0f} | Rs {r['monthly_run_rate']:>12,.0f}/mo | Rs {r['mf_balance']:>10,.0f} | Rs {r['fd_balance']:>8,.0f}")
