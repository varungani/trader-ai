"""
Score top momentum candidates on 27 Oct close.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import yfinance as yf
import pandas as pd
import numpy as np

SYMBOLS = ["BHARTIARTL.NS", "KAYNES.NS", "BSE.NS", "TRENT.NS", "CDSL.NS", "COFORGE.NS", "DIXON.NS"]
raw = yf.download(SYMBOLS + ["^NSEI"], period="100d", interval="1d", progress=False, group_by="ticker")

nifty = raw["^NSEI"]["Close"].dropna()

print("--- 4-PILLAR QUANT SCORE FOR TODAY (27 OCT 2026) ---")
for sym in SYMBOLS:
    df = raw[sym].dropna(subset=["Close", "Volume"])
    c = df["Close"]
    v = df["Volume"]
    h = df["High"]
    
    curr_c = float(c.iloc[-1])
    ema20 = float(c.ewm(span=20, adjust=False).mean().iloc[-1])
    sma50 = float(c.rolling(50).mean().iloc[-1])
    sma20_vol = float(v.rolling(20).mean().iloc[-1])
    rvol = float(v.iloc[-1]) / (sma20_vol + 1e-8)
    h20 = float(h.rolling(20).max().shift(1).iloc[-1])
    
    # RS vs Nifty
    aligned_nifty = nifty.reindex(c.index).ffill()
    ratio = c / (aligned_nifty + 1e-8)
    rs_50 = ((ratio / ratio.rolling(50).mean()) - 1.0) * 100.0
    curr_rs = float(rs_50.iloc[-1])
    
    # 4 pillars
    p1 = 0.0
    if curr_c > ema20: p1 += 10.0
    if ema20 > sma50: p1 += 10.0
    if float(nifty.iloc[-1]) > float(nifty.rolling(50).mean().iloc[-1]): p1 += 5.0
    
    p2 = min(25.0, max(0.0, curr_rs * 2.5 + 10.0))
    p3 = min(25.0, rvol * 12.0)
    p4 = 25.0 if curr_c >= h20 * 0.995 else 10.0
    
    score = round(p1 + p2 + p3 + p4, 1)
    verdict = "BUY 🟢" if score >= 70 else "HOLD 🟡" if score >= 50 else "AVOID 🔴"
    action = "🚀 VOLUME SURGE BREAKOUT" if rvol >= 2.0 and curr_c >= h20 else "STAGE 2 CONTINUATION"
    
    print(f"• {sym:<14}: Rs {curr_c:>9,.2f} | Score: {score:>4.1f} | Verdict: {verdict} | RVOL: {rvol:>4.2f}x | RS: {curr_rs:>+5.1f}% | Action: {action}")
    print(f"  Stop: Rs {curr_c * 0.95:>8,.2f} (-5.0%) | Target: Rs {curr_c * 1.15:>8,.2f} (+15.0%)")
