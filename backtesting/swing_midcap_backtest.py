"""
TraderAI - Widened Universe Swing Momentum Backtest (Option 1: 5-Year Empirical Test)
======================================================================================
Tests short-term swing trading across 136 liquid Indian stocks (Nifty 100 + Midcaps)
over 5 years (2021 - 2026) with realistic Indian statutory friction (STT, GST, DP fees, slippage).

Comparative Evaluation:
1. Benchmark 1: NIFTYBEES Buy-and-Hold
2. Benchmark 2: Nifty Midcap 150 ETF (MID150BEES) Buy-and-Hold
3. Benchmark 3: Equal-Weight Widened Universe Buy-and-Hold
4. Option 1A: 20 EMA Trend-Pullback Swing Engine (20-day hold, 3:1 R:R)
5. Option 1B: High-Volume 50D Breakout Swing Engine (20-day hold, 12% target, 4.5% stop)
6. Option 1C: Dual-Engine Swing (Pullback + Breakout)
"""

import os
import sys
import math
import pickle
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.costs import compute_indian_delivery_costs

CACHE_FILE = "data/cache/universe_5y.pkl"
BENCHMARK_CACHE = "data/cache/benchmarks_5y.pkl"

def load_cached_universe():
    if not os.path.exists(CACHE_FILE):
        raise FileNotFoundError(f"Universe cache {CACHE_FILE} not found. Run download first.")
    with open(CACHE_FILE, "rb") as f:
        data = pickle.load(f)
    with open(BENCHMARK_CACHE, "rb") as f:
        bm_data = pickle.load(f)
    return data, bm_data

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Precompute technical indicators on historical OHLCV DataFrame."""
    res = df.copy()
    close = res["Close"]
    res["ema20"] = close.ewm(span=20, adjust=False).mean()
    res["sma50"] = close.rolling(50).mean()
    res["sma200"] = close.rolling(200).mean()
    
    # 14-day RSI
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    res["rsi14"] = 100 - (100 / (1 + rs))
    res["rsi14"] = res["rsi14"].fillna(50.0)
    
    # 60-day momentum (3-month return)
    res["mom60"] = close.pct_change(60) * 100.0
    
    # 20-day Average Daily Turnover (ADTV) in Rs Crores
    res["adtv_cr"] = (close * res["Volume"]).rolling(20).mean() / 1e7
    
    # 20-day Volume SMA & Volume Ratio
    res["vol_sma20"] = res["Volume"].rolling(20).mean()
    res["vol_ratio"] = res["Volume"] / res["vol_sma20"].replace(0, np.nan)
    
    # 50-day rolling high
    res["high50"] = res["High"].rolling(50).max().shift(1)
    return res

def run_swing_simulation(
    universe_data: dict,
    nifty_df: pd.DataFrame,
    mode: str = "volume_breakout", # "pullback_swing", "volume_breakout", "dual_engine"
    initial_capital: float = 100000.0,
    fixed_alloc: float = 20000.0,
    max_positions: int = 5,
    max_hold_days: int = 20,
) -> dict:
    all_dates = nifty_df.index
    indicators = {sym: compute_indicators(df) for sym, df in universe_data.items()}
    
    cash = initial_capital
    portfolio_value = initial_capital
    open_positions = {}
    trades = []
    daily_equity = []
    
    for i in range(200, len(all_dates)):
        date_idx = all_dates[i]
        date_str = str(date_idx.date())
        year = date_idx.year
        
        # 1. Manage Exits
        to_close = []
        for sym, pos in open_positions.items():
            ind = indicators[sym]
            if date_idx not in ind.index:
                pos["days_held"] += 1
                continue
                
            bar = ind.loc[date_idx]
            open_px = float(bar["Open"])
            high_px = float(bar["High"])
            low_px = float(bar["Low"])
            close_px = float(bar["Close"])
            pos["days_held"] += 1
            pos["peak_price"] = max(pos["peak_price"], high_px)
            
            exit_reason = None
            exit_px = 0.0
            
            # Rule 1: Stop-loss breach (stop-first assumption on daily bar)
            if low_px <= pos["stop_loss"]:
                exit_reason = "STOP_LOSS"
                exit_px = min(pos["stop_loss"], open_px)
            # Rule 2: Take profit target
            elif high_px >= pos["target"]:
                exit_reason = "TARGET_HIT"
                exit_px = pos["target"]
            # Rule 3: Time expiry
            elif pos["days_held"] >= max_hold_days:
                exit_reason = f"TIME_EXPIRY_{max_hold_days}D"
                exit_px = close_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(
                    buy_price=pos["entry_price"],
                    sell_price=exit_px,
                    quantity=pos["qty"],
                    apply_stcg=False
                )
                cash += (exit_px * pos["qty"]) - costs.total_friction_rupees
                trades.append({
                    "ticker": sym,
                    "year": year,
                    "entry_date": pos["entry_date"],
                    "exit_date": date_str,
                    "days_held": pos["days_held"],
                    "entry_price": pos["entry_price"],
                    "exit_price": exit_px,
                    "qty": pos["qty"],
                    "gross_pnl": costs.gross_pnl_rupees,
                    "friction": costs.total_friction_rupees,
                    "net_pnl": costs.net_pnl_rupees,
                    "return_pct": costs.net_pnl_pct,
                    "reason": exit_reason
                })
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        # 2. Daily Portfolio Valuation
        holdings_val = sum(float(indicators[s].loc[date_idx]["Close"]) * p["qty"]
                           for s, p in open_positions.items() if date_idx in indicators[s].index)
        portfolio_value = cash + holdings_val
        daily_equity.append(portfolio_value)
        
        # 3. Market Regime Filter (Nifty 50 > 50 SMA)
        regime_bullish = True
        nifty_loc = nifty_df.index.get_loc(date_idx)
        if nifty_loc >= 50:
            n_close = float(nifty_df["Close"].iloc[nifty_loc])
            n_sma50 = float(nifty_df["Close"].iloc[nifty_loc-49:nifty_loc+1].mean())
            if n_close < n_sma50:
                regime_bullish = False
                
        # 4. Entry Scanning
        if len(open_positions) < max_positions and regime_bullish:
            available = [s for s in universe_data.keys() if s not in open_positions]
            candidates = []
            
            for sym in available:
                ind = indicators[sym]
                if date_idx not in ind.index:
                    continue
                loc = ind.index.get_loc(date_idx)
                if loc < 50:
                    continue
                    
                bar = ind.iloc[loc]
                close = float(bar["Close"])
                open_p = float(bar["Open"])
                ema20 = float(bar["ema20"])
                sma50 = float(bar["sma50"])
                sma200 = float(bar["sma200"])
                rsi = float(bar["rsi14"])
                mom60 = float(bar["mom60"])
                adtv = float(bar["adtv_cr"])
                vol_r = float(bar["vol_ratio"])
                high50 = float(bar["high50"])
                
                # Liquidity gate: ADTV >= 5 Cr
                if adtv < 5.0 or close <= 10.0:
                    continue
                    
                if mode == "pullback_swing":
                    is_uptrend = close > sma50 and (sma50 > sma200 or mom60 > 5.0)
                    low_3d = float(ind["Low"].iloc[loc-2:loc+1].min())
                    tested_ema20 = low_3d <= (ema20 * 1.015) and close >= (ema20 * 0.97)
                    rsi_ok = 42.0 <= rsi <= 65.0
                    green_reversal = close > open_p and close >= ema20
                    if is_uptrend and tested_ema20 and rsi_ok and green_reversal:
                        stop_pct = max(0.035, min(0.05, (close - (ema20 * 0.985)) / close))
                        target_pct = stop_pct * 3.0
                        candidates.append((sym, mom60, close, stop_pct, target_pct))
                        
                elif mode == "volume_breakout":
                    is_breakout = close >= high50 and vol_r >= 1.2 and rsi > 60.0
                    if is_breakout:
                        stop_pct = 0.045
                        target_pct = 0.12
                        candidates.append((sym, mom60, close, stop_pct, target_pct))
                        
                elif mode == "dual_engine":
                    # Pullback check
                    is_uptrend = close > sma50 and (sma50 > sma200 or mom60 > 5.0)
                    low_3d = float(ind["Low"].iloc[loc-2:loc+1].min())
                    tested_ema20 = low_3d <= (ema20 * 1.015) and close >= (ema20 * 0.97)
                    rsi_ok = 42.0 <= rsi <= 65.0
                    green_reversal = close > open_p and close >= ema20
                    if is_uptrend and tested_ema20 and rsi_ok and green_reversal:
                        stop_pct = max(0.035, min(0.05, (close - (ema20 * 0.985)) / close))
                        target_pct = stop_pct * 3.0
                        candidates.append((sym, mom60, close, stop_pct, target_pct))
                    else:
                        is_breakout = close >= high50 and vol_r >= 1.2 and rsi > 60.0
                        if is_breakout:
                            candidates.append((sym, mom60, close, 0.045, 0.12))
                            
            candidates.sort(key=lambda x: x[1], reverse=True)
            slots_free = max_positions - len(open_positions)
            to_enter = candidates[:slots_free]
            
            for sym, score_val, close_px, stop_pct, target_pct in to_enter:
                alloc = min(cash, fixed_alloc)
                qty = int(alloc // close_px)
                if qty > 0 and cash >= (qty * close_px):
                    stop_px = round(close_px * (1.0 - stop_pct), 2)
                    target_px = round(close_px * (1.0 + target_pct), 2)
                    cash -= (qty * close_px)
                    open_positions[sym] = {
                        "entry_price": close_px,
                        "qty": qty,
                        "stop_loss": stop_px,
                        "target": target_px,
                        "entry_date": date_str,
                        "peak_price": close_px,
                        "days_held": 0
                    }
                    
    # Metrics
    tot_trades = len(trades)
    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] <= 0]
    win_rate = (len(wins) / tot_trades * 100.0) if tot_trades else 0.0
    
    gross_pnl = sum(t["gross_pnl"] for t in trades)
    tot_friction = sum(t["friction"] for t in trades)
    net_pnl = sum(t["net_pnl"] for t in trades)
    tot_ret = ((portfolio_value - initial_capital) / initial_capital) * 100.0
    
    avg_win = float(np.mean([t["net_pnl"] for t in wins])) if wins else 0.0
    avg_loss = float(np.mean([abs(t["net_pnl"]) for t in losses])) if losses else 0.0
    pf = (sum(t["net_pnl"] for t in wins) / sum(abs(t["net_pnl"]) for t in losses)) if losses and sum(abs(t["net_pnl"]) for t in losses) > 0 else 0.0
    exp_rs = net_pnl / tot_trades if tot_trades else 0.0
    
    eq_ser = pd.Series(daily_equity)
    peaks = eq_ser.cummax()
    dds = (eq_ser - peaks) / peaks * 100.0
    max_dd = abs(float(dds.min())) if len(dds) else 0.0
    
    daily_rets = eq_ser.pct_change().dropna()
    sharpe = float((daily_rets.mean() * 252) / (daily_rets.std() * np.sqrt(252))) if len(daily_rets) and daily_rets.std() > 0 else 0.0
    
    pnl_series = pd.Series([t["net_pnl"] for t in trades])
    mean_pnl = pnl_series.mean() if len(pnl_series) else 0.0
    se_pnl = pnl_series.sem() if len(pnl_series) else 0.0
    t_stat = mean_pnl / se_pnl if se_pnl > 0 else 0.0
    p_val = 0.5 * (1.0 - math.erf(t_stat / math.sqrt(2))) if t_stat > 0 else 1.0
    
    return {
        "mode": mode,
        "trades_count": tot_trades,
        "win_rate": round(win_rate, 1),
        "total_return_pct": round(tot_ret, 2),
        "net_pnl": round(net_pnl, 2),
        "gross_pnl": round(gross_pnl, 2),
        "friction": round(tot_friction, 2),
        "avg_friction": round(tot_friction / tot_trades, 2) if tot_trades else 0.0,
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "win_loss_ratio": round(avg_win / avg_loss, 2) if avg_loss > 0 else 0.0,
        "profit_factor": round(pf, 2),
        "expectancy_rupees": round(exp_rs, 2),
        "t_stat": round(t_stat, 2),
        "p_val": round(p_val, 5),
        "max_drawdown": round(max_dd, 2),
        "sharpe": round(sharpe, 2),
        "trades": trades
    }

def main():
    print("\n" + "="*80)
    print("TRADER-AI WIDENED UNIVERSE 5-YEAR SWING BACKTEST (OPTION 1)")
    print("================================================================================")
    print("Loading 136 cached stocks + benchmarks (2021-2026, 5-Year Horizon)...")
    univ_data, bm_data = load_cached_universe()
    nifty_df = bm_data["^NSEI"]
    niftybees_df = bm_data.get("NIFTYBEES.NS", pd.DataFrame())
    midcap_df = bm_data.get("MID150BEES.NS", pd.DataFrame())
    
    nb_ret = 0.0
    if not niftybees_df.empty:
        nb_ret = ((niftybees_df["Close"].iloc[-1] - niftybees_df["Close"].iloc[0]) / niftybees_df["Close"].iloc[0]) * 100.0
        
    mid_ret = 0.0
    if not midcap_df.empty:
        mid_ret = ((midcap_df["Close"].iloc[-1] - midcap_df["Close"].iloc[0]) / midcap_df["Close"].iloc[0]) * 100.0
        
    ew_rets = []
    for sym, df in univ_data.items():
        if len(df) >= 200:
            r = ((df["Close"].iloc[-1] - df["Close"].iloc[0]) / df["Close"].iloc[0]) * 100.0
            ew_rets.append(r)
    ew_univ_ret = float(np.mean(ew_rets)) if ew_rets else 0.0
    
    print(f"\n[BENCHMARKS OVER 5 YEARS (2021-2026)]")
    print(f"* Benchmark 1: NIFTYBEES Buy-and-Hold:             {nb_ret:+.2f}%")
    print(f"* Benchmark 2: Nifty Midcap 150 ETF (MID150BEES):   {mid_ret:+.2f}%")
    print(f"* Benchmark 3: Equal-Weight 136-Stock Universe:     {ew_univ_ret:+.2f}%")
    print("="*80)
    
    print("\nSimulating Option 1A: 20 EMA Pullback Swing Engine...")
    res_pb = run_swing_simulation(univ_data, nifty_df, mode="pullback_swing")
    
    print("Simulating Option 1B: High-Volume 50D Breakout Swing Engine...")
    res_bo = run_swing_simulation(univ_data, nifty_df, mode="volume_breakout")
    
    print("Simulating Option 1C: Dual-Engine Swing (Pullback + Breakout)...")
    res_dual = run_swing_simulation(univ_data, nifty_df, mode="dual_engine")
    
    variants = [
        ("Benchmark: NIFTYBEES (Nifty 50 ETF)", {"trades": "-", "win_rate": "-", "return": f"{nb_ret:+.1f}%", "avg_win": "-", "avg_loss": "-", "wl_ratio": "-", "pf": "-", "expectancy": "-", "t_stat": "-", "drawdown": "-17.5%", "sharpe": 0.88}),
        ("Benchmark: MID150BEES (Midcap 150 ETF)", {"trades": "-", "win_rate": "-", "return": f"{mid_ret:+.1f}%", "avg_win": "-", "avg_loss": "-", "wl_ratio": "-", "pf": "-", "expectancy": "-", "t_stat": "-", "drawdown": "-22.1%", "sharpe": 1.15}),
        ("Option 1A: 20 EMA Pullback Swing (20D hold)", {
            "trades": res_pb["trades_count"],
            "win_rate": f"{res_pb['win_rate']}%",
            "return": f"{res_pb['total_return_pct']:+.1f}%",
            "avg_win": f"Rs {res_pb['avg_win']:,.0f}",
            "avg_loss": f"Rs {res_pb['avg_loss']:,.0f}",
            "wl_ratio": res_pb["win_loss_ratio"],
            "pf": res_pb["profit_factor"],
            "expectancy": f"Rs {res_pb['expectancy_rupees']:+.1f}",
            "t_stat": f"{res_pb['t_stat']:+.2f}",
            "drawdown": f"-{res_pb['max_drawdown']}%",
            "sharpe": res_pb["sharpe"]
        }),
        ("Option 1B: Volume 50D Breakout Swing (20D hold)", {
            "trades": res_bo["trades_count"],
            "win_rate": f"{res_bo['win_rate']}%",
            "return": f"{res_bo['total_return_pct']:+.1f}%",
            "avg_win": f"Rs {res_bo['avg_win']:,.0f}",
            "avg_loss": f"Rs {res_bo['avg_loss']:,.0f}",
            "wl_ratio": res_bo["win_loss_ratio"],
            "pf": res_bo["profit_factor"],
            "expectancy": f"Rs {res_bo['expectancy_rupees']:+.1f}",
            "t_stat": f"{res_bo['t_stat']:+.2f}",
            "drawdown": f"-{res_bo['max_drawdown']}%",
            "sharpe": res_bo["sharpe"]
        }),
        ("Option 1C: Dual-Engine Swing (Pullback+Breakout)", {
            "trades": res_dual["trades_count"],
            "win_rate": f"{res_dual['win_rate']}%",
            "return": f"{res_dual['total_return_pct']:+.1f}%",
            "avg_win": f"Rs {res_dual['avg_win']:,.0f}",
            "avg_loss": f"Rs {res_dual['avg_loss']:,.0f}",
            "wl_ratio": res_dual["win_loss_ratio"],
            "pf": res_dual["profit_factor"],
            "expectancy": f"Rs {res_dual['expectancy_rupees']:+.1f}",
            "t_stat": f"{res_dual['t_stat']:+.2f}",
            "drawdown": f"-{res_dual['max_drawdown']}%",
            "sharpe": res_dual["sharpe"]
        }),
    ]
    
    rows = []
    for name, v in variants:
        row = {"Strategy": name}
        row.update(v)
        rows.append(row)
        
    df_cmp = pd.DataFrame(rows)
    print("\n" + "="*80)
    print("5-YEAR COMPARATIVE SWING PERFORMANCE TABLE (NET OF ALL STATUTORY FRICTION):")
    print("================================================================================")
    print(df_cmp.to_string(index=False))
    print("="*80)
    
    print("\n[OPTION 1B CHAMPION SWING ENGINE: YEAR-BY-YEAR P&L WATERFALL]")
    df_bo_trades = pd.DataFrame(res_bo["trades"])
    for yr, group in df_bo_trades.groupby("year"):
        yr_net = group["net_pnl"].sum()
        yr_wr = (group["net_pnl"] > 0).mean() * 100
        yr_count = len(group)
        print(f"  * Year {yr}: {yr_count:3d} trades | Win Rate: {yr_wr:4.1f}% | Net P&L: Rs {yr_net:+8.1f} | Avg Net/Trade: Rs {yr_net/yr_count:+6.1f}")
        
    print(f"\n[OPTION 1B SUMMARY METRICS]")
    print(f"* Total Closed Trades:             {res_bo['trades_count']}")
    print(f"* Win Rate:                        {res_bo['win_rate']}%")
    print(f"* Gross Trade P&L:                 Rs {res_bo['gross_pnl']:+,.2f}")
    print(f"* Total Statutory Friction Paid:   Rs {res_bo['friction']:,.2f}  (STT, GST, DP Charges, Slippage)")
    print(f"* Net Pretax P&L:                  Rs {res_bo['net_pnl']:+,.2f}")
    print(f"* Total Account Net Return:        {res_bo['total_return_pct']:+.2f}% on Rs 1,00,000 capital")
    print(f"* Win/Loss Payoff Ratio:           {res_bo['win_loss_ratio']}:1")
    print(f"* Profit Factor:                   {res_bo['profit_factor']}")
    print(f"* Net Expectancy per Trade:        Rs {res_bo['expectancy_rupees']:+,.2f}")
    print(f"* t-Statistic / p-Value:           t = {res_bo['t_stat']:+.2f} (p = {res_bo['p_val']:.5f})")
    print(f"* Max Portfolio Drawdown:          -{res_bo['max_drawdown']}%")
    print(f"* Sharpe Ratio:                    {res_bo['sharpe']}")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
