import yfinance as yf

COINDCX_ALL = [
    # Core & Bluechips
    {"symbol": "BTC-USD", "name": "Bitcoin", "display": "BTC", "category": "Core Benchmark"},
    {"symbol": "ETH-USD", "name": "Ethereum", "display": "ETH", "category": "Core Layer 1"},
    {"symbol": "SOL-USD", "name": "Solana", "display": "SOL", "category": "High-Throughput L1"},
    {"symbol": "BNB-USD", "name": "BNB", "display": "BNB", "category": "Exchange Ecosystem"},
    {"symbol": "XRP-USD", "name": "XRP", "display": "XRP", "category": "Payments"},
    {"symbol": "ADA-USD", "name": "Cardano", "display": "ADA", "category": "PoS Layer 1"},
    {"symbol": "AVAX-USD", "name": "Avalanche", "display": "AVAX", "category": "Multi-Chain L1"},
    {"symbol": "DOT-USD", "name": "Polkadot", "display": "DOT", "category": "Interoperability"},
    {"symbol": "NEAR-USD", "name": "Near Protocol", "display": "NEAR", "category": "AI / Sharded L1"},
    {"symbol": "LTC-USD", "name": "Litecoin", "display": "LTC", "category": "Payments"},
    # Next-Gen L1 / L2 Rockets
    {"symbol": "SUI20947-USD", "name": "Sui", "display": "SUI", "category": "Next-Gen L1"},
    {"symbol": "APT21794-USD", "name": "Aptos", "display": "APT", "category": "Move L1"},
    {"symbol": "SEI-USD", "name": "Sei Network", "display": "SEI", "category": "Trading L1"},
    {"symbol": "INJ-USD", "name": "Injective", "display": "INJ", "category": "DeFi L1"},
    {"symbol": "TIA-USD", "name": "Celestia", "display": "TIA", "category": "Modular L1"},
    {"symbol": "ARB-USD", "name": "Arbitrum", "display": "ARB", "category": "Ethereum L2"},
    {"symbol": "OP-USD", "name": "Optimism", "display": "OP", "category": "Ethereum L2"},
    {"symbol": "KAS-USD", "name": "Kaspa", "display": "KAS", "category": "PoW Layer 1"},
    {"symbol": "STX4847-USD", "name": "Stacks", "display": "STX", "category": "Bitcoin L2"},
    {"symbol": "ICP-USD", "name": "Internet Computer", "display": "ICP", "category": "Compute L1"},
    {"symbol": "RUNE-USD", "name": "THORChain", "display": "RUNE", "category": "Cross-Chain"},
    # AI & Compute Leaders
    {"symbol": "RENDER-USD", "name": "Render", "display": "RENDER", "category": "AI & GPU Compute"},
    {"symbol": "FET-USD", "name": "Artificial Superintelligence", "display": "FET", "category": "AI Agents"},
    {"symbol": "TAO22974-USD", "name": "Bittensor", "display": "TAO", "category": "Decentralized AI"},
    {"symbol": "GRT6719-USD", "name": "The Graph", "display": "GRT", "category": "Data & Indexing"},
    # High-Velocity Memes (Top CoinDCX Retail)
    {"symbol": "DOGE-USD", "name": "Dogecoin", "display": "DOGE", "category": "Meme King"},
    {"symbol": "SHIB-USD", "name": "Shiba Inu", "display": "SHIB", "category": "Meme Ecosystem"},
    {"symbol": "PEPE24478-USD", "name": "Pepe", "display": "PEPE", "category": "Meme Wave"},
    {"symbol": "WIF-USD", "name": "dogwifhat", "display": "WIF", "category": "Solana Meme"},
    {"symbol": "BONK-USD", "name": "Bonk", "display": "BONK", "category": "Solana Meme"},
    {"symbol": "FLOKI-USD", "name": "Floki", "display": "FLOKI", "category": "Meme & Gaming"},
    # DeFi & RWA
    {"symbol": "LINK-USD", "name": "Chainlink", "display": "LINK", "category": "Oracle / RWA"},
    {"symbol": "AAVE-USD", "name": "Aave", "display": "AAVE", "category": "DeFi Lending"},
    {"symbol": "UNI7083-USD", "name": "Uniswap", "display": "UNI", "category": "DEX Leader"},
    {"symbol": "PENDLE-USD", "name": "Pendle", "display": "PENDLE", "category": "Yield Trading"},
    {"symbol": "ONDO-USD", "name": "Ondo Finance", "display": "ONDO", "category": "Tokenized RWA"},
    {"symbol": "MKR-USD", "name": "Maker", "display": "MKR", "category": "DeFi Stablecoin"},
]

symbols = [c["symbol"] for c in COINDCX_ALL]
print(f"Downloading batch of {len(symbols)} tokens...")
raw = yf.download(symbols, period="30d", interval="1d", progress=False, group_by="ticker")

found = 0
for c in COINDCX_ALL:
    sym = c["symbol"]
    try:
        if sym in raw.columns.levels[0]:
            df = raw[sym].dropna(subset=["Close", "Volume"])
            if len(df) >= 10:
                found += 1
                p = float(df['Close'].iloc[-1])
                print(f"  OK: {c['display']:<7} ({c['name']:<25}): ${p:,.4f} | Cat: {c['category']}")
    except Exception as e:
        print(f"  ERR: {sym} -> {e}")

print(f"\nTotal verified CoinDCX tokens: {found} / {len(COINDCX_ALL)}")
