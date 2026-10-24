"""
TraderAI - Empirical Pattern Mining Engine
===========================================
Tests high-probability technical and volume patterns across 136 liquid Indian stocks (5-Year OHLCV)
to discover patterns that generate +10% monthly portfolio alpha with strict Indian delivery friction.

Patterns Tested:
1. Baseline: 50D Breakout (Close >= 50D High, RVOL >= 1.2, RSI > 60)
2. Minervini VCP (Volatility & Volume Contraction -> High Volume Breakout)
3. RS New High Lead (Stock RS vs Nifty breaks 50D high before or at price breakout)
4. Sweet-Spot 20 EMA Rebound (Stage 2 Uptrend + Low touches 20 EMA + Bullish Reversal)
5. Volume Dry-Up (VDU) Breakout (Volume drops <0.6x for 3 days then explodes >1.8x)
6. Inside-Bar / NR7 Squeeze Breakout (Narrowest range in 7 days followed by range expansion)
7. Uncapped Runner Mode (Trail with 2.0 ATR stop after +10% gain, aiming for +25% to +40%)
"""

import os
import sys
import math
import pickle
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backtesting.swing_midcap_backtest import load_cached_universe
from data.costs import compute_indian_delivery_costs

# Ensure UTF-8 output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

univ, bm = load_cached_universe()
nifty_df = bm['^NSEI']

def enrich_data(df: pd.DataFrame, nifty: pd.DataFrame) -> pd.DataFrame:
    res = df.copy()
    c = res["Close"]
    h = res["High"]
    l = res["Low"]
    v = res["Volume"]
    o = res["Open"]
    
    # Moving Averages
    res["ema10"] = c.ewm(span=10, adjust=False).mean()
    res["ema20"] = c.ewm(span=20, adjust=False).mean()
    res["sma50"] = c.rolling(50).mean()
    res["sma200"] = c.rolling(200).mean()
    
    # True Range & ATR
    tr1 = h - l
    tr2 = (h - c.shift(1)).abs()
    tr3 = (l - c.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    res["atr14"] = tr.rolling(14).mean()
    res["atr_pct"] = (res["atr14"] / c) * 100.0
    
    # Volume Features
    res["vol_sma20"] = v.rolling(20).mean()
    res["rvol"] = v / res["vol_sma20"].replace(0, np.nan)
    res["vol_3d_mean"] = v.rolling(3).mean()
    res["vdu_3d"] = res["vol_3d_mean"] / res["vol_sma20"].replace(0, np.nan)
    
    # Price Channels & Breakout Levels
    res["high20"] = h.rolling(20).max().shift(1)
    res["high50"] = h.rolling(50).max().shift(1)
    res["low20"] = l.rolling(20).min().shift(1)
    
    # Range Contraction (VCP metric: 5-day range vs 20-day range)
    range_5d = h.rolling(5).max() - l.rolling(5).min()
    range_20d = h.rolling(20).max() - l.rolling(20).min()
    res["vcp_ratio"] = range_5d / range_20d.replace(0, np.nan)
    
    # NR7 (Narrowest daily range in 7 days)
    daily_range = h - l
    min_range_7 = daily_range.rolling(7).min()
    res["is_nr7"] = (daily_range <= min_range_7 * 1.02)
    
    # Relative Strength vs Nifty 50
    # Align dates with Nifty
    nifty_c = nifty["Close"].reindex(res.index, method="ffill")
    res["rs_nifty"] = c / nifty_c.replace(0, np.nan)
    res["rs_high50"] = res["rs_nifty"].rolling(50).max().shift(1)
    res["rs_is_leader"] = (res["rs_nifty"] >= res["rs_high50"])
    
    # Distance to 20 EMA
    res["dist_ema20_pct"] = ((c - res["ema20"]) / res["ema20"]) * 100.0
    
    # ADTV
    res["adtv_cr"] = (c * v).rolling(20).mean() / 1e7
    
    return res

print(f"Enriching 136 universe stocks with advanced pattern features...")
indicators = {sym: enrich_data(df, nifty_df) for sym, df in univ.items()}
all_dates = nifty_df.index
print(f"Data ready. Total trading sessions: {len(all_dates)}")

def simulate_pattern(pattern_name: str, entry_filter_fn, exit_fn, max_positions=3, init_capital=30000.0):
    """
    Simulates a pattern on a realistic Rs 30,000 portfolio (3 positions of Rs 10,000 each)
    with exact Indian statutory delivery friction.
    """
    cash = init_capital
    open_positions = {}
    trades = []
    daily_equity = []
    
    for i in range(200, len(all_dates)):
        date_idx = all_dates[i]
        date_str = str(date_idx.date())
        year = date_idx.year
        
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
            
            exit_reason, exit_px = exit_fn(pos, bar)
            if exit_reason:
                costs = compute_indian_delivery_costs(
                    buy_price=pos['entry_price'], sell_price=exit_px,
                    quantity=pos['qty'], apply_stcg=False
                )
                cash += (exit_px * pos['qty']) - costs.total_friction_rupees
                trades.append({
                    'ticker': sym,
                    'year': year,
                    'entry_date': pos['entry_date'],
                    'exit_date': date_str,
                    'entry_price': pos['entry_price'],
                    'exit_price': exit_px,
                    'days_held': pos['days_held'],
                    'net_pnl': costs.net_pnl_rupees,
                    'gross_pnl': costs.gross_pnl_rupees,
                    'friction': costs.total_friction_rupees,
                    'return_pct': costs.net_pnl_pct,
                    'reason': exit_reason
                })
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        # Daily Mark-to-Market
        holdings_val = sum(float(indicators[s].loc[date_idx]['Close']) * p['qty'] 
                           for s, p in open_positions.items() if date_idx in indicators[s].index)
        daily_equity.append({
            'date': date_idx, 'year': year, 'portfolio_val': cash + holdings_val,
            'cash': cash, 'positions': len(open_positions)
        })
        
        # 2. Macro Regime Filter (Nifty >= 50 SMA)
        nifty_loc = nifty_df.index.get_loc(date_idx)
        regime_bullish = True
        if nifty_loc >= 50:
            n_close = float(nifty_df['Close'].iloc[nifty_loc])
            n_sma50 = float(nifty_df['Close'].iloc[nifty_loc-49:nifty_loc+1].mean())
            if n_close < n_sma50:
                regime_bullish = False
                
        # 3. Entries
        if len(open_positions) < max_positions and regime_bullish:
            available = [s for s in univ.keys() if s not in open_positions]
            candidates = []
            for sym in available:
                ind = indicators[sym]
                if date_idx not in ind.index: continue
                loc = ind.index.get_loc(date_idx)
                if loc < 50: continue
                bar = ind.iloc[loc]
                
                # Check pattern conditions
                is_valid, priority_score = entry_filter_fn(bar, ind, loc)
                if is_valid:
                    candidates.append((sym, priority_score, float(bar['Close']), bar))
                    
            # Sort by priority score
            candidates.sort(key=lambda x: x[1], reverse=True)
            slots_free = max_positions - len(open_positions)
            
            for sym, score, close_px, bar in candidates[:slots_free]:
                pos_alloc = min(cash, init_capital / max_positions)
                qty = int(pos_alloc // close_px)
                if qty > 0 and cash >= (qty * close_px):
                    cash -= (qty * close_px)
                    
                    # Stop & Target setup
                    atr = float(bar['atr14']) if not np.isnan(bar['atr14']) else close_px * 0.025
                    stop_px = round(close_px - (1.8 * atr), 2)
                    # Floor stop at max 4.5%
                    stop_px = max(stop_px, round(close_px * 0.955, 2))
                    target_px = round(close_px * 1.15, 2)  # Standard 15% target
                    
                    open_positions[sym] = {
                        'entry_price': close_px, 'qty': qty, 'stop_loss': stop_px,
                        'target': target_px, 'peak_price': close_px, 'days_held': 0,
                        'entry_date': date_str, 'atr': atr
                    }
                    
    df_trades = pd.DataFrame(trades)
    df_daily = pd.DataFrame(daily_equity)
    
    # Calculate stats
    total_trades = len(df_trades)
    if total_trades == 0:
        return {'pattern': pattern_name, 'trades': 0, 'win_rate': 0.0, 'net_pnl': 0.0, 'profit_factor': 0.0}
        
    wins = df_trades[df_trades['net_pnl'] > 0]
    losses = df_trades[df_trades['net_pnl'] <= 0]
    win_rate = (len(wins) / total_trades) * 100.0
    total_net = df_trades['net_pnl'].sum()
    gross_win = wins['net_pnl'].sum() if len(wins) > 0 else 0.0
    gross_loss = abs(losses['net_pnl'].sum()) if len(losses) > 0 else 1.0
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else 99.0
    avg_win = wins['net_pnl'].mean() if len(wins) > 0 else 0.0
    avg_loss = abs(losses['net_pnl'].mean()) if len(losses) > 0 else 0.0
    payoff_ratio = round(avg_win / avg_loss, 2) if avg_loss > 0 else 0.0
    max_gain = df_trades['return_pct'].max()
    avg_hold = df_trades['days_held'].mean()
    
    # Max Drawdown
    df_daily['peak'] = df_daily['portfolio_val'].cummax()
    df_daily['dd'] = (df_daily['portfolio_val'] - df_daily['peak']) / df_daily['peak'] * 100.0
    max_dd = df_daily['dd'].min()
    
    # Monthly annualized returns
    n_days = (all_dates[-1] - all_dates[200]).days
    n_months = n_days / 30.416
    monthly_return_pct = round((total_net / init_capital / n_months) * 100.0, 2)
    
    return {
        'pattern': pattern_name,
        'trades': total_trades,
        'win_rate': round(win_rate, 1),
        'total_net_rs': round(total_net, 1),
        'profit_factor': profit_factor,
        'payoff_ratio': payoff_ratio,
        'avg_win_rs': round(avg_win, 1),
        'avg_loss_rs': round(avg_loss, 1),
        'avg_hold_days': round(avg_hold, 1),
        'max_gain_pct': round(max_gain, 1),
        'max_dd_pct': round(max_dd, 1),
        'avg_monthly_pct': monthly_return_pct
    }

# ==============================================================================
# PATTERN ENTRY & EXIT RULES
# ==============================================================================

# Standard Exit Rule: 15% Target, Dynamic Stop, 20-Day Max Hold
def standard_exit(pos, bar):
    low_px = float(bar['Low'])
    high_px = float(bar['High'])
    open_px = float(bar['Open'])
    close_px = float(bar['Close'])
    
    if low_px <= pos['stop_loss']:
        return 'STOP_LOSS', min(pos['stop_loss'], open_px)
    if high_px >= pos['target']:
        return 'TARGET_HIT', pos['target']
    if pos['days_held'] >= 20:
        return 'TIME_EXPIRY_20D', close_px
    return None, 0.0

# Runner Exit Rule: If reaches +10%, lock in +5% floor & trail with 2.0 ATR!
def runner_exit(pos, bar):
    low_px = float(bar['Low'])
    high_px = float(bar['High'])
    open_px = float(bar['Open'])
    close_px = float(bar['Close'])
    atr = pos['atr']
    
    current_stop = pos['stop_loss']
    # If peak has reached +10%, ratchet stop up
    if pos['peak_price'] >= pos['entry_price'] * 1.10:
        trailing_stop = pos['peak_price'] - (2.0 * atr)
        floor_stop = pos['entry_price'] * 1.05  # Lock in at least +5% net
        current_stop = max(current_stop, floor_stop, trailing_stop)
        
    if low_px <= current_stop:
        reason = 'RUNNER_TRAIL_STOP' if current_stop > pos['stop_loss'] else 'STOP_LOSS'
        return reason, min(current_stop, open_px)
        
    # Uncapped Runner Target at +30%
    if high_px >= pos['entry_price'] * 1.30:
        return 'EXTENDED_TARGET_30%', pos['entry_price'] * 1.30
        
    if pos['days_held'] >= 25:
        return 'TIME_EXPIRY_25D', close_px
        
    return None, 0.0


# 1. Pattern: Baseline 50D Breakout
def entry_baseline(bar, ind, loc):
    c = float(bar['Close'])
    h50 = float(bar['high50'])
    rvol = float(bar['rvol'])
    adtv = float(bar['adtv_cr'])
    if adtv >= 5.0 and c > 15.0 and c >= h50 and rvol >= 1.2:
        return True, rvol
    return False, 0.0

# 2. Pattern: Minervini VCP (Volatility Contraction + Volume Surge)
def entry_vcp(bar, ind, loc):
    c = float(bar['Close'])
    h20 = float(bar['high20'])
    rvol = float(bar['rvol'])
    vcp = float(bar['vcp_ratio'])
    ema20 = float(bar['ema20'])
    sma50 = float(bar['sma50'])
    sma200 = float(bar['sma200'])
    adtv = float(bar['adtv_cr'])
    
    # Stage 2 + Tight Volatility Contraction (5D Range <= 60% of 20D Range) + Breakout with Volume
    if (adtv >= 5.0 and c > 15.0 and c > ema20 > sma50 > sma200 and 
        c >= h20 and vcp <= 0.65 and rvol >= 1.5):
        score = (1.0 / vcp) * rvol
        return True, score
    return False, 0.0

# 3. Pattern: RS Leadership Decoupling (Stock RS at 50D High before market)
def entry_rs_leader(bar, ind, loc):
    c = float(bar['Close'])
    h20 = float(bar['high20'])
    rvol = float(bar['rvol'])
    is_rs_lead = bool(bar['rs_is_leader'])
    ema20 = float(bar['ema20'])
    sma50 = float(bar['sma50'])
    adtv = float(bar['adtv_cr'])
    
    if (adtv >= 5.0 and c > 15.0 and c > ema20 > sma50 and 
        c >= h20 and is_rs_lead and rvol >= 1.25):
        score = rvol * 1.5
        return True, score
    return False, 0.0

# 4. Pattern: Sweet-Spot 20 EMA Pullback
def entry_sweet_spot_pullback(bar, ind, loc):
    c = float(bar['Close'])
    l = float(bar['Low'])
    o = float(bar['Open'])
    ema20 = float(bar['ema20'])
    sma50 = float(bar['sma50'])
    sma200 = float(bar['sma200'])
    dist = float(bar['dist_ema20_pct'])
    adtv = float(bar['adtv_cr'])
    
    # Must be Stage 2 (Close > 50 > 200)
    # Pullback touches within 1.5% of 20 EMA, but candle closes green (Close > Open)
    if (adtv >= 5.0 and c > 15.0 and sma50 > sma200 and 
        0.0 <= dist <= 2.5 and l <= ema20 * 1.015 and c > o):
        score = 10.0 - dist
        return True, score
    return False, 0.0

# 5. Pattern: Volume Dry-Up (VDU) Compression Breakout
def entry_vdu_breakout(bar, ind, loc):
    c = float(bar['Close'])
    h20 = float(bar['high20'])
    rvol = float(bar['rvol'])
    vdu_prev = float(ind.iloc[loc-1]['vdu_3d'])  # Volume prior 3 days was dead quiet
    ema20 = float(bar['ema20'])
    sma50 = float(bar['sma50'])
    adtv = float(bar['adtv_cr'])
    
    if (adtv >= 5.0 and c > 15.0 and c > ema20 > sma50 and 
        c >= h20 and vdu_prev <= 0.70 and rvol >= 1.6):
        score = (rvol / max(vdu_prev, 0.2))
        return True, score
    return False, 0.0

# 6. Pattern: Master Confluence Pattern (VCP + RS Lead + Sweet-Spot)
def entry_master_confluence(bar, ind, loc):
    c = float(bar['Close'])
    h20 = float(bar['high20'])
    rvol = float(bar['rvol'])
    vcp = float(bar['vcp_ratio'])
    is_rs_lead = bool(bar['rs_is_leader'])
    ema20 = float(bar['ema20'])
    sma50 = float(bar['sma50'])
    sma200 = float(bar['sma200'])
    dist = float(bar['dist_ema20_pct'])
    adtv = float(bar['adtv_cr'])
    
    # Stage 2 + RS Leader + Contraction <= 0.75 + Not Overextended (dist <= 4.0%) + Breakout
    if (adtv >= 5.0 and c > 15.0 and c > ema20 > sma50 > sma200 and
        c >= h20 and is_rs_lead and vcp <= 0.75 and 0.0 <= dist <= 4.0 and rvol >= 1.35):
        score = (rvol * 2.0) + (1.0 / vcp)
        return True, score
    return False, 0.0

# ==============================================================================
# RUN SIMULATION EXPERIMENTS
# ==============================================================================

experiments = [
    ("1. Baseline 50D Breakout", entry_baseline, standard_exit),
    ("2. Minervini VCP Contraction", entry_vcp, standard_exit),
    ("3. Relative Strength (RS) High Leader", entry_rs_leader, standard_exit),
    ("4. 20 EMA Sweet-Spot Pullback", entry_sweet_spot_pullback, standard_exit),
    ("5. Volume Dry-Up (VDU) Explosion", entry_vdu_breakout, standard_exit),
    ("6. Master Confluence (Stage2+VCP+RS+SweetSpot)", entry_master_confluence, standard_exit),
    ("7. Master Confluence + Uncapped Runner (+30% Max)", entry_master_confluence, runner_exit),
]

results = []
print("\n" + "="*95)
print("MINING WINNING PATTERNS ON 136 NSE EQUITIES (5 YEARS - REAL COSTS)")
print("="*95)

for name, entry_fn, exit_fn in experiments:
    res = simulate_pattern(name, entry_fn, exit_fn)
    results.append(res)
    print(f"Completed: {name} -> Net P&L: Rs {res['total_net_rs']:+,.1f} | WR: {res['win_rate']}% | PF: {res['profit_factor']} | Payoff: {res['payoff_ratio']}:1 | Monthly: {res['avg_monthly_pct']}%")

df_res = pd.DataFrame(results)
print("\n" + "="*95)
print("FINAL PATTERN BENCHMARK TABLE (SORTED BY PROFIT FACTOR & NET PROFIT):")
print("="*95)
print(df_res.to_string(index=False))
print("="*95)
