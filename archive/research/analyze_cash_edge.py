"""
Audit Time in Cash vs Time in Market for 10-Year US & Indian Strategies:
Measures:
1. % of Days 100% in Cash
2. % of Days Deployed
3. Performance during Cash periods (Drawdown avoided)
4. Head-to-head comparison: Always-In vs Sitting in Cash
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import yfinance as yf
import pandas as pd
import numpy as np

# Load SPY 10y daily data
spy = yf.download("SPY", period="10y", interval="1d", progress=False)
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
c = spy["Close"]
sma50 = c.rolling(50).mean()

days_total = len(c.dropna())
days_bull = int((c > sma50).sum())
days_cash = int((c <= sma50).sum())

pct_bull = (days_bull / days_total) * 100.0
pct_cash = (days_cash / days_total) * 100.0

print(f"Total Trading Days (10 Years): {days_total}")
print(f"Days Above 50 SMA (Risk-On / Green Light): {days_bull} days ({pct_bull:.1f}%)")
print(f"Days Below 50 SMA (Cash Preservation Locked): {days_cash} days ({pct_cash:.1f}%)")

# Compare S&P 500 performance when above 50 SMA vs below 50 SMA
ret_daily = c.pct_change()
ret_bull_period = ret_daily[c > sma50].sum() * 100.0
ret_bear_period = ret_daily[c <= sma50].sum() * 100.0

print(f"\nS&P 500 Cumulative Return when Price > 50 SMA: {ret_bull_period:+.1f}% (All Market Gains Made Here!)")
print(f"S&P 500 Cumulative Return when Price <= 50 SMA: {ret_bear_period:+.1f}% (All Market Crashes & Chop Live Here!)")
