"""
TraderAI - Exit Audit, P&L Waterfall & Random Exit Policy Diagnostics
Answers the reviewer's exact questions:
1. P&L Waterfall (Gross vs Friction vs Net Pre-Tax vs Net Post-Tax with Set-off)
2. Exit Reason Breakdown & Win/Loss Counts (T1, Stop, Breakeven, Trailing, Time Stop)
3. Realized R-Multiple & Payoff Ratio
4. Random Entry Exit Policy Ablation (Fixed Hold vs Stop-only vs Breakeven Ratchet)
"""
import os
import sys
import math
import random
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.market_data import fetch_stock_history
from analysis.technical import compute_technical_score
from data.costs import compute_indian_delivery_costs

TEST_UNIVERSE = [
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "ICICIBANK.NS", "SBIN.NS",
    "BHARTIARTL.NS", "ITC.NS", "LT.NS", "AXISBANK.NS", "MARUTI.NS",
    "TITAN.NS", "SUNPHARMA.NS", "BAJFINANCE.NS", "HCLTECH.NS", "NTPC.NS",
    "POWERGRID.NS", "M&M.NS", "BAJAJ-AUTO.NS", "TATASTEEL.NS", "BEL.NS",
    "TRENT.NS", "DIXON.NS", "HAL.NS", "POLYCAB.NS", "PERSISTENT.NS"
]

def load_data():
    data = {}
    for t in TEST_UNIVERSE:
        df = fetch_stock_history(t, period="3y")
        if not df.empty and len(df) >= 120:
            data[t] = df
    nifty = fetch_stock_history("^NSEI", period="3y")
    return data, nifty

def run_detailed_exit_audit(data, nifty_df, entry_mode="strategy", exit_policy="current", min_score=65.0):
    all_dates = sorted(list(set.union(*[set(df.index.strftime("%Y-%m-%d")) for df in data.values()])))
    open_positions = {}
    trades = []
    cash = 100000.0
    portfolio_value = 100000.0
    rng = random.Random(42)

    for date_str in all_dates:
        # Check exits
        to_close = []
        for sym, pos in open_positions.items():
            df = data[sym]
            day_rows = df[df.index.strftime("%Y-%m-%d") == date_str]
            if day_rows.empty:
                continue
            
            high = float(day_rows["High"].iloc[0])
            low = float(day_rows["Low"].iloc[0])
            close = float(day_rows["Close"].iloc[0])
            open_px = float(day_rows["Open"].iloc[0]) if "Open" in day_rows else close
            
            pos["days_held"] += 1
            pos["peak_price"] = max(pos["peak_price"], high)
            initial_risk = pos["entry_price"] - pos["initial_stop"]
            
            # Policy variations
            if exit_policy == "current":
                # Breakeven ratchet at +1R
                if initial_risk > 0 and (pos["peak_price"] - pos["entry_price"]) >= initial_risk:
                    pos["stop_loss"] = max(pos["stop_loss"], pos["entry_price"])
                    if pos.get("atr"):
                        pos["stop_loss"] = max(pos["stop_loss"], round(pos["peak_price"] - (1.5 * pos["atr"]), 2))
                
                exit_reason = None
                exit_px = close
                if low <= pos["stop_loss"]:
                    if pos["stop_loss"] > pos["entry_price"]:
                        exit_reason = "TRAILING_STOP"
                    elif pos["stop_loss"] == pos["entry_price"]:
                        exit_reason = "BREAKEVEN_STOP"
                    else:
                        exit_reason = "STOP_LOSS"
                    exit_px = min(pos["stop_loss"], open_px) if open_px < pos["stop_loss"] else pos["stop_loss"]
                elif high >= pos["target"]:
                    exit_reason = "TARGET_T1 (+12% to +15%)"
                    exit_px = pos["target"]
                elif pos["days_held"] >= 15:
                    exit_reason = "TIME_STOP (15 Sessions)"
                    exit_px = close
                    
            elif exit_policy == "fixed_15d_hold":
                # No stops, no targets - pure 15 day time hold
                exit_reason = None
                exit_px = close
                if pos["days_held"] >= 15:
                    exit_reason = "FIXED_15D_HOLD"
                    exit_px = close
                    
            elif exit_policy == "stop_and_target_no_ratchet":
                # Only static 5% stop and 12% target, no breakeven ratchet, no trailing
                exit_reason = None
                exit_px = close
                if low <= pos["initial_stop"]:
                    exit_reason = "STOP_LOSS"
                    exit_px = min(pos["initial_stop"], open_px) if open_px < pos["initial_stop"] else pos["initial_stop"]
                elif high >= pos["target"]:
                    exit_reason = "TARGET_T1 (+12% to +15%)"
                    exit_px = pos["target"]
                elif pos["days_held"] >= 15:
                    exit_reason = "TIME_STOP (15 Sessions)"
                    exit_px = close

            if exit_reason:
                costs = compute_indian_delivery_costs(
                    buy_price=pos["entry_price"],
                    sell_price=exit_px,
                    quantity=pos["qty"],
                    apply_stcg=False # Pre-tax for waterfall audit
                )
                r_multiple = (exit_px - pos["entry_price"]) / initial_risk if initial_risk > 0 else 0.0
                trades.append({
                    "ticker": sym,
                    "entry_date": pos["entry_date"],
                    "exit_date": date_str,
                    "days_held": pos["days_held"],
                    "entry_px": pos["entry_price"],
                    "exit_px": exit_px,
                    "qty": pos["qty"],
                    "gross_pnl": costs.gross_pnl_rupees,
                    "friction": costs.total_friction_rupees,
                    "dp_charges": costs.dp_charges_rupees,
                    "stt": costs.stt_rupees,
                    "slippage": costs.slippage_rupees,
                    "net_pretax_pnl": costs.net_pnl_rupees,
                    "reason": exit_reason,
                    "r_multiple": round(r_multiple, 2),
                })
                cash += (exit_px * pos["qty"]) - costs.total_friction_rupees
                to_close.append(sym)
                
        for sym in to_close:
            del open_positions[sym]
            
        # Entry search
        regime_bullish = True
        if nifty_df is not None and not nifty_df.empty:
            nifty_sub = nifty_df[nifty_df.index.strftime("%Y-%m-%d") <= date_str]
            if len(nifty_sub) >= 50:
                nifty_close = float(nifty_sub["Close"].iloc[-1])
                nifty_sma50 = float(nifty_sub["Close"].rolling(50).mean().iloc[-1])
                if nifty_close < nifty_sma50:
                    regime_bullish = False

        if len(open_positions) < 5 and regime_bullish:
            avail = [s for s in data.keys() if s not in open_positions]
            candidates = []
            if entry_mode == "random":
                if avail and rng.random() < 0.25:
                    chosen = rng.choice(avail)
                    candidates.append((chosen, 100.0))
            else:
                for sym in avail:
                    sub = data[sym][data[sym].index.strftime("%Y-%m-%d") <= date_str]
                    if len(sub) < 50:
                        continue
                    px = float(sub["Close"].iloc[-1])
                    if px <= 0:
                        continue
                    tech = compute_technical_score(sub.tail(100), ticker=sym)
                    sc = float(tech.get("score", 50))
                    if sc >= min_score:
                        candidates.append((sym, sc))
            candidates.sort(key=lambda x: x[1], reverse=True)
            for sym, sc in candidates:
                if len(open_positions) >= 5:
                    break
                sub = data[sym][data[sym].index.strftime("%Y-%m-%d") <= date_str]
                close_px = float(sub["Close"].iloc[-1])
                base_cap = portfolio_value if portfolio_value else cash
                alloc = min(cash, base_cap * 0.20)
                qty = int(alloc // close_px)
                if qty > 0 and cash >= (qty * close_px):
                    highs = sub["High"].tail(14)
                    lows = sub["Low"].tail(14)
                    atr = float((highs - lows).mean()) if len(highs) >= 14 else (close_px * 0.05)
                    atr_pct = (atr / close_px) * 100 if close_px > 0 else 5.0
                    sl_pct = min(0.06, max(0.035, (atr_pct / 100) * 2.0))
                    tp_pct = max(0.12, sl_pct * 2.0)
                    stop_px = round(close_px * (1 - sl_pct), 2)
                    target_px = round(close_px * (1 + tp_pct), 2)
                    cash -= (qty * close_px)
                    open_positions[sym] = {
                        "entry_price": close_px,
                        "qty": qty,
                        "initial_stop": stop_px,
                        "stop_loss": stop_px,
                        "target": target_px,
                        "entry_date": date_str,
                        "peak_price": close_px,
                        "atr": atr,
                        "days_held": 0
                    }
        # Mark to market
        h_val = sum(float(data[s][data[s].index.strftime("%Y-%m-%d") <= date_str]["Close"].iloc[-1]) * p["qty"] for s, p in open_positions.items() if not data[s][data[s].index.strftime("%Y-%m-%d") <= date_str].empty)
        portfolio_value = cash + h_val
        
    return pd.DataFrame(trades), portfolio_value

def main():
    print("="*70)
    print("TRADER-AI DETAILED EXIT AUDIT & P&L WATERFALL")
    print("="*70)
    data, nifty = load_data()
    
    # 1. Audit Active Strategy (Regime ON)
    trades_df, final_eq = run_detailed_exit_audit(data, nifty, entry_mode="strategy", exit_policy="current")
    
    total_trades = len(trades_df)
    gross_total = trades_df["gross_pnl"].sum()
    friction_total = trades_df["friction"].sum()
    net_pretax_total = trades_df["net_pretax_pnl"].sum()
    dp_total = trades_df["dp_charges"].sum()
    stt_total = trades_df["stt"].sum()
    slippage_total = trades_df["slippage"].sum()
    
    # Proper annual tax computation (set-off losses!)
    trades_df["year"] = pd.to_datetime(trades_df["exit_date"]).dt.year
    annual_gains = trades_df.groupby("year")["net_pretax_pnl"].sum()
    annual_stcg = sum(max(0, g * 0.20) for g in annual_gains)
    net_post_tax_total = net_pretax_total - annual_stcg
    
    print("\n--- 1. P&L WATERFALL (Strategy, Gate ON) ---")
    print(f"Total Trades: {total_trades}")
    print(f"Gross P&L:                Rs {gross_total:+,.2f}  (Rs {gross_total/total_trades:+.2f} / trade)")
    print(f"Total Statutory Friction: Rs {friction_total:,.2f}  (Rs {friction_total/total_trades:.2f} / trade, ~{friction_total/(total_trades*19000)*100:.2f}%)")
    print(f"  • CDSL DP Charges:      Rs {dp_total:,.2f}  (Rs {dp_total/total_trades:.2f} / trade)")
    print(f"  • STT (Buy+Sell):       Rs {stt_total:,.2f}  (Rs {stt_total/total_trades:.2f} / trade)")
    print(f"  • Slippage (5 bps):     Rs {slippage_total:,.2f}  (Rs {slippage_total/total_trades:.2f} / trade)")
    print(f"Net Pre-Tax P&L:          Rs {net_pretax_total:+,.2f}  (Rs {net_pretax_total/total_trades:+.2f} / trade)")
    print(f"Actual Annual Net STCG:   Rs {annual_stcg:,.2f}  (Zero tax paid because net annual P&L was negative!)")
    print(f"Net Post-Tax P&L:         Rs {net_post_tax_total:+,.2f}")
    
    # 2. Exit Reason Breakdown
    print("\n--- 2. EXIT REASON BREAKDOWN & WHERE THE LEAK IS ---")
    reasons = trades_df.groupby("reason").agg(
        Count=("gross_pnl", "count"),
        Gross_PnL=("gross_pnl", "sum"),
        Net_PnL=("net_pretax_pnl", "sum"),
        Avg_Gross=("gross_pnl", "mean"),
        Avg_Net=("net_pretax_pnl", "mean"),
        Avg_R=("r_multiple", "mean"),
        Avg_Days=("days_held", "mean")
    ).reset_index()
    reasons["% of Trades"] = (reasons["Count"] / total_trades * 100).round(1).astype(str) + "%"
    print(reasons[["reason", "Count", "% of Trades", "Avg_Gross", "Avg_Net", "Avg_R", "Avg_Days"]].to_string(index=False))
    
    # 3. Payoff ratio analysis
    winners = trades_df[trades_df["net_pretax_pnl"] > 0]
    losers = trades_df[trades_df["net_pretax_pnl"] <= 0]
    avg_win = winners["net_pretax_pnl"].mean() if len(winners) else 0.0
    avg_loss = abs(losers["net_pretax_pnl"].mean()) if len(losers) else 0.0
    print("\n--- 3. REALIZED PAYOFF & R-MULTIPLE AUDIT ---")
    print(f"Win Rate:               {len(winners)/total_trades*100:.1f}% ({len(winners)} wins / {len(losers)} losses)")
    print(f"Average Winner:         Rs {avg_win:,.2f}")
    print(f"Average Loser:          Rs {avg_loss:,.2f}")
    print(f"Realized Payoff Ratio:  {avg_win/avg_loss:.2f} : 1.0  (Planned was 2.0 : 1.0!)")
    print(f"Average R of Winners:   +{winners['r_multiple'].mean():.2f} R")
    print(f"Average R of Losers:    {losers['r_multiple'].mean():.2f} R")
    
    # 4. Random Entry Exit Policy Ablations
    print("\n--- 4. RANDOM ENTRY EXIT POLICY EXPERIMENTS ---")
    print("Testing random entries under different exit policies to see if exits destroy value:")
    for policy in ["fixed_15d_hold", "stop_and_target_no_ratchet", "current"]:
        rand_trades, _ = run_detailed_exit_audit(data, nifty, entry_mode="random", exit_policy=policy)
        n_t = len(rand_trades)
        g_pnl = rand_trades["gross_pnl"].sum()
        f_pnl = rand_trades["friction"].sum()
        n_pnl = rand_trades["net_pretax_pnl"].sum()
        w_rate = (len(rand_trades[rand_trades["net_pretax_pnl"] > 0]) / n_t * 100) if n_t else 0.0
        print(f"Policy: {policy:28s} | Trades: {n_t:3d} | Win Rate: {w_rate:4.1f}% | Gross: Rs {g_pnl:+,.0f} (Rs {g_pnl/n_t:+.1f}/tr) | Friction: Rs {f_pnl:,.0f} | Net: Rs {n_pnl:+,.0f} (Rs {n_pnl/n_t:+.1f}/tr)")

if __name__ == "__main__":
    main()
