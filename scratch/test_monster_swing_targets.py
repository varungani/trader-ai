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

# Precompute indicators
processed = {}
for sym, df in univ.items():
    if len(df) < 200 or "Close" not in df.columns:
        continue
    c = df["Close"]
    h = df["High"]
    l = df["Low"]
    v = df["Volume"]
    
    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    sma200 = c.rolling(200).mean()
    stage2 = (c > ema50) & (ema50 > sma200)
    
    dev_ema20 = (c - ema20) / ema20 * 100.0
    sweet_spot = (dev_ema20 >= -1.0) & (dev_ema20 <= 4.0)
    
    vol_sma20 = v.rolling(20).mean()
    rvol = v / vol_sma20.replace(0, np.nan)
    
    range5 = (h.rolling(5).max() - l.rolling(5).min()) / c
    range20 = (h.rolling(20).max() - l.rolling(20).min()) / c
    is_vcp = (range5 / range20.replace(0, np.nan)) <= 0.65
    
    high50 = h.rolling(50).max().shift(1)
    air_pocket = ((high50 - c) / c * 100.0 >= 4.0) | (c >= high50)
    
    p_df = pd.DataFrame({
        "Open": df["Open"], "High": h, "Low": l, "Close": c, "Volume": v,
        "stage2": stage2, "sweet_spot": sweet_spot, "rvol": rvol,
        "is_vcp": is_vcp, "air_pocket": air_pocket
    }, index=df.index)
    processed[sym] = p_df

nifty_bullish = nifty_df["Close"] > nifty_df["Close"].rolling(50).mean()

def run_precision_swing(name: str, target_pct: float = 0.07, stop_pct: float = 0.035, lock_trigger_pct: float = 0.045):
    cash = 100000.0
    open_positions = {}
    trades = []
    
    for i in range(250, len(dates)):
        d = dates[i]
        d_str = d.strftime("%Y-%m-%d")
        
        # Exits
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
            
            gain = ((high_px - pos["entry"]) / pos["entry"])
            
            # Step 1: Trailing Profit Lock
            # When gain hits lock_trigger (e.g. +4.5%), elevate stop to lock +1.5% profit net of fees!
            if gain >= lock_trigger_pct:
                locked_stop = round(pos["entry"] * 1.015, 2)
                if pos["stop"] < locked_stop:
                    pos["stop"] = locked_stop
                    
            exit_reason = None
            exit_px = 0.0
            
            if low_px <= pos["stop"]:
                exit_reason = "PROFIT_LOCK_STOP" if pos["stop"] > pos["entry"] else "STOP_LOSS"
                exit_px = min(pos["stop"], open_px)
            elif high_px >= pos["target"]:
                exit_reason = f"TARGET_HIT (+{target_pct*100:.0f}%)"
                exit_px = pos["target"]
            elif pos["days"] >= 10:
                # 10-session momentum exit
                exit_reason = "TIME_EXPIRY_10D"
                exit_px = close_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(buy_price=pos["entry"], sell_price=exit_px, quantity=pos["qty"], apply_stcg=False)
                cash += (exit_px * pos["qty"]) - costs.total_friction_rupees
                trades.append({
                    "ticker": sym, "entry_price": pos["entry"], "exit_price": exit_px,
                    "net_pnl": costs.net_pnl_rupees, "return_pct": costs.net_pnl_pct, "reason": exit_reason
                })
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        # Entries
        if len(open_positions) < 5 and nifty_bullish.loc[d]:
            candidates = []
            for sym, pdf in processed.items():
                if sym in open_positions or d not in pdf.index:
                    continue
                bar = pdf.loc[d]
                c_px = float(bar["Close"])
                if c_px < 50.0:
                    continue
                if bool(bar["stage2"]) and bool(bar["sweet_spot"]) and float(bar["rvol"]) >= 1.25 and bool(bar["is_vcp"]) and bool(bar["air_pocket"]):
                    candidates.append((sym, float(bar["rvol"]), c_px))
                    
            candidates.sort(key=lambda x: x[1], reverse=True)
            for sym, rv, px in candidates[:5-len(open_positions)]:
                alloc = 20000.0
                qty = int(alloc // px)
                if qty > 0 and cash >= (qty * px):
                    stop_px = round(px * (1.0 - stop_pct), 2)
                    target_px = round(px * (1.0 + target_pct), 2)
                    cash -= (qty * px)
                    open_positions[sym] = {
                        "entry": px, "qty": qty, "stop": stop_px,
                        "target": target_px, "days": 0
                    }
                    
    tdf = pd.DataFrame(trades)
    if tdf.empty:
        print(f"No trades for {name}")
        return
        
    wins = tdf[tdf["net_pnl"] > 0]
    losses = tdf[tdf["net_pnl"] <= 0]
    wr = len(wins) / len(tdf) * 100.0
    tot_pnl = tdf["net_pnl"].sum()
    avg_win = wins["net_pnl"].mean() if len(wins) else 0.0
    avg_loss = abs(losses["net_pnl"].mean()) if len(losses) else 1.0
    pf = (wins["net_pnl"].sum() / abs(losses["net_pnl"].sum())) if len(losses) and abs(losses["net_pnl"].sum()) > 0 else 99.0
    
    print("\n" + "="*85)
    print(f"RESULTS: {name}")
    print("="*85)
    print(f"Total Trades:           {len(tdf)}")
    print(f"WIN RATE:               {wr:.2f}%  {'🔥 (70-80% ACCURACY TARGET REACHED!)' if wr >= 70.0 else ''}")
    print(f"Profit Factor:          {pf:.2f}")
    print(f"Total Net P&L:          Rs. {tot_pnl:+,.2f}")
    print(f"Avg Win / Avg Loss:     Rs. {avg_win:,.2f} / Rs. {avg_loss:,.2f} (Ratio: {avg_win/avg_loss:.2f}:1)")
    print(f"Exits Breakdown:        Target: {len(tdf[tdf['reason'].str.contains('TARGET')])} | Profit-Lock: {len(tdf[tdf['reason'].str.contains('PROFIT_LOCK')])} | Stop: {len(tdf[tdf['reason'].str.contains('STOP_LOSS')])} | Time: {len(tdf[tdf['reason'].str.contains('TIME')])}")
    print("="*85)

# Target +7%, Stop 3.5%, Profit Lock trigger +4.0%
run_precision_swing("Precision Swing Engine A (+7% Target, 3.5% Stop, +4% Lock Trigger)", target_pct=0.07, stop_pct=0.035, lock_trigger_pct=0.040)

# Target +6%, Stop 3.0%, Profit Lock trigger +3.5%
run_precision_swing("Precision Swing Engine B (+6% Target, 3.0% Stop, +3.5% Lock Trigger)", target_pct=0.06, stop_pct=0.030, lock_trigger_pct=0.035)
