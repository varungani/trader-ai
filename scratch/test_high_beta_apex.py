import os, sys, pickle, math
from collections import Counter
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.costs import compute_indian_delivery_costs

# Load High Beta Universe
hb_path = "data/cache/high_beta_universe.pkl"
b_path = "data/cache/benchmarks_5y.pkl"

with open(hb_path, "rb") as f:
    hb_data = pickle.load(f)

with open(b_path, "rb") as f:
    benchmarks = pickle.load(f)

ndf = benchmarks["^NSEI"].copy()
if isinstance(ndf.columns, pd.MultiIndex):
    ndf.columns = [c[0] if isinstance(c, tuple) else c for c in ndf.columns]
ndf.index = ndf.index.strftime("%Y-%m-%d")
ndf = ndf[~ndf.index.duplicated(keep="last")]
ndf["nifty_sma50"] = ndf["Close"].astype(float).rolling(50).mean()

data_by_ticker = {}
for t, df in hb_data.items():
    if not df.empty and len(df) >= 100:
        d = df.copy()
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
        d.columns = [str(c).capitalize() for c in d.columns]
        if not all(c in d.columns for c in ["Open", "High", "Low", "Close", "Volume"]):
            continue
        d.index = d.index.strftime("%Y-%m-%d")
        d = d[~d.index.duplicated(keep="last")]
        c = d["Close"].astype(float)
        h = d["High"].astype(float)
        l = d["Low"].astype(float)
        v = d["Volume"].astype(float)
        d["sma_50"] = c.rolling(50).mean()
        d["sma_200"] = c.rolling(min(200, len(c))).mean()
        d["ema_10"] = c.ewm(span=10).mean()
        d["ema_20"] = c.ewm(span=20).mean()
        d["vol_sma"] = v.rolling(20).mean()
        d["rvol"] = v / (d["vol_sma"] + 1e-6)
        d["high_52w"] = h.rolling(250).max().shift(1)
        d["pct_from_52w"] = ((c - d["high_52w"]) / d["high_52w"]) * 100.0
        d["high_20"] = h.rolling(20).max().shift(1)
        data_by_ticker[t] = d

all_dates = sorted(list(set.union(*[set(df.index) for df in data_by_ticker.values()])))
print(f"Loaded {len(data_by_ticker)} high-beta monster stocks across {len(all_dates)} trading dates...")

def run_high_beta_apex(slots=3, target_pct=0.25, stop_pct=0.07):
    pos_pct = 1.0 / slots
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

        # Fills
        if pending_buys:
            for item in pending_buys:
                sym, alloc = item
                if sym in open_positions or len(open_positions) >= slots:
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
                    stop_px = round(fill_px * (1 - stop_pct), 2)
                    target_px = round(fill_px * (1 + target_pct), 2)
                    open_positions[sym] = {
                        "entry_price": fill_px,
                        "qty": qty,
                        "stop_loss": stop_px,
                        "target": target_px,
                        "entry_date": date_str,
                        "peak_price": fill_px,
                        "days_held": 0,
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
                exit_reason = f"TARGET (+{round(target_pct*100, 1)}%)"
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
        portfolio_value = cash + holdings_value
        daily_equity.append({"date": date_str, "equity": round(portfolio_value, 2)})

        # Scan for entries
        if mkt_ok and len(open_positions) < slots:
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
                        empty_slots = slots - len(open_positions)
                        alloc = min(cash / max(1, empty_slots), portfolio_value * pos_pct)
                        candidates.append((sym, alloc, score))

            candidates.sort(key=lambda x: x[2], reverse=True)
            for c in candidates[:slots - len(open_positions)]:
                pending_buys.append((c[0], c[1]))

    daily_eq_df = pd.DataFrame(daily_equity)
    daily_eq_df["date"] = pd.to_datetime(daily_eq_df["date"])
    daily_eq_df.set_index("date", inplace=True)
    monthly_eq = daily_eq_df["equity"].resample("ME").last()
    monthly_df = pd.DataFrame({
        "ending": monthly_eq,
        "starting": monthly_eq.shift(1).fillna(initial_cap)
    })
    monthly_df["pnl"] = monthly_df["ending"] - monthly_df["starting"]
    monthly_df["ret_pct"] = (monthly_df["pnl"] / monthly_df["starting"]) * 100.0
    monthly_df = monthly_df.iloc[1:]

    return {
        "final_capital": round(portfolio_value, 2),
        "total_return": round(((portfolio_value - initial_cap) / initial_cap) * 100.0, 2),
        "win_rate": round((pd.Series([t['pnl'] for t in trades]) > 0).mean() * 100.0, 1),
        "total_trades": len(trades),
        "avg_pos_month": round(monthly_df[monthly_df["pnl"] > 0]["ret_pct"].mean(), 2),
        "best_month": round(monthly_df["ret_pct"].max(), 2),
        "cagr": round(((portfolio_value / initial_cap) ** (1.0 / (len(monthly_df) / 12.0)) - 1.0) * 100.0, 2),
        "all_trades": trades,
        "monthly_df": monthly_df,
    }

if __name__ == "__main__":
    for slots in [3, 4]:
        for tp in [0.20, 0.25]:
            res = run_high_beta_apex(slots=slots, target_pct=tp, stop_pct=0.07)
            mdf = res["monthly_df"]
            active_m = mdf[mdf["pnl"].abs() > 10.0]
            print(f"Slots: {slots} | Target: +{tp*100:2.0f}% -> Total: {res['total_return']:+7.2f}% | Final: Rs.{res['final_capital']:10,.0f} | Win: {res['win_rate']:4.1f}% | Avg Pos Mo: +{res['avg_pos_month']:4.1f}% | Active Mo Avg: +{active_m['ret_pct'].mean():4.2f}% (Rs.{active_m['pnl'].mean():+6.0f}/mo) | Best Mo: +{res['best_month']:4.1f}% | CAGR: +{res['cagr']:4.1f}%")
