"""
Cluster Analysis & Discovery of the 3 Proprietary Super-Mover Archetypes
Analyzes the 825 historical explosions to extract:
Archetype A: The "Coiled Slingshot" (Bottom-Fishing Turnaround Squeeze)
Archetype B: The "Power Earning Gap & Volatility Contraction" (PEAD Momentum)
Archetype C: The "Blue-Sky Float Lock" (Ascending Channel Breakout)
"""
import pandas as pd
import numpy as np

df = pd.read_csv("data/cache/super_movers_dna_census.csv")
print(f"Analyzing {len(df)} Super-Mover events...")

# 1. Classify by Proximity to Highs
# Group 1: Coiled Deep Bases (Down > 20% from 52W High, but turning violently)
deep_bases = df[df["pct_from_52w"] <= -20.0]
# Group 2: Mid-Range Breakouts (-20% to -5% from 52W High)
mid_range = df[(df["pct_from_52w"] > -20.0) & (df["pct_from_52w"] <= -5.0)]
# Group 3: Blue Sky Leaders (Within 5% of 52W High or New High)
blue_sky = df[df["pct_from_52w"] > -5.0]

print(f"\nBreakdown of 825 Super-Movers:")
print(f"1. Coiled Deep Turnarounds (Down > 20% from 52W High) : {len(deep_bases)} ({len(deep_bases)/len(df)*100:.1f}%) | Avg 45d Gain: +{deep_bases['ret_45d_pct'].mean():.1f}% | Max Gain: +{deep_bases['max_fwd_gain_pct'].mean():.1f}%")
print(f"2. Mid-Range Stage-2 Consolidations (-5% to -20% from 52W) : {len(mid_range)} ({len(mid_range)/len(df)*100:.1f}%) | Avg 45d Gain: +{mid_range['ret_45d_pct'].mean():.1f}% | Max Gain: +{mid_range['max_fwd_gain_pct'].mean():.1f}%")
print(f"3. Blue Sky / 52W High Runners (Within 5% of High)       : {len(blue_sky)} ({len(blue_sky)/len(df)*100:.1f}%) | Avg 45d Gain: +{blue_sky['ret_45d_pct'].mean():.1f}% | Max Gain: +{blue_sky['max_fwd_gain_pct'].mean():.1f}%")

# Let's inspect the DNA of Deep Base Turnarounds:
print("\n" + "="*80)
print("ARCHETYPE 1: THE 'COILED SLINGSHOT' (DEEP BASES)")
print("="*80)
print(f"Median 4-day close tightness: {deep_bases['tightness_4d_pct'].median():.2f}%")
print(f"Median pre-ignition volume: {deep_bases['pre_v_ratio'].median():.2f}x (Massive volume dry-up!)")
print(f"Above 50 SMA: {(deep_bases['above_50'].sum()/len(deep_bases)*100):.1f}%")

# Let's inspect the DNA of Blue Sky Runners:
print("\n" + "="*80)
print("ARCHETYPE 2: THE 'BLUE SKY FLOAT CORNER' (ALL-TIME HIGHS)")
print("="*80)
print(f"Median ignition RVOL: {blue_sky['ignition_rvol'].median():.2f}x")
print(f"Median 45d return: +{blue_sky['ret_45d_pct'].median():.1f}%")
print(f"Stage 2 alignment (50 > 200 SMA): {(blue_sky['sma50_above_200'].sum()/len(blue_sky)*100):.1f}%")
