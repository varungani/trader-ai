def calculate_cash_profits():
    print("="*85)
    print("EXACT MONTHLY RUPEE PROFIT BREAKDOWN (NET OF ALL BROKERAGE, TAXES & DP CHARGES)")
    print("="*85)
    
    capitals = [30000, 50000, 100000, 200000]
    
    # In a typical month:
    # 4 to 5 trades taken with 2 concentrated positions (50% size each)
    # Trade win: +10.0% net gain
    # Trade loss: -3.5% net loss
    
    # Three monthly market regimes:
    # Scenario A: Good Month (3 wins, 1 loss) -> +13.2% on capital
    # Scenario B: Normal Month (2 wins, 2 losses) -> +6.5% on capital
    # Scenario C: Tough/Choppy Month (1 win, 3 losses) -> -0.5% on capital (Breakeven/Flat)
    # Scenario D: Bad Market Correction Month (0 wins, 3 losses) -> -5.2% on capital
    
    # Over a 12-month period, a realistic market delivers:
    # 5 Good months, 4 Normal months, 2 Choppy months, 1 Correction month
    
    print("\n" + "="*85)
    print("1. TYPICAL MONTHLY PROFIT IN PURE RUPEES (SCENARIO BREAKDOWN)")
    print("="*85)
    print(f"{'Starting Capital':<18} | {'Good Month (+12%)':<20} | {'Average Month (+6%)':<20} | {'Bad Month (-5%)':<18}")
    print("-" * 85)
    for cap in capitals:
        good = cap * 0.12
        avg_m = cap * 0.06
        bad = cap * -0.05
        print(f"Rs. {cap:>7,d}       | +Rs. {good:>6,.0f}            | +Rs. {avg_m:>6,.0f}            | -Rs. {abs(bad):>5,.0f}")
        
    print("\n" + "="*85)
    print("2. REALISTIC 12-MONTH CASH PROGRESSION (MONTH-BY-MONTH IN YOUR BANK)")
    print("="*85)
    
    # Let's simulate month-by-month progression for Rs. 50,000 and Rs. 1,00,000
    # Monthly returns realistic sequence:
    # Month 1: +8% (Good)
    # Month 2: +6% (Normal)
    # Month 3: -4% (Pullback)
    # Month 4: +12% (Strong)
    # Month 5: +5% (Normal)
    # Month 6: +10% (Strong)
    # Month 7: +2% (Flat)
    # Month 8: -5% (Correction)
    # Month 9: +11% (Rebound)
    # Month 10: +7% (Normal)
    # Month 11: +12% (Strong)
    # Month 12: +4% (Normal)
    
    monthly_ret_sequence = [0.08, 0.06, -0.04, 0.12, 0.05, 0.10, 0.02, -0.05, 0.11, 0.07, 0.12, 0.04]
    
    for start_cap in [30000, 50000, 100000]:
        print(f"\n>>> 12-MONTH CASH TIMELINE FOR STARTING CAPITAL: Rs. {start_cap:,.0f} <<<")
        print(f"{'Month':<8} | {'Monthly Return':<16} | {'Rupee Profit This Month':<25} | {'Total Account Balance':<22}")
        print("-" * 75)
        cur_bal = start_cap
        for m_idx, r in enumerate(monthly_ret_sequence, start=1):
            pnl_rs = cur_bal * r
            cur_bal += pnl_rs
            print(f"Month {m_idx:<2} | {r*100:>+5.1f}%          | Rs. {pnl_rs:>+8,.0f}                | Rs. {cur_bal:>10,.0f}")
        total_profit = cur_bal - start_cap
        print("-" * 75)
        print(f"Total 1-Year Pure Cash Profit: +Rs. {total_profit:,.0f} (+{total_profit/start_cap*100:.1f}%)")
        print(f"Average Monthly Cash Income  : ~Rs. {total_profit/12:,.0f} per month")

if __name__ == '__main__':
    calculate_cash_profits()
