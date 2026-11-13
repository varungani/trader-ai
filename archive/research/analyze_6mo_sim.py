import io
import pandas as pd

csv_data = """
,ticker,entry_date,exit_date,days_held,entry_price,exit_price,quantity,pnl,pnl_percent,gross_pnl,friction_costs,post_tax_pnl,stcg_tax,reason
0,FEDERALBNK.NS,2026-07-01,2026-07-29,20,330.27166748046875,357.93,12,302.62,7.64,331.87,29.25,242.1,60.52,TIME_STOP (20 Sessions)
1,MPHASIS.NS,2026-07-06,2026-08-03,20,2246.959716796875,2429,1,158.56,7.06,182.04,23.48,126.85,31.71,TIME_STOP (20 Sessions)
2,FEDERALBNK.NS,2026-07-29,2026-08-25,19,357.92718505859375,343.5,11,-187.13,-4.75,-158.7,28.43,-187.13,0,STOP_LOSS
3,RELIANCE.NS,2026-08-12,2026-08-27,11,1329,1282.48,3,-168.18,-4.22,-139.56,28.62,-168.18,0,STOP_LOSS
4,MPHASIS.NS,2026-08-03,2026-08-31,20,2429,2427.4,1,-25.38,-1.04,-1.6,23.78,-25.38,0,TIME_STOP (20 Sessions)
5,MPHASIS.NS,2026-09-01,2026-09-07,4,2505.5,2384.81,1,-144.54,-5.77,-120.69,23.85,-144.54,0,STOP_LOSS
"""

df = pd.read_csv(io.StringIO(csv_data.strip()))

total_trades = len(df)
wins = df[df["pnl"] > 0]
losses = df[df["pnl"] < 0]
win_rate = (len(wins) / total_trades) * 100

total_gross = df["gross_pnl"].sum()
total_friction = df["friction_costs"].sum()
total_net = df["pnl"].sum()
total_post_tax = df["post_tax_pnl"].sum()
total_stcg = df["stcg_tax"].sum()

avg_win = wins["pnl"].mean()
avg_loss = losses["pnl"].mean()
profit_factor = wins["pnl"].sum() / abs(losses["pnl"].sum())

print("=== 6-MONTH SIMULATION BREAKDOWN ===")
print(f"Total Completed Trades: {total_trades}")
print(f"Wins: {len(wins)} ({win_rate:.1f}%) | Losses: {len(losses)} ({100 - win_rate:.1f}%)")
print(f"Average Win:  Rs. {avg_win:+,.2f} (+{wins['pnl_percent'].mean():.2f}%)")
print(f"Average Loss: Rs. {avg_loss:+,.2f} ({losses['pnl_percent'].mean():.2f}%)")
print(f"Profit Factor: {profit_factor:.2f}")
print(f"\nGross P&L:        Rs. {total_gross:+,.2f}")
print(f"Total Friction:   Rs. {total_friction:,.2f} (DP charges, STT, GST, etc.)")
print(f"Net Pre-Tax P&L:  Rs. {total_net:+,.2f}")
print(f"STCG Tax (20%):   Rs. {total_stcg:,.2f}")
print(f"Net Post-Tax P&L: Rs. {total_post_tax:+,.2f}")

print("\n=== EXIT REASONS ===")
print(df["reason"].value_counts().to_string())
