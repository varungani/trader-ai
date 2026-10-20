import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import math
from data.costs import compute_indian_delivery_costs

def generate_zero_drift_gbm(n_assets=25, n_days=750, s0=1000.0, vol=0.25, seed=42):
    """
    Generate synthetic stock price series under geometric Brownian motion with ZERO drift (mu = 0).
    """
    rng = np.random.default_rng(seed)
    dt = 1.0 / 252.0
    dates = pd.date_range("2023-01-01", periods=n_days, freq="B")
    
    data = {}
    for i in range(n_assets):
        sym = f"SYNTH_{i+1:02d}"
        # Daily log returns with mean 0
        daily_vol = vol * math.sqrt(dt)
        ret = rng.normal(loc=-0.5 * (daily_vol**2), scale=daily_vol, size=n_days)
        prices = s0 * np.exp(np.cumsum(ret))
        
        # Synthesize realistic Open, High, Low, Close
        # Intraday range proportional to daily volatility
        intraday_noise_h = rng.uniform(0.002, 0.015, size=n_days)
        intraday_noise_l = rng.uniform(0.002, 0.015, size=n_days)
        intraday_noise_o = rng.uniform(-0.005, 0.005, size=n_days)
        
        close = prices
        open_px = np.roll(close, 1)
        open_px[0] = s0
        open_px = open_px * (1.0 + intraday_noise_o)
        
        high = np.maximum(open_px, close) * (1.0 + intraday_noise_h)
        low = np.minimum(open_px, close) * (1.0 - intraday_noise_l)
        
        vol_arr = rng.integers(100000, 1000000, size=n_days)
        
        df = pd.DataFrame({
            "Open": open_px,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": vol_arr
        }, index=dates)
        data[sym] = df
        
    return data

def run_simulation(data, entry_mode="random", exit_policy="clean_target", fixed_alloc=20000.0, max_positions=5, seed=42):
    """
    Simulates trades with fixed position sizing (no compounding distortion),
    stop-first bar resolution, and proper exit accounting.
    """
    rng = np.random.default_rng(seed)
    all_dates = sorted(list(next(iter(data.values())).index))
    
    cash = 100000.0
    open_positions = {}
    trades = []
    daily_invested_capital = []
    
    for date in all_dates:
        date_str = date.strftime("%Y-%m-%d")
        
        # 1. Update and resolve existing open positions
        to_close = []
        for sym, pos in open_positions.items():
            pos["days_held"] += 1
            df = data[sym]
            if date not in df.index:
                continue
            row = df.loc[date]
            open_px = float(row["Open"])
            high = float(row["High"])
            low = float(row["Low"])
            close = float(row["Close"])
            
            pos["peak_price"] = max(pos["peak_price"], high)
            
            exit_reason = None
            exit_px = close
            
            # CRITICAL RULE: If both Stop and Target are touched on the same bar,
            # conservative institutional standard assumes STOP HIT FIRST.
            if low <= pos["stop_loss"]:
                exit_reason = "STOP_LOSS"
                # Realistic gap-down fill: min(stop, open) if opened below stop
                exit_px = min(pos["stop_loss"], open_px) if open_px < pos["stop_loss"] else pos["stop_loss"]
            elif high >= pos["target"]:
                exit_reason = "TARGET"
                exit_px = pos["target"]
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
            
        # Track capital deployed
        currently_invested = sum(pos["qty"] * float(data[s].loc[date]["Close"]) for s, pos in open_positions.items() if date in data[s].index)
        daily_invested_capital.append(currently_invested)
        
        # 2. Entries on Next Bar Close (or open)
        if len(open_positions) < max_positions:
            available_symbols = [s for s in data.keys() if s not in open_positions]
            if available_symbols and rng.random() < 0.25: # 25% chance of entry
                chosen = rng.choice(available_symbols)
                df = data[chosen]
                sub_df = df[df.index <= date]
                if len(sub_df) >= 15:
                    close_px = float(sub_df["Close"].iloc[-1])
                    qty = int(fixed_alloc // close_px)
                    if qty > 0 and cash >= (qty * close_px):
                        highs = sub_df["High"].tail(14)
                        lows = sub_df["Low"].tail(14)
                        atr_est = float((highs - lows).mean()) if len(highs) >= 14 else (close_px * 0.05)
                        atr_pct = (atr_est / close_px) * 100.0 if close_px > 0 else 5.0
                        sl_pct = min(0.06, max(0.035, (atr_pct / 100.0) * 2.0))
                        tp_pct = max(0.12, sl_pct * 2.0)
                        
                        cash -= (qty * close_px)
                        open_positions[chosen] = {
                            "entry_price": close_px,
                            "qty": qty,
                            "stop_loss": round(close_px * (1 - sl_pct), 2),
                            "target": round(close_px * (1 + tp_pct), 2),
                            "entry_date": date_str,
                            "peak_price": close_px,
                            "atr": atr_est,
                            "days_held": 0
                        }
                        
    # Analysis
    n_trades = len(trades)
    if n_trades == 0:
        return {"n_trades": 0}
        
    gross_pnl_total = sum(t["gross_pnl"] for t in trades)
    net_pnl_total = sum(t["net_pnl"] for t in trades)
    friction_total = sum(t["friction"] for t in trades)
    avg_pos_size = float(np.mean([t["position_size"] for t in trades]))
    avg_gross_per_trade = gross_pnl_total / n_trades
    avg_net_per_trade = net_pnl_total / n_trades
    avg_friction_per_trade = friction_total / n_trades
    avg_pct_invested = (float(np.mean(daily_invested_capital)) / 100000.0) * 100.0
    
    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] <= 0]
    win_rate = (len(wins) / n_trades) * 100.0
    
    return {
        "n_trades": n_trades,
        "win_rate": win_rate,
        "avg_pos_size": avg_pos_size,
        "gross_pnl_total": gross_pnl_total,
        "net_pnl_total": net_pnl_total,
        "friction_total": friction_total,
        "avg_gross_per_trade": avg_gross_per_trade,
        "avg_net_per_trade": avg_net_per_trade,
        "avg_friction_per_trade": avg_friction_per_trade,
        "avg_pct_invested": avg_pct_invested,
        "trades": trades
    }

if __name__ == "__main__":
    print("="*70)
    print("RUNNING ZERO-DRIFT SYNTHETIC NULL TEST (10 Monte Carlo Runs)")
    print("="*70)
    
    gross_per_trade_list = []
    net_per_trade_list = []
    friction_per_trade_list = []
    
    for s in range(10):
        synth_data = generate_zero_drift_gbm(seed=100 + s)
        res = run_simulation(synth_data, entry_mode="random", fixed_alloc=20000.0, seed=200 + s)
        gross_per_trade_list.append(res["avg_gross_per_trade"])
        net_per_trade_list.append(res["avg_net_per_trade"])
        friction_per_trade_list.append(res["avg_friction_per_trade"])
        print(f"Run {s+1:02d}: Trades={res['n_trades']:3d} | WinRate={res['win_rate']:4.1f}% | AvgPos=Rs.{res['avg_pos_size']:,.0f} | AvgGross=Rs.{res['avg_gross_per_trade']:+6.2f} | AvgFriction=Rs.{res['avg_friction_per_trade']:5.2f} | AvgNet=Rs.{res['avg_net_per_trade']:+6.2f}")
        
    print("-" * 70)
    print(f"Across 10 Independent Zero-Drift Universes:")
    print(f"* Mean Gross P&L per trade:    Rs.{np.mean(gross_per_trade_list):+6.2f} (Null Expectation: ~Rs.0.00)")
    print(f"* Mean Friction per trade:     Rs.{np.mean(friction_per_trade_list):6.2f} (Standard friction)")
    print(f"* Mean Net P&L per trade:      Rs.{np.mean(net_per_trade_list):+6.2f} (Null Expectation: -Friction)")
    print("="*70)
