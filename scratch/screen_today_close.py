"""
Screen today's closing prices (26 Oct 2026) for fresh Stage-2 breakouts and BUY signals.
Universe: High-Beta Rockets & Monster Midcaps
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import yfinance as yf
import pandas as pd
import numpy as np

# High Beta Rockets universe from config
ROCKETS = [
    "TRENT.NS", "DIXON.NS", "KAYNES.NS", "POLYCAB.NS", "SUZLON.NS", "PERSISTENT.NS",
    "COFORGE.NS", "MPHASIS.NS", "FEDERALBNK.NS", "KOTAKBANK.NS", "HDFCBANK.NS", "ICICIBANK.NS",
    "BHARTIARTL.NS", "HAL.NS", "BEL.NS", "BSE.NS", "CDSL.NS", "MCX.NS", "ZOMATO.NS"
]

print(f"Screening {len(ROCKETS)} high-beta momentum stocks on today's closing data (26 Oct 2026)...")
raw = yf.download(ROCKETS, period="60d", interval="1d", progress=False, group_by="ticker")

candidates = []
for sym in ROCKETS:
    try:
        if sym in raw.columns.levels[0]:
            df = raw[sym].dropna(subset=["Close", "Volume"])
            if len(df) >= 25:
                c = df["Close"]
                v = df["Volume"]
                h = df["High"]
                
                curr_c = float(c.iloc[-1])
                curr_v = float(v.iloc[-1])
                prev_c = float(c.iloc[-2])
                chg = ((curr_c - prev_c) / prev_c) * 100
                
                ema20 = float(c.ewm(span=20, adjust=False).mean().iloc[-1])
                sma50 = float(c.rolling(50).mean().iloc[-1]) if len(c) >= 50 else float(c.rolling(20).mean().iloc[-1])
                vol_sma20 = float(v.rolling(20).mean().iloc[-1])
                rvol = curr_v / (vol_sma20 + 1e-8)
                h20 = float(h.rolling(20).max().shift(1).iloc[-1])
                
                is_breakout = curr_c >= h20 * 0.99
                trend_ok = curr_c > ema20 and ema20 > sma50
                
                score = (25.0 if trend_ok else 10.0) + (min(25.0, rvol * 15.0)) + (25.0 if is_breakout else 10.0) + (15.0 if chg > 1.0 else 5.0)
                
                candidates.append({
                    "symbol": sym,
                    "close": curr_c,
                    "change": chg,
                    "rvol": rvol,
                    "score": score,
                    "is_breakout": is_breakout,
                    "trend_ok": trend_ok,
                    "h20": h20
                })
    except Exception as e:
        pass

df_cands = pd.DataFrame(candidates).sort_values(by="score", ascending=False)
print("\n--- TOP BREAKOUT & MOMENTUM CANDIDATES FROM TODAY'S CLOSE ---")
for idx, r in df_cands.head(8).iterrows():
    bo_str = "🚀 20D BREAKOUT" if r['is_breakout'] else "In Range"
    trend_str = "🟢 Stage 2 Bull" if r['trend_ok'] else "⚪ Consolidating"
    print(f"• {r['symbol']:<14}: Close Rs {r['close']:>8,.2f} ({r['change']:>+5.2f}%) | RVOL: {r['rvol']:>4.2f}x | {bo_str} | {trend_str} | Score: {r['score']:.1f}")
