import os, sys, pickle, math
from collections import Counter
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scratch.test_compounded_apex import data_by_ticker, all_dates, ndf
from data.costs import compute_indian_delivery_costs

def run_high_utilization(max_open=4, pos_pct=0.25, allow_runner_extension=True):
    initial_cap = 100000.0
    cash = initial_cap
    portfolio_value = initial_cap
    trades = []
    daily_equity = []
    open_positions = {}
    pending_buys = []
    SLIPPAGE_PCT = 0.002

    for date_str in all_dates:
        mkt_ok = True
        if date_str in ndf.index:
            n_px = float(ndf["Close"].loc[date_str])
            n_sma = float(ndf["nifty_sma50"].loc[date_str])
            mkt_ok = (n_px >= n_sma) if not math.isnan(n_sma) else True

        # Open fills
        if pending_buys:
            for item in pending_buys:
                sym, alloc = item
                if sym in open_positions or len(open_positions) >= max_open:
                    continue
                df = data_by_ticker.get(sym)
                if df is None or date_str not in df.index:
                    continue
                row = df.loc[date_str]
                today_open = float(row["Open"] if "Open" in row and not math.isnan(row["Open"]) else row["Close"])
                if today_open <= 0 or math.isnan(today_open):
                    continue
                fill_px = round(today_open * (1.0 + SLIPPAGE_PCT), 2)
                trade_alloc = min(cash, alloc)
                qty = int(trade_alloc // fill_px)
                cost = qty * fill_px
                if qty > 0 and cash >= cost:
                    cash -= cost
                    stop_px = round(fill_px * 0.93, 2) # 7% Daily Close stop
                    target_px = round(fill_px * 1.20, 2) # 20% base target
                    open_positions[sym] = {
                        "entry_price": fill_px,
                        "qty": qty,
                        "stop_loss": stop_px,
                        "target": target_px,
                        "entry_date": date_str,
                        "peak_price": fill_px,
                        "days_held": 0,
                        "is_runner": False,
                    }
            pending_buys = []

        # Exits
        to_close = []
        for sym, pos in open_positions.items():
            df = data_by_ticker.get(sym)
            if df is None or date_str not in df.index:
                continue
            row = df.loc[date_str]
            high = float(row["High"])
            low = float(row["Low"])
            close = float(row["Close"])

            pos["days_held"] = pos.get("days_held", 0) + 1
            pos["peak_price"] = max(pos.get("peak_price", pos["entry_price"]), high)

            exit_reason = None
            exit_px = close

            # Daily close stop loss
            if close < pos["stop_loss"]:
                exit_reason = "STOP_LOSS_DAILY_CLOSE"
                exit_px = close
            elif high >= pos["target"]:
                if allow_runner_extension and not pos["is_runner"]:
                    # Turn into runner: lock stop at +10% and extend target to +35%
                    pos["is_runner"] = True
                    pos["stop_loss"] = max(pos["stop_loss"], round(pos["entry_price"] * 1.10, 2))
                    pos["target"] = round(pos["entry_price"] * 1.35, 2)
                    continue
                else:
                    exit_reason = "TARGET_HIT (+20% to +35%)"
                    exit_px = pos["target"]
            elif pos["days_held"] >= 21:
                gain_pct = round(((close - pos['entry_price']) / pos['entry_price']) * 100, 1)
                exit_reason = f"MAX_1_MONTH_EXPIRED (21d, {gain_pct:+.1f}%)"
                exit_px = close

            if exit_reason:
                costs = compute_indian_delivery_costs(pos["entry_price"], exit_px, pos["qty"])
                cash += (exit_px * pos["qty"]) - costs.total_friction_rupees
                trades.append({
                    "ticker": sym,
                    "entry_date": pos["entry_date"],
                    "exit_date": date_str,
                    "days_held": pos["days_held"],
                    "entry_price": pos["entry_price"],
                    "exit_price": round(exit_px, 2),
                    "quantity": pos["qty"],
                    "pnl": costs.net_pnl_rupees,
                    "pnl_percent": costs.net_pnl_pct,
                    "friction_costs": costs.total_friction_rupees,
                    "reason": exit_reason,
                })
                to_close.append(sym)

        for sym in to_close:
            del open_positions[sym]

        holdings_value = sum(
            float(data_by_ticker[sym]["Close"].loc[date_str]) * pos["qty"]
            for sym, pos in open_positions.items()
            if date_str in data_by_ticker[sym].index
        )
        # Add LiquidBees 6.5% annual return on unallocated cash
        cash += cash * (0.065 / 252.0)
        portfolio_value = cash + holdings_value
        daily_equity.append({"date": date_str, "equity": round(portfolio_value, 2)})

        # Scan for entries
        if mkt_ok and len(open_positions) < max_open:
            candidates = []
            for sym, df in data_by_ticker.items():
                if sym in open_positions or any(sym == p[0] for p in pending_buys):
                    continue
                if date_str not in df.index:
                    continue
                idx = df.index.get_loc(date_str)
                if idx < 60:
                    continue
                c_px = float(df["Close"].iloc[idx])
                if math.isnan(c_px) or c_px <= 0:
                    continue
                
                sma50 = float(df["sma_50"].iloc[idx])
                sma200 = float(df["sma_200"].iloc[idx])
                ema10 = float(df["ema_10"].iloc[idx])
                ema20 = float(df["ema_20"].iloc[idx])
                rv = float(df["rvol"].iloc[idx])
                pct_52w = float(df["pct_from_52w"].iloc[idx])
                h20 = float(df["high_20"].iloc[idx])
                
                if sma50 > sma200 and ema10 > ema20 and c_px >= sma50:
                    if pct_52w >= -15.0 and rv >= 1.25 and c_px >= (h20 * 0.98):
                        score = rv * 10.0 + (100.0 + pct_52w)
                        empty_slots = max_open - len(open_positions)
                        alloc = min(cash / max(1, empty_slots), portfolio_value * pos_pct)
                        candidates.append((sym, alloc, score))

            candidates.sort(key=lambda x: x[2], reverse=True)
            for c in candidates[:max_open - len(open_positions)]:
                pending_buys.append((c[0], c[1]))

    daily_eq_df = pd.DataFrame(daily_equity)
    daily_eq_df["date"] = pd.to_datetime(daily_eq_df["date"])
    daily_eq_df.set_index("date", inplace=True)
    monthly_eq = daily_eq_df["equity"].resample("ME").last()
    monthly_df = pd.DataFrame({
        "ending": monthly_eq,
        "starting": monthly_eq.shift(1).fillna(100000.0)
    })
    monthly_df["pnl"] = monthly_df["ending"] - monthly_df["starting"]
    monthly_df["ret_pct"] = (monthly_df["pnl"] / monthly_df["starting"]) * 100.0
    monthly_df = monthly_df.iloc[1:]

    return {
        "final_capital": round(portfolio_value, 2),
        "total_return": round(((portfolio_value - initial_cap) / initial_cap) * 100.0, 2),
        "avg_monthly_pnl": round(monthly_df["pnl"].mean(), 2),
        "avg_monthly_pct": round(monthly_df["ret_pct"].mean(), 2),
        "win_rate_months": round((monthly_df["pnl"] > 0).mean() * 100.0, 1),
        "best_month_pct": round(monthly_df["ret_pct"].max(), 2),
        "worst_month_pct": round(monthly_df["ret_pct"].min(), 2),
        "total_trades": len(trades),
    }

if __name__ == "__main__":
    for slots in [3, 4, 5]:
        p_pct = 1.0 / slots
        res = run_high_utilization(max_open=slots, pos_pct=p_pct)
        print(f"Slots: {slots} ({p_pct*100:2.0f}% per slot) -> Final: Rs.{res['final_capital']:10,.0f} ({res['total_return']:+7.2f}%) | Avg Monthly Profit: Rs.{res['avg_monthly_pnl']:+6.0f}/mo ({res['avg_monthly_pct']:+4.2f}%/mo) | Monthly Win Rate: {res['win_rate_months']}% | Best Mo: +{res['best_month_pct']}% | Worst Mo: {res['worst_month_pct']}%")

