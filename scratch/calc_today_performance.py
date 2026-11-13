import yfinance as yf
import pandas as pd

tickers = ['TECHM.NS', 'HCLTECH.NS', 'HAL.NS', 'INDHOTEL.NS', 'NIFTYBEES.NS', '^NSEI']
sl_targets = {
    'TECHM.NS': {'sl': 1694.41, 'target': 2148.00, 'entry': 1772.00, 'score': 84.9},
    'HCLTECH.NS': {'sl': 1297.20, 'target': 1587.00, 'entry': 1380.70, 'score': 81.9},
    'HAL.NS': {'sl': 4689.66, 'target': 5737.35, 'entry': 4843.00, 'score': 81.8},
    'INDHOTEL.NS': {'sl': 737.36, 'target': 926.52, 'entry': 882.10, 'score': 81.5},
    'NIFTYBEES.NS': {'sl': 248.07, 'target': 303.48, 'entry': 288.49, 'score': 78.2},
}

data = {}
for t in tickers:
    h = yf.Ticker(t).history(period='5d')
    data[t] = h

nifty_hist = data['^NSEI']
nifty_yesterday_close = nifty_hist['Close'].iloc[-2]
nifty_today_close = nifty_hist['Close'].iloc[-1]
nifty_chg_pct = (nifty_today_close - nifty_yesterday_close) / nifty_yesterday_close * 100

print(f"NIFTY 50 (Benchmark): Yesterday Close = {nifty_yesterday_close:.2f}, Today Close = {nifty_today_close:.2f} ({nifty_chg_pct:+.2f}%)\n")

results = []
for t, cfg in sl_targets.items():
    h = data[t]
    prev_close = h['Close'].iloc[-2]
    today_open = h['Open'].iloc[-1]
    today_high = h['High'].iloc[-1]
    today_low = h['Low'].iloc[-1]
    today_close = h['Close'].iloc[-1]
    vol = h['Volume'].iloc[-1]
    
    # 1-day change vs yesterday close
    close_to_close_pct = (today_close - prev_close) / prev_close * 100
    # Day T+1 intraday change (from Open to Close)
    open_to_close_pct = (today_close - today_open) / today_open * 100
    # Day T+1 peak gain (from Open to High)
    open_to_high_pct = (today_high - today_open) / today_open * 100
    # Alpha vs Nifty
    alpha_pct = close_to_close_pct - nifty_chg_pct
    
    # Distance from Stop Loss
    sl_buffer_pct = (today_close - cfg['sl']) / cfg['sl'] * 100
    
    results.append({
        'Ticker': t,
        'Score': cfg['score'],
        'Yesterday Close': round(prev_close, 2),
        'Today Open': round(today_open, 2),
        'Today High': round(today_high, 2),
        'Today Low': round(today_low, 2),
        'Today Close': round(today_close, 2),
        'Day Chg %': round(close_to_close_pct, 2),
        'Open->High %': round(open_to_high_pct, 2),
        'Open->Close %': round(open_to_close_pct, 2),
        'Alpha vs Nifty %': round(alpha_pct, 2),
        'Stop Loss': cfg['sl'],
        'Buffer above SL %': round(sl_buffer_pct, 2),
        'Target': cfg['target']
    })

res_df = pd.DataFrame(results)
print(res_df.to_string(index=False))
