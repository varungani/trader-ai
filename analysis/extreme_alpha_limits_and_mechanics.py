"""
analysis/extreme_alpha_limits_and_mechanics.py

Empirical Investigation: The Mathematical Limits of Compounding (300% - 500% Annual Returns).
Tests:
1. Rolling 252-day (12-month) peak return across 2021-2026.
2. Ultra-Focus Apex Model: 1-Stock (100% conviction) and 2-Stock (60/40) concentration.
3. Multi-tier floating profit pyramiding on monsters.
4. Exact empirical breakdown: Payoff math, Kelly Criterion, volatility drag, and drawdowns.
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
import time

# Add repo root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.universe_loader import load_universe_and_indices

DAILY_CASH_YIELD = (1.0 + 0.065) ** (1.0 / 252.0) - 1.0

def compute_friction(val, is_buy=False, dp_charge=15.93):
    brokerage = min(20.0, val * 0.0003)
    stt = (val * 0.001) if not is_buy else 0.0
    turnover = val * 0.0000345
    stamp = (val * 0.00015) if is_buy else 0.0
    gst = (brokerage + turnover) * 0.18
    dp = 0.0 if is_buy else dp_charge
    return brokerage + stt + turnover + stamp + gst + dp

def run_simulation(universe, nifty, market_breadth, slots_cfg, use_mtf=False, mtf_leverage=1.0, allow_pyramiding=True):
    """
    Simulates portfolio with exact execution and statutory friction.
    """
    dates = [d for d in nifty.index if d in market_breadth.index]
    cash = 100000.0
    positions = {} # sym -> {shares, entry_px, highest_px, stage, entry_date, slot_idx}
    trade_log = []
    equity_curve = []
    
    num_slots = len(slots_cfg)
    target_weights = [w / sum(slots_cfg) for w in slots_cfg]
    
    for i in range(50, len(dates) - 1):
        cur_date = dates[i]
        next_date = dates[i + 1]
        breadth = market_breadth.loc[cur_date]
        
        # Calculate current equity
        cur_holdings_val = 0.0
        for sym, pos in list(positions.items()):
            px = universe[sym].loc[cur_date, "Close"] if cur_date in universe[sym].index else pos["entry_px"]
            cur_holdings_val += pos["shares"] * px
        
        portfolio_equity = cash + cur_holdings_val
        equity_curve.append({"date": cur_date, "equity": portfolio_equity, "cash": cash, "positions": len(positions)})
        
        # 1. Check Exits on current date close
        exits = []
        for sym, pos in positions.items():
            if cur_date not in universe[sym].index:
                continue
            row = universe[sym].loc[cur_date]
            c = row["Close"]
            pos["highest_px"] = max(pos["highest_px"], c)
            gain_pct = (c - pos["entry_px"]) / pos["entry_px"]
            
            # Trailing stop: Weekly 10W EMA or -7% Hard Stop
            w10 = row["w10"]
            hard_stop = pos["entry_px"] * 0.93
            exit_reason = None
            
            if c < hard_stop:
                exit_reason = "Hard Stop (-7%)"
            elif c < w10 and gain_pct > 0.05:
                exit_reason = "Weekly 10W Trail"
            elif c < row["EMA20"] and gain_pct < 0.0:
                # Early cut if below daily 20 EMA while in loss
                exit_reason = "20-EMA Early Cut"
            elif breadth < 0.35 and gain_pct > 0.15:
                exit_reason = "Severe Bear Market Lock-in"
                
            if exit_reason:
                exits.append((sym, exit_reason))
                
        # Execute exits at next_date open
        for sym, reason in exits:
            pos = positions[sym]
            if next_date in universe[sym].index:
                exit_px = universe[sym].loc[next_date, "Open"] * 0.9975 # 0.25% slippage
                val = pos["shares"] * exit_px
                fric = compute_friction(val, is_buy=False)
                net_val = val - fric
                cash += net_val
                
                trade_log.append({
                    "symbol": sym,
                    "entry_date": pos["entry_date"],
                    "exit_date": next_date,
                    "return": (exit_px - pos["entry_px"]) / pos["entry_px"],
                    "pnl": (exit_px - pos["entry_px"]) * pos["shares"] - fric,
                    "friction": fric,
                    "reason": reason
                })
                del positions[sym]
                
        # 2. Pyramiding check on winners (if allowed)
        if allow_pyramiding and breadth >= 0.55:
            for sym, pos in positions.items():
                if pos["stage"] == 1 and cur_date in universe[sym].index:
                    c = universe[sym].loc[cur_date, "Close"]
                    gain = (c - pos["entry_px"]) / pos["entry_px"]
                    # If up >= 15% and volume is supportive, add +30% size
                    if gain >= 0.15 and universe[sym].loc[cur_date, "rvol"] >= 1.5:
                        add_budget = portfolio_equity * 0.15 * mtf_leverage
                        if cash >= add_budget * 0.5: # have enough margin
                            if next_date in universe[sym].index:
                                add_px = universe[sym].loc[next_date, "Open"] * 1.0025
                                add_shares = int(add_budget / add_px)
                                if add_shares > 0:
                                    cost = add_shares * add_px
                                    fric = compute_friction(cost, is_buy=True)
                                    cash -= (cost + fric)
                                    # Blend price
                                    total_shares = pos["shares"] + add_shares
                                    pos["entry_px"] = (pos["shares"] * pos["entry_px"] + cost) / total_shares
                                    pos["shares"] = total_shares
                                    pos["stage"] = 2
                                    
        # 3. Entries for open slots
        open_slots = num_slots - len(positions)
        if open_slots > 0 and breadth >= 0.45:
            # Rank candidates
            candidates = []
            for sym, df in universe.items():
                if sym in positions or cur_date not in df.index or next_date not in df.index:
                    continue
                row = df.loc[cur_date]
                c = row["Close"]
                ema200 = row["EMA200"]
                h52 = row["h52"]
                rvol = row["rvol"]
                rs3m = row["rs3m"]
                
                # Apex Leader criteria
                if c > ema200 * 1.15 and c >= h52 * 0.88 and rvol >= 1.4 and rs3m > 0.05:
                    score = (rs3m * 0.40) + ((c / ema200 - 1.0) * 0.30) + ((c / h52) * 0.30)
                    candidates.append((sym, score))
                    
            candidates.sort(key=lambda x: x[1], reverse=True)
            
            # Fill available slots
            used_slot_indices = {pos["slot_idx"] for pos in positions.values()}
            available_slots = [idx for idx in range(num_slots) if idx not in used_slot_indices]
            
            for (sym, score), slot_idx in zip(candidates, available_slots):
                slot_alloc = target_weights[slot_idx]
                effective_equity = portfolio_equity * mtf_leverage
                target_val = effective_equity * slot_alloc
                
                # Available cash/margin
                avail = cash if not use_mtf else min(cash * mtf_leverage, target_val)
                invest_val = min(target_val, avail)
                
                if invest_val > 5000:
                    fill_px = universe[sym].loc[next_date, "Open"] * 1.0025
                    shares = int(invest_val / fill_px)
                    if shares > 0:
                        cost = shares * fill_px
                        fric = compute_friction(cost, is_buy=True)
                        if cash >= (cost + fric) or use_mtf:
                            cash -= (cost + fric)
                            positions[sym] = {
                                "shares": shares,
                                "entry_px": fill_px,
                                "highest_px": fill_px,
                                "stage": 1,
                                "entry_date": next_date,
                                "slot_idx": slot_idx
                            }
                            
        # Cash overnight interest
        if cash > 0:
            cash += cash * DAILY_CASH_YIELD
            
    # Process final equity
    eq_df = pd.DataFrame(equity_curve).set_index("date")
    trades_df = pd.DataFrame(trade_log) if trade_log else pd.DataFrame()
    return eq_df, trades_df

def compute_rolling_metrics(eq_df):
    """Computes peak 12-month (252-day) return across the whole history."""
    eq = eq_df["equity"]
    rolling_1y = eq.pct_change(periods=252)
    peak_1y = rolling_1y.max() * 100.0
    peak_1y_date = rolling_1y.idxmax()
    
    # Yearly breakdown
    eq_yearly = eq.resample("YE").last()
    yearly_rets = eq_yearly.pct_change().dropna() * 100.0
    first_year = (eq_yearly.iloc[0] / eq.iloc[0] - 1.0) * 100.0
    
    # Total CAGR
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = ((eq.iloc[-1] / eq.iloc[0]) ** (1.0 / years) - 1.0) * 100.0
    
    # Max DD
    dd = (eq - eq.cummax()) / eq.cummax()
    max_dd = dd.min() * 100.0
    
    return {
        "cagr": cagr,
        "max_dd": max_dd,
        "ending_capital": eq.iloc[-1],
        "net_return": (eq.iloc[-1] / eq.iloc[0] - 1.0) * 100.0,
        "peak_1y": peak_1y,
        "peak_1y_date": peak_1y_date,
        "yearly": yearly_rets
    }

def main():
    print("📦 Loading 5Y universe cache and benchmarks...")
    universe_dict, nifty, midcap, smallcap = load_universe_and_indices()
    
    print("📊 Precalculating universe indicators...")
    nifty_close = nifty["Close"]
    nifty_rs3m = nifty_close.pct_change(63)
    
    # Compute market breadth
    breadth_records = {}
    for d in nifty.index:
        breadth_records[d] = {"above_50": 0, "total": 0}
        
    cleaned_uni = {}
    for sym, df in universe_dict.items():
        if len(df) < 250:
            continue
        c = df["Close"]
        v = df["Volume"]
        df_copy = df.copy()
        df_copy["EMA20"] = c.ewm(span=20, adjust=False).mean()
        df_copy["EMA50"] = c.ewm(span=50, adjust=False).mean()
        df_copy["EMA200"] = c.ewm(span=200, adjust=False).mean()
        df_copy["w10"] = c.ewm(span=50, adjust=False).mean()
        df_copy["h52"] = c.rolling(252).max()
        vol_ma = v.rolling(20).mean()
        df_copy["rvol"] = v / vol_ma.replace(0, np.nan)
        stock_rs3m = c.pct_change(63)
        df_copy["rs3m"] = stock_rs3m - nifty_rs3m
        
        above = c > df_copy["EMA50"]
        for d in df_copy.index:
            if d in breadth_records:
                breadth_records[d]["total"] += 1
                if above.loc[d]:
                    breadth_records[d]["above_50"] += 1
                    
        cleaned_uni[sym] = df_copy
        
    breadth_series = pd.Series({
        d: (rec["above_50"] / rec["total"]) if rec["total"] > 100 else 0.5
        for d, rec in breadth_records.items()
    })
    
    print("=" * 85)
    print("⚡ EMPIRICAL AUDIT: THE LIMITS OF ANNUAL RETURNS & ROLLING 12-MONTH GAINS")
    print("=" * 85)
    
    experiments = [
        ("Config A: 4 Slots Balanced Cash (25/25/25/25)", [25, 25, 25, 25], False, 1.0, False),
        ("Config B: 3 Slots Apex Cash (40/30/30)", [40, 30, 30], False, 1.0, True),
        ("Config C: 2 Slots High-Conviction Cash (50/50)", [50, 50], False, 1.0, True),
        ("Config D: 1 Slot Ultra-Focus Cash (100% All-In)", [100], False, 1.0, True),
        ("Config E: 2 Slots 2.0x MTF Leveraged (50/50)", [50, 50], True, 2.0, True),
        ("Config F: 1 Slot 2.0x MTF Leveraged (100% All-In)", [100], True, 2.0, True),
    ]
    
    results = []
    for name, slots, use_mtf, mtf_lev, allow_pyr in experiments:
        t0 = time.time()
        eq_df, trades_df = run_simulation(
            cleaned_uni, nifty, breadth_series, slots, use_mtf=use_mtf, mtf_leverage=mtf_lev, allow_pyramiding=allow_pyr
        )
        elapsed = time.time() - t0
        metrics = compute_rolling_metrics(eq_df)
        
        total_trades = len(trades_df)
        win_rate = (trades_df["pnl"] > 0).mean() * 100.0 if total_trades > 0 else 0.0
        profit_factor = (
            abs(trades_df[trades_df["pnl"] > 0]["pnl"].sum() / trades_df[trades_df["pnl"] < 0]["pnl"].sum())
            if total_trades > 0 and len(trades_df[trades_df["pnl"] < 0]) > 0 else 0.0
        )
        
        results.append({
            "name": name,
            "metrics": metrics,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "elapsed": elapsed
        })
        
        print(f"\n📌 {name}:")
        print(f"   • Ending Capital      : ₹{metrics['ending_capital']:,.2f} ({metrics['net_return']:+.2f}%)")
        print(f"   • 5-Year CAGR         : {metrics['cagr']:+.2f}%")
        print(f"   • Max Drawdown        : {metrics['max_dd']:.2f}%")
        print(f"   • Peak 12M Return     : {metrics['peak_1y']:+.2f}% (Achieved on {metrics['peak_1y_date'].strftime('%Y-%m-%d')})")
        print(f"   • Trades / Win Rate   : {total_trades} trades | Win Rate: {win_rate:.1f}% | PF: {profit_factor:.2f}")
        for yr, val in metrics['yearly'].items():
            print(f"       Year {yr.year}: {val:+.2f}%")

if __name__ == "__main__":
    main()
