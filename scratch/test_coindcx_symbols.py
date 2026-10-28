"""
Test Yahoo Finance tickers for top CoinDCX traded cryptocurrencies.
"""
import yfinance as yf

candidate_symbols = [
    # Core & L1s
    "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD", "ADA-USD", "AVAX-USD", "DOT-USD", "NEAR-USD", "LTC-USD",
    # Modern High-Beta L1/L2 Rockets
    "SUI-USD", "APT-USD", "SEI-USD", "INJ-USD", "TIA-USD", "ARB-USD", "OP-USD", "POL-USD", "FTM-USD", "KAS-USD",
    # AI & Compute Rockets (Huge CoinDCX volume)
    "RENDER-USD", "FET-USD", "TAO-USD", "GRT-USD",
    # High-Beta Memes (Top CoinDCX retail volume)
    "DOGE-USD", "SHIB-USD", "PEPE-USD", "BONK-USD", "WIF-USD", "FLOKI-USD",
    # DeFi & Real World Assets (RWA)
    "LINK-USD", "AAVE-USD", "UNI-USD", "PENDLE-USD", "ONDO-USD", "MKR-USD",
    # Gaming & Web3
    "GALA-USD", "STX-USD", "ICP-USD", "RUNE-USD"
]

print(f"Testing download for {len(candidate_symbols)} popular CoinDCX crypto tokens...")
raw = yf.download(candidate_symbols, period="10d", interval="1d", progress=False, group_by="ticker")

valid_symbols = []
for sym in candidate_symbols:
    try:
        if sym in raw.columns.levels[0]:
            df = raw[sym].dropna(subset=["Close", "Volume"])
            if len(df) >= 5:
                valid_symbols.append((sym, float(df['Close'].iloc[-1])))
    except Exception:
        pass

print(f"\nSuccessfully verified {len(valid_symbols)} tokens on Yahoo Finance:")
for s, p in valid_symbols:
    print(f"  {s:<12}: ${p:,.4f}")
