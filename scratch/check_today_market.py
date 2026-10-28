"""
Check Indian and US market status for today (2026-10-26).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import yfinance as yf
import pandas as pd

tickers = ['^NSEI', '^NSEBANK', 'FEDERALBNK.NS', 'KOTAKBANK.NS', 'MPHASIS.NS', 'SPY', 'QQQ', 'NVDA', 'PLTR', 'AVGO']
data = yf.download(tickers, period='5d', interval='1d', progress=False, group_by='ticker')

print("--- INDIAN MARKET TODAY (26 OCT 2026) ---")
for sym in ['^NSEI', '^NSEBANK', 'FEDERALBNK.NS', 'KOTAKBANK.NS', 'MPHASIS.NS']:
    try:
        df = data[sym].dropna(subset=['Close'])
        c = float(df['Close'].iloc[-1])
        prev = float(df['Close'].iloc[-2])
        chg = ((c - prev) / prev) * 100
        h = float(df['High'].iloc[-1])
        l = float(df['Low'].iloc[-1])
        dt = str(df.index[-1])[:10]
        print(f"{sym:<15}: Close Rs {c:,.2f} ({chg:+.2f}%) | High: Rs {h:,.2f} | Low: Rs {l:,.2f} | Date: {dt}")
    except Exception as e:
        print(f"{sym}: {e}")

print("\n--- US MARKET BENCHMARKS & LEADERS ---")
for sym in ['SPY', 'QQQ', 'NVDA', 'PLTR', 'AVGO']:
    try:
        df = data[sym].dropna(subset=['Close'])
        c = float(df['Close'].iloc[-1])
        prev = float(df['Close'].iloc[-2])
        chg = ((c - prev) / prev) * 100
        dt = str(df.index[-1])[:10]
        print(f"{sym:<8}: ${c:,.2f} ({chg:+.2f}%) | Date: {dt}")
    except Exception as e:
        print(f"{sym}: {e}")
