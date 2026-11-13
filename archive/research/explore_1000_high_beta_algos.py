"""
Ultra-Fast Vectorized 1,000 Pattern & Algorithm Exploration Engine
Focus: High-Beta Midcaps, Smallcaps, and High-Velocity Growth Rockets ONLY
(Zero slow-moving mega-cap elephants like Reliance or TCS).

Explores a 1,000-cell combinatorial matrix of:
- 10 Entry Pattern Archetypes
- 4 Stop-Loss Architectures
- 5 Exit / Runner Policies
- 5 Holding Windows / Time Limits
= Exactly 1,000 Quantitative Algorithms tested across 72 High-Beta Rockets (5-Year Historical Data).
"""
import pickle
import os
import itertools
import numpy as np
import pandas as pd
import time

t0 = time.time()

# Load the 72 high-beta datasets
CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cache", "high_beta_universe.pkl")
with open(CACHE_PATH, "rb") as f:
    universe = pickle.load(f)

print(f"Loaded {len(universe)} High-Beta Rocket datasets for 1,000-Algorithm Exploration.", flush=True)

# 10 Entry Archetypes
ENTRY_PATTERNS = [
    "P1_DONCHIAN_20D",          # Close >= 20-day high & RVOL >= 1.2
    "P2_FAST_10D",              # Close >= 10-day high & RVOL >= 1.3
    "P3_SLINGSHOT_5D",          # Close >= 5-day high & Pullback bounce from 10/20 EMA
    "P4_VCP_SQUEEZE",           # VCP <= 0.65 (volatility squeeze) + breakout 10d high
    "P5_52W_HIGH_BLUE_SKY",     # Close >= 98% of 250-day high (Blue Sky, 0 overhead supply)
    "P6_TURBO_RVOL_ACCUM",      # RVOL >= 2.0x institutional blast + Price > 20 EMA
    "P7_EMA_CROSS_SWEET_RSI",   # 10 EMA > 20 EMA & RSI between 60 and 72
    "P8_COILED_VCP_EXTREME",    # VCP <= 0.52 (super tight coil) & RVOL >= 1.4
    "P9_STAGE2_PULLBACK",       # Price > 50 SMA > 200 SMA & Low touches 20 EMA & Close > Open
    "P10_PARABOLIC_LEADER",     # Price > 10 EMA > 20 EMA > 50 SMA & RSI > 65 & RVOL >= 1.25
]

# 4 Stop-Loss Variants
STOP_LOSSES = [
    0.035,   # -3.5% (Scalp / tight)
    0.050,   # -5.0% (Standard swing baseline)
    0.070,   # -7.0% (Wide room for midcap volatility)
    "ATR",   # 1.5x ATR dynamic
]

# 5 Exit / Runner Policies
EXIT_POLICIES = [
    "FIXED_15PCT",          # Fixed +15% profit take
    "FIXED_25PCT",          # Fixed +25% profit take
    "TRAIL_10EMA",          # Close < 10 EMA
    "TRAIL_15EMA",          # Close < 15 EMA (wide runner)
    "HYBRID_SCALE_35",      # Sell 35% at +15%, move SL to Breakeven, trail 65% behind 10 EMA
]

# 5 Holding Windows
HOLD_WINDOWS = [
    5,                      # 5-day fast flip
    10,                     # 10-day sprint
    15,                     # 15-day swing standard
    20,                     # 20-day extended
    "RUNNER_30D",           # 15-day standard, but extend to 30 days if gain >= +5%
]

# Pre-calculate data & signals per ticker
ticker_data = {}
signals_by_pattern = {p: [] for p in ENTRY_PATTERNS}

for sym, df in universe.items():
    if len(df) < 60:
        continue
    c = df["close"].values
    h = df["high"].values
    l = df["low"].values
    o = df["open"].values
    v = df["volume"].values
    n = len(df)
    
    # Fast Pandas / Numpy indicators
    s_c = pd.Series(c)
    ema5 = s_c.ewm(span=5, adjust=False).mean().values
    ema10 = s_c.ewm(span=10, adjust=False).mean().values
    ema15 = s_c.ewm(span=15, adjust=False).mean().values
    ema20 = s_c.ewm(span=20, adjust=False).mean().values
    sma50 = s_c.rolling(50).mean().values
    sma200 = s_c.rolling(min(200, n)).mean().values
    
    s_h = pd.Series(h)
    h5 = s_h.rolling(5).max().shift(1).values
    h10 = s_h.rolling(10).max().shift(1).values
    h20 = s_h.rolling(20).max().shift(1).values
    h250 = s_h.rolling(min(250, n)).max().shift(1).values
    
    s_v = pd.Series(v)
    vol_sma20 = s_v.rolling(20).mean().values
    rvol = v / (vol_sma20 + 1e-8)
    
    # ATR & VCP
    tr1 = h - l
    tr2 = np.abs(h - np.roll(c, 1))
    tr3 = np.abs(l - np.roll(c, 1))
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    s_tr = pd.Series(tr)
    atr5 = s_tr.rolling(5).mean().values
    atr20 = s_tr.rolling(20).mean().values
    vcp = atr5 / (atr20 + 1e-8)
    
    # RSI 14
    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean().values
    avg_loss = loss.rolling(14).mean().values
    rs = avg_gain / (avg_loss + 1e-8)
    rsi14 = 100 - (100 / (1 + rs))
    
    ticker_data[sym] = {
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "ema10": ema10,
        "ema15": ema15,
        "ema20": ema20,
        "atr20": atr20,
        "n": n,
    }
    
    # Vectorized signals
    idx_range = np.arange(50, n - 1)
    
    s1 = (c[idx_range] >= h20[idx_range] * 0.995) & (rvol[idx_range] >= 1.20) & (c[idx_range] > ema20[idx_range])
    s2 = (c[idx_range] >= h10[idx_range] * 0.995) & (rvol[idx_range] >= 1.30) & (c[idx_range] > ema10[idx_range])
    s3 = (c[idx_range] >= h5[idx_range] * 0.995) & (l[idx_range] <= ema10[idx_range] * 1.01) & (c[idx_range] > o[idx_range]) & (rvol[idx_range] >= 1.15)
    s4 = (vcp[idx_range] <= 0.65) & (c[idx_range] >= h10[idx_range] * 0.992) & (rvol[idx_range] >= 1.25)
    s5 = (c[idx_range] >= h250[idx_range] * 0.980) & (rvol[idx_range] >= 1.20) & (c[idx_range] > ema20[idx_range])
    s6 = (rvol[idx_range] >= 2.00) & (c[idx_range] > o[idx_range]) & (c[idx_range] > ema20[idx_range])
    s7 = (ema10[idx_range] > ema20[idx_range]) & (rsi14[idx_range] >= 60.0) & (rsi14[idx_range] <= 72.0) & (c[idx_range] > ema10[idx_range])
    s8 = (vcp[idx_range] <= 0.52) & (rvol[idx_range] >= 1.40) & (c[idx_range] > ema20[idx_range])
    s9 = (c[idx_range] > sma50[idx_range]) & (sma50[idx_range] > sma200[idx_range]) & (l[idx_range] <= ema20[idx_range] * 1.01) & (c[idx_range] > ema20[idx_range]) & (c[idx_range] > o[idx_range])
    s10 = (c[idx_range] > ema10[idx_range]) & (ema10[idx_range] > ema20[idx_range]) & (ema20[idx_range] > sma50[idx_range]) & (rsi14[idx_range] >= 65.0) & (rvol[idx_range] >= 1.25)
    
    sigs = [s1, s2, s3, s4, s5, s6, s7, s8, s9, s10]
    for p_name, s_arr in zip(ENTRY_PATTERNS, sigs):
        true_indices = idx_range[s_arr]
        for tidx in true_indices:
            # We record (symbol, signal_bar, next_bar_entry_open, atr20)
            signals_by_pattern[p_name].append((sym, tidx, o[tidx + 1], atr20[tidx]))

print(f"Signal extraction finished in {time.time()-t0:.2f}s. Pre-filtering Non-Overlapping Trades...", flush=True)

# Function to simulate a single configuration across pre-detected signals
def evaluate_strategy(entry_p, sl_var, exit_p, hold_w):
    raw_signals = signals_by_pattern[entry_p]
    if len(raw_signals) < 15:
        return None
        
    trades = []
    # To prevent look-ahead and overlapping bias on the same ticker:
    last_exit_by_sym = {}
    
    for sym, sig_idx, entry_px, atr_val in raw_signals:
        entry_idx = sig_idx + 1
        if sym in last_exit_by_sym and entry_idx <= last_exit_by_sym[sym]:
            continue  # Already in position on this stock
            
        d = ticker_data[sym]
        n = d["n"]
        
        # Stop loss
        if sl_var == "ATR":
            stop_px = entry_px - (1.5 * atr_val)
        else:
            stop_px = entry_px * (1.0 - float(sl_var))
            
        max_bars = 15 if hold_w == "RUNNER_30D" else int(hold_w)
        scaled_out = False
        scale_pnl = 0.0
        
        exit_bar = min(n - 1, entry_idx + max_bars)
        exit_px = d["close"][exit_bar]
        exit_reason = "TIME_EXPIRY"
        
        for bar in range(entry_idx, min(n, entry_idx + max_bars + 1)):
            held = bar - entry_idx
            cur_c = d["close"][bar]
            cur_l = d["low"][bar]
            cur_h = d["high"][bar]
            
            # Runner 30D extension
            if hold_w == "RUNNER_30D" and held == 15:
                if (cur_c - entry_px) / entry_px >= 0.05:
                    max_bars = 30
                    
            # Hybrid scale
            if exit_p == "HYBRID_SCALE_35" and not scaled_out:
                if cur_h >= entry_px * 1.15:
                    scaled_out = True
                    scale_pnl = 0.35 * 0.15
                    stop_px = max(stop_px, entry_px * 1.002)
                    
            if cur_l <= stop_px:
                exit_bar = bar
                exit_px = stop_px
                exit_reason = "STOP_LOSS"
                break
            elif exit_p == "FIXED_15PCT" and cur_h >= entry_px * 1.15:
                exit_bar = bar
                exit_px = entry_px * 1.15
                exit_reason = "TARGET_15"
                break
            elif exit_p == "FIXED_25PCT" and cur_h >= entry_px * 1.25:
                exit_bar = bar
                exit_px = entry_px * 1.25
                exit_reason = "TARGET_25"
                break
            elif exit_p in ("TRAIL_10EMA", "HYBRID_SCALE_35") and held >= 3:
                if cur_c < d["ema10"][bar]:
                    exit_bar = bar
                    exit_px = cur_c
                    exit_reason = "10EMA_TRAIL"
                    break
            elif exit_p == "TRAIL_15EMA" and held >= 3:
                if cur_c < d["ema15"][bar]:
                    exit_bar = bar
                    exit_px = cur_c
                    exit_reason = "15EMA_TRAIL"
                    break
            elif held >= max_bars:
                exit_bar = bar
                exit_px = cur_c
                exit_reason = "TIME_EXPIRY"
                break
                
        last_exit_by_sym[sym] = exit_bar
        
        raw_ret = (exit_px - entry_px) / entry_px
        final_pnl = (scale_pnl + 0.65 * raw_ret) if scaled_out else raw_ret
        net_pnl = final_pnl - 0.0025  # Statutory friction
        trades.append(net_pnl)
        
    if len(trades) < 20:
        return None
        
    pnls = np.array(trades)
    tot = len(pnls)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    win_rate = len(wins) / tot * 100.0
    gw = np.sum(wins) if len(wins) else 0.0
    gl = np.abs(np.sum(losses)) if len(losses) else 0.0
    pf = (gw / (gl + 1e-8)) if gl > 0 else (gw if gw > 0 else 1.0)
    avg_pnl = np.mean(pnls) * 100.0
    best_t = np.max(pnls) * 100.0
    
    # Portfolio Compounding Simulation (Starting ₹100,000, 3 slots)
    cap = 100000.0
    peak = cap
    max_dd = 0.0
    for p in pnls:
        cap += (cap * 0.333) * p
        if cap > peak:
            peak = cap
        dd = (peak - cap) / peak * 100.0
        if dd > max_dd:
            max_dd = dd
            
    net_ret = ((cap - 100000.0) / 100000.0) * 100.0
    
    avg_w = np.mean(wins) if len(wins) else 0.0
    avg_l = np.abs(np.mean(losses)) if len(losses) else 0.0
    expectancy = (win_rate / 100.0 * avg_w) - ((100.0 - win_rate) / 100.0 * avg_l)
    
    # Composite Score
    score = (pf * (1.0 + max(0.0, net_ret) / 100.0)) / (max_dd + 10.0) * 10.0
    
    return {
        "entry_pattern": entry_p,
        "stop_loss": sl_var,
        "exit_policy": exit_p,
        "hold_window": str(hold_w),
        "total_trades": tot,
        "win_rate": round(win_rate, 1),
        "profit_factor": round(pf, 2),
        "avg_trade_pct": round(avg_pnl, 2),
        "net_return_pct": round(net_ret, 1),
        "final_capital": round(cap, 0),
        "max_drawdown": round(max_dd, 1),
        "expectancy_pct": round(expectancy * 100.0, 2),
        "best_trade_pct": round(best_t, 1),
        "score": round(score, 2),
    }

print("Running 1,000 Quantitative Combinations across High-Beta Rockets...", flush=True)

algo_results = []
counter = 0

for entry_p, sl_var, exit_p, hold_w in itertools.product(ENTRY_PATTERNS, STOP_LOSSES, EXIT_POLICIES, HOLD_WINDOWS):
    counter += 1
    res = evaluate_strategy(entry_p, sl_var, exit_p, hold_w)
    if res:
        res["algo_id"] = f"ALGO_{counter:04d}"
        algo_results.append(res)

df_algos = pd.DataFrame(algo_results)
df_algos = df_algos.sort_values(by="score", ascending=False)

print(f"\nSuccessfully simulated and audited {len(df_algos)} quantitative algorithms in {time.time()-t0:.2f} seconds!", flush=True)

print("\n" + "="*85)
print("🏆 TOP 15 BEST PERFORMING QUANT ALGORITHMS ACROSS HIGH-BETA ROCKETS (5-YEAR CENSUS):")
print("="*85)
for idx, r in df_algos.head(15).reset_index().iterrows():
    print(f"#{idx+1:02d} [{r['algo_id']}] Score: {r['score']} | {r['entry_pattern']} | SL: {r['stop_loss']} | {r['exit_policy']} | Hold: {r['hold_window']}")
    print(f"    Net Return: +{r['net_return_pct']}% (₹100k -> ₹{r['final_capital']:,.0f}) | PF: {r['profit_factor']} | WinRate: {r['win_rate']}% | MaxDD: -{r['max_drawdown']}% | Best: +{r['best_trade_pct']}% | Trades: {r['total_trades']}")

# Breakdown by Entry Archetype Average Performance
print("\n" + "="*85)
print("📊 PERFORMANCE BREAKDOWN BY ENTRY PATTERN ARCHETYPE (ACROSS ALL COMBINATIONS):")
print("="*85)
archetype_stats = df_algos.groupby("entry_pattern").agg({
    "profit_factor": "mean",
    "win_rate": "mean",
    "net_return_pct": "mean",
    "max_drawdown": "mean",
    "total_trades": "mean",
    "score": "mean"
}).sort_values(by="score", ascending=False)
print(archetype_stats.round(2).to_string())

# Breakdown by Exit Policy Average Performance
print("\n" + "="*85)
print("📊 PERFORMANCE BREAKDOWN BY EXIT & RUNNER POLICY (ACROSS ALL COMBINATIONS):")
print("="*85)
exit_stats = df_algos.groupby("exit_policy").agg({
    "profit_factor": "mean",
    "win_rate": "mean",
    "net_return_pct": "mean",
    "max_drawdown": "mean",
    "score": "mean"
}).sort_values(by="score", ascending=False)
print(exit_stats.round(2).to_string())

# Breakdown by Stop Loss Average Performance
print("\n" + "="*85)
print("📊 PERFORMANCE BREAKDOWN BY STOP-LOSS PROTECTION (ACROSS ALL COMBINATIONS):")
print("="*85)
sl_stats = df_algos.groupby("stop_loss").agg({
    "profit_factor": "mean",
    "win_rate": "mean",
    "net_return_pct": "mean",
    "max_drawdown": "mean",
    "score": "mean"
}).sort_values(by="score", ascending=False)
print(sl_stats.round(2).to_string())

# Breakdown by Holding Window Average Performance
print("\n" + "="*85)
print("📊 PERFORMANCE BREAKDOWN BY HOLDING WINDOW & RUNNER EXTENSION:")
print("="*85)
hold_stats = df_algos.groupby("hold_window").agg({
    "profit_factor": "mean",
    "win_rate": "mean",
    "net_return_pct": "mean",
    "max_drawdown": "mean",
    "score": "mean"
}).sort_values(by="score", ascending=False)
print(hold_stats.round(2).to_string())

CSV_OUT = os.path.join(os.path.dirname(__file__), "..", "data", "cache", "1000_high_beta_algos_leaderboard.csv")
df_algos.to_csv(CSV_OUT, index=False)
print(f"\nSaved all {len(df_algos)} algorithms to {CSV_OUT}!", flush=True)
