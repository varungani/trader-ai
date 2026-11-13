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
    
nifty_sma50 = None
if nifty_df is not None:
    ndf = nifty_df.copy()
    if isinstance(ndf.columns, pd.MultiIndex):
        ndf.columns = [c[0] if isinstance(c, tuple) else c for c in ndf.columns]
    ndf.index = ndf.index.strftime("%Y-%m-%d")
    ndf = ndf[~ndf.index.duplicated(keep="last")]
    if "Close" in ndf.columns:
        nifty_sma50 = ndf["Close"].rolling(50).mean()

tickers = [k for k, v in cache.items() if not k.startswith("^") and not k.endswith("BEES.NS") and len(v) >= 200]
print(f"Testing Stage-2 Leader Dip Buyer vs Breakout Chaser across {len(tickers)} tickers...")

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
        
        # 14-day RSI
        delta = c.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / (loss + 1e-6)
        d["rsi_14"] = 100 - (100 / (1 + rs))
        
        high_low = h - l
        d["atr_14"] = high_low.rolling(14).mean()
        data_by_ticker[t] = d

all_dates = sorted(list(set.union(*[set(df.index) for df in data_by_ticker.values()])))

def run_strategy(mode="LEADER_PULLBACK", holding_sessions=21, target_pct=0.15, stop_pct=0.05):
    cash = 100000.0
    portfolio_value = 100000.0
    trades = []
    daily_equity = []
    open_positions = {}
    pending_buys = []
    SLIPPAGE_PCT = 0.002
    max_open = 5

    for date_str in all_dates:
        mkt_ok = True
        if nifty_sma50 is not None and date_str in nifty_sma50.index and date_str in nifty_df.index:
            n_px = float(nifty_df["Close"].loc[date_str])
            n_sma = float(nifty_sma50.loc[date_str])
            mkt_ok = (n_px >= n_sma) if not math.isnan(n_sma) else True

        # Fills
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
                trade_alloc = min(cash, max(alloc, min(cash, 10000.0)))
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

            exit_reason = None
            exit_px = close

            if low <= pos["stop_loss"]:
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

        # Scan for candidates
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
                ema20 = float(df["ema_20"].iloc[idx])
                pct_52w = float(df["pct_from_52w"].iloc[idx])
                rsi = float(df["rsi_14"].iloc[idx])
                rv = float(df["rvol"].iloc[idx])

                if mode == "LEADER_PULLBACK":
                    # Stage 2 Super-Leader in Sweet Spot:
                    # 1. Strong uptrend: 50 SMA > 200 SMA and Price > 50 SMA
                    # 2. Leader pedigree: within 15% of 52W high
                    # 3. Sweet Spot Pullback: Price touching/near 20 EMA (within 1.5%)
                    # 4. RSI not overbought: RSI between 42 and 58
                    # 5. Low volume dry-up: RVOL <= 1.2x (institutional accumulation, no selling pressure)
                    if sma50 > sma200 and c_px >= sma50 and -15.0 <= pct_52w <= -1.0:
                        dist_to_ema20 = (c_px - ema20) / ema20 * 100.0
                        if -2.5 <= dist_to_ema20 <= 1.5 and 42 <= rsi <= 58 and rv <= 1.3:
                            score = 100.0 - abs(dist_to_ema20) * 10.0 + (pct_52w * 0.5)
                            alloc = min(cash / max(1, max_open - len(open_positions)), portfolio_value * 0.20)
                            candidates.append((sym, alloc, stop_pct, target_pct, score))

                elif mode == "BREAKOUT_CHASER":
                    # High volume 20d breakout (old approach)
                    h20 = float(df["High"].iloc[max(0, idx-20):idx].max())
                    if c_px >= h20 and rv >= 1.5 and rsi >= 60 and c_px >= sma50:
                        score = rv * 20.0 + rsi
                        alloc = min(cash / max(1, max_open - len(open_positions)), portfolio_value * 0.20)
                        candidates.append((sym, alloc, stop_pct, target_pct, score))

            candidates.sort(key=lambda x: x[4], reverse=True)
            for c in candidates[:max_open - len(open_positions)]:
                pending_buys.append((c[0], c[1], c[2], c[3]))

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

    return {
        "mode": mode,
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
    for mode in ["BREAKOUT_CHASER", "LEADER_PULLBACK"]:
        res = run_strategy(mode=mode, holding_sessions=21, target_pct=0.15, stop_pct=0.045)
        print(f"\n=======================================================")
        print(f"MODE: {res['mode']}")
        print(f"=======================================================")
        print(f"• Total Return:    {res['total_return']:+.2f}% (Rs. {res['net_pnl']:+,.1f})")
        print(f"• Win Rate:        {res['win_rate']}% ({res['wins']}W / {res['losses']}L on {res['total_trades']} trades)")
        print(f"• Payoff Ratio:    {res['payoff_ratio']}:1")
        print(f"• Sharpe Ratio:    {res['sharpe_ratio']}")
        print(f"• Max Drawdown:    -{res['max_drawdown']}%")
        print(f"• Total Friction:  Rs. {res['friction']:,.1f}")
        print(f"• Avg Days Held:   {res['avg_days_held']} sessions (Strict <= 21 Sessions)")

