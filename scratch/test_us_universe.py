"""
Test downloading top INDmoney / DriveWealth US Equities universe.
"""
import yfinance as yf

US_UNIVERSE = [
    # Magnificent 7 Tech Titans
    {"symbol": "NVDA", "name": "Nvidia", "sector": "AI & Semiconductors", "tag": "mag7"},
    {"symbol": "AAPL", "name": "Apple", "sector": "Consumer Tech", "tag": "mag7"},
    {"symbol": "MSFT", "name": "Microsoft", "sector": "Enterprise & Cloud AI", "tag": "mag7"},
    {"symbol": "AMZN", "name": "Amazon", "sector": "E-Commerce & Cloud", "tag": "mag7"},
    {"symbol": "GOOGL", "name": "Alphabet (Google)", "sector": "Search & AI", "tag": "mag7"},
    {"symbol": "META", "name": "Meta Platforms", "sector": "Social & AI", "tag": "mag7"},
    {"symbol": "TSLA", "name": "Tesla", "sector": "EV & Autonomous Robotics", "tag": "mag7"},
    
    # High-Beta AI & Semiconductor Rockets
    {"symbol": "PLTR", "name": "Palantir Technologies", "sector": "Enterprise AI Software", "tag": "ai_semi"},
    {"symbol": "AVGO", "name": "Broadcom", "sector": "Semiconductors & Networking", "tag": "ai_semi"},
    {"symbol": "AMD", "name": "Advanced Micro Devices", "sector": "Semiconductors", "tag": "ai_semi"},
    {"symbol": "QCOM", "name": "Qualcomm", "sector": "Mobile & Edge AI", "tag": "ai_semi"},
    {"symbol": "ARM", "name": "Arm Holdings", "sector": "Semiconductor Architecture", "tag": "ai_semi"},
    {"symbol": "MU", "name": "Micron Technology", "sector": "Memory & Storage", "tag": "ai_semi"},
    {"symbol": "TSM", "name": "Taiwan Semiconductor", "sector": "Foundry Monopoly", "tag": "ai_semi"},
    {"symbol": "ASML", "name": "ASML Holding", "sector": "EUV Lithography", "tag": "ai_semi"},
    
    # High-Velocity Growth & Fintech Momentum
    {"symbol": "COIN", "name": "Coinbase Global", "sector": "Crypto Infrastructure", "tag": "growth"},
    {"symbol": "HOOD", "name": "Robinhood Markets", "sector": "Retail Fintech", "tag": "growth"},
    {"symbol": "UBER", "name": "Uber Technologies", "sector": "Mobility & Delivery", "tag": "growth"},
    {"symbol": "APP", "name": "AppLovin", "sector": "AdTech & AI Mobile", "tag": "growth"},
    {"symbol": "CRWD", "name": "CrowdStrike", "sector": "Cybersecurity", "tag": "growth"},
    {"symbol": "ANET", "name": "Arista Networks", "sector": "Cloud & AI Networking", "tag": "growth"},
    {"symbol": "NET", "name": "Cloudflare", "sector": "Cloud & Edge Security", "tag": "growth"},
    {"symbol": "SNOW", "name": "Snowflake", "sector": "Cloud Data Warehousing", "tag": "growth"},
    {"symbol": "NOW", "name": "ServiceNow", "sector": "Enterprise Workflow", "tag": "growth"},
    {"symbol": "SHOP", "name": "Shopify", "sector": "Global E-Commerce", "tag": "growth"},
    {"symbol": "NFLX", "name": "Netflix", "sector": "Streaming Entertainment", "tag": "growth"},
    
    # Major Market & Sector ETFs
    {"symbol": "QQQ", "name": "Invesco QQQ (Nasdaq 100)", "sector": "US Tech Index ETF", "tag": "etf"},
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "sector": "Broad Market Index ETF", "tag": "etf"},
    {"symbol": "SMH", "name": "VanEck Semiconductor ETF", "sector": "Semiconductor Index ETF", "tag": "etf"},
    {"symbol": "IWM", "name": "iShares Russell 2000 ETF", "sector": "US Small-Cap Index ETF", "tag": "etf"},
]

symbols = [u["symbol"] for u in US_UNIVERSE]
print(f"Testing real-time download for {len(symbols)} INDmoney US Equities...")
raw = yf.download(symbols + ["^GSPC", "^IXIC"], period="30d", interval="1d", progress=False, group_by="ticker")

verified = 0
for u in US_UNIVERSE:
    sym = u["symbol"]
    try:
        if sym in raw.columns.levels[0]:
            df = raw[sym].dropna(subset=["Close", "Volume"])
            if len(df) >= 10:
                verified += 1
                p = float(df['Close'].iloc[-1])
                print(f"  OK: {sym:<6} ({u['name']:<25}): ${p:,.2f} | {u['sector']}")
    except Exception as e:
        print(f"  ERR: {sym} -> {e}")

print(f"\nTotal verified US Equities: {verified} / {len(US_UNIVERSE)}")
