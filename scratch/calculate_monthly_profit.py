import os, sys, pickle, math
from collections import Counter
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scratch.test_compounded_apex import run_compounded_apex

# Run the 5-year compounded apex strategy
res = run_compounded_apex(compound=True, max_open=4, pos_pct=0.25, sl_pct=0.07, tp_pct=0.20)
trades = res["all_trades"]

# Get daily equity series
daily_equity = pd.DataFrame(res["daily_equity"])
daily_equity["date"] = pd.to_datetime(daily_equity["date"])
daily_equity.set_index("date", inplace=True)

# Resample to monthly equity (taking end-of-month equity)
monthly_equity = daily_equity["equity"].resample("ME").last()

# Monthly returns and profit
monthly_df = pd.DataFrame({
    "ending_equity": monthly_equity,
    "starting_equity": monthly_equity.shift(1).fillna(100000.0)
})
monthly_df["monthly_pnl_rupees"] = monthly_df["ending_equity"] - monthly_df["starting_equity"]
monthly_df["monthly_return_pct"] = (monthly_df["monthly_pnl_rupees"] / monthly_df["starting_equity"]) * 100.0

# Drop any zero-volume or start month if identical
monthly_df = monthly_df.iloc[1:] # First full month onwards

print("=== MONTHLY PERFORMANCE AUDIT ===")
total_months = len(monthly_df)
pos_months = monthly_df[monthly_df["monthly_pnl_rupees"] > 0]
neg_months = monthly_df[monthly_df["monthly_pnl_rupees"] <= 0]

avg_monthly_pnl = monthly_df["monthly_pnl_rupees"].mean()
median_monthly_pnl = monthly_df["monthly_pnl_rupees"].median()
avg_monthly_pct = monthly_df["monthly_return_pct"].mean()
median_monthly_pct = monthly_df["monthly_return_pct"].median()

monthly_win_rate = (len(pos_months) / total_months) * 100.0
avg_pos_month = pos_months["monthly_return_pct"].mean()
avg_neg_month = neg_months["monthly_return_pct"].mean()

best_month = monthly_df.loc[monthly_df["monthly_return_pct"].idxmax()]
worst_month = monthly_df.loc[monthly_df["monthly_return_pct"].idxmin()]

print(f"Total Months Tracked:     {total_months} months (~{total_months/12:.1f} years)")
print(f"Average Monthly Profit:   Rs. {avg_monthly_pnl:+,.2f} / month")
print(f"Average Monthly Return:   {avg_monthly_pct:+.2f}% / month")
print(f"Median Monthly Return:    {median_monthly_pct:+.2f}% / month")
print(f"Profitable Months:        {len(pos_months)} of {total_months} ({monthly_win_rate:.1f}% monthly win rate)")
print(f"Avg Profitable Month:     +{avg_pos_month:.2f}% (Rs. +{pos_months['monthly_pnl_rupees'].mean():,.2f})")
print(f"Avg Negative Month:       {avg_neg_month:.2f}% (Rs. {neg_months['monthly_pnl_rupees'].mean():,.2f})")
print(f"Best Single Month:        +{best_month['monthly_return_pct']:.2f}% (Rs. +{best_month['monthly_pnl_rupees']:,.2f}) on {best_month.name.strftime('%b %Y')}")
print(f"Worst Single Month:       {worst_month['monthly_return_pct']:.2f}% (Rs. {worst_month['monthly_pnl_rupees']:,.2f}) on {worst_month.name.strftime('%b %Y')}")

print("\n--- ANNUALIZED COMPOUNDED RATE OF RETURN (CAGR) ---")
cagr = ((res['final_capital'] / res['initial_capital']) ** (1.0 / (total_months / 12.0)) - 1.0) * 100.0
print(f"Starting Capital:         Rs. {res['initial_capital']:,.2f}")
print(f"Final Net Capital:        Rs. {res['final_capital']:,.2f}")
print(f"Total Net Return:         {res['total_return']:+.2f}%")
print(f"Annualized Return (CAGR): {cagr:+.2f}% p.a.")

print("\n--- MONTH BY MONTH DETAIL TABLE ---")
monthly_df["Year"] = monthly_df.index.year
monthly_df["Month"] = monthly_df.index.strftime("%b")
pivot_pnl = monthly_df.pivot(index="Year", columns="Month", values="monthly_return_pct")
# Reorder months
month_order = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
pivot_pnl = pivot_pnl.reindex(columns=[m for m in month_order if m in pivot_pnl.columns])
print(pivot_pnl.round(1).fillna("-").to_string())

# Also calculate from closed trades basis (trade resolution month)
print("\n--- CLOSED TRADES MONTHLY PNL ---")
tdf = pd.DataFrame(trades)
tdf["exit_date"] = pd.to_datetime(tdf["exit_date"])
tdf["month_year"] = tdf["exit_date"].dt.to_period("M")
monthly_trades = tdf.groupby("month_year").agg(
    trades_count=("pnl", "count"),
    wins=("pnl", lambda s: (s > 0).sum()),
    net_pnl=("pnl", "sum")
)
monthly_trades["win_rate"] = (monthly_trades["wins"] / monthly_trades["trades_count"]) * 100.0
print(f"Average Net Profit per Active Trading Month: Rs. {monthly_trades['net_pnl'].mean():+,.2f}")
print(f"Median Net Profit per Active Trading Month:  Rs. {monthly_trades['net_pnl'].median():+,.2f}")

