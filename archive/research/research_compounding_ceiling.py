import numpy as np
import pandas as pd

def analyze_compounding_mechanics():
    print("="*85)
    print("THE MATHEMATICS OF COMPOUNDING VELOCITY: WHY IT STALLS AT 68% AND HOW IT SKYROCKETS")
    print("="*85)
    
    # Let's analyze the exact formula for annual portfolio compounding:
    # Annual Return = (1 + Net Portfolio EV per Cycle) ^ (Cycles per Year) - 1.0
    
    # Case 1: Varying Cycles per Year (Holding Duration / Capital Turn Speed)
    # Assume a solid net portfolio edge of +4.0% per trade (e.g. 50% position making +8%)
    ev_portfolio = 0.04 # +4.0% net gain on total account per trade
    
    cycles_scenarios = [
        ("Slow / Infrequent", 10, "Takes 24 days per cycle (only 10 trades/year)"),
        ("Moderate Swing", 12, "Takes 20 days per cycle (approx 1 per month)"),
        ("Active Short-Term", 20, "Takes 12 days per cycle (1.6 per month)"),
        ("High-Velocity Quant", 30, "Takes 8 days per cycle (2.5 per month)"),
        ("Elite Velocity Sniper", 45, "Takes 5 days per cycle (almost 1 per week)"),
        ("Maximum Theoretical", 60, "Takes 4 days per cycle (continuous turnover)")
    ]
    
    print("\n--- TABLE 1: HOW CAPITAL TURNOVER EXPLODES COMPOUNDING (+4% Edge/Trade) ---")
    print(f"{'Trading Frequency':<25} | {'Cycles/Year':<12} | {'Annual Compounded Return':<25} | {'Rs. 1 Lakh Becomes':<20}")
    print("-" * 90)
    for name, cycles, desc in cycles_scenarios:
        ann_ret = ((1 + ev_portfolio) ** cycles - 1.0) * 100
        ending_val = 100000 * (1 + ann_ret / 100)
        print(f"{name:<25} | {cycles:<12} | +{ann_ret:>7.1f}%                   | Rs. {ending_val:>11,.0f}")
        
    print("\nObservation on Table 1:")
    print("  -> At 10-12 cycles, +4% edge produces only +48% to +60% (exactly what you noticed!).")
    print("  -> At 30 cycles, +4% edge explodes into +224% (3.2x your money!).")
    print("  -> At 45 cycles, +4% edge SKYROCKETS into +483% (almost 6x your money in 1 year!).")
    
    # Case 2: What determines Net Portfolio Edge per Trade?
    # EV_portfolio = Position_Size * [ (Win_Rate * Avg_Win) - (Loss_Rate * Avg_Loss) ]
    print("\n" + "="*85)
    print("TABLE 2: THE 3 LEVERS THAT DETERMINE NET EDGE PER TRADE")
    print("="*85)
    
    # Let's test combinations:
    # Win Rate: 45%, 55%, 65%
    # Avg Win: +6%, +10%, +15%
    # Avg Loss: -3%, -4%
    # Position Size: 33% (3 stocks), 50% (2 stocks), 100% (1 concentrated stock)
    
    scenarios = [
        # (Name, WinRate, AvgWin, AvgLoss, PosSize, Cycles)
        ("Retail Churn (Tiny Win, Small Size)", 0.45, 5.0, 3.5, 0.20, 25),
        ("Standard Swing (Fixed +8%, -4% Stop)", 0.50, 7.5, 4.0, 0.33, 20),
        ("User Observed Baseline", 0.52, 8.5, 4.2, 0.33, 16),
        ("High-Asymmetry Cheetah (Concentrated 50%)", 0.50, 12.0, 3.5, 0.50, 25),
        ("Institutional Momentum Thrust (A+ Setups)", 0.58, 14.0, 3.2, 0.50, 30),
        ("Elite Sniper Engine (1-2 Stocks, Full Thrust)", 0.60, 15.0, 3.0, 0.65, 35)
    ]
    
    print(f"{'Strategy Architecture':<38} | {'Win%':<6} | {'Win/Loss':<8} | {'PosSize':<7} | {'Trade EV':<9} | {'Port EV':<8} | {'Cycles':<6} | {'Annual Compounded':<16}")
    print("-" * 115)
    for name, wr, aw, al, ps, cyc in scenarios:
        trade_ev = (wr * aw) - ((1 - wr) * al)
        port_ev = trade_ev * ps
        ann_comp = ((1 + port_ev / 100) ** cyc - 1.0) * 100
        print(f"{name:<38} | {wr*100:<5.0f}% | +{aw:.0f}/-{al:.1f}% | {ps*100:<6.0f}% | +{trade_ev:>5.2f}%   | +{port_ev:>5.2f}%  | {cyc:<6} | +{ann_comp:>7.1f}%")
        
if __name__ == '__main__':
    analyze_compounding_mechanics()
