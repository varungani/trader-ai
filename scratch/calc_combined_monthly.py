"""
Combined Barbell Portfolio Monthly Metrics:
Blend 90% Stocks / 10% Crypto equity curves to compute:
- Combined Average Monthly Return
- Combined Average Winning Month
- Combined Average Losing Month
- Combined Worst Month (Worst Case)
- Combined Best Month
"""
import pandas as pd, numpy as np

# Let's import df_stock_eq and df_crypto_eq
import pickle

with open("scratch/stock_crypto_eq.pkl", "wb") as f:
    pass
