"""
TraderAI - The Apex High-Volume Sniper & VCP Breakthrough
========================================================
Combines:
1. Institutional Volume Shock (RVOL >= 2.0x)
2. Pre-Breakout Tight Base (VCP <= 0.65 or 4-day Close Tightness <= 2.5%)
3. Two-Tier Exit: Tranche 1 locks 50% at +14%, Tranche 2 trails 20 EMA (giving runners room to reach 50%+)
4. Dynamic Re-investing / Compounding
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

u_path = "data/cache/universe_5y.pkl"
b_path = "data/cache/benchmarks_5y.pkl"

with open(u_path, "rb") as f:
    universe = pickle.load(f)

with open(b_path, "rb") as f:
    benchmarks = pickle.load(f)

nifty_df = benchmarks["^NSEI"]
all_dates = nifty_df.index

def enrich_features(df: pd.DataFrame, nifty: pd.DataFrame) -> pd.DataFrame:
    res = df.copy()
    c, h, l, v = res["Close"], res["High"], res["Low"], res["Volume"]
    o = res["Open"] if "Open" in res.columns else c

    res["ema10"] = c.ewm(span=10, adjust=False).mean()
    res["ema20"] = c.ewm(span=20, adjust=False).mean()
    res["sma50"] = c.rolling(50).mean()
    res["sma200"] = c.rolling(min(200, len(c))).mean()

    # Relative Volume
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

    # 5-day Relative Strength vs NIFTY 50
    n_c = nifty["Close"].reindex(res.index, method="ffill")
    res["rs_5d"] = (c.pct_change(5) - n_c.pct_change(5)) * 100.0

    # Volatility Contraction Pattern (VCP)
    range_5d = h.rolling(5).max() - l.rolling(5).min()
    range_20d = h.rolling(20).max() - l.rolling(20).min()
    res["vcp_ratio"] = range_5d / range_20d.replace(0, np.nan)

    # 4-Day Close Tightness (%)
    close_max_4d = c.rolling(4).max()
    close_min_4d = c.rolling(4).min()
    res["tightness_4d"] = ((close_max_4d - close_min_4d) / c) * 100.0

    return res

indicators = {sym: enrich_features(df, nifty_df) for sym, df in universe.items() if len(df) >= 200}

def test_apex_engine(trail_choice="EMA20", compound=False):
    init_cap = 100000.0
    cash = init_cap
    open_positions = {}
    pending_buys = []
    trades = []
    daily_equity = []
    max_positions = 5
    SLIPPAGE = 0.002
    MIN_TICKET = 4000.0

    for i in range(250, len(all_dates)):
        date_idx = all_dates[i]
        date_str = str(date_idx.date())

        # 1. Open Fills
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
                    stop_px = round(fill_px * 0.955, 2)   # 4.5% planned stop
                    target_px = round(fill_px * 1.14, 2)  # 14.0% T1 target
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

        # 2. Exits
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

            if pos["partial_booked"]:
                ema_val = float(bar["ema20"] if trail_choice == "EMA20" else bar["ema10"])
                if not math.isnan(ema_val) and ema_val > current_stop:
                    current_stop = max(current_stop, round(ema_val, 2))
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
            elif pos["days_held"] >= 45:
                exit_reason = "TIME_EXPIRY (45d)"
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
                })
                to_close.append(sym)

        for sym in to_close:
            del open_positions[sym]

        # Total equity calculation
        holdings_val = sum(pos["qty"] * float(indicators[s].loc[date_idx]["Close"]) for s, pos in open_positions.items() if date_idx in indicators[s].index)
        tot_equity = cash + holdings_val

        # 3. Entries at EOD
        empty_slots = max_positions - (len(open_positions) + len(pending_buys))
        if empty_slots > 0:
            candidates = []
            for sym, ind in indicators.items():
                if sym in open_positions or any(sym == p[0] for p in pending_buys):
                    continue
                if date_idx not in ind.index:
                    continue
                bar = ind.loc[date_idx]

                if bar["adtv_cr"] < 5.0 or bar["Close"] < 15.0:
                    continue
                if bar["Close"] <= bar["sma50"]:
                    continue
                if bar["pct_from_52w"] < -10.0:
                    continue
                if bar["rvol"] < 1.7:
                    continue
                if bar["close_loc"] < 0.75 or not bar["is_bullish_bar"]:
                    continue
                if bar["rs_5d"] < 2.0:
                    continue
                # Tight base pre-condition (VCP contraction OR close tightness)
                if bar["vcp_ratio"] > 0.70 and bar["tightness_4d"] > 3.0:
                    continue

                score = float(bar["rvol"] * 20.0 + bar["rs_5d"] * 5.0)
                candidates.append((sym, score, float(bar["Close"])))

            candidates.sort(key=lambda x: x[1], reverse=True)
            for c in candidates[:empty_slots]:
                base_capital = tot_equity if compound else init_cap
                alloc = min(cash / max(1, empty_slots), base_capital * 0.20)
                pending_buys.append((c[0], alloc))

    return pd.DataFrame(trades), cash

print("Evaluating Non-Compounded vs Compounded Apex Super-Mover Engine...")
df_static, final_cash_static = test_apex_engine(trail_choice="EMA20", compound=False)
df_comp, final_cash_comp = test_apex_engine(trail_choice="EMA20", compound=True)

print("\n" + "=" * 90)
print("🚀 APEX SUPER-MOVER EXPERIMENT: STATIC ALLOCATION VS COMPOUNDED WEALTH")
print("=" * 90)

for label, df, final_c in [("Static Allocation (Fixed ₹20k/slot)", df_static, final_cash_static),
                           ("Compounded Growth (Reinvesting Profits)", df_comp, final_cash_comp)]:
    tot_pnl = df["net_pnl"].sum()
    wr = (df["net_pnl"] > 0).mean() * 100.0
    wins = df[df["net_pnl"] > 0]["net_pnl"]
    losses = df[df["net_pnl"] <= 0]["net_pnl"].abs()
    pf = (wins.sum() / losses.sum()) if losses.sum() > 0 else 99.0
    payoff = (wins.mean() / losses.mean()) if len(losses) and len(wins) else 0.0
    r20 = (df["peak_gain_pct"] >= 20.0).sum()
    max_peak = df["peak_gain_pct"].max()
    print(f"\n{label}:")
    print(f"  • Total Trades         : {len(df)}")
    print(f"  • Win Rate             : {wr:.1f}%")
    print(f"  • Profit Factor        : {pf:.2f}")
    print(f"  • Payoff Ratio         : {payoff:.2f} : 1")
    print(f"  • Total Net P&L (₹)    : ₹{tot_pnl:+,.1f} (after ₹{df['friction'].sum():,.0f} friction)")
    print(f"  • Final Account Cash   : ₹{final_c:,.1f}")
    print(f"  • 20%+ Monster Runners : {r20} trades")
    print(f"  • Maximum Single Move  : +{max_peak:.1f}%")

print("\n" + "=" * 90)

