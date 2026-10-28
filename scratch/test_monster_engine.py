import os
import sys
import pickle
import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.costs import compute_indian_delivery_costs

with open("data/cache/universe_5y.pkl", "rb") as f:
    univ = pickle.load(f)

with open("data/cache/benchmarks_5y.pkl", "rb") as f:
    bm = pickle.load(f)

nifty_df = bm["^NSEI"]
dates = nifty_df.index

print(f"Loaded {len(univ)} stocks over {len(dates)} trading dates ({dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')})")

# Precompute indicators for all stocks
processed = {}
for sym, df in univ.items():
    if len(df) < 200 or "Close" not in df.columns:
        continue
    c = df["Close"]
    h = df["High"]
    l = df["Low"]
    v = df["Volume"]
    
    # 1. Stage 2 Trend Template
    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    sma200 = c.rolling(200).mean()
    sma200_slope = sma200 - sma200.shift(20)
    stage2 = (c > ema50) & (ema50 > sma200) & (sma200_slope >= 0)
    
    # 2. Distance to 20 EMA
    dev_ema20 = (c - ema20) / ema20 * 100.0
    sweet_spot = (dev_ema20 >= 0.5) & (dev_ema20 <= 4.0)
    
    # 3. RVOL & Pocket Pivot
    vol_sma20 = v.rolling(20).mean()
    rvol = v / vol_sma20.replace(0, np.nan)
    
    # 4. Volatility Contraction Pattern (VCP)
    # Range of high-low over 5d vs 20d
    range5 = (h.rolling(5).max() - l.rolling(5).min()) / c
    range20 = (h.rolling(20).max() - l.rolling(20).min()) / c
    vcp_tightness = range5 / range20.replace(0, np.nan)
    is_vcp = vcp_tightness <= 0.65  # Volatility compressed in last 5 days
    
    # 5. Resistance clearance (High of last 50 days)
    high50 = h.rolling(50).max().shift(1)
    is_breakout = c >= high50
    dist_high50 = (high50 - c) / c * 100.0
    air_pocket = (dist_high50 >= 4.0) | is_breakout
    
    p_df = pd.DataFrame({
        "Open": df["Open"], "High": h, "Low": l, "Close": c, "Volume": v,
        "stage2": stage2, "sweet_spot": sweet_spot, "rvol": rvol,
        "is_vcp": is_vcp, "is_breakout": is_breakout, "air_pocket": air_pocket,
        "dev_ema20": dev_ema20, "high50": high50
    }, index=df.index)
    processed[sym] = p_df

# Nifty Trend Filter
nifty_close = nifty_df["Close"]
nifty_sma50 = nifty_close.rolling(50).mean()
nifty_bullish = nifty_close > nifty_sma50

def run_simulation(name: str, use_stage2: bool, use_sweet_spot: bool, use_rvol: bool, use_vcp: bool, min_rvol: float = 1.25):
    cash = 100000.0
    open_positions = {}
    trades = []
    
    for i in range(250, len(dates)):
        d = dates[i]
        d_str = d.strftime("%Y-%m-%d")
        
        # 1. Manage Exits
        to_close = []
        for sym, pos in open_positions.items():
            pdf = processed[sym]
            if d not in pdf.index:
                pos["days"] += 1
                continue
            bar = pdf.loc[d]
            low_px = float(bar["Low"])
            high_px = float(bar["High"])
            close_px = float(bar["Close"])
            open_px = float(bar["Open"])
            pos["days"] += 1
            
            gain = ((high_px - pos["entry"]) / pos["entry"]) * 100.0
            
            # Trailing stop to breakeven if gain >= +5%
            if gain >= 5.0 and pos["stop"] < pos["entry"]:
                pos["stop"] = pos["entry"]
                
            exit_reason = None
            exit_px = 0.0
            
            if low_px <= pos["stop"]:
                exit_reason = "BREAKEVEN_STOP" if pos["stop"] >= pos["entry"] else "STOP_LOSS"
                exit_px = min(pos["stop"], open_px)
            elif high_px >= pos["target"]:
                exit_reason = "TARGET_HIT (+12%)"
                exit_px = pos["target"]
            elif pos["days"] >= 15:
                exit_reason = "TIME_EXPIRY_15D"
                exit_px = close_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(buy_price=pos["entry"], sell_price=exit_px, quantity=pos["qty"], apply_stcg=False)
                cash += (exit_px * pos["qty"]) - costs.total_friction_rupees
                trades.append({
                    "ticker": sym, "entry_date": pos["date"], "exit_date": d_str,
                    "entry_price": pos["entry"], "exit_price": exit_px, "days": pos["days"],
                    "net_pnl": costs.net_pnl_rupees, "return_pct": costs.net_pnl_pct, "reason": exit_reason
                })
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        # 2. Entries (Max 5 open positions, Nifty must be Bullish)
        if len(open_positions) < 5 and nifty_bullish.loc[d]:
            candidates = []
            for sym, pdf in processed.items():
                if sym in open_positions or d not in pdf.index:
                    continue
                bar = pdf.loc[d]
                c_px = float(bar["Close"])
                if c_px < 50.0:
                    continue
                
                # Check Filter criteria
                cond = True
                if use_stage2 and not bool(bar["stage2"]):
                    cond = False
                if use_sweet_spot and not bool(bar["sweet_spot"]):
                    cond = False
                if use_rvol and float(bar["rvol"]) < min_rvol:
                    cond = False
                if use_vcp and not bool(bar["is_vcp"]):
                    cond = False
                if not bool(bar["air_pocket"]):
                    cond = False
                    
                if cond:
                    candidates.append((sym, float(bar["rvol"]), c_px))
                    
            candidates.sort(key=lambda x: x[1], reverse=True) # Sort by volume surge
            slots_available = 5 - len(open_positions)
            for sym, rv, px in candidates[:slots_available]:
                alloc = 20000.0
                qty = int(alloc // px)
                if qty > 0 and cash >= (qty * px):
                    stop_px = round(px * 0.955, 2) # 4.5% risk
                    target_px = round(px * 1.12, 2) # 12% target
                    cash -= (qty * px)
                    open_positions[sym] = {
                        "entry": px, "qty": qty, "stop": stop_px,
                        "target": target_px, "days": 0, "date": d_str
                    }
                    
    tdf = pd.DataFrame(trades)
    if tdf.empty:
        print(f"No trades executed for {name}")
        return
        
    n_trades = len(tdf)
    wins = tdf[tdf["net_pnl"] > 0]
    losses = tdf[tdf["net_pnl"] <= 0]
    win_rate = (len(wins) / n_trades) * 100.0
    tot_pnl = tdf["net_pnl"].sum()
    avg_win = wins["net_pnl"].mean() if len(wins) else 0.0
    avg_loss = abs(losses["net_pnl"].mean()) if len(losses) else 1.0
    profit_factor = (wins["net_pnl"].sum() / abs(losses["net_pnl"].sum())) if len(losses) and abs(losses["net_pnl"].sum()) > 0 else 99.0
    
    print("\n" + "="*85)
    print(f"RESULTS: {name}")
    print("="*85)
    print(f"Total Trades:           {n_trades}")
    print(f"WIN RATE:               {win_rate:.2f}%  {'🔥 (TARGET >= 75-80% ACHIEVED!)' if win_rate >= 75.0 else ''}")
    print(f"Profit Factor:          {profit_factor:.2f}")
    print(f"Total Net P&L:          Rs. {tot_pnl:+,.2f}")
    print(f"Avg Win / Avg Loss:     Rs. {avg_win:,.2f} / Rs. {avg_loss:,.2f} (Ratio: {avg_win/avg_loss:.2f}:1)")
    print(f"Exits Breakdown:        Target: {len(tdf[tdf['reason'].str.contains('TARGET')])} | Breakeven: {len(tdf[tdf['reason'].str.contains('BREAKEVEN')])} | Stop: {len(tdf[tdf['reason'].str.contains('STOP_LOSS')])} | Time: {len(tdf[tdf['reason'].str.contains('TIME')])}")
    print("="*85)

# 1. Baseline: Naive Breakout (Loose filters)
run_simulation("Variant 0: Naive Breakout (Loose Filters)", use_stage2=False, use_sweet_spot=False, use_rvol=False, use_vcp=False)

# 2. Stage 2 + Sweet Spot
run_simulation("Variant 1: Stage 2 Trend + Sweet Spot Corridor", use_stage2=True, use_sweet_spot=True, use_rvol=False, use_vcp=False)

# 3. Full Monster Engine: Stage 2 + Sweet Spot + RVOL 1.25x + VCP Coiling
run_simulation("Variant 2: THE MONSTER (Stage 2 + Sweet Spot + RVOL 1.25x + VCP Compression)", use_stage2=True, use_sweet_spot=True, use_rvol=True, use_vcp=True, min_rvol=1.25)
