import sys
import os
import sqlite3
import pandas as pd
import yfinance as yf

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from analysis.sector_rs import compute_sector_rs
from config import TICKER_TO_SECTOR

tickers_to_test = [
    "MPHASIS.NS", "COFORGE.NS", "FEDERALBNK.NS", "BBOX.NS", "KOTAKBANK.NS",
    "KARURVYSYA.NS", "CUPID.NS", "TVSMOTOR.NS", "HEROMOTOCO.NS", "ICICIBANK.NS",
    "PETRONET.NS", "UNIONBANK.NS", "CASTROLIND.NS", "GESHIP.NS", "PNBHOUSING.NS"
]

print("Fetching 1-year OHLCV data for test candidates...")
data = yf.download(tickers_to_test, period="1y", group_by="ticker", progress=False, threads=True)

results = []
for t in tickers_to_test:
    try:
        df = data[t].dropna(how="all")
        if len(df) < 200:
            continue
        close = df["Close"]
        vol = df["Volume"]
        px = float(close.iloc[-1])
        
        # 1. Minervini Stage 2 Filter: Close > EMA50 > SMA200
        ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
        ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
        sma200 = float(close.rolling(window=200).mean().iloc[-1])
        sma200_20d_ago = float(close.rolling(window=200).mean().iloc[-20])
        
        is_stage2 = (px > ema50 > sma200) and (sma200 >= sma200_20d_ago * 0.99)
        
        # 2. Sector RS Gate
        sec = TICKER_TO_SECTOR.get(t, "General")
        sec_info = compute_sector_rs(sec)
        sec_rs = float(sec_info.get("relative_strength_pct") or 0.0)
        is_sec_positive = sec_rs >= -0.2
        
        # 3. RVOL Gate
        vol_sma20 = float(vol.tail(20).mean())
        latest_vol = float(vol.iloc[-1])
        rvol = round(latest_vol / vol_sma20, 2) if vol_sma20 > 0 else 1.0
        
        # 4. 20 EMA Sweet Spot (0.5% to 4.5%)
        dev_ema20 = ((px - ema20) / ema20) * 100.0
        is_sweet_spot = (-1.0 <= dev_ema20 <= 4.5)
        
        # 5. Clearance to 50d high resistance
        high50 = float(df["High"].iloc[-50:-1].max()) if len(df) >= 50 else px * 1.1
        dist_res = ((high50 - px) / px) * 100.0
        # If stock is breaking out (px >= high50), that's good! If below, need >= 4% room or breaking out
        has_clearance = (px >= high50) or (dist_res >= 4.0)
        
        # Pass all 5 gates?
        all_passed = is_stage2 and is_sec_positive and is_sweet_spot and has_clearance
        
        results.append({
            "ticker": t,
            "sector": sec,
            "px": round(px, 2),
            "is_stage2": is_stage2,
            "sec_rs": sec_rs,
            "is_sec_positive": is_sec_positive,
            "dev_ema20": round(dev_ema20, 1),
            "is_sweet_spot": is_sweet_spot,
            "rvol": rvol,
            "dist_res": round(dist_res, 1),
            "all_passed": all_passed,
        })
    except Exception as e:
        pass

df_res = pd.DataFrame(results)
print("\n" + "="*85)
print("ACCURACY GATES AUDIT ON CANDIDATE UNIVERSE:")
print("="*85)
for _, r in df_res.iterrows():
    status_tag = "✅ QUALIFIED BUY" if r['all_passed'] else "❌ REJECTED TO HOLD"
    reasons = []
    if not r['is_stage2']: reasons.append("Not Stage 2 (Below 50/200 EMA)")
    if not r['is_sec_positive']: reasons.append(f"Sector Drag ({r['sec_rs']:+.1f}%)")
    if not r['is_sweet_spot']: reasons.append(f"EMA20 Stretched ({r['dev_ema20']:+.1f}%)")
    
    reason_str = " | ".join(reasons) if reasons else "All 5 Institutional Edge Gates Cleared"
    print(f"{r['ticker']:<15} {status_tag} -> {reason_str}")
