"""
Fetch and cache 5-year crypto universe daily OHLCV bars.
Covers top liquid cryptocurrencies traded in India (CoinDCX, CoinSwitch).
"""
import sys
import os
import pickle
import pandas as pd
import yfinance as yf

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

CRYPTO_SYMBOLS = [
    "BTC-USD",   # Bitcoin (Macro Benchmark + Core)
    "ETH-USD",   # Ethereum
    "SOL-USD",   # Solana
    "BNB-USD",   # Binance Coin
    "XRP-USD",   # Ripple
    "ADA-USD",   # Cardano
    "AVAX-USD",  # Avalanche
    "LINK-USD",  # Chainlink
    "DOGE-USD",  # Dogecoin
    "DOT-USD",   # Polkadot
    "NEAR-USD",  # Near Protocol
    "LTC-USD",   # Litecoin
    "APT-USD",   # Aptos
    "SUI-USD",   # Sui
]

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "cache")
os.makedirs(CACHE_DIR, exist_ok=True)
CACHE_FILE = os.path.join(CACHE_DIR, "crypto_5y.pkl")

print(f"Downloading historical data for {len(CRYPTO_SYMBOLS)} crypto pairs (5 years)...")
crypto_data = {}

for sym in CRYPTO_SYMBOLS:
    try:
        df = yf.download(sym, period="5y", interval="1d", progress=False)
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
