import yfinance as yf

alt_symbols = [
    "SUI20947-USD", "PEPE24478-USD", "APT21794-USD", "UNI7083-USD", "MATIC-USD", "STX4847-USD", "TAO22974-USD", "GRT6719-USD"
]

print("Testing alternative tickers...")
raw = yf.download(alt_symbols, period="10d", interval="1d", progress=False, group_by="ticker")
for sym in alt_symbols:
    try:
        if sym in raw.columns.levels[0]:
            df = raw[sym].dropna(subset=["Close", "Volume"])
            if len(df) >= 3:
                print(f"  FOUND: {sym} -> ${float(df['Close'].iloc[-1]):,.4f}")
    except Exception as e:
        print(f"  FAIL: {sym} -> {e}")
