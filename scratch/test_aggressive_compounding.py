import os, sys, time, pickle, math
from collections import Counter
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.market_data import _load_all_caches, fetch_stock_history
from data.costs import compute_indian_delivery_costs

cache = _load_all_caches()
nifty_df = cache.get("^NSEI")
if nifty_df is None:
    nifty_df = cache.get("NIFTYBEES.NS")

ndf = nifty_df.copy()
if isinstance(ndf.columns, pd.MultiIndex):
    ndf.columns = [c[0] if isinstance(c, tuple) else c for c in ndf.columns]
ndf.index = ndf.index.strftime("%Y-%m-%d")
ndf = ndf[~ndf.index.duplicated(keep="last")]

# Market indicators
n_close = ndf["Close"].astype(float)
ndf["nifty_ema20"] = n_close.ewm(span=20).mean()
ndf["nifty_sma50"] = n_close.rolling(50).mean()
# Confirmed Bull Regime: Nifty above 20 EMA and 20 EMA above 50 SMA
ndf["super_bull"] = (n_close > ndf["nifty_ema20"]) & (ndf["nifty_ema20"] > ndf["nifty_sma50"])

tickers = [k for k, v in cache.items() if not k.startswith("^") and not k.endswith("BEES.NS") and len(v) >= 200]
print(f"Loading data for {len(tickers)} tickers across 5 years...")

data_by_ticker = {}
for t in tickers:
    df = fetch_stock_history(t, period="5y")
    if not df.empty and len(df) >= 150 and all(c in df.columns for c in ["Open", "High", "Low", "Close", "Volume"]):
        d = df.copy()
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
        d.index = d.index.strftime("%Y-%m-%d")
        d = d[~d.index.duplicated(keep="last")]
        
        c = d["Close"].astype(float)
        h = d["High"].astype(float)
        l = d["Low"].astype(float)
        v = d["Volume"].astype(float)
        
        d["sma_20"] = c.rolling(20).mean()
        d["sma_50"] = c.rolling(50).mean()
        d["sma_200"] = c.rolling(min(200, len(c))).mean()
        d["ema_10"] = c.ewm(span=10).mean()
        d["ema_20"] = c.ewm(span=20).mean()
        d["vol_sma"] = v.rolling(20).mean()
        d["rvol"] = v / (d["vol_sma"] + 1e-6)
        d["high_52w"] = h.rolling(250).max().shift(1)
        d["pct_from_52w"] = ((c - d["high_52w"]) / d["high_52w"]) * 100.0
        
        # 1-month Relative Strength vs NIFTY 50
        n_c_aligned = n_close.reindex(d.index, method="ffill")
        d["rs_21d"] = (c.pct_change(21) - n_c_aligned.pct_change(21)) * 100.0
        d["rs_5d"] = (c.pct_change(5) - n_c_aligned.pct_change(5)) * 100.0

        # Donchian 20-day high
        d["high_20"] = h.rolling(20).max().shift(1)
        
        high_low = h - l
        d["atr_14"] = high_low.rolling(14).mean()
        data_by_ticker[t] = d

all_dates = sorted(list(set.union(*[set(df.index) for df in data_by_ticker.values()])))

def run_apex_growth(max_open=4, pos_pct=0.25, compound=True, holding_sessions=21, target_pct=0.20, stop_pct=0.05, regime_filter="SUPER_BULL"):
    initial_cap = 100000.0
    cash = initial_cap
    portfolio_value = initial_cap
    trades = []
    daily_equity = []
    open_positions = {}
    pending_buys = []
    SLIPPAGE_PCT = 0.002

    for date_str in all_dates:
        # Market Regime Check
        regime_ok = True
        if date_str in ndf.index:
            if regime_filter == "SUPER_BULL":
                regime_ok = bool(ndf["super_bull"].loc[date_str])
            elif regime_filter == "MKT_ABOVE_50":
                n_px = float(ndf["Close"].loc[date_str])
                n_sma = float(ndf["nifty_sma50"].loc[date_str])
                regime_ok = (n_px >= n_sma) if not math.isnan(n_sma) else True
            else:
                regime_ok = True

        # Fills at Open
        if pending_buys:
            for item in pending_buys:
                sym, alloc, sl_p, tp_p = item
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
                    stop_px = round(fill_px * (1 - sl_p), 2)
                    target_px = round(fill_px * (1 + tp_p), 2)
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
            low = float(row["Low"])
            close = float(row["Close"])
            open_px = float(row["Open"] if "Open" in row else close)

            pos["days_held"] = pos.get("days_held", 0) + 1
            pos["peak_price"] = max(pos.get("peak_price", pos["entry_price"]), high)

            # Move stop to breakeven when gain >= 7%
            if pos["peak_price"] >= pos["entry_price"] * 1.07:
                pos["stop_loss"] = max(pos["stop_loss"], round(pos["entry_price"] * 1.01, 2))

            exit_reason = None
            exit_px = close

            if low <= pos["stop_loss"]:
                if pos["stop_loss"] > pos["entry_price"]:
                    exit_reason = "BREAKEVEN_GUARD"
                else:
                    exit_reason = "STOP_LOSS"
                exit_px = min(pos["stop_loss"], open_px) if open_px < pos["stop_loss"] else pos["stop_loss"]
            elif high >= pos["target"]:
                exit_reason = f"TARGET (+{round(target_pct*100, 1)}%)"
                exit_px = pos["target"]
            elif pos["days_held"] >= holding_sessions:
                gain_pct = round(((close - pos['entry_price']) / pos['entry_price']) * 100, 1)
                exit_reason = f"MAX_1_MONTH_EXPIRED ({holding_sessions}d, {gain_pct:+.1f}%)"
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
                    "gross_pnl": costs.gross_pnl_rupees,
                    "friction_costs": costs.total_friction_rupees,
                    "reason": exit_reason,
                })
                to_close.append(sym)

        for sym in to_close:
            del open_positions[sym]

        # Calculate current total equity
        holdings_value = sum(
            float(data_by_ticker[sym]["Close"].loc[date_str]) * pos["qty"]
            for sym, pos in open_positions.items()
            if date_str in data_by_ticker[sym].index
        )
        portfolio_value = cash + holdings_value
        daily_equity.append({"date": date_str, "equity": round(portfolio_value, 2)})

        # Entries: ONLY during confirmed regime
        if regime_ok and len(open_positions) < max_open:
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
                rs_21 = float(df["rs_21d"].iloc[idx])
                rs_5 = float(df["rs_5d"].iloc[idx])
                rv = float(df["rvol"].iloc[idx])
                pct_52w = float(df["pct_from_52w"].iloc[idx])
                h20 = float(df["high_20"].iloc[idx])
                
                # APEX ELITE ALPHA FILTER:
                # 1. Structural Leader: 50 SMA > 200 SMA and 10 EMA > 20 EMA
                # 2. Extreme Relative Strength: Outperforming NIFTY over past 21 days by >= +5%
                # 3. Leading near 52W high: within 12% of 52W high
                # 4. Immediate Momentum: 5-day outperformance > 0% and RVOL >= 1.25x
                # 5. Breakout or tight thrust near 20d high: close within 1.5% of 20d high
                if sma50 > sma200 and ema10 > ema20 and c_px >= sma50:
                    if rs_21 >= 5.0 and pct_52w >= -12.0 and rs_5 >= 1.0 and rv >= 1.25 and c_px >= (h20 * 0.985):
                        score = rs_21 * 2.0 + rv * 10.0 + (100.0 + pct_52w)
                        base_cap = portfolio_value if compound else initial_cap
                        empty_slots = max_open - len(open_positions)
                        alloc = min(cash / max(1, empty_slots), base_cap * pos_pct)
                        candidates.append((sym, alloc, stop_pct, target_pct, score))

            candidates.sort(key=lambda x: x[4], reverse=True)
            for c in candidates[:max_open - len(open_positions)]:
                pending_buys.append((c[0], c[1], c[2], c[3]))

    eq_series = pd.Series([d["equity"] for d in daily_equity])
    ret_pct = ((portfolio_value - initial_cap) / initial_cap) * 100.0
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0
    cummax = eq_series.cummax()
    dd = (cummax - eq_series) / cummax * 100.0
    max_dd = float(dd.max()) if not dd.empty else 0.0
    daily_rets = eq_series.pct_change().dropna()
    sharpe = float((daily_rets.mean() / (daily_rets.std() + 1e-9)) * np.sqrt(252)) if len(daily_rets) > 1 else 0.0
    avg_win = (sum(t["pnl"] for t in wins) / len(wins)) if wins else 0.0
    avg_loss = (abs(sum(t["pnl"] for t in losses)) / len(losses)) if losses else 0.0
    payoff = round(avg_win / avg_loss, 2) if avg_loss > 0 else 0.0

    return {
        "regime": regime_filter,
        "compound": compound,
        "max_open": max_open,
        "target_pct": target_pct,
        "stop_pct": stop_pct,
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "total_return": round(ret_pct, 2),
        "final_capital": round(portfolio_value, 2),
        "net_pnl": round(sum(t["pnl"] for t in trades), 2),
        "friction": round(sum(t["friction_costs"] for t in trades), 2),
        "payoff_ratio": payoff,
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown": round(max_dd, 1),
        "avg_days_held": round(sum(t["days_held"] for t in trades) / len(trades), 1) if trades else 0,
        "all_trades": trades,
    }

if __name__ == "__main__":
    print("Testing Non-Compounded vs Compounded Apex Super-Growth...")
    for comp in [False, True]:
        for reg in ["MKT_ABOVE_50", "SUPER_BULL"]:
            for tp in [0.15, 0.20]:
                res = run_apex_growth(max_open=4, pos_pct=0.25, compound=comp, holding_sessions=21, target_pct=tp, stop_pct=0.045, regime_filter=reg)
                print(f"Comp={str(comp):5s} | Reg={reg:12s} | Target=+{tp*100:2.0f}% -> Ret: {res['total_return']:+7.2f}% (Rs.{res['net_pnl']:+9,.0f}) | Win: {res['win_rate']:4.1f}% | Trades: {res['total_trades']:3d} | Sharpe: {res['sharpe_ratio']:+4.2f} | DD: -{res['max_drawdown']:4.1f}% | Payoff: {res['payoff_ratio']}:1 | Friction: Rs.{res['friction']:5,.0f}")

