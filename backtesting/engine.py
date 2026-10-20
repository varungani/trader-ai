"""
TraderAI - Historical Backtesting Engine
Evaluates multi-factor recommendation strategies against historical market data.
Persists results to SQLite backtest_results table.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta
import math
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import RISK_CONFIG, TIMEFRAMES
from data.db import get_connection, save_backtest_result
from data.market_data import fetch_stock_history
from analysis.technical import compute_technical_score

logger = logging.getLogger(__name__)


def run_simple_backtest(
    tickers: list[str],
    timeframe: str = "short_term",
    period: str = "2y",
    initial_capital: float = 100000.0,
    strategy_name: str = "TraderAI Multi-Factor Rules",
    stop_loss_pct: Optional[float] = None,
    target_pct: Optional[float] = None,
    use_trailing_stop: bool = True,
    use_trend_filter: bool = True,
    min_score_to_buy: Optional[float] = None,
    max_position_pct: Optional[float] = None,
    allow_runners: bool = True,
) -> dict:
    """
    Simulate trading rules on historical stock data with risk-managed exits.
    
    Args:
        tickers: List of NSE tickers (e.g., ['RELIANCE.NS', 'TCS.NS'])
        timeframe: 'short_term', 'mid_term', or 'long_term'
        period: Historical period (e.g., '1y', '2y')
        initial_capital: Starting capital in INR
        strategy_name: Identifier for database
        stop_loss_pct: Stop loss fraction (default from config: 0.07)
        target_pct: Target gain fraction (default from config: 0.15)
        use_trailing_stop: If True, trails stop to lock in profits on rallies
        use_trend_filter: If True, only enters trades when price is above 50-day SMA
        min_score_to_buy: Min multi-factor score to enter (default: 65)
        max_position_pct: Max fraction of portfolio per position (e.g. 0.25 for 25%)
    
    Returns:
        Dict with metrics (return, win rate, sharpe, max drawdown, trades)
    """
    logger.info(f"Running backtest for {len(tickers)} tickers over {period} ({timeframe}) [trailing={use_trailing_stop}, trend_filter={use_trend_filter}]")
    
    cash = initial_capital
    portfolio_value = initial_capital
    trades = []
    daily_equity = []
    
    sl_pct = stop_loss_pct if stop_loss_pct is not None else RISK_CONFIG.get("default_stop_loss_pct", 0.05)
    tp_pct = target_pct if target_pct is not None else RISK_CONFIG.get("default_target_pct", 0.12)
    buy_score_min = min_score_to_buy if min_score_to_buy is not None else RISK_CONFIG.get("min_score_to_buy", 65)
    if max_position_pct is not None:
        max_pos_pct = max_position_pct
    else:
        max_pos_pct = RISK_CONFIG.get("max_position_pct", 0.20)
    
    # Download data for all tickers
    data_by_ticker = {}
    for t in tickers:
        df = fetch_stock_history(t, period=period)
        if not df.empty and len(df) >= 60:
            data_by_ticker[t] = df
            
    if not data_by_ticker:
        return {"error": "No historical data found for given tickers."}
        
    # Get common date index
    all_dates = sorted(
        list(set.union(*[set(df.index.strftime("%Y-%m-%d")) for df in data_by_ticker.values()]))
    )
    
    open_positions = {}  # ticker -> {entry_price, qty, stop_loss, target, entry_date, peak_price, atr, days_held}
    
    for date_str in all_dates:
        # Check exits first
        to_close = []
        for sym, pos in open_positions.items():
            df = data_by_ticker.get(sym)
            if df is None:
                continue
            day_rows = df[df.index.strftime("%Y-%m-%d") == date_str]
            if day_rows.empty:
                continue
            
            high = float(day_rows["High"].iloc[0])
            low = float(day_rows["Low"].iloc[0])
            close = float(day_rows["Close"].iloc[0])
            open_px = float(day_rows["Open"].iloc[0]) if "Open" in day_rows else close

            pos["days_held"] = pos.get("days_held", 0) + 1
            pos["peak_price"] = max(pos.get("peak_price", pos["entry_price"]), high)

            # Unshackled Exit Policy: Give trades breathing room to reach 2:1 R:R target.
            # Trailing stops and breakeven locks only engage after base target is achieved.
            initial_risk = pos["entry_price"] - pos["initial_stop"]
            if pos.get("is_runner") and use_trailing_stop and pos.get("atr"):
                trailing_level = round(pos["peak_price"] - (2.0 * pos["atr"]), 2)
                pos["stop_loss"] = max(pos["stop_loss"], trailing_level)

            exit_reason = None
            exit_px = close
            
            # Priority 1: Stop-loss / gap-down hit
            if low <= pos["stop_loss"]:
                if pos["stop_loss"] > pos["entry_price"]:
                    exit_reason = "TRAILING_STOP"
                elif pos["stop_loss"] == pos["entry_price"]:
                    exit_reason = "BREAKEVEN_STOP"
                else:
                    exit_reason = "STOP_LOSS"
                # Realistic gap-down fill: min of stop, low, or open
                exit_px = min(pos["stop_loss"], open_px) if open_px < pos["stop_loss"] else pos["stop_loss"]
            # Priority 2: Target hit
            elif high >= pos["target"]:
                if allow_runners and not pos.get("is_runner"):
                    # Uncapped Runner: Lock in +8% minimum profit, extend target to +60%, and trail with ATR
                    pos["is_runner"] = True
                    pos["stop_loss"] = max(pos["stop_loss"], round(pos["entry_price"] * 1.08, 2))
                    pos["target"] = round(pos["entry_price"] * 1.60, 2)
                    continue
                else:
                    exit_reason = "RUNNER_TARGET (+60%)" if pos.get("is_runner") else "TARGET"
                    exit_px = pos["target"]
            # Priority 3: Time stop (20 trading sessions max hold, unless actively running in substantial profit)
            elif pos["days_held"] >= 20 and not (pos.get("is_runner") and close > pos["entry_price"] * 1.08):
                exit_reason = "TIME_STOP (20 Sessions)"
                exit_px = close
                
            if exit_reason:
                if pos.get("is_runner") and "TRAILING" in str(exit_reason):
                    exit_reason = f"RUNNER_TRAILING_EXIT (+{round(((exit_px - pos['entry_price'])/pos['entry_price'])*100, 1)}%)"
                from data.costs import compute_indian_delivery_costs
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
            
        # Check potential entries
        for sym, df in data_by_ticker.items():
            if sym in open_positions:
                continue
            if len(open_positions) >= RISK_CONFIG.get("max_open_positions", 5):
                break
                
            sub_df = df[df.index.strftime("%Y-%m-%d") <= date_str]
            if len(sub_df) < 50:
                continue
                
            close_px = float(sub_df["Close"].iloc[-1])
            if math.isnan(close_px) or close_px <= 0:
                continue

            # Trend filter: only take entries aligned with intermediate 50-day trend
            if use_trend_filter:
                sma_50 = sub_df["Close"].rolling(50).mean().iloc[-1]
                if not math.isnan(sma_50) and close_px < sma_50:
                    continue

            # Technical score evaluation
            tech = compute_technical_score(sub_df.tail(100), ticker=sym)
            score = float(tech.get("score", 50))
            
            if score >= buy_score_min:
                base_cap = portfolio_value if (portfolio_value and not math.isnan(portfolio_value)) else cash
                alloc = min(cash, base_cap * max_pos_pct)
                if math.isnan(alloc) or alloc <= 0:
                    continue
                qty = int(alloc // close_px)
                if qty > 0 and cash >= qty * close_px:
                    # Dynamic ATR stop calculation
                    highs = sub_df["High"].tail(14)
                    lows = sub_df["Low"].tail(14)
                    atr_est = float((highs - lows).mean()) if len(highs) >= 14 else (close_px * sl_pct)
                    atr_pct = (atr_est / close_px) * 100.0 if close_px > 0 else 5.0
                    actual_sl_pct = min(0.06, max(0.035, (atr_pct / 100.0) * 2.0))
                    actual_tp_pct = max(tp_pct, actual_sl_pct * 2.0)

                    cost = qty * close_px
                    cash -= cost
                    stop_px = round(close_px * (1 - actual_sl_pct), 2)
                    open_positions[sym] = {
                        "entry_price": close_px,
                        "qty": qty,
                        "initial_stop": stop_px,
                        "stop_loss": stop_px,
                        "target": round(close_px * (1 + actual_tp_pct), 2),
                        "entry_date": date_str,
                        "peak_price": close_px,
                        "atr": atr_est,
                        "days_held": 0,
                    }
                    
        # Daily portfolio mark-to-market
        holdings_value = 0.0
        for sym, pos in open_positions.items():
            df = data_by_ticker[sym]
            day_rows = df[df.index.strftime("%Y-%m-%d") <= date_str]
            if not day_rows.empty:
                px = float(day_rows["Close"].iloc[-1])
                if not math.isnan(px) and px > 0:
                    holdings_value += px * pos["qty"]
        portfolio_value = cash + holdings_value
        if math.isnan(portfolio_value):
            portfolio_value = cash
        daily_equity.append({"date": date_str, "equity": round(portfolio_value, 2)})
        
    # Calculate performance metrics
    total_trades = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    win_rate = round(len(wins) / total_trades * 100, 1) if total_trades else 0.0
    total_return_pct = round((portfolio_value - initial_capital) / initial_capital * 100, 2)
    
    # Expectancy and Profit Factor
    avg_win = (sum(t["pnl"] for t in wins) / len(wins)) if wins else 0.0
    avg_loss = (abs(sum(t["pnl"] for t in losses)) / len(losses)) if losses else 0.0
    win_frac = len(wins) / total_trades if total_trades else 0.0
    loss_frac = len(losses) / total_trades if total_trades else 0.0
    expectancy = round((win_frac * avg_win) - (loss_frac * avg_loss), 2)

    total_gross_gain = sum(t["pnl"] for t in wins)
    total_gross_loss = abs(sum(t["pnl"] for t in losses))
    profit_factor = round(total_gross_gain / total_gross_loss, 2) if total_gross_loss > 0 else (99.0 if total_gross_gain > 0 else 0.0)

    avg_days_held = round(sum(t.get("days_held", 1) for t in trades) / total_trades, 1) if total_trades else 0.0

    # Drawdown
    equity_curve = [d["equity"] for d in daily_equity]
    if equity_curve:
        peaks = pd.Series(equity_curve).cummax()
        drawdowns = (pd.Series(equity_curve) - peaks) / peaks * 100
        max_drawdown = round(abs(drawdowns.min()), 2)
    else:
        max_drawdown = 0.0
        
    # Sharpe ratio approximation
    if len(daily_equity) > 5:
        eq_series = pd.Series(equity_curve)
        daily_rets = eq_series.pct_change().dropna()
        mean_ret = daily_rets.mean() * 252
        std_ret = daily_rets.std() * np.sqrt(252)
        sharpe = round(mean_ret / std_ret, 2) if std_ret > 0 else 0.0
    else:
        sharpe = 0.0
        
    # Benchmark comparison: NIFTY 50 (NIFTYBEES) buy & hold return
    bench_ret = 0.0
    try:
        nifty_df = fetch_stock_history("NIFTYBEES.NS", period=period)
        if not nifty_df.empty and len(nifty_df) >= 2:
            b_start = float(nifty_df["Close"].iloc[0])
            b_end = float(nifty_df["Close"].iloc[-1])
            if b_start > 0:
                bench_ret = round((b_end - b_start) / b_start * 100, 2)
    except Exception as e:
        logger.debug(f"Benchmark fetch error: {e}")

    # Statistical Validity Warning:
    is_valid_sample = bool(total_trades >= 50)
    sample_warning = "" if is_valid_sample else f"⚠️ Low sample size ({total_trades} trades < 50): Results are anecdotal and lack statistical significance. Test across broader universe or longer timeframe before concluding strategy edge."

    biggest_winner = round(max([t["pnl_percent"] for t in trades] or [0.0]), 2)
    runner_trades_count = sum(1 for t in trades if "RUNNER" in str(t.get("reason", "")))

    result = {
        "strategy_name": strategy_name,
        "timeframe": timeframe,
        "start_date": all_dates[0] if all_dates else "",
        "end_date": all_dates[-1] if all_dates else "",
        "initial_capital": initial_capital,
        "final_capital": round(portfolio_value, 2),
        "total_return": total_return_pct,
        "benchmark_return": bench_ret,
        "alpha": round(total_return_pct - bench_ret, 2),
        "sharpe_ratio": sharpe,
        "max_drawdown": max_drawdown,
        "win_rate": win_rate,
        "total_trades": total_trades,
        "expectancy_rupees": expectancy,
        "profit_factor": profit_factor,
        "avg_days_held": avg_days_held,
        "biggest_winner_pct": biggest_winner,
        "runner_trades_count": runner_trades_count,
        "allow_runners": allow_runners,
        "is_valid_sample": is_valid_sample,
        "sample_warning": sample_warning,
        "avg_return_per_trade": round(
            sum(t["pnl_percent"] for t in trades) / total_trades, 2
        ) if total_trades else 0.0,
        "detailed_results": {
            "trades_count": total_trades,
            "wins_count": len(wins),
            "sample_trades": trades[-10:],
        },
    }
    
    # Save to SQLite
    try:
        conn = get_connection()
        save_backtest_result(conn, result)
        conn.close()
    except Exception as e:
        logger.warning(f"Could not persist backtest result to DB: {e}")
        
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    res = run_simple_backtest(["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS"])
    print(f"Backtest complete: Return={res.get('total_return')}% | WinRate={res.get('win_rate')}% | Sharpe={res.get('sharpe_ratio')}")
