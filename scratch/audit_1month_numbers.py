import os, sys, pickle
from collections import Counter
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backtesting.engine import run_simple_backtest

# Load cached universe tickers
cache_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cache", "universe_5y.pkl")
tickers = []
if os.path.exists(cache_path):
    with open(cache_path, "rb") as f:
        d = pickle.load(f)
        tickers = [k for k in d.keys() if not k.startswith("^") and not k.endswith("BEES.NS")][:100]

if not tickers:
    from config import NIFTY50_STOCKS, MIDCAP_LIQUID_STOCKS
    tickers = NIFTY50_STOCKS + MIDCAP_LIQUID_STOCKS

print(f"Running 1-Month Max Holding Empirical Audit across {len(tickers)} liquid Indian stocks...")
print("Parameters:")
print("• Maximum Holding Window: Strictly 21 Sessions (1 Month)")
print("• Stop Loss: Dynamic ATR (3.5% - 6.0%, default 5.0%)")
print("• Target 1 (Base): +15.0% (Tranche 1 Lock & Stop to Breakeven)")
print("• Target 2 (Runner): Uncapped ATR Trail up to Day 21 Hard Ceiling")
print("• Stagnation Exit: Day 8 exit if +/- 1.5% flat")
print("• Statutory Friction: Full CDSL DP charges (Rs 15.93), 0.1% STT, GST 18%, Stamp Duty, 0.20% Slippage Deducted\n")

# Run 2-Year Backtest (2024–2026)
res_2y = run_simple_backtest(
    tickers=tickers,
    period="2y",
    initial_capital=100000.0,
    strategy_name="1-Month Pure Swing Strategy (2Y)",
    allow_runners=True,
    use_trailing_stop=True,
    use_trend_filter=True,
)

# Run 5-Year Backtest (2021–2026)
res_5y = run_simple_backtest(
    tickers=tickers,
    period="5y",
    initial_capital=100000.0,
    strategy_name="1-Month Pure Swing Strategy (5Y)",
    allow_runners=True,
    use_trailing_stop=True,
    use_trend_filter=True,
)

def print_audit(label, r):
    trades = r.get("all_trades") or []
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    avg_win = (sum(t["pnl"] for t in wins) / len(wins)) if wins else 0.0
    avg_loss = (abs(sum(t["pnl"] for t in losses)) / len(losses)) if losses else 0.0
    payoff = round(avg_win / avg_loss, 2) if avg_loss > 0 else 0.0

    print(f"========================================================")
    print(f"📊 {label}")
    print(f"========================================================")
    print(f"• Backtest Period:       {r.get('start_date')} to {r.get('end_date')}")
    print(f"• Starting Capital:       Rs. {r.get('initial_capital'):,.2f}")
    print(f"• Final Net Capital:      Rs. {r.get('final_capital'):,.2f}")
    print(f"• Net Profit (After All): Rs. {(r.get('final_capital') - r.get('initial_capital')):+, .2f} ({r.get('total_return'):+.2f}%)")
    print(f"• Benchmark (NIFTYBEES):  {r.get('benchmark_return'):+.2f}%")
    print(f"• Alpha vs NIFTY 50:      {r.get('alpha'):+.2f}%")
    print(f"• Sharpe Ratio:           {r.get('sharpe_ratio')}")
    print(f"• Max Portfolio Drawdown: -{r.get('max_drawdown')}%")
    print(f"--------------------------------------------------------")
    print(f"• Total Closed Trades:    {r.get('total_trades')}")
    print(f"• Win Rate:               {r.get('win_rate')}% ({len(wins)} Wins / {len(losses)} Losses)")
    print(f"• Realized Payoff Ratio:  {payoff} : 1 (Avg Win: Rs.{avg_win:,.1f} | Avg Loss: Rs.{avg_loss:,.1f})")
    print(f"• Profit Factor:          {r.get('profit_factor')}")
    print(f"• Per-Trade Expectancy:   Rs. {r.get('expectancy_rupees'):+,.2f}")
    print(f"• Average Holding Period: {r.get('avg_days_held')} trading sessions (Strict <= 21 Sessions)")
    print(f"• Biggest Single Gain:    +{r.get('biggest_winner_pct')}%")
    print(f"• Monster Runners (>20%): {sum(1 for t in trades if t.get('pnl_percent', 0) >= 20.0)}")
    print(f"--------------------------------------------------------")

    # Reason breakdown
    reasons = Counter()
    for t in trades:
        raw_r = str(t.get("reason", ""))
        if "RUNNER" in raw_r:
            reasons["Runner Trailing / Target"] += 1
        elif "TARGET" in raw_r:
            reasons["Base Target (T1 Hit)"] += 1
        elif "STOP_LOSS" in raw_r:
            reasons["Planned Stop Loss Hit"] += 1
        elif "TRAILING_STOP" in raw_r or "BREAKEVEN" in raw_r:
            reasons["Breakeven / Trailing Lock"] += 1
        elif "1_MONTH" in raw_r or "21 Sessions" in raw_r:
            reasons["Hard 1-Month Ceiling (Day 21)"] += 1
        elif "TIME_STOP" in raw_r or "SWING_TIME" in raw_r:
            reasons["Swing Time Expired (Day 15)"] += 1
        elif "STAGNATION" in raw_r:
            reasons["Momentum Stagnation Cut (Day 8)"] += 1
        else:
            reasons[raw_r[:25]] += 1

    print("• Exit Breakdown:")
    for k, v in reasons.most_common():
        pct = (v / len(trades) * 100) if trades else 0
        print(f"   - {k:32s}: {v:3d} trades ({pct:.1f}%)")

    # Top 5 winners
    sorted_trades = sorted(trades, key=lambda x: x.get("pnl_percent", 0), reverse=True)
    print("\n• Top 5 Monster Winners in this Period:")
    for t in sorted_trades[:5]:
        print(f"   - {t.get('ticker'):15s}: {t.get('pnl_percent'):+6.2f}% | Entry: Rs.{t.get('entry_price'):8.2f} | Exit: Rs.{t.get('exit_price'):8.2f} | Held: {t.get('days_held'):2d} sessions | Reason: {t.get('reason')}")
    print("\n")

print_audit("2-YEAR COMPREHENSIVE PERFORMANCE (2024–2026, 1-Month Max Holding)", res_2y)
print_audit("5-YEAR COMPREHENSIVE PERFORMANCE (2021–2026, 1-Month Max Holding)", res_5y)
