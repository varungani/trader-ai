import os, sys, time, pickle, math
from collections import Counter
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import RISK_CONFIG, MIN_DELIVERY_TICKET_RUPEES
from data.market_data import _load_all_caches, fetch_stock_history
from analysis.technical import compute_technical_score
from data.costs import compute_indian_delivery_costs

def test_alpha_strategy(tickers, period="2y", min_rvol=1.3, use_market_filter=True, max_holding_days=21):
    cache = _load_all_caches()
    nifty_df = cache.get("^NSEI")
    if nifty_df is None:
        nifty_df = cache.get("NIFTYBEES.NS")
        
    nifty_sma50 = None
    if nifty_df is not None:
        ndf = nifty_df.copy()
        if isinstance(ndf.columns, pd.MultiIndex):
            ndf.columns = [c[0] if isinstance(c, tuple) else c for c in ndf.columns]
        ndf.index = ndf.index.strftime("%Y-%m-%d")
        ndf = ndf[~ndf.index.duplicated(keep="last")]
        if "Close" in ndf.columns:
            nifty_sma50 = ndf["Close"].rolling(50).mean()

    data_by_ticker = {}
    for t in tickers:
        df = fetch_stock_history(t, period=period)
        if not df.empty and len(df) >= 60 and all(c in df.columns for c in ["Open", "High", "Low", "Close", "Volume"]):
            d = df.copy()
            if isinstance(d.columns, pd.MultiIndex):
                d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
            d.index = d.index.strftime("%Y-%m-%d")
            d = d[~d.index.duplicated(keep="last")]
            d["sma_50"] = d["Close"].rolling(50).mean()
            d["ema_10"] = d["Close"].ewm(span=10).mean()
            d["ema_20"] = d["Close"].ewm(span=20).mean()
            d["vol_sma"] = d["Volume"].rolling(20).mean()
            d["rvol"] = d["Volume"] / (d["vol_sma"] + 1e-6)
            d["high_20"] = d["High"].rolling(20).max().shift(1)
            high_low = d["High"] - d["Low"]
            d["atr_14"] = high_low.rolling(14).mean()
            data_by_ticker[t] = d

    all_dates = sorted(list(set.union(*[set(df.index) for df in data_by_ticker.values()])))

    cash = 100000.0
    portfolio_value = 100000.0
    trades = []
    daily_equity = []
    open_positions = {}
    pending_buys = []
    SLIPPAGE_PCT = 0.002
    max_open = 5
    max_pos_pct = 0.20

    for date_str in all_dates:
        # Check market filter
        mkt_ok = True
        if use_market_filter and nifty_sma50 is not None and date_str in nifty_sma50.index and date_str in nifty_df.index:
            n_px = float(nifty_df["Close"].loc[date_str])
            n_sma = float(nifty_sma50.loc[date_str])
            mkt_ok = (n_px >= n_sma) if not math.isnan(n_sma) else True

        # Step 1: Execute pending buys at open
        if pending_buys:
            for item in pending_buys:
                sym, alloc, actual_sl_pct, actual_tp_pct, atr_est = item
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
                trade_alloc = min(cash, max(alloc, min(cash, 10000.0)))
                qty = int(trade_alloc // fill_px)
                cost = qty * fill_px
                if qty > 0 and cash >= cost:
                    cash -= cost
                    stop_px = round(fill_px * (1 - actual_sl_pct), 2)
                    target_px = round(fill_px * (1 + actual_tp_pct), 2)
                    open_positions[sym] = {
                        "entry_price": fill_px,
                        "qty": qty,
                        "initial_stop": stop_px,
                        "stop_loss": stop_px,
                        "target": target_px,
                        "entry_date": date_str,
                        "peak_price": fill_px,
                        "atr": atr_est,
                        "days_held": 0,
                    }
            pending_buys = []

        # Step 2: Check exits on active positions
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

            # Breakeven lock when up +7%
            if not pos.get("breakeven_set") and pos["peak_price"] >= pos["entry_price"] * 1.07:
                pos["stop_loss"] = max(pos["stop_loss"], round(pos["entry_price"] * 1.01, 2))
                pos["breakeven_set"] = True

            # Trailing stop for runners
            if pos.get("is_runner") and pos.get("atr"):
                trailing_level = round(pos["peak_price"] - (1.8 * pos["atr"]), 2)
                pos["stop_loss"] = max(pos["stop_loss"], trailing_level)

            exit_reason = None
            exit_px = close

            # Stop loss hit
            if low <= pos["stop_loss"]:
                if pos["stop_loss"] > pos["entry_price"]:
                    exit_reason = "TRAILING_STOP_PROFIT"
                elif pos["stop_loss"] == round(pos["entry_price"] * 1.01, 2):
                    exit_reason = "BREAKEVEN_STOP"
                else:
                    exit_reason = "STOP_LOSS"
                exit_px = min(pos["stop_loss"], open_px) if open_px < pos["stop_loss"] else pos["stop_loss"]
            # Target 1 hit (+15%) -> Unlock Runner
            elif high >= pos["target"]:
                if not pos.get("is_runner"):
                    pos["is_runner"] = True
                    pos["stop_loss"] = max(pos["stop_loss"], round(pos["entry_price"] * 1.08, 2))
                    pos["target"] = round(pos["entry_price"] * 1.50, 2) # extend runner target to +50%
                    continue
                else:
                    exit_reason = "RUNNER_SUPER_TARGET (+50%)"
                    exit_px = pos["target"]
            # Hard 1-Month Window Exit (Strict Day 21)
            elif pos["days_held"] >= max_holding_days:
                gain_pct = round(((close - pos['entry_price']) / pos['entry_price']) * 100, 1)
                exit_reason = f"MAX_1_MONTH_EXPIRED ({max_holding_days}d, {gain_pct:+.1f}%)"
                exit_px = close

            if exit_reason:
                costs = compute_indian_delivery_costs(
                    buy_price=pos["entry_price"],
                    sell_price=exit_px,
                    quantity=pos["qty"],
                )
                net_pnl = costs.net_pnl_rupees
                friction = costs.total_friction_rupees
                cash += (exit_px * pos["qty"]) - friction
                trades.append({
                    "ticker": sym,
                    "entry_date": pos["entry_date"],
                    "exit_date": date_str,
                    "days_held": pos["days_held"],
                    "entry_price": pos["entry_price"],
                    "exit_price": round(exit_px, 2),
                    "quantity": pos["qty"],
                    "pnl": net_pnl,
                    "pnl_percent": costs.net_pnl_pct,
                    "gross_pnl": costs.gross_pnl_rupees,
                    "friction_costs": friction,
                    "reason": exit_reason,
                })
                to_close.append(sym)

        for sym in to_close:
            del open_positions[sym]

        # Step 3: Scan for candidates (ONLY if Market Regime is OK)
        if mkt_ok and len(open_positions) < max_open:
            candidates = []
            for sym, df in data_by_ticker.items():
                if sym in open_positions or any(sym == p[0] for p in pending_buys):
                    continue
                if date_str not in df.index:
                    continue
                idx = df.index.get_loc(date_str)
                if idx < 49:
                    continue
                close_px = float(df["Close"].iloc[idx])
                if math.isnan(close_px) or close_px <= 0:
                    continue
                
                # Filter 1: Stage 2 Uptrend (Close > 50 SMA and 10 EMA > 20 EMA)
                sma_50 = float(df["sma_50"].iloc[idx])
                ema_10 = float(df["ema_10"].iloc[idx])
                ema_20 = float(df["ema_20"].iloc[idx])
                if close_px < sma_50 or ema_10 < ema_20:
                    continue

                # Filter 2: Institutional Ignition (RVOL >= min_rvol)
                rv = float(df["rvol"].iloc[idx])
                if math.isnan(rv) or rv < min_rvol:
                    continue

                # Filter 3: Momentum breakout near 20-day high (within 2.5% of 20d high)
                h20 = float(df["high_20"].iloc[idx])
                if math.isnan(h20) or close_px < (h20 * 0.975):
                    continue

                # Score candidate
                sub_df = df.iloc[max(0, idx - 99) : idx + 1]
                tech = compute_technical_score(sub_df, ticker=sym)
                score = float(tech.get("score", 50))
                
                if score >= 65:
                    atr_val = float(df["atr_14"].iloc[idx])
                    atr_est = atr_val if not math.isnan(atr_val) else (close_px * 0.05)
                    # Adaptive Stop: 4.5% to 6.5% based on ATR
                    atr_pct = (atr_est / close_px) * 100.0 if close_px > 0 else 5.0
                    actual_sl_pct = min(0.065, max(0.045, (atr_pct / 100.0) * 1.8))
                    actual_tp_pct = 0.15 # Base 15% target
                    base_cap = portfolio_value if (portfolio_value and not math.isnan(portfolio_value)) else cash
                    empty_slots = max_open - len(open_positions)
                    alloc = min(cash / max(1, empty_slots), base_cap * max_pos_pct)
                    candidates.append((sym, score, alloc, actual_sl_pct, actual_tp_pct, atr_est))

            candidates.sort(key=lambda x: x[1], reverse=True)
            for c in candidates[:max_open - len(open_positions)]:
                pending_buys.append((c[0], c[2], c[3], c[4], c[5]))

        # Daily Mark-to-market
        holdings_value = sum(
            float(data_by_ticker[sym]["Close"].loc[date_str]) * pos["qty"]
            for sym, pos in open_positions.items()
            if date_str in data_by_ticker[sym].index
        )
        portfolio_value = cash + holdings_value
        daily_equity.append({"date": date_str, "equity": round(portfolio_value, 2)})

    eq_series = pd.Series([d["equity"] for d in daily_equity])
    ret_pct = ((portfolio_value - 100000.0) / 100000.0) * 100.0
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
    gross_pnl = sum(t["gross_pnl"] for t in trades)
    net_pnl = sum(t["pnl"] for t in trades)
    friction = sum(t["friction_costs"] for t in trades)
    runners = sum(1 for t in trades if t["pnl_percent"] >= 15.0)

    return {
        "period": period,
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "total_return": round(ret_pct, 2),
        "final_capital": round(portfolio_value, 2),
        "gross_pnl": round(gross_pnl, 2),
        "net_pnl": round(net_pnl, 2),
        "friction": round(friction, 2),
        "payoff_ratio": payoff,
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown": round(max_dd, 1),
        "avg_days_held": round(sum(t["days_held"] for t in trades) / len(trades), 1) if trades else 0,
        "runners_15pct_plus": runners,
        "all_trades": trades,
    }

if __name__ == "__main__":
    cache = _load_all_caches()
    tickers = [k for k, v in cache.items() if not k.startswith("^") and not k.endswith("BEES.NS") and len(v) >= 200]
    
    print("Testing Institutional Alpha Strategy (2-Year: 2024–2026)...")
    res_2y = test_alpha_strategy(tickers, period="2y", min_rvol=1.3, use_market_filter=True, max_holding_days=21)
    print(f"2Y Net Return:       {res_2y['total_return']:+.2f}%")
    print(f"2Y Win Rate:         {res_2y['win_rate']}% ({res_2y['wins']}W / {res_2y['losses']}L on {res_2y['total_trades']} trades)")
    print(f"2Y Payoff Ratio:     {res_2y['payoff_ratio']}:1")
    print(f"2Y Sharpe Ratio:     {res_2y['sharpe_ratio']}")
    print(f"2Y Max Drawdown:     -{res_2y['max_drawdown']}%")
    print(f"2Y Total Friction:   Rs. {res_2y['friction']:,.1f}")
    print(f"2Y Avg Days Held:    {res_2y['avg_days_held']} sessions (Strict <= 21 Sessions)")
    print(f"2Y Monster Runners:  {res_2y['runners_15pct_plus']} trades >= +15%")

    print("\nTesting Institutional Alpha Strategy (5-Year: 2021–2026)...")
    res_5y = test_alpha_strategy(tickers, period="5y", min_rvol=1.3, use_market_filter=True, max_holding_days=21)
    print(f"5Y Net Return:       {res_5y['total_return']:+.2f}%")
    print(f"5Y Win Rate:         {res_5y['win_rate']}% ({res_5y['wins']}W / {res_5y['losses']}L on {res_5y['total_trades']} trades)")
    print(f"5Y Payoff Ratio:     {res_5y['payoff_ratio']}:1")
    print(f"5Y Sharpe Ratio:     {res_5y['sharpe_ratio']}")
    print(f"5Y Max Drawdown:     -{res_5y['max_drawdown']}%")
    print(f"5Y Total Friction:   Rs. {res_5y['friction']:,.1f}")
    print(f"5Y Avg Days Held:    {res_5y['avg_days_held']} sessions (Strict <= 21 Sessions)")
    print(f"5Y Monster Runners:  {res_5y['runners_15pct_plus']} trades >= +15%")

