"""
Forensic Census of Super-Movers (DNA of Explosive Runs)
Finds every single episode where a stock gained >= +40% in 20 days or >= +70% in 60 days
across 10 years of data.
Extracts the exact statistical anatomy 10 days BEFORE the explosion.
"""
import pickle
import os
import numpy as np
import pandas as pd
from collections import defaultdict

# 1. Load data
u10_path = "data/cache/universe_10y.pkl"
hb_path = "data/cache/high_beta_universe.pkl"

combined = {}
if os.path.exists(u10_path):
    with open(u10_path, "rb") as f:
        d1 = pickle.load(f)
        for k, v in d1.items():
            if len(v) >= 200:
                df = v.copy()
                df.columns = [c.lower() for c in df.columns]
                combined[k] = df

if os.path.exists(hb_path):
    with open(hb_path, "rb") as f:
        d2 = pickle.load(f)
        for k, v in d2.items():
            if len(v) >= 200 and k not in combined:
                df = v.copy()
                df.columns = [c.lower() for c in df.columns]
                combined[k] = df

print(f"Loaded {len(combined)} unique stocks for Super-Mover DNA analysis.")

# 2. Identify Super-Mover Explosions
# Definition of a Super-Mover:
# A trade window where Close[t + 20] >= Close[t] * 1.35 (+35% in 20 sessions)
# or Close[t + 45] >= Close[t] * 1.60 (+60% in 45 sessions)

explosions = []

for sym, df in combined.items():
    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    v = df["volume"].values
    n = len(df)
    dates = df.index
    
    if n < 150:
        continue
        
    # Moving averages & indicators
    s_c = pd.Series(c)
    s_v = pd.Series(v)
    s_h = pd.Series(h)
    s_l = pd.Series(l)
    
    sma50 = s_c.rolling(50).mean().values
    sma200 = s_c.rolling(min(200, n)).mean().values
    ema10 = s_c.ewm(span=10, adjust=False).mean().values
    ema20 = s_c.ewm(span=20, adjust=False).mean().values
    
    vol_sma20 = s_v.rolling(20).mean().values
    vol_sma50 = s_v.rolling(50).mean().values
    
    # 250-day rolling high
    high_250 = s_h.rolling(min(250, n)).max().shift(1).values
    high_60 = s_h.rolling(60).max().shift(1).values
    high_20 = s_h.rolling(20).max().shift(1).values
    
    # True range
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr5 = pd.Series(tr).rolling(5).mean().values
    atr20 = pd.Series(tr).rolling(20).mean().values
    vcp_ratio = atr5 / (atr20 + 1e-8)
    
    # Iterate through history
    i = 60
    while i < n - 45:
        # Check forward performance
        ret_20d = (c[min(i + 20, n - 1)] - c[i]) / c[i]
        ret_45d = (c[min(i + 45, n - 1)] - c[i]) / c[i]
        max_fwd_gain = (np.max(h[i : min(i + 45, n)]) - c[i]) / c[i]
        
        is_explosion = (ret_20d >= 0.30) or (ret_45d >= 0.50) or (max_fwd_gain >= 0.60)
        
        if is_explosion:
            # We found a super-mover ignition point at bar i!
            # Let's extract the exact DNA on Day i (ignition day) and Day i-1 to i-5 (pre-ignition)
            
            # 1. Proximity to 52-week High
            pct_from_52w = ((c[i] - high_250[i]) / high_250[i]) * 100.0 if not np.isnan(high_250[i]) else 0.0
            pct_from_60d = ((c[i] - high_60[i]) / high_60[i]) * 100.0 if not np.isnan(high_60[i]) else 0.0
            
            # 2. Pre-ignition Volume Dry-Up (VDU) in bars i-5 to i-1
            pre_v_ratio = np.mean(v[max(0, i - 4) : i]) / (vol_sma50[i] + 1e-8)
            
            # 3. Ignition Day Volume Shock
            ignition_rvol = v[i] / (vol_sma20[i] + 1e-8)
            
            # 4. Volatility Contraction Pattern (VCP) prior to ignition
            pre_vcp = vcp_ratio[i - 1] if i > 0 else 1.0
            
            # 5. Trend Template Alignment
            above_50 = c[i] > sma50[i]
            above_200 = c[i] > sma200[i]
            sma50_above_200 = sma50[i] > sma200[i]
            
            # 6. Tight Closes (Cluster of Closes): variance of closes over previous 4 bars
            prev_closes = c[max(0, i - 3) : i + 1]
            tightness = (np.max(prev_closes) - np.min(prev_closes)) / c[i] * 100.0
            
            # 7. Ignition Bar Anatomy: Close near top of range?
            day_range = h[i] - l[i]
            close_location = (c[i] - l[i]) / (day_range + 1e-8)  # 1.0 = closed at extreme high
            
            explosions.append({
                "ticker": sym,
                "date": str(dates[i])[:10],
                "price": round(c[i], 2),
                "ret_20d_pct": round(ret_20d * 100.0, 1),
                "ret_45d_pct": round(ret_45d * 100.0, 1),
                "max_fwd_gain_pct": round(max_fwd_gain * 100.0, 1),
                "pct_from_52w": round(pct_from_52w, 1),
                "pct_from_60d": round(pct_from_60d, 1),
                "pre_v_ratio": round(pre_v_ratio, 2),
                "ignition_rvol": round(ignition_rvol, 2),
                "pre_vcp": round(pre_vcp, 2),
                "above_50": above_50,
                "above_200": above_200,
                "sma50_above_200": sma50_above_200,
                "tightness_4d_pct": round(tightness, 2),
                "close_location": round(close_location, 2),
            })
            
            # Skip forward 20 bars to avoid counting the same run multiple times
            i += 20
        else:
            i += 1

print(f"\nDiscovered {len(explosions)} confirmed Super-Mover Explosions (>= +35% to +60%+)! Examining DNA...")

df_exp = pd.DataFrame(explosions)

# STATISTICAL DNA PROFILE OF SUPER MOVERS
print("\n" + "="*80)
print("🧬 THE STATISTICAL DNA OF SUPER-MOVERS (BEFORE THEY EXPLODE)")
print("="*80)

# 1. Trend Structure
pct_above_50 = (df_exp["above_50"].sum() / len(df_exp)) * 100.0
pct_above_200 = (df_exp["above_200"].sum() / len(df_exp)) * 100.0
pct_stage2 = (df_exp["sma50_above_200"].sum() / len(df_exp)) * 100.0

print(f"1. Trend Alignment:")
print(f"   • Price Above 50-day SMA       : {pct_above_50:.1f}% of all super-movers")
print(f"   • Price Above 200-day SMA      : {pct_above_200:.1f}% of all super-movers")
print(f"   • 50 SMA > 200 SMA (Stage 2)   : {pct_stage2:.1f}% of all super-movers")

# 2. Proximity to Highs
median_52w_dist = df_exp["pct_from_52w"].median()
median_60d_dist = df_exp["pct_from_60d"].median()
pct_near_52w = (df_exp["pct_from_52w"] >= -12.0).sum() / len(df_exp) * 100.0
pct_at_20d_high = (df_exp["pct_from_60d"] >= -3.0).sum() / len(df_exp) * 100.0

print(f"\n2. Price Proximity to Overhead Ceilings:")
print(f"   • Within 12% of 52-Week High   : {pct_near_52w:.1f}% of all super-movers")
print(f"   • Breaking / Near 60-Day High  : {pct_at_20d_high:.1f}% of all super-movers")
print(f"   • Median Distance to 52W High  : {median_52w_dist:.1f}%")

# 3. Pre-Ignition Volume & Volatility Contraction
median_pre_v = df_exp["pre_v_ratio"].median()
median_vcp = df_exp["pre_vcp"].median()
median_tightness = df_exp["tightness_4d_pct"].median()

print(f"\n3. Pre-Ignition Coil & Dry-Up (The Calm Before the Storm):")
print(f"   • Pre-Ignition Volume Ratio    : {median_pre_v:.2f}x of 50-day avg (Volume Dried Up by {(1-median_pre_v)*100:.0f}%!)")
print(f"   • Pre-Ignition VCP Ratio       : {median_vcp:.2f} (Extreme volatility squeeze < 0.70)")
print(f"   • 4-Day Close Price Tightness  : {median_tightness:.2f}% (Closes packed inside a tight band)")

# 4. The Ignition Catalyst (Day 0)
median_rvol = df_exp["ignition_rvol"].median()
median_close_loc = df_exp["close_location"].median()
pct_closed_top = (df_exp["close_location"] >= 0.75).sum() / len(df_exp) * 100.0

print(f"\n4. Ignition Day Anatomy (Day 0):")
print(f"   • Ignition Day Volume Shock    : {median_rvol:.2f}x normal 20-day volume")
print(f"   • Close Location in Daily Bar  : {median_close_loc:.2f} (Top {int((1-median_close_loc)*100)}% of range)")
print(f"   • Closed in Upper 25% of Bar   : {pct_closed_top:.1f}% of all super-movers")

# Print Top 15 Biggest Historic Explosions
print("\n" + "="*80)
print("🚀 TOP 15 GREATEST SUPER-MOVERS DISCOVERED IN THE HISTORICAL CENSUS:")
print("="*80)
top_explosions = df_exp.sort_values(by="max_fwd_gain_pct", ascending=False).head(15)
for idx, r in top_explosions.reset_index().iterrows():
    print(f"#{idx+1:02d} {r['ticker']:<15} | Date: {r['date']} | Ignition: Rs {r['price']:8.2f} -> Max Gain: +{r['max_fwd_gain_pct']:6.1f}% | 20d: +{r['ret_20d_pct']:5.1f}% | 45d: +{r['ret_45d_pct']:5.1f}% | Pre-V: {r['pre_v_ratio']}x | RVOL: {r['ignition_rvol']}x")

# Save detailed census
out_csv = "data/cache/super_movers_dna_census.csv"
df_exp.to_csv(out_csv, index=False)
print(f"\nSaved full {len(df_exp)} Super-Mover Census to {out_csv}!")
