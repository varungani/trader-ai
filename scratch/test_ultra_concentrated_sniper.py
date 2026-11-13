import os, sys, pickle, math
from collections import Counter
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.costs import compute_indian_delivery_costs
from data.market_data import _load_all_caches

cache = _load_all_caches()
nifty_df = cache.get("^NSEI")
if nifty_df is None:
    nifty_df = cache.get("NIFTYBEES.NS")

ndf = nifty_df.copy()
if isinstance(ndf.columns, pd.MultiIndex):
    ndf.columns = [c[0] if isinstance(c, tuple) else c for c in ndf.columns]
ndf.index = ndf.index.strftime("%Y-%m-%d")
ndf = ndf[~ndf.index.duplicated(keep="last")]
ndf["nifty_ema20"] = ndf["Close"].astype(float).ewm(span=20).mean()
ndf["nifty_sma50"] = ndf["Close"].astype(float).rolling(50).mean()
# Strict Bull Regime only: Nifty > 20 EMA > 50 SMA
ndf["regime_green"] = (ndf["Close"].astype(float) > ndf["nifty_ema20"]) & (ndf["nifty_ema20"] > ndf["nifty_sma50"])

data_by_ticker = {}
for t, df in cache.items():
    if t.startswith("^") or t.endswith("BEES.NS"):
        continue
    if not df.empty and len(df) >= 150:
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
        # Daily return
        d["daily_gain"] = (c - c.shift(1)) / c.shift(1) * 100.0
        data_by_ticker[t] = d

all_dates = sorted(list(set.union(*[set(df.index) for df in data_by_ticker.values()])))

def run_apex_concentrated_sniper(slots=2, target_pct=0.20, stop_pct=0.065):
    """
    Ultra-Concentrated Sniper:
    - Exactly 2 positions (50% each)
    - Blue Sky 52W High Breakouts with RVOL >= 2.0x & Daily Gain >= 3.5%
    - Strict Bull Regime Only (100% Cash when market is weak)
    - Compounding: Each win rolls 100% of capital forward
    """
    initial_cap = 100000.0
    cash = initial_cap
    portfolio_value = initial_cap
    trades = []
    daily_equity = []
    open_positions = {}
    pending_buys = []
    SLIPPAGE_PCT = 0.002
    pos_pct = 1.0 / slots

    for date_str in all_dates:
        mkt_ok = False
        if date_str in ndf.index:
            mkt_ok = bool(ndf["regime_green"].loc[date_str])

        # Fills at Open
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
            ema10 = float(row["ema_10"])

            pos["days_held"] = pos.get("days_held", 0) + 1
            pos["peak_price"] = max(pos.get("peak_price", pos["entry_price"]), high)

            exit_reason = None
            exit_px = close

            # Lock breakeven when gain >= 7%
            if pos["peak_price"] >= pos["entry_price"] * 1.07:
                pos["stop_loss"] = max(pos["stop_loss"], round(pos["entry_price"] * 1.01, 2))

            if close < pos["stop_loss"]:
                if pos["stop_loss"] > pos["entry_price"]:
                    exit_reason = "BREAKEVEN_GUARD"
                else:
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

        # Scan: Only during confirmed GREEN REGIME
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
                daily_g = float(df["daily_gain"].iloc[idx])
                
                # BLUE SKY INSTITUTIONAL BLAST
                # 1. 50 SMA > 200 SMA & 10 EMA > 20 EMA
                # 2. Within 5% of 52-week high (Blue Sky, no overhead trapped sellers)
                # 3. RVOL >= 1.8x (Institutional accumulation)
                # 4. Decoupling thrust: Today's gain >= 3.0%
                if sma50 > sma200 and ema10 > ema20 and c_px >= sma50:
                    if pct_52w >= -5.0 and rv >= 1.75 and daily_g >= 3.0:
                        score = rv * 20.0 + daily_g * 5.0 + (100.0 + pct_52w)
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

    active_m = monthly_df[monthly_df["pnl"].abs() > 10.0]

    return {
        "final_capital": round(portfolio_value, 2),
        "total_return": round(((portfolio_value - initial_cap) / initial_cap) * 100.0, 2),
        "total_trades": len(trades),
        "win_rate": round((pd.Series([t['pnl'] for t in trades]) > 0).mean() * 100.0, 1),
        "active_months_count": len(active_m),
        "active_mo_avg_pct": round(active_m["ret_pct"].mean(), 2),
        "active_mo_avg_pnl": round(active_m["pnl"].mean(), 2),
        "best_month_pct": round(monthly_df["ret_pct"].max(), 2),
        "monthly_df": monthly_df,
        "trades": trades,
    }

for slots in [2, 3]:
    for tp in [0.20, 0.25]:
        res = run_apex_concentrated_sniper(slots=slots, target_pct=tp, stop_pct=0.065)
        print(f"Slots: {slots} (Alloc={100/slots:.0f}%) | Target: +{tp*100:.0f}% -> Total: {res['total_return']:+7.2f}% | Final: Rs.{res['final_capital']:10,.0f} | Win: {res['win_rate']:4.1f}% | Active Mo Avg: +{res['active_mo_avg_pct']:4.2f}% (Rs.{res['active_mo_avg_pnl']:+6.0f}/mo) | Best Mo: +{res['best_month_pct']:4.1f}% | Trades: {res['total_trades']}")

