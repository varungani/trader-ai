import os, sys, pickle, math
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scratch.test_fast_backtest import fast_backtest
from data.market_data import _load_all_caches

cache = _load_all_caches()
tickers = [k for k, v in cache.items() if not k.startswith("^") and not k.endswith("BEES.NS") and len(v) >= 200][:80]
res = fast_backtest(tickers, period="2y")
trades = res["all_trades"]

stopped_out = [t for t in trades if "STOP_LOSS" in t["reason"]]
print(f"Total stopped out trades: {len(stopped_out)}")

post_stop_performance = []
for t in stopped_out:
    sym = t["ticker"]
    entry_d = t["entry_date"]
    entry_px = t["entry_price"]
    exit_d = t["exit_date"]
    df = cache[sym].copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df.index = df.index.strftime("%Y-%m-%d")
    if entry_d in df.index:
        idx = df.index.get_loc(entry_d)
        window = df.iloc[idx : min(len(df), idx + 22)]
        max_px = window["High"].max()
        final_px = window["Close"].iloc[-1]
        max_gain = (max_px - entry_px) / entry_px * 100.0
        final_gain = (final_px - entry_px) / entry_px * 100.0
        post_stop_performance.append({
            "ticker": sym,
            "entry_d": entry_d,
            "exit_d": exit_d,
            "days_held": t["days_held"],
            "stopped_loss_pct": t["pnl_percent"],
            "subsequent_max_gain": round(max_gain, 1),
            "end_of_month_gain": round(final_gain, 1),
        })

df_post = pd.DataFrame(post_stop_performance)
print(f"Average loss at stop: {df_post['stopped_loss_pct'].mean():.1f}%")
print(f"Average max gain during that 1-month: +{df_post['subsequent_max_gain'].mean():.1f}%")
print(f"Percentage of stopped-out trades that would have been POSITIVE by month end: {(df_post['end_of_month_gain'] > 0).mean()*100:.1f}%")
print(f"Percentage of stopped-out trades that reached +10% or more: {(df_post['subsequent_max_gain'] >= 10.0).mean()*100:.1f}%")
print(f"Percentage of stopped-out trades that reached +15% or more: {(df_post['subsequent_max_gain'] >= 15.0).mean()*100:.1f}%")

print("\nTop 5 premature stop-outs that surged:")
print(df_post.sort_values(by="subsequent_max_gain", ascending=False).head(10).to_string())

