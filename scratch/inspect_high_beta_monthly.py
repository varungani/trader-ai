import os, sys, pickle, math
from collections import Counter
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scratch.test_high_beta_apex import run_high_beta_apex

res = run_high_beta_apex(slots=3, target_pct=0.25, stop_pct=0.07)
trades = res["all_trades"]

print(f"Total Trades: {len(trades)}")
print(f"Total Return: {res['total_return']:+.2f}%")
print(f"Final Capital: Rs. {res['final_capital']:,.2f}")
print(f"Win Rate: {res['win_rate']}%")

# Trade level stats
trades_df = pd.DataFrame(trades)
trades_df["exit_date"] = pd.to_datetime(trades_df["exit_date"])
trades_df["year"] = trades_df["exit_date"].dt.year
trades_df["month_year"] = trades_df["exit_date"].dt.to_period("M")

# Monthly trade aggregates
monthly_agg = trades_df.groupby("month_year").agg(
    trades=("pnl", "count"),
    wins=("pnl", lambda s: (s > 0).sum()),
    net_profit=("pnl", "sum"),
    avg_gain_pct=("pnl_percent", "mean")
)
monthly_agg["win_rate"] = (monthly_agg["wins"] / monthly_agg["trades"]) * 100.0

print(f"\nTotal Active Trading Months: {len(monthly_agg)}")
print(f"Average Profit per Active Month: Rs. {monthly_agg['net_profit'].mean():+,.2f} / month")
print(f"Median Profit per Active Month:  Rs. {monthly_agg['net_profit'].median():+,.2f} / month")
print(f"Profitable Active Months:       {(monthly_agg['net_profit'] > 0).sum()} of {len(monthly_agg)} ({(monthly_agg['net_profit'] > 0).mean()*100:.1f}%)")

print("\n--- TOP 10 BEST TRADING MONTHS (NET PROFIT) ---")
print(monthly_agg.sort_values(by="net_profit", ascending=False).head(10)[["trades", "wins", "win_rate", "net_profit"]].to_string())

print("\n--- SAMPLE WINNING TRADES ---")
print(trades_df.sort_values(by="pnl", ascending=False).head(10)[["ticker", "entry_date", "exit_date", "days_held", "pnl_percent", "pnl", "reason"]].to_string())

