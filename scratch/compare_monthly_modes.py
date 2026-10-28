"""
TraderAI - Compare Monthly Distribution of VCP vs 20 EMA Sweet Spot
"""
import os, sys, pickle, numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backtesting.swing_midcap_backtest import load_cached_universe
from data.costs import compute_indian_delivery_costs

if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

univ, bm = load_cached_universe()
nifty_df = bm['^NSEI']

def enrich_data(df: pd.DataFrame, nifty: pd.DataFrame) -> pd.DataFrame:
    res = df.copy()
    c, h, l, v, o = res["Close"], res["High"], res["Low"], res["Volume"], res["Open"]
    res["ema20"] = c.ewm(span=20, adjust=False).mean()
    res["sma50"] = c.rolling(50).mean()
    res["sma200"] = c.rolling(200).mean()
    
    tr1 = h - l
    tr2 = (h - c.shift(1)).abs()
    tr3 = (l - c.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    res["atr14"] = tr.rolling(14).mean()
    
    res["vol_sma20"] = v.rolling(20).mean()
    res["rvol"] = v / res["vol_sma20"].replace(0, np.nan)
    res["high20"] = h.rolling(20).max().shift(1)
    
    range_5d = h.rolling(5).max() - l.rolling(5).min()
    range_20d = h.rolling(20).max() - l.rolling(20).min()
    res["vcp_ratio"] = range_5d / range_20d.replace(0, np.nan)
    
    res["dist_ema20_pct"] = ((c - res["ema20"]) / res["ema20"]) * 100.0
    res["adtv_cr"] = (c * v).rolling(20).mean() / 1e7
    return res

indicators = {sym: enrich_data(df, nifty_df) for sym, df in univ.items()}
all_dates = nifty_df.index

def run_pattern_monthly(pattern_mode="VCP"):
    init_capital = 30000.0
    cash = init_capital
    open_positions = {}
    daily_equity = []
    
    for i in range(200, len(all_dates)):
        date_idx = all_dates[i]
        date_str = str(date_idx.date())
        year_month = date_str[:7]
        
        # Exits
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
            
            if low_px <= pos['stop_loss']:
                exit_reason = 'STOP_LOSS'
                exit_px = min(pos['stop_loss'], open_px)
            elif high_px >= pos['target']:
                exit_reason = 'TARGET_HIT'
                exit_px = pos['target']
            elif pos['days_held'] >= 20:
                exit_reason = 'TIME_EXPIRY_20D'
                exit_px = close_px
                
            if exit_reason:
                costs = compute_indian_delivery_costs(
                    buy_price=pos['entry_price'], sell_price=exit_px,
                    quantity=pos['qty'], apply_stcg=False
                )
                cash += (exit_px * pos['qty']) - costs.total_friction_rupees
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        holdings_val = sum(float(indicators[s].loc[date_idx]['Close']) * p['qty'] 
                           for s, p in open_positions.items() if date_idx in indicators[s].index)
        daily_equity.append({
            'date': date_idx, 'year_month': year_month,
            'portfolio_val': cash + holdings_val
        })
        
        # Macro Regime (Nifty >= 50 SMA)
        nifty_loc = nifty_df.index.get_loc(date_idx)
        regime_bullish = True
        if nifty_loc >= 50:
            n_close = float(nifty_df['Close'].iloc[nifty_loc])
            n_sma50 = float(nifty_df['Close'].iloc[nifty_loc-49:nifty_loc+1].mean())
            if n_close < n_sma50:
                regime_bullish = False
                
        # Entries
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
                adtv = float(bar['adtv_cr'])
                
                if adtv < 5.0 or c < 15.0: continue
                
                if pattern_mode == "VCP":
                    # Minervini VCP Breakout
                    if c > ema20 > sma50 > sma200 and c >= h20 and vcp <= 0.65 and rvol >= 1.5:
                        score = (1.0 / vcp) * rvol
                        candidates.append((sym, score, c, bar))
                elif pattern_mode == "SWEET_SPOT":
                    # 20 EMA Sweet Spot Rebound
                    if c > sma50 > sma200 and 0.0 <= dist <= 2.5 and l <= ema20 * 1.015 and c > o:
                        score = 10.0 - dist
                        candidates.append((sym, score, c, bar))
                        
            candidates.sort(key=lambda x: x[1], reverse=True)
            slots_free = 3 - len(open_positions)
            
            for sym, score, close_px, bar in candidates[:slots_free]:
                pos_alloc = min(cash, 10000.0)
                qty = int(pos_alloc // close_px)
                if qty > 0 and cash >= (qty * close_px):
                    cash -= (qty * close_px)
                    atr = float(bar['atr14']) if not np.isnan(bar['atr14']) else close_px * 0.025
                    stop_px = round(max(close_px - (1.8 * atr), close_px * 0.955), 2)
                    tp_px = round(close_px * 1.15, 2)
                    open_positions[sym] = {
                        'entry_price': close_px, 'qty': qty, 'stop_loss': stop_px,
                        'target': tp_px, 'peak_price': close_px, 'days_held': 0,
                        'entry_date': date_str, 'atr': atr
                    }
                    
    df_daily = pd.DataFrame(daily_equity)
    monthly_snapshots = df_daily.groupby('year_month').last()
    monthly_snapshots['prev_val'] = monthly_snapshots['portfolio_val'].shift(1).fillna(init_capital)
    monthly_snapshots['monthly_net_pnl'] = monthly_snapshots['portfolio_val'] - monthly_snapshots['prev_val']
    monthly_snapshots['monthly_return_pct'] = (monthly_snapshots['monthly_net_pnl'] / monthly_snapshots['prev_val']) * 100.0
    
    m_pnl = monthly_snapshots['monthly_net_pnl']
    m_ret = monthly_snapshots['monthly_return_pct']
    
    total_net = monthly_snapshots['portfolio_val'].iloc[-1] - init_capital
    avg_mo = m_pnl.mean()
    best_mo = m_pnl.max()
    worst_mo = m_pnl.min()
    
    win_mos = (m_pnl > 0).sum()
    loss_mos = (m_pnl < 0).sum()
    flat_mos = (m_pnl == 0).sum()
    tot_mos = len(m_pnl)
    
    print(f"[{pattern_mode}] Total Net: Rs {total_net:+,.1f} | Avg Mo: Rs {avg_mo:+,.1f} ({m_ret.mean():+.1f}%) | Best Mo: Rs {best_mo:+,.1f} ({m_ret.max():+.1f}%) | Worst Mo: Rs {worst_mo:+,.1f} ({m_ret.min():+.1f}%) | Win Mo: {win_mos}/{tot_mos} ({win_mos/tot_mos*100:.1f}%)")

print("Monthly profiles:")
run_pattern_monthly("VCP")
run_pattern_monthly("SWEET_SPOT")
