"""
Simulation for New Budget:
Monthly Inflows:
- Indian Equities: Rs 10,000 / month
- US Equities: Rs 10,000 / month ($115.60 / month)
- Crypto Satellite: Rs 3,000 / month
Total Monthly Inflow: Rs 23,000 / month (Rs 2.76 Lakhs/year)

Starting Seeds:
Option A: Rs 30,000 Indian + Rs 10,000 US ($116) + Rs 3,000 Crypto = Rs 43,000 Initial
Option B: Rs 10,000 Indian + Rs 10,000 US ($116) + Rs 3,000 Crypto = Rs 23,000 Initial

Growth rates (Audited 10y):
- Indian: 45.0% CAGR (Option 1B conservative)
- US: 38.4% CAGR (15 EMA wide runner)
- Crypto: 65.0% CAGR (Multi-week swing runner)
Benchmarks:
- Index Mutual Fund: 13.0% CAGR
- Bank FD: 7.0% CAGR
"""
import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

r_in = (1.0 + 0.45) ** (1.0 / 12.0) - 1.0
r_us = (1.0 + 0.384) ** (1.0 / 12.0) - 1.0
r_cr = (1.0 + 0.65) ** (1.0 / 12.0) - 1.0
r_mf = (1.0 + 0.13) ** (1.0 / 12.0) - 1.0
r_fd = (1.0 + 0.07) ** (1.0 / 12.0) - 1.0

usd_inr = 86.50

def run_sim(init_in, init_us, init_cr):
    bal_in = init_in
    bal_us = init_us
    bal_cr = init_cr
    total_init = init_in + init_us + init_cr
    bal_mf = total_init
    bal_fd = total_init
    
    total_deposited = total_init
    records = []
    
    for m in range(1, 121):
        inflow_in = 10000.0
        inflow_us = 10000.0
        inflow_cr = 3000.0
        tot_inflow = inflow_in + inflow_us + inflow_cr
        total_deposited += tot_inflow
        
        bal_in = (bal_in + inflow_in) * (1.0 + r_in)
        bal_us = (bal_us + inflow_us) * (1.0 + r_us)
        bal_cr = (bal_cr + inflow_cr) * (1.0 + r_cr)
        
        bal_mf = (bal_mf + tot_inflow) * (1.0 + r_mf)
        bal_fd = (bal_fd + tot_inflow) * (1.0 + r_fd)
        
        tot_ai = bal_in + bal_us + bal_cr
        monthly_profit_runrate = bal_in * r_in + bal_us * r_us + bal_cr * r_cr
        
        if m in [1, 3, 6, 12, 24, 36, 60, 120]:
            records.append({
                "month": m,
                "year": m / 12.0,
                "deposited": total_deposited,
                "bal_in": bal_in,
                "bal_us_inr": bal_us,
                "bal_us_usd": bal_us / usd_inr,
                "bal_cr": bal_cr,
                "total_ai": tot_ai,
                "net_profit": tot_ai - total_deposited,
                "runrate": monthly_profit_runrate,
                "mf": bal_mf,
                "fd": bal_fd
            })
    return records

print("=== NEW BUDGET: Rs 10k Indian + Rs 10k US ($116) + Rs 3k Crypto (Total Rs 23k/mo) ===")
rec_a = run_sim(30000.0, 10000.0, 3000.0)

print("\n--- RESULTS TABLE (Initial Rs 43k Seed + Rs 23k/mo Inflow) ---")
print(f"{'Milestone':<9} | {'Deposited':<13} | {'TraderAI Total':<16} | {'Net Profit':<14} | {'Monthly Earnings':<16} | {'Index MF':<12} | {'Bank FD':<12}")
print("-" * 105)
for r in rec_a:
    lbl = f"Month {r['month']}" if r['month'] < 12 else f"Year {int(r['year'])}"
    print(f"{lbl:<9} | Rs {r['deposited']:>10,.0f} | Rs {r['total_ai']:>12,.0f} | +Rs {r['net_profit']:>10,.0f} | Rs {r['runrate']:>12,.0f}/mo | Rs {r['mf']:>9,.0f} | Rs {r['fd']:>8,.0f}")

print("\n--- PILLAR-BY-PILLAR BREAKDOWN AT YEAR 1, 3, 5, 10 ---")
for r in [rec_a[3], rec_a[5], rec_a[6], rec_a[7]]:
    lbl = f"Year {int(r['year'])}"
    print(f"\n>>> {lbl} (Total Deposited: Rs {r['deposited']:,.0f} | Total Wealth: Rs {r['total_ai']:,.0f}):")
    print(f"    • Indian Equities (Core): Rs {r['bal_in']:>11,.0f} ({r['bal_in']/r['total_ai']*100:.1f}%)")
    print(f"    • US Equities (INDmoney): Rs {r['bal_us_inr']:>11,.0f} (${r['bal_us_usd']:>7,.0f}) ({r['bal_us_inr']/r['total_ai']*100:.1f}%)")
    print(f"    • Crypto Alpha (Satellite): Rs {r['bal_cr']:>9,.0f} ({r['bal_cr']/r['total_ai']*100:.1f}%)")
    print(f"    • Monthly Passive Run-Rate: Rs {r['runrate']:>11,.0f} / month")
