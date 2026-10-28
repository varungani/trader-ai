"""
Fetch and cache maximum historical data (up to 10 years, 2016-2026) for major crypto assets.
"""
import sys
import os
import pickle
import pandas as pd
import yfinance as yf

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

CRYPTO_SYMBOLS = [
    "BTC-USD",   # Bitcoin (Macro Benchmark, 2014+)
    "ETH-USD",   # Ethereum (2017+)
    "SOL-USD",   # Solana (2020+)
    "BNB-USD",   # Binance Coin (2017+)
    "XRP-USD",   # Ripple (2017+)
    "ADA-USD",   # Cardano (2017+)
    "AVAX-USD",  # Avalanche (2020+)
    "LINK-USD",  # Chainlink (2017+)
    "DOGE-USD",  # Dogecoin (2017+)
    "NEAR-USD",  # Near Protocol (2020+)
    "LTC-USD",   # Litecoin (2014+)
    "DOT-USD",   # Polkadot (2020+)
]

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "cache")
os.makedirs(CACHE_DIR, exist_ok=True)
CACHE_FILE = os.path.join(CACHE_DIR, "crypto_10y.pkl")

print(f"Downloading maximum historical data (10y) for {len(CRYPTO_SYMBOLS)} crypto pairs...")
crypto_data = {}

for sym in CRYPTO_SYMBOLS:
    try:
        df = yf.download(sym, period="10y", interval="1d", progress=False)
        if df is not None and not df.empty and len(df) > 100:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [c.lower() for c in df.columns]
            df = df.dropna(subset=['close', 'volume'])
            crypto_data[sym] = df
            print(f"  [OK] {sym:10s}: {len(df)} bars ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")
        else:
            print(f"  [WARN] {sym}: Insufficient data")
    except Exception as e:
        print(f"  [ERR] {sym}: {e}")

print(f"\nSuccessfully downloaded {len(crypto_data)} crypto assets.")
with open(CACHE_FILE, "wb") as f:
    pickle.dump(crypto_data, f)
print(f"Cached to {CACHE_FILE}")
