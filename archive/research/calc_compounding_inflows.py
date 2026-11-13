"""
Calculate exact monthly contribution compounding for:
- Stocks: Rs 30,000 start + Rs 20,000/mo (M1-4) + Rs 50,000/mo (M5-48) [Total 48 months = 4 years]
- Crypto: Rs 3,000 start + Rs 3,000/mo (M1-4) + Rs 6,000/mo (M5-48) [Total 48 months = 4 years]

We compare:
1. Passive Benchmarks (NIFTY 13% CAGR | BTC 15% CAGR)
2. TraderAI Baseline (Stocks 11.3% CAGR | Crypto 21.4% CAGR)
3. TraderAI Optimized Strategy (Stocks 13.1% to 18% with Alpha selection | Crypto 32.2% CAGR)
4. Bull Cycle Accelerated Scenario (Stocks 25% CAGR | Crypto 55% CAGR)
"""
import numpy as np

def simulate_portfolio(start_stock, stock_m1_4, stock_m5_48, stock_cagr,
                       start_crypto, crypto_m1_4, crypto_m5_48, crypto_cagr,
                       months=48):
    stock_r_mo = (1.0 + stock_cagr)**(1/12) - 1.0
    crypto_r_mo = (1.0 + crypto_cagr)**(1/12) - 1.0
    
    stock_val = start_stock
    crypto_val = start_crypto
    stock_invested = start_stock
    crypto_invested = start_crypto
    
    for m in range(1, months + 1):
        # Monthly additions
        s_add = stock_m1_4 if m <= 4 else stock_m5_48
        c_add = crypto_m1_4 if m <= 4 else crypto_m5_48
        
        stock_invested += s_add
        crypto_invested += c_add
        
        stock_val = (stock_val + s_add) * (1.0 + stock_r_mo)
        crypto_val = (crypto_val + c_add) * (1.0 + crypto_r_mo)
        
    tot_inv = stock_invested + crypto_invested
    tot_val = stock_val + crypto_val
    profit = tot_val - tot_inv
    
    return {
        'stock_inv': stock_invested,
        'stock_val': stock_val,
        'stock_prof': stock_val - stock_invested,
        'crypto_inv': crypto_invested,
        'crypto_val': crypto_val,
        'crypto_prof': crypto_val - crypto_invested,
        'total_inv': tot_inv,
        'total_val': tot_val,
        'total_prof': profit,
        'return_on_invested_pct': (profit / tot_inv) * 100.0
    }

print("="*80)
print("4-YEAR DUAL-ENGINE COMPOUNDING AUDIT (WITH MONTHLY CONTRIBUTIONS)")
print("Stocks: Rs 30k initial + Rs 20k/mo (M1-4) -> Rs 50k/mo (M5-48)")
print("Crypto: Rs 3k initial + Rs 3k/mo (M1-4) -> Rs 6k/mo (M5-48)")
print("="*80)

scenarios = [
    ("Scenario A: Passive Long-Term (NIFTY 13% CAGR | BTC 15% CAGR)", 0.13, 0.15),
    ("Scenario B: Baseline Swing (Stocks 11.3% CAGR | Crypto 21.4% CAGR)", 0.113, 0.214),
    ("Scenario C: TraderAI OPTIMIZED (Stocks 18.0% CAGR | Crypto 32.2% CAGR)", 0.18, 0.322),
    ("Scenario D: Monster Momentum Bull Run (Stocks 25.0% CAGR | Crypto 55.0% CAGR)", 0.25, 0.55),
]

for name, s_cagr, c_cagr in scenarios:
    res = simulate_portfolio(30000, 20000, 50000, s_cagr, 3000, 3000, 6000, c_cagr, months=48)
    print(f"\n{name}")
    print(f"  Total Capital Injected: Rs {res['total_inv']:10,.2f}")
    print(f"    - Stocks Injected:    Rs {res['stock_inv']:10,.2f} -> Value: Rs {res['stock_val']:10,.2f} (Net: +Rs {res['stock_prof']:10,.2f})")
    print(f"    - Crypto Injected:    Rs {res['crypto_inv']:10,.2f} -> Value: Rs {res['crypto_val']:10,.2f} (Net: +Rs {res['crypto_prof']:10,.2f})")
    print(f"  ----------------------------------------------------------------------")
    print(f"  TOTAL ACCOUNT VALUE:   Rs {res['total_val']:10,.2f} (Rs {res['total_val']/100000:.2f} Lakhs)")
    print(f"  TOTAL PURE PROFIT:     +Rs {res['total_prof']:10,.2f} (+{res['return_on_invested_pct']:.1f}% on capital)")
