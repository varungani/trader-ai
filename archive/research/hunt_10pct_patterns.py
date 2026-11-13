"""
TraderAI - Deep Micro-Pattern Mining Engine for +10% Monthly Alpha & Zero Drawdown Defense
========================================================================================
Goal:
1. Protect Downside: Worst Month >= 0% or strictly bounded (via Ultra-Strict Nifty Trend Guard)
2. Maximize Yield: Achieve highest possible monthly return via Fast-Velocity Micro-Swing
"""
import os, sys, math, pickle
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backtesting.swing_midcap_backtest import load_cached_universe
from data.costs import compute_indian_delivery_costs

if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

univ, bm = load_cached_universe()
nifty_df = bm['^NSEI']

def enrich_micro_features(df: pd.DataFrame, nifty: pd.DataFrame) -> pd.DataFrame:
    res = df.copy()
    c, h, l, v, o = res["Close"], res["High"], res["Low"], res["Volume"], res["Open"]
    
    res["ema10"] = c.ewm(span=10, adjust=False).mean()
    res["ema20"] = c.ewm(span=20, adjust=False).mean()
    res["sma50"] = c.rolling(50).mean()
    res["sma200"] = c.rolling(200).mean()
    
    tr1 = h - l
    tr2 = (h - c.shift(1)).abs()
    tr3 = (l - c.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    res["atr14"] = tr.rolling(14).mean()
    
    # Micro 1: Strong Close Ratio (Close location in bar range: 1.0 = at High, 0.0 = at Low)
    daily_range = h - l
    res["close_loc"] = (c - l) / daily_range.replace(0, np.nan)
    
    # Micro 2: Coiling Pre-Breakout Range (NR4 / Narrow Range Bar)
    res["prev_range_ratio"] = daily_range.shift(1) / daily_range.rolling(5).mean().shift(1).replace(0, np.nan)
    
    # Micro 3: Distance to 20 EMA
    res["dist_ema20_pct"] = ((c - res["ema20"]) / res["ema20"]) * 100.0
    
    # Volume Features
    res["vol_sma20"] = v.rolling(20).mean()
    res["rvol"] = v / res["vol_sma20"].replace(0, np.nan)
    res["high20"] = h.rolling(20).max().shift(1)
    
    # VCP ratio
    range_5d = h.rolling(5).max() - l.rolling(5).min()
    range_20d = h.rolling(20).max() - l.rolling(20).min()
    res["vcp_ratio"] = range_5d / range_20d.replace(0, np.nan)
    
    # Relative Strength Alpha vs Nifty 50 over 3 and 10 days
    nifty_c = nifty["Close"].reindex(res.index, method="ffill")
    res["rs_alpha_3d"] = (c.pct_change(3) - nifty_c.pct_change(3)) * 100.0
    res["rs_alpha_10d"] = (c.pct_change(10) - nifty_c.pct_change(10)) * 100.0
    
    res["adtv_cr"] = (c * v).rolling(20).mean() / 1e7
    return res

print("Enriching universe with micro-patterns...")
indicators = {sym: enrich_micro_features(df, nifty_df) for sym, df in univ.items()}
all_dates = nifty_df.index

# Precalculate Nifty 20 EMA and 50 SMA
nifty_c = nifty_df["Close"]
nifty_ema20 = nifty_c.ewm(span=20, adjust=False).mean()
nifty_sma50 = nifty_c.rolling(50).mean()
nifty_ret_5d = nifty_c.pct_change(5) * 100.0

def simulate_micro_swing(
    name: str,
    target_pct: float = 10.0,
    stop_pct: float = 3.5,
    max_hold_days: int = 7,
    fast_breakeven_pct: float = 4.0,
    require_strong_close: bool = True,
    require_coiling: bool = True,
    require_rs_alpha: bool = True,
    nifty_strict_mode: bool = True,
    compound: bool = True
):
    init_capital = 30000.0
    cash = init_capital
    open_positions = {}
    trades = []
    daily_equity = []
    
    for i in range(200, len(all_dates)):
        date_idx = all_dates[i]
        date_str = str(date_idx.date())
        year_month = date_str[:7]
        
        # 1. Manage Exits
        to_close = []
        for sym, pos in open_positions.items():
            ind = indicators[sym]
            if date_idx not in ind.index:
                pos['days_held'] += 1
                continue
            bar = ind.loc[date_idx]
            pos['days_held'] += 1
            pos['peak_price'] = max(pos['peak_price'], float(bar['High']))
            
            low_px = float(bar['Low'])
            high_px = float(bar['High'])
            open_px = float(bar['Open'])
            close_px = float(bar['Close'])
            
            exit_reason = None
            exit_px = 0.0
            
            # Fast breakeven ratchet: if reaches fast_breakeven_pct, stop moves to entry + 1%
            current_stop = pos['stop_loss']
            if pos['peak_price'] >= pos['entry_price'] * (1.0 + (fast_breakeven_pct / 100.0)):
                current_stop = max(current_stop, pos['entry_price'] * 1.01)
                
            if low_px <= current_stop:
                exit_reason = 'STOP_LOSS'
                exit_px = min(current_stop, open_px)
            elif high_px >= pos['target']:
                exit_reason = 'TARGET_HIT'
                exit_px = pos['target']
            elif pos['days_held'] >= max_hold_days:
                exit_reason = f'TIME_EXPIRY_{max_hold_days}D'
                exit_px = close_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(
                    buy_price=pos['entry_price'], sell_price=exit_px,
                    quantity=pos['qty'], apply_stcg=False
                )
                cash += (exit_px * pos['qty']) - costs.total_friction_rupees
                trades.append({
                    'ticker': sym, 'month': year_month, 'entry_price': pos['entry_price'],
                    'exit_price': exit_px, 'days_held': pos['days_held'],
                    'net_pnl': costs.net_pnl_rupees, 'return_pct': costs.net_pnl_pct,
                    'reason': exit_reason
                })
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        # Daily Mark-to-Market
        holdings_val = sum(float(indicators[s].loc[date_idx]['Close']) * p['qty'] 
                           for s, p in open_positions.items() if date_idx in indicators[s].index)
        curr_equity = cash + holdings_val
        daily_equity.append({
            'date': date_idx, 'year_month': year_month,
            'portfolio_val': curr_equity, 'cash': cash
        })
        
        # 2. Strict Nifty Regime Guard
        # If Nifty is weak, DO NOT TRADE. Sit 100% in cash!
        n_close = float(nifty_c.loc[date_idx])
        n_ema20 = float(nifty_ema20.loc[date_idx])
        n_sma50 = float(nifty_sma50.loc[date_idx])
        n_ret5 = float(nifty_ret_5d.loc[date_idx])
        
        if nifty_strict_mode:
            # Must be above 20 EMA, above 50 SMA, and 5-day return >= -0.5%
            regime_bullish = (n_close >= n_ema20 and n_close >= n_sma50 and n_ret5 >= -0.5)
        else:
            regime_bullish = (n_close >= n_sma50)
            
        # 3. Entries
        if len(open_positions) < 3 and regime_bullish:
            available = [s for s in univ.keys() if s not in open_positions]
            candidates = []
            for sym in available:
                ind = indicators[sym]
                if date_idx not in ind.index: continue
                loc = ind.index.get_loc(date_idx)
                if loc < 50: continue
                bar = ind.iloc[loc]
                
                c = float(bar['Close'])
                l = float(bar['Low'])
                o = float(bar['Open'])
                h20 = float(bar['high20'])
                ema20 = float(bar['ema20'])
                sma50 = float(bar['sma50'])
                sma200 = float(bar['sma200'])
                vcp = float(bar['vcp_ratio'])
                rvol = float(bar['rvol'])
                dist = float(bar['dist_ema20_pct'])
                close_loc = float(bar['close_loc'])
                prev_coil = float(bar['prev_range_ratio'])
                rs_alpha_3 = float(bar['rs_alpha_3d'])
                adtv = float(bar['adtv_cr'])
                
                if adtv < 5.0 or c < 15.0: continue
                if c <= ema20 or ema20 <= sma50 or sma50 <= sma200: continue # Stage 2 mandatory
                
                # Check Micro-Patterns
                # Micro 1: Strong close (buyers held control till the bell, close_loc >= 0.70)
                if require_strong_close and close_loc < 0.70: continue
                
                # Micro 2: Coiling contraction before breakout (prev day range narrow <= 0.85)
                if require_coiling and prev_coil > 0.85: continue
                
                # Micro 3: Relative Alpha Decoupling (outperformed Nifty by >= +1.5% in last 3 days)
                if require_rs_alpha and rs_alpha_3 < 1.5: continue
                
                # Setup Criteria: Either clean tight VCP breakout OR Sweet-spot 20 EMA bounce
                is_vcp = (c >= h20 and vcp <= 0.65 and rvol >= 1.35 and 0.0 <= dist <= 3.5)
                is_sweet_spot = (0.0 <= dist <= 2.2 and c > o and rvol >= 1.0)
                
                if is_vcp or is_sweet_spot:
                    score = (rvol * 2.0) + close_loc + (rs_alpha_3 * 0.1)
                    candidates.append((sym, score, c, bar))
                    
            candidates.sort(key=lambda x: x[1], reverse=True)
            slots_free = 3 - len(open_positions)
            
            for sym, score, close_px, bar in candidates[:slots_free]:
                total_equity = curr_equity if compound else init_capital
                pos_alloc = min(cash, total_equity / 3.0)
                qty = int(pos_alloc // close_px)
                if qty > 0 and cash >= (qty * close_px):
                    cash -= (qty * close_px)
                    
                    stop_px = round(close_px * (1.0 - (stop_pct / 100.0)), 2)
                    tp_px = round(close_px * (1.0 + (target_pct / 100.0)), 2)
                    
                    open_positions[sym] = {
                        'entry_price': close_px, 'qty': qty, 'stop_loss': stop_px,
                        'target': tp_px, 'peak_price': close_px, 'days_held': 0,
                        'entry_date': date_str
                    }
                    
    df_daily = pd.DataFrame(daily_equity)
    df_trades = pd.DataFrame(trades)
    
    monthly_snapshots = df_daily.groupby('year_month').last()
    monthly_snapshots['prev_val'] = monthly_snapshots['portfolio_val'].shift(1).fillna(init_capital)
    monthly_snapshots['monthly_net_pnl'] = monthly_snapshots['portfolio_val'] - monthly_snapshots['prev_val']
    monthly_snapshots['monthly_return_pct'] = (monthly_snapshots['monthly_net_pnl'] / monthly_snapshots['prev_val']) * 100.0
    
    m_pnl = monthly_snapshots['monthly_net_pnl']
    m_ret = monthly_snapshots['monthly_return_pct']
    
    final_eq = df_daily['portfolio_val'].iloc[-1]
    net_profit = final_eq - init_capital
    wr = (df_trades['net_pnl'] > 0).mean() * 100.0 if len(df_trades) else 0.0
    
    win_mos = (m_pnl > 0).sum()
    loss_mos = (m_pnl < 0).sum()
    flat_mos = (m_pnl == 0).sum()
    tot_mos = len(m_pnl)
    
    return {
        'name': name,
        'trades': len(df_trades),
        'trade_wr': round(wr, 1),
        'final_equity': round(final_eq, 1),
        'net_profit_rs': round(net_profit, 1),
        'avg_monthly_pct': round(m_ret.mean(), 2),
        'best_month_pct': round(m_ret.max(), 1),
        'worst_month_pct': round(m_ret.min(), 1),
        'best_month_rs': round(m_pnl.max(), 1),
        'worst_month_rs': round(m_pnl.min(), 1),
        'monthly_wr_pct': round(win_mos / tot_mos * 100.0, 1),
        'loss_months_count': loss_mos,
        'flat_months_count': flat_mos
    }

# Test grid of micro-pattern setups
configs = [
    ("Baseline (Nifty 50 SMA)", 12.0, 4.0, 15, 6.0, False, False, False, False, True),
    ("Strict Guard (Nifty 20EMA+Slope)", 12.0, 4.0, 15, 6.0, False, False, False, True, True),
    ("Micro: Strong Close Only (>=0.70)", 10.0, 3.5, 10, 4.0, True, False, False, True, True),
    ("Micro: Coiling (NR4) Only", 10.0, 3.5, 10, 4.0, False, True, False, True, True),
    ("Micro: RS Alpha Lead Only", 10.0, 3.5, 10, 4.0, False, False, True, True, True),
    ("Micro Velocity Combo (Close+Coil+RS)", 8.5, 3.0, 6, 3.5, True, True, True, True, True),
    ("Aggressive Velocity (7D hold, 10% target)", 10.0, 3.5, 7, 4.0, True, True, True, True, True),
]

res_list = []
print("\n" + "="*95)
print("RUNNING MICRO-PATTERN ABLATION FOR 10%+ MONTHLY ALPHA & WORST-MONTH DEFENSE")
print("="*95)

for cfg in configs:
    name, tp, sl, hold, be, sc, coil, rs, n_strict, comp = cfg
    r = simulate_micro_swing(name, tp, sl, hold, be, sc, coil, rs, n_strict, comp)
    res_list.append(r)
    print(f"Done: {name[:35]:35s} | Trades: {r['trades']:3d} | WR: {r['trade_wr']:4.1f}% | Avg Mo: {r['avg_monthly_pct']:+5.2f}% | Worst Mo: {r['worst_month_pct']:+5.1f}% (Rs {r['worst_month_rs']:+6.0f}) | Best Mo: {r['best_month_pct']:+5.1f}% (Rs {r['best_month_rs']:+6.0f}) | Losing Mos: {r['loss_months_count']:2d}")

df_grid = pd.DataFrame(res_list)
print("\n" + "="*110)
print("FINAL MICRO-PATTERN COMPARISON TABLE:")
print("="*110)
print(df_grid.to_string(index=False))
print("="*110)
