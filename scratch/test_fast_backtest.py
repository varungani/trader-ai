import os, sys, time, pickle, math
from collections import Counter
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import RISK_CONFIG, MIN_DELIVERY_TICKET_RUPEES
from data.market_data import _load_all_caches, fetch_stock_history
from analysis.technical import compute_technical_score
from data.costs import compute_indian_delivery_costs

def fast_backtest(tickers, period="2y", initial_capital=100000.0, allow_runners=True, use_trailing_stop=True, use_trend_filter=True):
    t0 = time.time()
    data_by_ticker = {}
    for t in tickers:
        df = fetch_stock_history(t, period=period)
        if not df.empty and len(df) >= 60:
            d = df.copy()
            if isinstance(d.columns, pd.MultiIndex):
                d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
            d.index = d.index.strftime("%Y-%m-%d")
            d = d[~d.index.duplicated(keep="last")]
            d["sma_50"] = d["Close"].rolling(50).mean()
            d["atr_14"] = (d["High"] - d["Low"]).rolling(14).mean()
            data_by_ticker[t] = d

    if not data_by_ticker:
        return {"error": "No data"}

    all_dates = sorted(list(set.union(*[set(df.index) for df in data_by_ticker.values()])))
    print(f"Loaded {len(data_by_ticker)} tickers across {len(all_dates)} dates in {time.time()-t0:.2f}s")

    cash = initial_capital
    portfolio_value = initial_capital
    trades = []
    daily_equity = []
    open_positions = {}
    pending_buys = []
    SLIPPAGE_PCT = 0.002
    max_open = RISK_CONFIG.get("max_open_positions", 5)
    max_pos_pct = RISK_CONFIG.get("max_position_pct", 0.20)
    sl_pct = RISK_CONFIG.get("default_stop_loss_pct", 0.05)
    tp_pct = RISK_CONFIG.get("default_target_pct", 0.12)
    buy_score_min = RISK_CONFIG.get("min_score_to_buy", 65)

    sim_start = time.time()
    for date_str in all_dates:
        # Step 1: Execute pending buys at today's open + slippage
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
                ticket_floor = min(cash, MIN_DELIVERY_TICKET_RUPEES)
                trade_alloc = max(alloc, ticket_floor)
                trade_alloc = min(cash, trade_alloc)
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

            if pos.get("is_runner") and use_trailing_stop and pos.get("atr"):
                trailing_level = round(pos["peak_price"] - (2.0 * pos["atr"]), 2)
                pos["stop_loss"] = max(pos["stop_loss"], trailing_level)

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
                if allow_runners and not pos.get("is_runner"):
                    pos["is_runner"] = True
                    pos["stop_loss"] = max(pos["stop_loss"], round(pos["entry_price"] * 1.08, 2))
                    pos["target"] = round(pos["entry_price"] * 1.60, 2)
                    continue
                else:
                    exit_reason = "RUNNER_TARGET (+60%)" if pos.get("is_runner") else "TARGET"
                    exit_px = pos["target"]
            elif pos["days_held"] >= 21:
                exit_reason = f"MAX_1_MONTH_EXPIRED (21 Sessions, {round(((close - pos['entry_price'])/pos['entry_price'])*100, 1):+.1f}%)"
                exit_px = close
            elif pos["days_held"] >= 15 and not (pos.get("is_runner") and close > pos["entry_price"] * 1.05):
                exit_reason = "SWING_TIME_EXPIRED (15 Sessions)"
                exit_px = close

            if exit_reason:
                if pos.get("is_runner") and "TRAILING" in str(exit_reason):
                    exit_reason = f"RUNNER_TRAILING_EXIT (+{round(((exit_px - pos['entry_price'])/pos['entry_price'])*100, 1)}%)"
                costs = compute_indian_delivery_costs(
                    buy_price=pos["entry_price"],
                    sell_price=exit_px,
                    quantity=pos["qty"],
                )
                net_pnl = costs.net_pnl_rupees
                net_pnl_pct = costs.net_pnl_pct
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
                    "pnl_percent": net_pnl_pct,
                    "gross_pnl": costs.gross_pnl_rupees,
                    "friction_costs": friction,
                    "post_tax_pnl": costs.net_post_tax_pnl_rupees,
                    "stcg_tax": costs.stcg_tax_rupees,
                    "reason": exit_reason,
                })
                to_close.append(sym)

        for sym in to_close:
            del open_positions[sym]

        # Step 3: Scan for candidates
        if len(open_positions) < max_open:
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
                if use_trend_filter:
                    sma_50 = float(df["sma_50"].iloc[idx])
                    if not math.isnan(sma_50) and close_px < sma_50:
                        continue
                sub_df = df.iloc[max(0, idx - 99) : idx + 1]
                tech = compute_technical_score(sub_df, ticker=sym)
                score = float(tech.get("score", 50))
                if score >= buy_score_min:
                    atr_val = float(df["atr_14"].iloc[idx])
                    atr_est = atr_val if not math.isnan(atr_val) else (close_px * sl_pct)
                    atr_pct = (atr_est / close_px) * 100.0 if close_px > 0 else 5.0
                    actual_sl_pct = min(0.06, max(0.035, (atr_pct / 100.0) * 2.0))
                    actual_tp_pct = max(tp_pct, actual_sl_pct * 2.0)
                    base_cap = portfolio_value if (portfolio_value and not math.isnan(portfolio_value)) else cash
                    empty_slots = max_open - len(open_positions)
                    alloc = min(cash / max(1, empty_slots), base_cap * max_pos_pct)
                    candidates.append((sym, score, alloc, actual_sl_pct, actual_tp_pct, atr_est))

            candidates.sort(key=lambda x: x[1], reverse=True)
            for c in candidates[:max_open - len(open_positions)]:
                pending_buys.append((c[0], c[2], c[3], c[4], c[5]))

        # Step 4: Mark to Market
        holdings_value = sum(
            float(data_by_ticker[sym]["Close"].loc[date_str]) * pos["qty"]
            for sym, pos in open_positions.items()
            if date_str in data_by_ticker[sym].index
        )
        portfolio_value = cash + holdings_value
        daily_equity.append({"date": date_str, "equity": round(portfolio_value, 2)})

    print(f"Simulation loop completed in {time.time()-sim_start:.2f}s")
    
    # Calculate performance metrics
    eq_series = pd.Series([d["equity"] for d in daily_equity])
    ret_pct = ((portfolio_value - initial_capital) / initial_capital) * 100.0
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
    
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
    
    avg_days_held = round(sum(t["days_held"] for t in trades) / len(trades), 1) if trades else 0.0

    return {
        "period": period,
        "initial_capital": initial_capital,
        "final_capital": round(portfolio_value, 2),
        "total_return": round(ret_pct, 2),
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "payoff_ratio": payoff,
        "profit_factor": profit_factor,
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown": round(max_dd, 1),
        "avg_days_held": avg_days_held,
        "all_trades": trades,
        "daily_equity": daily_equity,
    }

if __name__ == "__main__":
    cache = _load_all_caches()
    tickers = [k for k, v in cache.items() if not k.startswith("^") and not k.endswith("BEES.NS") and len(v) >= 200]
    print(f"Testing fast backtest on {len(tickers)} tickers...")
    res_2y = fast_backtest(tickers[:80], period="2y")
    print(f"\n2Y Return: {res_2y['total_return']}% | Win Rate: {res_2y['win_rate']}% | Trades: {res_2y['total_trades']} | Sharpe: {res_2y['sharpe_ratio']} | Max DD: {res_2y['max_drawdown']}% | Avg Hold: {res_2y['avg_days_held']} sessions")

