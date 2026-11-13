"""
TraderAI - Deep Quantitative Pattern Mining & Monster Runner Laboratory
=======================================================================
Rigorous empirical research across 136 NSE Equities over 5 Years (1,236 sessions).
Explores non-obvious institutional momentum patterns, volume shocks, pocket pivots,
and multi-tranche runner exits under full Indian statutory delivery friction.
"""
import os
import sys
import math
import pickle
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.costs import compute_indian_delivery_costs

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 1. Load Cached Universe
univ_path = "data/cache/universe_5y.pkl"
bm_path = "data/cache/benchmarks_5y.pkl"

if not os.path.exists(univ_path) or not os.path.exists(bm_path):
    print("Universe cache not found!")
    sys.exit(1)

with open(univ_path, "rb") as f:
    universe = pickle.load(f)

with open(bm_path, "rb") as f:
    benchmarks = pickle.load(f)

nifty_df = benchmarks["^NSEI"]
all_dates = nifty_df.index
print(f"Loaded {len(universe)} NSE liquid equities across {len(all_dates)} historical sessions.")

# 2. Feature Enrichment Pipeline
def enrich_stock_features(df: pd.DataFrame, nifty: pd.DataFrame) -> pd.DataFrame:
    res = df.copy()
    c = res["Close"]
    h = res["High"]
    l = res["Low"]
    v = res["Volume"]
    o = res["Open"] if "Open" in res.columns else c

    # Moving averages
    res["ema10"] = c.ewm(span=10, adjust=False).mean()
    res["ema20"] = c.ewm(span=20, adjust=False).mean()
    res["sma50"] = c.rolling(50).mean()
    res["sma200"] = c.rolling(min(200, len(c))).mean()

    # True range & ATR
    tr1 = h - l
    tr2 = (h - c.shift(1)).abs()
    tr3 = (l - c.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    res["atr14"] = tr.rolling(14).mean()

    # Relative Volume (RVOL)
    res["vol_sma20"] = v.rolling(20).mean()
    res["rvol"] = v / res["vol_sma20"].replace(0, np.nan)

    # Bar Anatomy: Close Location (1.0 = closed at extreme high, 0.0 = low)
    bar_range = h - l
    res["close_loc"] = (c - l) / bar_range.replace(0, np.nan)
    res["is_bullish_bar"] = c >= o

    # Proximity to Highs
    res["high20"] = h.rolling(20).max().shift(1)
    res["high50"] = h.rolling(50).max().shift(1)
    res["high250"] = h.rolling(min(250, len(h))).max().shift(1)
    res["pct_from_52w"] = ((c - res["high250"]) / res["high250"].replace(0, np.nan)) * 100.0
    res["pct_from_50d"] = ((c - res["high50"]) / res["high50"].replace(0, np.nan)) * 100.0

    # Volume Dry-Up (VDU) in prior 3-5 days
    res["prior_v_min"] = v.shift(1).rolling(4).min() / res["vol_sma20"].shift(1).replace(0, np.nan)

    # Volatility Contraction Pattern (VCP ratio)
    range_5d = h.rolling(5).max() - l.rolling(5).min()
    range_20d = h.rolling(20).max() - l.rolling(20).min()
    res["vcp_ratio"] = range_5d / range_20d.replace(0, np.nan)

    # Pocket Pivot: Is today's up volume > highest down-day volume of past 10 days?
    down_vol = v.where(c < c.shift(1), 0.0)
    res["max_down_vol_10d"] = down_vol.shift(1).rolling(10).max()
    res["pocket_pivot"] = (c > c.shift(1)) & (v > res["max_down_vol_10d"]) & (c >= res["ema20"] * 0.98)

    # Distance to 20 EMA
    res["dist_ema20_pct"] = ((c - res["ema20"]) / res["ema20"].replace(0, np.nan)) * 100.0

    # Relative Strength vs NIFTY 50 over 5 and 20 days
    n_c = nifty["Close"].reindex(res.index, method="ffill")
    res["rs_5d"] = (c.pct_change(5) - n_c.pct_change(5)) * 100.0
    res["rs_20d"] = (c.pct_change(20) - n_c.pct_change(20)) * 100.0

    # Average Daily Turnover in Crores
    res["adtv_cr"] = (c * v).rolling(20).mean() / 1e7
    return res

print("Computing deep technical features across all equities...")
indicators = {sym: enrich_stock_features(df, nifty_df) for sym, df in universe.items()}

# Precalculate Nifty 50 Trend
nifty_c = nifty_df["Close"]
nifty_sma50 = nifty_c.rolling(50).mean()

# 3. Strategy Evaluation Framework
def run_simulation(
    strategy_name: str,
    signal_func,
    exit_mode: str = "FREE_ROLL_50",  # "FIXED_TARGET", "TRAIL_10EMA", "FREE_ROLL_50"
    base_target_pct: float = 12.0,
    base_stop_pct: float = 4.5,
    max_hold_days: int = 40,
    max_positions: int = 5,
    capital: float = 100000.0,
):
    cash = capital
    open_positions = {}
    pending_buys = []
    trades = []
    SLIPPAGE = 0.002  # 0.20% open fill slippage
    MIN_TICKET = 5000.0

    for i in range(250, len(all_dates)):
        date_idx = all_dates[i]
        date_str = str(date_idx.date())

        # Step 1: Execute Pending Orders from Yesterday at Today's OPEN
        if pending_buys:
            for item in pending_buys:
                sym, alloc = item
                if sym in open_positions or len(open_positions) >= max_positions:
                    continue
                ind = indicators[sym]
                if date_idx not in ind.index:
                    continue
                bar = ind.loc[date_idx]
                today_open = float(bar["Open"])
                if today_open <= 0 or math.isnan(today_open):
                    continue

                fill_px = round(today_open * (1.0 + SLIPPAGE), 2)
                trade_alloc = min(cash, alloc)
                if trade_alloc < MIN_TICKET:
                    continue

                qty = int(trade_alloc // fill_px)
                cost = qty * fill_px
                if qty > 0 and cash >= cost:
                    cash -= cost
                    stop_px = round(fill_px * (1.0 - (base_stop_pct / 100.0)), 2)
                    target_px = round(fill_px * (1.0 + (base_target_pct / 100.0)), 2)
                    open_positions[sym] = {
                        "entry_price": fill_px,
                        "qty": qty,
                        "initial_qty": qty,
                        "stop_loss": stop_px,
                        "target": target_px,
                        "peak_price": fill_px,
                        "days_held": 0,
                        "entry_date": date_str,
                        "is_runner": False,
                        "partial_booked": False,
                        "partial_profit": 0.0,
                        "partial_friction": 0.0,
                    }
            pending_buys = []

        # Step 2: Evaluate Exits on Active Positions
        to_close = []
        for sym, pos in open_positions.items():
            ind = indicators[sym]
            if date_idx not in ind.index:
                pos["days_held"] += 1
                continue
            bar = ind.loc[date_idx]
            pos["days_held"] += 1

            open_px = float(bar["Open"])
            high_px = float(bar["High"])
            low_px = float(bar["Low"])
            close_px = float(bar["Close"])
            ema10 = float(bar["ema10"]) if not math.isnan(bar["ema10"]) else close_px
            pos["peak_price"] = max(pos["peak_price"], high_px)

            exit_reason = None
            exit_px = close_px

            # Check Stop Loss First (Stop-First Daily Sequencing)
            current_stop = pos["stop_loss"]

            # Mode specific stop adjustments
            if exit_mode == "TRAIL_10EMA":
                if close_px > pos["entry_price"] * 1.05 and ema10 > current_stop:
                    current_stop = max(current_stop, round(ema10, 2))
                    pos["stop_loss"] = current_stop
            elif exit_mode == "FREE_ROLL_50":
                # If partial booked, trail remaining 50% with 10 EMA
                if pos["partial_booked"]:
                    if ema10 > current_stop:
                        current_stop = max(current_stop, round(ema10, 2))
                        pos["stop_loss"] = current_stop

            if low_px <= current_stop:
                exit_reason = "STOP_LOSS" if current_stop <= pos["entry_price"] else "TRAILING_STOP_HIT"
                exit_px = min(current_stop, open_px) if open_px < current_stop else current_stop
            elif exit_mode == "FIXED_TARGET" and high_px >= pos["target"]:
                exit_reason = "TARGET_HIT"
                exit_px = pos["target"]
            elif exit_mode == "FREE_ROLL_50" and not pos["partial_booked"] and high_px >= pos["target"]:
                # Partial profit take on 50% shares, ratchet stop on remaining 50% to Breakeven + 1%
                half_qty = pos["qty"] // 2
                if half_qty > 0:
                    costs = compute_indian_delivery_costs(
                        buy_price=pos["entry_price"],
                        sell_price=pos["target"],
                        quantity=half_qty,
                    )
                    cash += (pos["target"] * half_qty) - costs.total_friction_rupees
                    pos["partial_profit"] = costs.net_pnl_rupees
                    pos["partial_friction"] = costs.total_friction_rupees
                    pos["qty"] -= half_qty
                    pos["partial_booked"] = True
                    # Ratchet stop on remaining shares to Breakeven + 1%
                    pos["stop_loss"] = max(pos["stop_loss"], round(pos["entry_price"] * 1.01, 2))
                    pos["is_runner"] = True
            elif pos["days_held"] >= max_hold_days:
                exit_reason = "TIME_EXPIRY"
                exit_px = close_px

            if exit_reason:
                # Final exit
                costs = compute_indian_delivery_costs(
                    buy_price=pos["entry_price"],
                    sell_price=exit_px,
                    quantity=pos["qty"],
                )
                tot_pnl = costs.net_pnl_rupees + pos["partial_profit"]
                tot_friction = costs.total_friction_rupees + pos["partial_friction"]
                cash += (exit_px * pos["qty"]) - costs.total_friction_rupees
                pnl_pct = ((exit_px - pos["entry_price"]) / pos["entry_price"]) * 100.0

                trades.append({
                    "ticker": sym,
                    "entry_date": pos["entry_date"],
                    "exit_date": date_str,
                    "days_held": pos["days_held"],
                    "entry_px": pos["entry_price"],
                    "exit_px": exit_px,
                    "peak_gain_pct": round(((pos["peak_price"] - pos["entry_price"]) / pos["entry_price"]) * 100.0, 1),
                    "net_pnl": tot_pnl,
                    "pnl_pct": pnl_pct,
                    "friction": tot_friction,
                    "reason": exit_reason,
                    "partial_booked": pos["partial_booked"],
                })
                to_close.append(sym)

        for sym in to_close:
            del open_positions[sym]

        # Step 3: Scan for New Setups at EOD
        empty_slots = max_positions - (len(open_positions) + len(pending_buys))
        if empty_slots > 0:
            candidates = []
            for sym, ind in indicators.items():
                if sym in open_positions or any(sym == p[0] for p in pending_buys):
                    continue
                if date_idx not in ind.index:
                    continue
                bar = ind.loc[date_idx]

                # Check signal
                score = signal_func(bar, nifty_c.loc[date_idx], nifty_sma50.loc[date_idx])
                if score > 0:
                    candidates.append((sym, score, float(bar["Close"])))

            candidates.sort(key=lambda x: x[1], reverse=True)
            for c in candidates[:empty_slots]:
                alloc = min(cash / max(1, empty_slots), capital * 0.20)
                pending_buys.append((c[0], alloc))

    df_t = pd.DataFrame(trades)
    return df_t

# 4. Pattern Definitions
def pattern_1_volume_ignition(bar, n_close, n_sma):
    """
    Pattern 1: Volume Shock Ignition following Consolidation
    - RVOL >= 1.8x
    - Close location in bar >= 0.75 (strong close)
    - Close above 20 EMA & 50 SMA
    - ADTV >= 5 Cr
    """
    if bar["adtv_cr"] < 5.0 or bar["Close"] < 15.0:
        return 0
    if bar["rvol"] >= 1.8 and bar["close_loc"] >= 0.75 and bar["is_bullish_bar"]:
        if bar["Close"] > bar["ema20"] and bar["Close"] > bar["sma50"]:
            return float(bar["rvol"] * 10.0 + bar["close_loc"] * 20.0)
    return 0

def pattern_2_springboard_vdu_to_shock(bar, n_close, n_sma):
    """
    Pattern 2: The Springboard (VDU Dry-Up -> Volume Shock Ignition)
    - Prior 4-day volume dried up to <= 0.65x
    - Volatility contracted (VCP <= 0.65)
    - Day 0 Volume Shock RVOL >= 1.6x, Bullish Close
    """
    if bar["adtv_cr"] < 5.0 or bar["Close"] < 15.0:
        return 0
    if bar["prior_v_min"] <= 0.65 and bar["vcp_ratio"] <= 0.65:
        if bar["rvol"] >= 1.6 and bar["is_bullish_bar"] and bar["close_loc"] >= 0.70:
            if bar["Close"] > bar["ema20"]:
                return float(bar["rvol"] * 15.0 + (1.0 - bar["vcp_ratio"]) * 30.0)
    return 0

def pattern_3_alpha_decoupling_rocket(bar, n_close, n_sma):
    """
    Pattern 3: Alpha Decoupling Leader (Outperforming NIFTY during chop)
    - 5-day RS vs Nifty >= +3.5%
    - Within 12% of 52-week High
    - RVOL >= 1.4x
    - Stage 2: Price > 50 SMA
    """
    if bar["adtv_cr"] < 5.0 or bar["Close"] < 15.0:
        return 0
    if bar["rs_5d"] >= 3.5 and bar["pct_from_52w"] >= -12.0:
        if bar["rvol"] >= 1.4 and bar["Close"] > bar["sma50"] and bar["is_bullish_bar"]:
            return float(bar["rs_5d"] * 5.0 + bar["rvol"] * 10.0)
    return 0

def pattern_4_pocket_pivot(bar, n_close, n_sma):
    """
    Pattern 4: Institutional Pocket Pivot Breakout (Wyckoff/O'Neil)
    - Today's up-volume exceeds highest down-day volume of past 10 days
    - Rebounding or breaking out near 10 EMA / 20 EMA
    - Stage 2 Trend (Close > 50 SMA)
    """
    if bar["adtv_cr"] < 5.0 or bar["Close"] < 15.0:
        return 0
    if bar["pocket_pivot"] and bar["Close"] > bar["sma50"] and bar["close_loc"] >= 0.70:
        return float(bar["rvol"] * 12.0)
    return 0

def pattern_5_super_mover_master(bar, n_close, n_sma):
    """
    Pattern 5: Master Confluence Super-Mover
    - Confluence of Stage 2 + Proximity to 52W High (within 10%)
    - RVOL >= 1.7x & Strong Close >= 0.75
    - Decoupled RS 5d >= +2.0%
    """
    if bar["adtv_cr"] < 5.0 or bar["Close"] < 15.0:
        return 0
    if bar["pct_from_52w"] >= -10.0 and bar["Close"] > bar["sma50"]:
        if bar["rvol"] >= 1.7 and bar["close_loc"] >= 0.75 and bar["is_bullish_bar"]:
            if bar["rs_5d"] >= 2.0:
                return float(bar["rvol"] * 20.0 + bar["rs_5d"] * 5.0)
    return 0

# 5. Execute Empirical Battery of Tests
experiments = [
    # Baseline comparison: Fixed Target vs Trailing 10 EMA vs Free-Roll 50/50
    ("1. Volume Ignition (Fixed +12% Target)", pattern_1_volume_ignition, "FIXED_TARGET", 12.0, 4.5),
    ("2. Volume Ignition (Uncapped 10 EMA Runner)", pattern_1_volume_ignition, "TRAIL_10EMA", 12.0, 4.5),
    ("3. Volume Ignition (Free-Roll 50/50 Staged)", pattern_1_volume_ignition, "FREE_ROLL_50", 12.0, 4.5),
    
    # Pattern Explorations
    ("4. The Springboard (VDU -> Volume Shock)", pattern_2_springboard_vdu_to_shock, "FREE_ROLL_50", 12.0, 4.5),
    ("5. Alpha Decoupling Rocket (RS >= 3.5%)", pattern_3_alpha_decoupling_rocket, "FREE_ROLL_50", 12.0, 4.5),
    ("6. Institutional Pocket Pivot", pattern_4_pocket_pivot, "FREE_ROLL_50", 12.0, 4.5),
    ("7. Master Confluence Super-Mover", pattern_5_super_mover_master, "FREE_ROLL_50", 14.0, 4.5),
]

results = []

print("\n" + "=" * 90)
print("⚡ RUNNING DEEP EMPIRICAL PATTERN & ALGORITHM EXPLORATION (136 NSE EQUITIES, 5 YEARS)")
print("=" * 90)

for name, p_func, mode, target, stop in experiments:
    df_res = run_simulation(name, p_func, exit_mode=mode, base_target_pct=target, base_stop_pct=stop)
    if len(df_res) == 0:
        continue
    
    n_trades = len(df_res)
    win_rate = (df_res["net_pnl"] > 0).mean() * 100.0
    tot_pnl = df_res["net_pnl"].sum()
    tot_friction = df_res["friction"].sum()
    wins = df_res[df_res["net_pnl"] > 0]["net_pnl"]
    losses = df_res[df_res["net_pnl"] <= 0]["net_pnl"].abs()
    avg_win = wins.mean() if len(wins) else 0.0
    avg_loss = losses.mean() if len(losses) else 0.0
    profit_factor = (wins.sum() / losses.sum()) if losses.sum() > 0 else 99.0
    payoff = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    expectancy = df_res["net_pnl"].mean()

    # Outlier capture metrics: How many runners gained >= 20% and >= 35%?
    runners_20 = (df_res["peak_gain_pct"] >= 20.0).sum()
    runners_35 = (df_res["peak_gain_pct"] >= 35.0).sum()
    max_single_gain = df_res["peak_gain_pct"].max()

    results.append({
        "Strategy": name,
        "Trades": n_trades,
        "Win Rate": f"{win_rate:.1f}%",
        "Net P&L (₹)": tot_pnl,
        "Profit Factor": f"{profit_factor:.2f}",
        "Payoff (W/L)": f"{payoff:.2f}:1",
        "Expectancy": f"₹{expectancy:+.1f}",
        "Runners >=20%": runners_20,
        "Runners >=35%": runners_35,
        "Max Peak Gain": f"+{max_single_gain:.1f}%",
        "Friction Paid": tot_friction,
    })

df_summary = pd.DataFrame(results)

print("\n" + "=" * 115)
print("🏆 EMPIRICAL LEADERBOARD: ALGORITHM & PATTERN DISCOVERY BENCHMARK")
print("=" * 115)
print(f"{'Strategy / Algorithm':<42} | {'Trades':<6} | {'WinRate':<7} | {'Net P&L (₹)':<14} | {'PF':<5} | {'Payoff':<6} | {'20%+ Run':<8} | {'Max Peak':<8}")
print("-" * 115)
for _, r in df_summary.iterrows():
    print(f"{r['Strategy']:<42} | {r['Trades']:<6} | {r['Win Rate']:<7} | ₹{r['Net P&L (₹)']:>11,.1f} | {r['Profit Factor']:<5} | {r['Payoff (W/L)']:<6} | {r['Runners >=20%']:<8} | {r['Max Peak Gain']:<8}")
print("=" * 115)

# Find top monster trades in the best performing strategy
print("\n" + "=" * 90)
print("🚀 TOP 10 GREATEST MONSTER RUNNERS DISCOVERED ACROSS SIMULATIONS:")
print("=" * 90)
best_run = run_simulation("Master Confluence Super-Mover", pattern_5_super_mover_master, exit_mode="FREE_ROLL_50", base_target_pct=14.0)
top_winners = best_run.sort_values(by="peak_gain_pct", ascending=False).head(10)
for idx, r in top_winners.reset_index().iterrows():
    print(f"#{idx+1:02d} {r['ticker']:<15} | Entry: {r['entry_date']} -> Exit: {r['exit_date']} ({r['days_held']:2d}d) | Entry: ₹{r['entry_px']:8.2f} -> Peak: +{r['peak_gain_pct']:5.1f}% | Net P&L: ₹{r['net_pnl']:+8.1f} ({r['pnl_pct']:+5.1f}%) | {r['reason']}")
print("=" * 90)

