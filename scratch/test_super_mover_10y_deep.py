"""
TraderAI - 10-Year Deep Super-Mover & Quantitative Frontier Laboratory
=====================================================================
Evaluates the Master Confluence Super-Mover & Free-Roll Architecture across 
10 FULL YEARS (2016 to 2026, ~2,500 trading days) on liquid NSE equities.
Tests multiple trailing runner variations, regime filters, and volume thresholds.
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

u10_path = "data/cache/universe_10y.pkl"
b10_path = "data/cache/benchmarks_10y.pkl"

if not os.path.exists(u10_path) or not os.path.exists(b10_path):
    print("10Y Cache missing, falling back to 5Y")
    u10_path = "data/cache/universe_5y.pkl"
    b10_path = "data/cache/benchmarks_5y.pkl"

with open(u10_path, "rb") as f:
    universe = pickle.load(f)

with open(b10_path, "rb") as f:
    benchmarks = pickle.load(f)

nifty_df = benchmarks["^NSEI"]
all_dates = nifty_df.index
print(f"Loaded {len(universe)} stocks across {len(all_dates)} historical bars ({all_dates[0].date()} to {all_dates[-1].date()}).")

def enrich_features(df: pd.DataFrame, nifty: pd.DataFrame) -> pd.DataFrame:
    res = df.copy()
    c, h, l, v = res["Close"], res["High"], res["Low"], res["Volume"]
    o = res["Open"] if "Open" in res.columns else c

    res["ema10"] = c.ewm(span=10, adjust=False).mean()
    res["ema20"] = c.ewm(span=20, adjust=False).mean()
    res["sma50"] = c.rolling(50).mean()
    res["sma200"] = c.rolling(min(200, len(c))).mean()

    # ATR 14
    tr1 = h - l
    tr2 = (h - c.shift(1)).abs()
    tr3 = (l - c.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    res["atr14"] = tr.rolling(14).mean()

    # RVOL & Turnover
    res["vol_sma20"] = v.rolling(20).mean()
    res["rvol"] = v / res["vol_sma20"].replace(0, np.nan)
    res["adtv_cr"] = (c * v).rolling(20).mean() / 1e7

    # Bar Anatomy
    bar_range = h - l
    res["close_loc"] = (c - l) / bar_range.replace(0, np.nan)
    res["is_bullish_bar"] = c >= o

    # 52W Proximity
    res["high250"] = h.rolling(min(250, len(h))).max().shift(1)
    res["pct_from_52w"] = ((c - res["high250"]) / res["high250"].replace(0, np.nan)) * 100.0

    # 5-day RS vs NIFTY 50
    n_c = nifty["Close"].reindex(res.index, method="ffill")
    res["rs_5d"] = (c.pct_change(5) - n_c.pct_change(5)) * 100.0

    # Volatility Contraction Pattern (VCP)
    range_5d = h.rolling(5).max() - l.rolling(5).min()
    range_20d = h.rolling(20).max() - l.rolling(20).min()
    res["vcp_ratio"] = range_5d / range_20d.replace(0, np.nan)

    return res

print("Computing 10-year indicators...")
indicators = {sym: enrich_features(df, nifty_df) for sym, df in universe.items() if len(df) >= 200}
nifty_c = nifty_df["Close"]
nifty_sma50 = nifty_c.rolling(50).mean()

def run_10y_backtest(
    name: str,
    rvol_thresh: float = 1.6,
    dist_52w_thresh: float = -10.0,
    rs_thresh: float = 2.0,
    trail_mode: str = "EMA10",  # "EMA10", "EMA20", "ATR2.0"
    base_target: float = 12.0,
    base_stop: float = 4.5,
    max_days: int = 40,
    max_positions: int = 5,
    capital: float = 100000.0,
):
    cash = capital
    open_positions = {}
    pending_buys = []
    trades = []
    SLIPPAGE = 0.002
    MIN_TICKET = 4000.0

    for i in range(250, len(all_dates)):
        date_idx = all_dates[i]
        date_str = str(date_idx.date())

        # Step 1: Execute Pending Orders at Open
        if pending_buys:
            for item in pending_buys:
                sym, alloc = item
                if sym in open_positions or len(open_positions) >= max_positions:
                    continue
                ind = indicators.get(sym)
                if ind is None or date_idx not in ind.index:
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
                    stop_px = round(fill_px * (1.0 - (base_stop / 100.0)), 2)
                    target_px = round(fill_px * (1.0 + (base_target / 100.0)), 2)
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

        # Step 2: Manage Exits
        to_close = []
        for sym, pos in open_positions.items():
            ind = indicators.get(sym)
            if ind is None or date_idx not in ind.index:
                pos["days_held"] += 1
                continue
            bar = ind.loc[date_idx]
            pos["days_held"] += 1

            open_px = float(bar["Open"])
            high_px = float(bar["High"])
            low_px = float(bar["Low"])
            close_px = float(bar["Close"])
            pos["peak_price"] = max(pos["peak_price"], high_px)

            current_stop = pos["stop_loss"]

            # Dynamic Trailing after Tranche 1 Partial Hit
            if pos["partial_booked"]:
                if trail_mode == "EMA10":
                    ema = float(bar["ema10"])
                    if not math.isnan(ema) and ema > current_stop:
                        current_stop = max(current_stop, round(ema, 2))
                elif trail_mode == "EMA20":
                    ema = float(bar["ema20"])
                    if not math.isnan(ema) and ema > current_stop:
                        current_stop = max(current_stop, round(ema, 2))
                elif trail_mode == "ATR2.0":
                    atr = float(bar["atr14"])
                    if not math.isnan(atr) and atr > 0:
                        trail_level = round(pos["peak_price"] - (2.0 * atr), 2)
                        current_stop = max(current_stop, trail_level)

                pos["stop_loss"] = current_stop

            exit_reason = None
            exit_px = close_px

            if low_px <= current_stop:
                exit_reason = "STOP_LOSS" if current_stop <= pos["entry_price"] else "TRAILING_STOP"
                exit_px = min(current_stop, open_px) if open_px < current_stop else current_stop
            elif not pos["partial_booked"] and high_px >= pos["target"]:
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
                    pos["stop_loss"] = max(pos["stop_loss"], round(pos["entry_price"] * 1.01, 2))
                    pos["is_runner"] = True
            elif pos["days_held"] >= max_days:
                exit_reason = "TIME_EXPIRY"
                exit_px = close_px

            if exit_reason:
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
                    "year": int(date_str[:4]),
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

        # Step 3: Scan for Setups at EOD
        empty_slots = max_positions - (len(open_positions) + len(pending_buys))
        if empty_slots > 0:
            candidates = []
            for sym, ind in indicators.items():
                if sym in open_positions or any(sym == p[0] for p in pending_buys):
                    continue
                if date_idx not in ind.index:
                    continue
                bar = ind.loc[date_idx]

                # Core Super-Mover Filter
                if bar["adtv_cr"] < 4.0 or bar["Close"] < 15.0:
                    continue
                if bar["Close"] <= bar["sma50"]:
                    continue
                if bar["pct_from_52w"] < dist_52w_thresh:
                    continue
                if bar["rvol"] < rvol_thresh:
                    continue
                if bar["close_loc"] < 0.70 or not bar["is_bullish_bar"]:
                    continue
                if bar["rs_5d"] < rs_thresh:
                    continue

                score = float(bar["rvol"] * 15.0 + bar["rs_5d"] * 5.0 + bar["close_loc"] * 10.0)
                candidates.append((sym, score, float(bar["Close"])))

            candidates.sort(key=lambda x: x[1], reverse=True)
            for c in candidates[:empty_slots]:
                alloc = min(cash / max(1, empty_slots), capital * 0.20)
                pending_buys.append((c[0], alloc))

    return pd.DataFrame(trades)

# Run Variations
configs = [
    ("A. 10Y Baseline (Target 12%, Trail 10 EMA, RVOL>=1.6)", 1.6, -10.0, 2.0, "EMA10", 12.0),
    ("B. 10Y Loose Trail (Target 14%, Trail 20 EMA, RVOL>=1.6)", 1.6, -10.0, 2.0, "EMA20", 14.0),
    ("C. 10Y Volatility Trail (Target 14%, Trail 2.0x ATR)", 1.6, -10.0, 2.0, "ATR2.0", 14.0),
    ("D. 10Y High-Volume Sniper (Target 15%, RVOL>=2.0x Shock)", 2.0, -8.0, 3.0, "EMA10", 15.0),
    ("E. 10Y Early Ignition (Target 15%, RVOL>=1.5x, Within 15% 52W)", 1.5, -15.0, 1.5, "EMA10", 15.0),
]

summary_rows = []
all_dfs = {}

print("\n" + "=" * 100)
print("⚡ EXECUTING 10-YEAR HISTORICAL EMPIRICAL SCRUTINY (2016 - 2026)")
print("=" * 100)

for name, rvol, dist, rs, trail, tgt in configs:
    df_res = run_10y_backtest(name, rvol_thresh=rvol, dist_52w_thresh=dist, rs_thresh=rs, trail_mode=trail, base_target=tgt)
    all_dfs[name] = df_res
    if len(df_res) == 0:
        continue

    n_trades = len(df_res)
    win_rate = (df_res["net_pnl"] > 0).mean() * 100.0
    tot_pnl = df_res["net_pnl"].sum()
    tot_friction = df_res["friction"].sum()
    wins = df_res[df_res["net_pnl"] > 0]["net_pnl"]
    losses = df_res[df_res["net_pnl"] <= 0]["net_pnl"].abs()
    pf = (wins.sum() / losses.sum()) if losses.sum() > 0 else 99.0
    payoff = (wins.mean() / losses.mean()) if len(losses) and len(wins) else 0.0
    r20 = (df_res["peak_gain_pct"] >= 20.0).sum()
    r35 = (df_res["peak_gain_pct"] >= 35.0).sum()
    max_peak = df_res["peak_gain_pct"].max()

    summary_rows.append({
        "Configuration": name,
        "Trades": n_trades,
        "WinRate": f"{win_rate:.1f}%",
        "Net P&L (₹)": tot_pnl,
        "Profit Factor": f"{pf:.2f}",
        "Payoff": f"{payoff:.2f}:1",
        "Runners >=20%": r20,
        "Runners >=35%": r35,
        "Max Move": f"+{max_peak:.1f}%",
        "Friction Paid": f"₹{tot_friction:,.0f}",
    })

df_sum = pd.DataFrame(summary_rows)

print("\n" + "=" * 115)
print("🏆 10-YEAR ROBUSTNESS BENCHMARK (2016 - 2026 NET OF ALL STATUTORY COSTS):")
print("=" * 115)
print(f"{'Configuration':<52} | {'Trades':<6} | {'WinRate':<7} | {'Net P&L (₹)':<14} | {'PF':<5} | {'Payoff':<6} | {'20%+ Run':<8} | {'Max Peak':<8}")
print("-" * 115)
for _, r in df_sum.iterrows():
    print(f"{r['Configuration']:<52} | {r['Trades']:<6} | {r['WinRate']:<7} | ₹{r['Net P&L (₹)']:>11,.1f} | {r['Profit Factor']:<5} | {r['Payoff']:<6} | {r['Runners >=20%']:<8} | {r['Max Move']:<8}")
print("=" * 115)

# Year-by-year consistency of the leading configuration
best_cfg_name = df_sum.sort_values(by="Net P&L (₹)", ascending=False).iloc[0]["Configuration"]
best_df = all_dfs[best_cfg_name]

print(f"\n" + "=" * 80)
print(f"📅 YEAR-BY-YEAR P&L OF BEST ENGINE: {best_cfg_name}")
print("=" * 80)
print(f"{'Year':<6} | {'Trades':<6} | {'Win Rate':<8} | {'Net P&L (₹)':<14} | {'Avg P&L/Trade':<14} | {'20%+ Runners':<12}")
print("-" * 80)
for yr, grp in best_df.groupby("year"):
    yr_pnl = grp["net_pnl"].sum()
    yr_wr = (grp["net_pnl"] > 0).mean() * 100.0
    yr_avg = grp["net_pnl"].mean()
    yr_r20 = (grp["peak_gain_pct"] >= 20.0).sum()
    print(f"{yr:<6} | {len(grp):<6} | {yr_wr:>6.1f}%  | ₹{yr_pnl:>11,.1f} | ₹{yr_avg:>+11.1f} | {yr_r20:<12}")
print("=" * 80)

