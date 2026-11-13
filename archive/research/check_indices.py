import yfinance as yf

for sym in ['^NSEI', '^NSEBANK', '^CNXIT']:
    t = yf.Ticker(sym)
    fi = t.fast_info
    print(f"{sym}: Last={fi.get('lastPrice')}, PrevClose={fi.get('previousClose')}")
