import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from data.market_data import fetch_stock_history

for ticker in ["FEDERALBNK.NS", "MPHASIS.NS", "RELIANCE.NS"]:
    df = fetch_stock_history(ticker, period="1y")
    if not df.empty:
        vol = df["Volume"]
        vol20 = vol.rolling(20).mean()
        rvol = vol / vol20
        df["RVOL"] = rvol
        print(f"\n=== {ticker} RECENT SAMPLES ===")
        print(df[["Close", "Volume", "RVOL"]].tail(5))
