"""
Fetch today's (2026-10-27) prices for Nifty, our paper trades, and run screener for fresh recommendations.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import yfinance as yf
import pandas as pd

tickers = ['^NSEI', '^NSEBANK', 'MPHASIS.NS', 'FEDERALBNK.NS', 'KOTAKBANK.NS', 'COFORGE.NS', 'TRENT.NS', 'DIXON.NS', 'KAYNES.NS', 'POLYCAB.NS', 'BHARTIARTL.NS', 'ICICIBANK.NS', 'HDFCBANK.NS', 'BSE.NS', 'CDSL.NS']

print("Downloading live closing data for 27 Oct 2026...")
data = yf.download(tickers, period='5d', interval='1d', progress=False, group_by='ticker')

print("\n--- 1. BENCHMARKS & OUR HOLDINGS TODAY (27 OCT 2026) ---")
for sym in ['^NSEI', '^NSEBANK', 'MPHASIS.NS', 'FEDERALBNK.NS', 'KOTAKBANK.NS']:
    try:
        df = data[sym].dropna(subset=['Close'])
        c = float(df['Close'].iloc[-1])
        prev = float(df['Close'].iloc[-2])
        chg = ((c - prev) / prev) * 100
        h = float(df['High'].iloc[-1])
        l = float(df['Low'].iloc[-1])
        dt = str(df.index[-1])[:10]
        print(f"• {sym:<14}: Close Rs {c:>9,.2f} ({chg:>+5.2f}%) | High: Rs {h:>9,.2f} | Low: Rs {l:>9,.2f} | Date: {dt}")
    except Exception as e:
        print(f"• {sym}: {e}")

print("\n--- 2. SCANNING POTENTIAL BUY BREAKOUTS TODAY (27 OCT) ---")
candidates = []
for sym in tickers:
    if sym in ['^NSEI', '^NSEBANK']: continue
    try:
        df = data[sym].dropna(subset=['Close', 'Volume'])
        if len(df) >= 4:
            c = df['Close']
            v = df['Volume']
            curr_c = float(c.iloc[-1])
            prev_c = float(c.iloc[-2])
            chg = ((curr_c - prev_c) / prev_c) * 100
            curr_v = float(v.iloc[-1])
            prev_v = float(v.iloc[-2])
            v_ratio = curr_v / (prev_v + 1e-8)
            dt = str(df.index[-1])[:10]
            candidates.append({
                "ticker": sym,
                "close": curr_c,
                "change": chg,
                "vol_ratio": v_ratio,
                "date": dt
            })
    except Exception as e:
        pass

df_c = pd.DataFrame(candidates).sort_values(by="change", ascending=False)
for idx, r in df_c.iterrows():
    print(f"• {r['ticker']:<14}: Rs {r['close']:>9,.2f} ({r['change']:>+5.2f}%) | Vol Surge: {r['vol_ratio']:>4.2f}x | Date: {r['date']}")
