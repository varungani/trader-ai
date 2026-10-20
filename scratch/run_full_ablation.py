import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import math
import random
from data.market_data import fetch_stock_history
from data.costs import compute_indian_delivery_costs, compute_annual_portfolio_stcg
from analysis.technical import compute_technical_score
BENCHMARK_TICKER = "NIFTYBEES.NS"
REGIME_INDEX_TICKER = "^NSEI"

TEST_UNIVERSE = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "ITC.NS", "SBIN.NS", "BHARTIARTL.NS", "KOTAKBANK.NS",
    "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS", "SUNPHARMA.NS",
    "TITAN.NS", "BAJFINANCE.NS", "HCLTECH.NS", "WIPRO.NS", "ULTRACEMCO.NS",
    "NTPC.NS", "POWERGRID.NS", "M&M.NS", "TATASTEEL.NS", "JSWSTEEL.NS"
]

def load_universe_data(tickers, period="3y"):
    data = {}
    for ticker in tickers:
        df = fetch_stock_history(ticker, period=period)
        if df is not None and not df.empty and len(df) >= 100:
            data[ticker] = df
    return data

def precompute_stock_scores(data):
    """Precompute technical indicators vectorized across the entire history for each stock."""
    score_lookup = {}
    for sym, df in data.items():
        if len(df) < 50:
            continue
        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]
        
        sma50 = close.rolling(50).mean()
        sma200 = close.rolling(200).mean()
        
        # RSI 14
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        rsi = 100 - (100 / (1 + rs))
        
        # Volume MA 20
        vol_ma20 = volume.rolling(20).mean()
        vol_ratio = volume / (vol_ma20 + 1e-9)
        
        scores = pd.Series(50.0, index=df.index)
        # Score calculation:
        # Trend component (SMA50 > SMA200): +15 pts
        # Momentum component (RSI 55-75): +20 pts
        # Breakout component (Close > SMA50 & vol_ratio > 1.3): +25 pts
        trend_score = np.where(sma50 > sma200, 70.0, 35.0)
        rsi_score = np.where((rsi >= 55) & (rsi <= 75), 75.0, np.where(rsi > 75, 55.0, 40.0))
        vol_score = np.where((close > sma50) & (vol_ratio >= 1.3), 80.0, 45.0)
        
        composite_tech = (0.35 * trend_score) + (0.35 * rsi_score) + (0.30 * vol_score)
        
        final_scores = pd.Series(
            (0.40 * composite_tech) + (0.20 * 60.0) + (0.15 * 70.0) + (0.15 * 65.0) + (0.10 * 65.0),
            index=df.index
        )
        
        score_lookup[sym] = {
            "score": final_scores,
            "sma50": sma50,
            "vol_ratio": vol_ratio,
            "close": close
        }
    return score_lookup

def bootstrap_expectancy_ci(net_pnls, n_boot=2000, alpha=0.05, seed=42):
    if len(net_pnls) < 5:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    arr = np.array(net_pnls)
    means = [np.mean(rng.choice(arr, size=len(arr), replace=True)) for _ in range(n_boot)]
    lower = float(np.percentile(means, 100 * (alpha / 2)))
    upper = float(np.percentile(means, 100 * (1 - alpha / 2)))
    return (round(lower, 2), round(upper, 2))

def run_simulation(
    data: dict,
    entry_mode: str = "strategy", # "strategy", "random", "simple_baseline"
    exit_policy: str = "clean_target", # "clean_target", "choked", "trailing"
    use_regime_gate: bool = True,
    nifty_df: pd.DataFrame | None = None,
    score_lookup: dict | None = None,
    initial_capital: float = 100000.0,
    fixed_alloc: float = 20000.0,
    max_positions: int = 5,
    min_score: float = 65.0,
    seed: int = 42,
) -> dict:
    rng = random.Random(seed)
    cash = initial_capital
    portfolio_value = initial_capital
    trades = []
    daily_equity = []
    daily_invested = []
    open_positions = {}
    
    all_dates = sorted(list(set.union(*[set(df.index.strftime("%Y-%m-%d")) for df in data.values()])))
    
    for date_str in all_dates:
        to_close = []
        for sym, pos in open_positions.items():
            df = data.get(sym)
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
            initial_risk = pos["entry_price"] - pos["initial_stop"]
            
            exit_reason = None
            exit_px = close
            
            if exit_policy == "choked":
                # Old Choked Policy: Breakeven ratchet at +1R and tight 1.5 ATR trailing
                if initial_risk > 0 and (pos["peak_price"] - pos["entry_price"]) >= initial_risk:
                    pos["stop_loss"] = max(pos["stop_loss"], pos["entry_price"])
                    if pos.get("atr"):
                        pos["stop_loss"] = max(pos["stop_loss"], round(pos["peak_price"] - (1.5 * pos["atr"]), 2))
                if low <= pos["stop_loss"]:
                    exit_reason = "TRAILING_STOP" if pos["stop_loss"] > pos["entry_price"] else ("BREAKEVEN" if pos["stop_loss"] == pos["entry_price"] else "STOP_LOSS")
                    exit_px = min(pos["stop_loss"], open_px) if open_px < pos["stop_loss"] else pos["stop_loss"]
                elif high >= pos["target"]:
                    exit_reason = "TARGET (+12% to +15%)"
                    exit_px = pos["target"]
                elif pos["days_held"] >= 15:
                    exit_reason = "TIME_STOP (15 Sessions)"
                    exit_px = close
                    
            elif exit_policy == "clean_target":
                # Honest Clean Exit:
                # Priority 1: Stop Loss (Must check low first on daily bar)
                if low <= pos["stop_loss"]:
                    exit_reason = "STOP_LOSS"
                    exit_px = min(pos["stop_loss"], open_px) if open_px < pos["stop_loss"] else pos["stop_loss"]
                # Priority 2: Target Hit at T1 (+12% to +15%)
                elif high >= pos["target"]:
                    exit_reason = "TARGET_T1 (+12% to +15%)"
                    exit_px = pos["target"]
                # Priority 3: Time Stop (15 Sessions)
                elif pos["days_held"] >= 15:
                    exit_reason = "TIME_STOP (15 Sessions)"
                    exit_px = close
                    
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
                    "entry_date": pos["entry_date"],
                    "exit_date": date_str,
                    "days_held": pos["days_held"],
                    "entry_price": pos["entry_price"],
                    "exit_price": exit_px,
                    "qty": pos["qty"],
                    "position_size": pos["qty"] * pos["entry_price"],
                    "gross_pnl": costs.gross_pnl_rupees,
                    "net_pnl": costs.net_pnl_rupees,
                    "pnl_pct": costs.net_pnl_pct,
                    "friction": costs.total_friction_rupees,
                    "reason": exit_reason
                })
                to_close.append(sym)
                
        for sym in to_close:
            del open_positions[sym]
            
        # Regime Gate Check
        regime_bullish = True
        if use_regime_gate and nifty_df is not None and not nifty_df.empty:
            nifty_sub = nifty_df[nifty_df.index.strftime("%Y-%m-%d") <= date_str]
            if len(nifty_sub) >= 50:
                nifty_close = float(nifty_sub["Close"].iloc[-1])
                nifty_sma50 = float(nifty_sub["Close"].rolling(50).mean().iloc[-1])
                if nifty_close < nifty_sma50:
                    regime_bullish = False
                    
        # Daily Invested Value
        holdings_val = 0.0
        for sym, pos in open_positions.items():
            df = data[sym]
            sub = df[df.index.strftime("%Y-%m-%d") <= date_str]
            if not sub.empty:
                px = float(sub["Close"].iloc[-1])
                if px > 0:
                    holdings_val += px * pos["qty"]
        daily_invested.append(holdings_val)
        portfolio_value = cash + holdings_val
        daily_equity.append({"date": date_str, "equity": portfolio_value})
        
        # New Entries
        if len(open_positions) < max_positions and regime_bullish:
            available_symbols = [s for s in data.keys() if s not in open_positions]
            candidates = []
            
            if entry_mode == "random":
                if available_symbols and rng.random() < 0.25:
                    chosen = rng.choice(available_symbols)
                    candidates.append((chosen, 100.0))
            else:
                for sym in available_symbols:
                    df = data[sym]
                    sub_df = df[df.index.strftime("%Y-%m-%d") <= date_str]
                    if len(sub_df) < 50:
                        continue
                    close_px = float(sub_df["Close"].iloc[-1])
                    if close_px <= 0 or math.isnan(close_px):
                        continue
                        
                    if entry_mode == "simple_baseline":
                        if score_lookup and sym in score_lookup:
                            item = score_lookup[sym]
                            dt_idx = pd.to_datetime(date_str)
                            if dt_idx in item["sma50"].index:
                                sma50 = float(item["sma50"].loc[dt_idx])
                                vr = float(item["vol_ratio"].loc[dt_idx])
                                if close_px > sma50 and vr >= 1.3:
                                    candidates.append((sym, 80.0))
                    elif entry_mode == "strategy":
                        if score_lookup and sym in score_lookup:
                            item = score_lookup[sym]
                            dt_idx = pd.to_datetime(date_str)
                            if dt_idx in item["score"].index:
                                sc = float(item["score"].loc[dt_idx])
                                if sc >= min_score:
                                    candidates.append((sym, sc))
                            
            candidates.sort(key=lambda x: x[1], reverse=True)
            to_add = candidates[:(max_positions - len(open_positions))]
            
            for sym, sc in to_add:
                df = data[sym]
                sub_df = df[df.index.strftime("%Y-%m-%d") <= date_str]
                close_px = float(sub_df["Close"].iloc[-1])
                
                # Fixed allocation (Rs. 20,000 per trade, max 5 positions = Rs 1,00,000)
                alloc = min(cash, fixed_alloc)
                qty = int(alloc // close_px)
                if qty > 0 and cash >= (qty * close_px):
                    highs = sub_df["High"].tail(14)
                    lows = sub_df["Low"].tail(14)
                    atr_est = float((highs - lows).mean()) if len(highs) >= 14 else (close_px * 0.05)
                    atr_pct = (atr_est / close_px) * 100.0 if close_px > 0 else 5.0
                    sl_pct = min(0.06, max(0.035, (atr_pct / 100.0) * 2.0))
                    tp_pct = max(0.12, sl_pct * 2.0)
                    
                    cash -= (qty * close_px)
                    open_positions[sym] = {
                        "entry_price": close_px,
                        "qty": qty,
                        "initial_stop": round(close_px * (1 - sl_pct), 2),
                        "stop_loss": round(close_px * (1 - sl_pct), 2),
                        "target": round(close_px * (1 + tp_pct), 2),
                        "entry_date": date_str,
                        "peak_price": close_px,
                        "atr": atr_est,
                        "days_held": 0
                    }
                    
    total_trades = len(trades)
    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] <= 0]
    win_rate = (len(wins) / total_trades * 100) if total_trades else 0.0
    total_return_pct = ((portfolio_value - initial_capital) / initial_capital) * 100
    
    gross_pnl_total = sum(t["gross_pnl"] for t in trades)
    net_pnl_total = sum(t["net_pnl"] for t in trades)
    friction_total = sum(t["friction"] for t in trades)
    
    gross_win = sum(t["net_pnl"] for t in wins)
    gross_loss = abs(sum(t["net_pnl"] for t in losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)
    
    expectancy = (net_pnl_total / total_trades) if total_trades else 0.0
    t1_count = len([t for t in trades if "TARGET" in str(t.get("reason", ""))])
    
    # Position size stats
    pos_sizes = [t["position_size"] for t in trades]
    min_pos = min(pos_sizes) if pos_sizes else 0.0
    med_pos = float(np.median(pos_sizes)) if pos_sizes else 0.0
    max_pos = max(pos_sizes) if pos_sizes else 0.0
    
    avg_invested_pct = (float(np.mean(daily_invested)) / initial_capital) * 100.0 if daily_invested else 0.0
    
    # 95% Bootstrap CI on Expectancy
    ci_lower, ci_upper = bootstrap_expectancy_ci([t["net_pnl"] for t in trades])
    
    # Drawdown
    equity_curve = [d["equity"] for d in daily_equity]
    if equity_curve:
        peaks = pd.Series(equity_curve).cummax()
        dd = (pd.Series(equity_curve) - peaks) / peaks * 100
        max_drawdown = abs(dd.min())
    else:
        max_drawdown = 0.0
        
    # Sharpe
    if len(equity_curve) > 5:
        eq_series = pd.Series(equity_curve)
        daily_rets = eq_series.pct_change().dropna()
        mean_r = daily_rets.mean() * 252
        std_r = daily_rets.std() * np.sqrt(252)
        sharpe = (mean_r / std_r) if std_r > 0 else 0.0
    else:
        sharpe = 0.0
        
    return {
        "trades_count": total_trades,
        "win_rate": round(win_rate, 1),
        "t1_hit_count": t1_count,
        "total_return_pct": round(total_return_pct, 2),
        "gross_pnl": round(gross_pnl_total, 2),
        "friction": round(friction_total, 2),
        "avg_friction": round(friction_total / total_trades, 2) if total_trades else 0.0,
        "net_pretax_pnl": round(net_pnl_total, 2),
        "profit_factor": round(profit_factor, 2),
        "expectancy_rupees": round(expectancy, 2),
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "avg_pct_invested": round(avg_invested_pct, 1),
        "min_pos": round(min_pos, 0),
        "med_pos": round(med_pos, 0),
        "max_pos": round(max_pos, 0),
        "max_drawdown": round(max_drawdown, 2),
        "sharpe": round(sharpe, 2),
    }

if __name__ == "__main__":
    print("Loading universe data...")
    data = load_universe_data(TEST_UNIVERSE, period="3y")
    nifty_df = fetch_stock_history(REGIME_INDEX_TICKER, period="3y")
    niftybees_df = fetch_stock_history(BENCHMARK_TICKER, period="3y")
    
    b_ret = 0.0
    if not niftybees_df.empty:
        b_ret = ((float(niftybees_df["Close"].iloc[-1]) - float(niftybees_df["Close"].iloc[0])) / float(niftybees_df["Close"].iloc[0])) * 100.0
        
    # Calculate Equal-Weight Buy-and-Hold Return of the 25 Universe Stocks
    univ_rets = []
    for sym, df in data.items():
        if len(df) >= 2:
            r = ((float(df["Close"].iloc[-1]) - float(df["Close"].iloc[0])) / float(df["Close"].iloc[0])) * 100.0
            univ_rets.append(r)
    ew_univ_ret = float(np.mean(univ_rets)) if univ_rets else 0.0
    
    print("\n" + "="*80)
    print("RUNNING ABLATION MATRIX (CLEAN EXITS, FIXED ALLOC Rs. 20,000, NO MAGIC FILLS)")
    print(f"Benchmark 1: NIFTYBEES Buy-and-Hold:              {b_ret:+.2f}%")
    print(f"Benchmark 2: Equal-Weight Universe Buy-and-Hold:  {ew_univ_ret:+.2f}%")
    print("="*80)
    
    score_lookup = precompute_stock_scores(data)
    
    # 1. Zero-Skill Control (Random Entries, Clean Exits)
    r_rand = run_simulation(data, entry_mode="random", exit_policy="clean_target", use_regime_gate=True, nifty_df=nifty_df, score_lookup=score_lookup)
    
    # 2. Simple Baseline (50 SMA + Vol, Clean Exits)
    r_simple = run_simulation(data, entry_mode="simple_baseline", exit_policy="clean_target", use_regime_gate=True, nifty_df=nifty_df, score_lookup=score_lookup)
    
    # 3. Strategy with Old Choked Exits (Regime Gate ON)
    r_choked = run_simulation(data, entry_mode="strategy", exit_policy="choked", use_regime_gate=True, nifty_df=nifty_df, score_lookup=score_lookup, min_score=65)
    
    # 4. Strategy with Clean Exits (Regime Gate OFF)
    r_clean_no_gate = run_simulation(data, entry_mode="strategy", exit_policy="clean_target", use_regime_gate=False, nifty_df=nifty_df, score_lookup=score_lookup, min_score=65)
    
    # 5. Strategy with Clean Exits (Regime Gate ON)
    r_clean_gate = run_simulation(data, entry_mode="strategy", exit_policy="clean_target", use_regime_gate=True, nifty_df=nifty_df, score_lookup=score_lookup, min_score=65)
    
    # 6. Strategy with Clean Exits (Score >= 75 High Conviction, Gate ON)
    r_clean_75 = run_simulation(data, entry_mode="strategy", exit_policy="clean_target", use_regime_gate=True, nifty_df=nifty_df, score_lookup=score_lookup, min_score=75)
    
    experiments = [
        ("Zero-Skill Control (Random + Clean Exits)", r_rand),
        ("Simple Baseline (50 SMA + Vol + Clean Exits)", r_simple),
        ("Strategy (Score >= 65, Old Choked Exits, Gate ON)", r_choked),
        ("Strategy (Score >= 65, Clean Exits, Regime Gate OFF)", r_clean_no_gate),
        ("Strategy (Score >= 65, Clean Exits, Regime Gate ON)", r_clean_gate),
        ("Strategy (Score >= 75, Clean Exits, Regime Gate ON)", r_clean_75),
    ]
    
    rows = []
    for name, r in experiments:
        rows.append({
            "Variant": name,
            "Trades": r["trades_count"],
            "WinRate": f"{r['win_rate']}%",
            "T1 Hits": r["t1_hit_count"],
            "Net Return": f"{r['total_return_pct']:+.1f}%",
            "Alpha (EW Univ)": f"{r['total_return_pct'] - ew_univ_ret:+.1f}%",
            "Expectancy (95% CI)": f"Rs {r['expectancy_rupees']:+.1f} [{r['ci_lower']:+.1f}, {r['ci_upper']:+.1f}]",
            "Avg Friction": f"Rs {r['avg_friction']}",
            "% Invested": f"{r['avg_pct_invested']}%",
            "Max DD": f"-{r['max_drawdown']}%",
            "Sharpe": r["sharpe"],
        })
        
    df_res = pd.DataFrame(rows)
    print(df_res.to_string(index=False))
    print("="*80)
    print(f"Position Size Distribution (Strategy Clean Exits):")
    print(f"Min: Rs {r_clean_gate['min_pos']:,.0f} | Median: Rs {r_clean_gate['med_pos']:,.0f} | Max: Rs {r_clean_gate['max_pos']:,.0f}")
