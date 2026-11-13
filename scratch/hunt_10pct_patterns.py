import os, sys, pickle, math
from collections import Counter
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.market_data import _load_all_caches

cache = _load_all_caches()
nifty_df = cache.get("^NSEI")
if nifty_df is None:
    nifty_df = cache.get("NIFTYBEES.NS")
    
if nifty_df is not None:
    nifty_df = nifty_df.copy()
    if isinstance(nifty_df.columns, pd.MultiIndex):
        nifty_df.columns = [c[0] if isinstance(c, tuple) else c for c in nifty_df.columns]
    nifty_df.index = nifty_df.index.strftime("%Y-%m-%d")
    nifty_df = nifty_df[~nifty_df.index.duplicated(keep="last")]

tickers = [k for k, v in cache.items() if not k.startswith("^") and not k.endswith("BEES.NS") and len(v) >= 200]
print(f"Analyzing {len(tickers)} tickers across history...")

all_episodes = []

for ticker in tickers:
    df = cache[ticker].copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df.index = df.index.strftime("%Y-%m-%d")
    df = df[~df.index.duplicated(keep="last")]
    if len(df) < 100 or not all(c in df.columns for c in ["Open", "High", "Low", "Close", "Volume"]):
        continue

    c = df["Close"].astype(float)
    h = df["High"].astype(float)
    l = df["Low"].astype(float)
    v = df["Volume"].astype(float)
    o = df["Open"].astype(float)

    # 1-month forward returns (21 trading sessions)
    fwd_close_21 = c.shift(-21)
    fwd_ret_21 = (fwd_close_21 - c) / c * 100.0
    fwd_max_21 = (h.rolling(21).max().shift(-21) - c) / c * 100.0
    fwd_min_21 = (l.rolling(21).min().shift(-21) - c) / c * 100.0

    # Indicators on Day 0
    sma_20 = c.rolling(20).mean()
    sma_50 = c.rolling(50).mean()
    sma_200 = c.rolling(min(200, len(c))).mean()
    ema_10 = c.ewm(span=10).mean()
    ema_20 = c.ewm(span=20).mean()
    vol_sma_20 = v.rolling(20).mean()
    rvol = v / (vol_sma_20 + 1e-6)
    adtv_cr = (c * v).rolling(20).mean() / 1e7

    # Return over past 1 month, 3 months, 6 months
    past_1m_ret = c.pct_change(21) * 100.0
    past_3m_ret = c.pct_change(63) * 100.0
    past_5d_ret = c.pct_change(5) * 100.0
    past_1d_ret = c.pct_change(1) * 100.0

    # 52-week High / Low proximity
    high_52w = h.rolling(250).max().shift(1)
    low_52w = l.rolling(250).min().shift(1)
    pct_from_52w_high = ((c - high_52w) / high_52w) * 100.0
    dist_from_52w_low = ((c - low_52w) / low_52w) * 100.0

    # Donchian 20-day high breakout
    high_20 = h.rolling(20).max().shift(1)
    low_20 = l.rolling(20).min().shift(1)
    breakout_20d = c >= high_20

    # ATR
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr_14 = tr.rolling(14).mean()
    atr_pct = (atr_14 / c) * 100.0

    # 14-day RSI
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-6)
    rsi_14 = 100 - (100 / (1 + rs))

    for i in range(250, len(df) - 22):
        d_str = df.index[i]
        ret = fwd_ret_21.iloc[i]
        if math.isnan(ret):
            continue

        all_episodes.append({
            "ticker": ticker,
            "date": d_str,
            "close": c.iloc[i],
            "fwd_ret_21": ret,
            "fwd_max_21": fwd_max_21.iloc[i],
            "fwd_min_21": fwd_min_21.iloc[i],
            "rvol": rvol.iloc[i],
            "adtv_cr": adtv_cr.iloc[i],
            "past_1d_ret": past_1d_ret.iloc[i],
            "past_5d_ret": past_5d_ret.iloc[i],
            "past_1m_ret": past_1m_ret.iloc[i],
            "past_3m_ret": past_3m_ret.iloc[i],
            "pct_from_52w_high": pct_from_52w_high.iloc[i],
            "breakout_20d": breakout_20d.iloc[i],
            "above_sma50": c.iloc[i] > sma_50.iloc[i] if not math.isnan(sma_50.iloc[i]) else False,
            "above_sma200": c.iloc[i] > sma_200.iloc[i] if not math.isnan(sma_200.iloc[i]) else False,
            "ema10_gt_ema20": ema_10.iloc[i] > ema_20.iloc[i] if not math.isnan(ema_20.iloc[i]) else False,
            "rsi_14": rsi_14.iloc[i],
            "atr_pct": atr_pct.iloc[i],
        })

df_ep = pd.DataFrame(all_episodes)
print(f"Total historical 1-month episodes analyzed: {len(df_ep):,}")

# Filter for monster 1-month winners (>= +20%)
monsters = df_ep[df_ep["fwd_ret_21"] >= 20.0].copy()
print(f"Total +20% 1-Month Surges: {len(monsters):,} ({len(monsters)/len(df_ep)*100:.1f}%)")

# Filter for super-monsters (>= +30%)
super_monsters = df_ep[df_ep["fwd_ret_21"] >= 30.0].copy()
print(f"Total +30% 1-Month Surges: {len(super_monsters):,} ({len(super_monsters)/len(df_ep)*100:.1f}%)")

print("\n" + "=" * 80)
print("🔍 WHAT DID THE +20% MONSTER SURGES LOOK LIKE ON DAY 0?")
print("=" * 80)
print(f"Median Past 3-Month Return before surge: {monsters['past_3m_ret'].median():+.1f}% (All stocks: {df_ep['past_3m_ret'].median():+.1f}%)")
print(f"Median Past 1-Month Return before surge: {monsters['past_1m_ret'].median():+.1f}% (All stocks: {df_ep['past_1m_ret'].median():+.1f}%)")
print(f"Median Past 5-Day Return before surge:   {monsters['past_5d_ret'].median():+.1f}% (All stocks: {df_ep['past_5d_ret'].median():+.1f}%)")
print(f"Median Past 1-Day Return (Ignition Bar): {monsters['past_1d_ret'].median():+.1f}% (All stocks: {df_ep['past_1d_ret'].median():+.1f}%)")
print(f"Median RVOL on Day 0:                   {monsters['rvol'].median():.2f}x (All stocks: {df_ep['rvol'].median():.2f}x)")
print(f"Median RSI-14 on Day 0:                 {monsters['rsi_14'].median():.1f} (All stocks: {df_ep['rsi_14'].median():.1f})")
print(f"Median % from 52W High on Day 0:        {monsters['pct_from_52w_high'].median():.1f}% (All stocks: {df_ep['pct_from_52w_high'].median():.1f}%)")
print(f"% of Monsters above 50 SMA on Day 0:    {(monsters['above_sma50']).mean()*100:.1f}%")
print(f"% of Monsters above 200 SMA on Day 0:   {(monsters['above_sma200']).mean()*100:.1f}%")
print(f"% of Monsters with 20D High Breakout:   {(monsters['breakout_20d']).mean()*100:.1f}%")
print(f"% of Monsters with 10 EMA > 20 EMA:     {(monsters['ema10_gt_ema20']).mean()*100:.1f}%")

print("\n" + "=" * 80)
print("🏆 TOP 15 GREATEST 1-MONTH RUNNERS IN RECENT DATA")
print("=" * 80)
top_15 = monsters.sort_values(by="fwd_ret_21", ascending=False).head(15)
for idx, r in top_15.iterrows():
    print(f"{r['ticker']:12s} | Date: {r['date']} | 21d Gain: +{r['fwd_ret_21']:5.1f}% (Peak +{r['fwd_max_21']:5.1f}%) | Day0 RVOL: {r['rvol']:4.1f}x | Day0 Px: Rs.{r['close']:7.1f} | 52w Dist: {r['pct_from_52w_high']:+5.1f}% | Past 1m: {r['past_1m_ret']:+5.1f}%")

