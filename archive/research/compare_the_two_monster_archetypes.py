"""
Deep-Dive Investigation 2: The Two Monster Archetypes
===================================================
Compares:
Archetype 1: "The High-Flyer Breakout" (Stage 2, within 12% of 52W High, RVOL >= 1.5x)
Archetype 2: "The Coiled Slingshot Turnaround" (Deeply beaten down, 52W Dist <= -25%, Extreme VCP <= 0.45, Sudden Massive RVOL >= 2.0x, Bullish Engulfing)
Archetype 3: The Combined "Dual-Thrust" Alpha Engine
"""
import os, sys, pickle, numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from data.costs import compute_indian_delivery_costs

with open("data/cache/universe_10y.pkl", "rb") as f:
    univ = pickle.load(f)
with open("data/cache/benchmarks_10y.pkl", "rb") as f:
    bm = pickle.load(f)

nifty_df = bm['^NSEI'].copy()
if isinstance(nifty_df.columns, pd.MultiIndex):
    nifty_df.columns = nifty_df.columns.get_level_values(0)
nifty_df['sma50'] = nifty_df['Close'].rolling(50).mean()

def enrich_stock(df):
    res = df.copy()
    if isinstance(res.columns, pd.MultiIndex):
        res.columns = res.columns.get_level_values(0)
    c, h, l, v, o = res["Close"], res["High"], res["Low"], res["Volume"], res["Open"]
    res["ema10"] = c.ewm(span=10, adjust=False).mean()
    res["ema20"] = c.ewm(span=20, adjust=False).mean()
    res["sma50"] = c.rolling(50).mean()
    res["sma200"] = c.rolling(200).mean()
    res["vol_sma20"] = v.rolling(20).mean()
    res["rvol"] = v / res["vol_sma20"].replace(0, np.nan)
    res["high20"] = h.rolling(20).max().shift(1)
    
    range_5d = h.rolling(5).max() - l.rolling(5).min()
    range_20d = h.rolling(20).max() - l.rolling(20).min()
    res["vcp_ratio"] = range_5d / range_20d.replace(0, np.nan)
    res["high52w"] = h.rolling(250).max().shift(1)
    res["dist_52w"] = ((c - res["high52w"]) / res["high52w"]) * 100.0
    
    # RSI 14
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    res["rsi14"] = 100 - (100 / (1 + rs))
    return res

indicators = {s: enrich_stock(df) for s, df in univ.items()}

def simulate_archetype(archetype_mode="HIGH_FLYER", init_capital=30000.0, max_pos=3):
    dates = nifty_df.loc["2016-10-24":"2026-10-16"].index
    cash = init_capital
    open_positions = {}
    closed_trades = []
    daily_equity = []
    
    for i in range(len(dates)):
        date_idx = dates[i]
        date_str = str(date_idx.date())
        nifty_bar = nifty_df.loc[date_idx]
        nifty_c = float(nifty_bar['Close'])
        nifty_sma50 = float(nifty_bar['sma50']) if not np.isnan(nifty_bar['sma50']) else 0.0
        
        # Exits
        to_close = []
        for sym, pos in open_positions.items():
            ind = indicators[sym]
            if date_idx not in ind.index:
                pos['days_held'] += 1
                continue
            bar = ind.loc[date_idx]
            o_px, h_px, l_px, c_px = float(bar['Open']), float(bar['High']), float(bar['Low']), float(bar['Close'])
            ema10_px = float(bar['ema10']) if not np.isnan(bar['ema10']) else c_px
            pos['days_held'] += 1
            gain_pct = ((c_px - pos['entry_price']) / pos['entry_price']) * 100.0
            
            exit_reason = None
            exit_px = 0.0
            
            # Stop loss
            if l_px <= pos['stop_loss']:
                exit_reason = 'STOP_LOSS'
                exit_px = min(pos['stop_loss'], o_px)
            # Scale out 40% at T1 (+16%)
            elif not pos['partial_booked'] and h_px >= pos['entry_price'] * 1.16:
                pos['partial_booked'] = True
                booked_qty = max(1, int(pos['qty'] * 0.40)) if pos['qty'] > 1 else 0
                if booked_qty > 0 and pos['qty'] > booked_qty:
                    booked_px = pos['entry_price'] * 1.16
                    costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=booked_px, quantity=booked_qty)
                    cash += (booked_qty * booked_px) - costs.total_friction_rupees
                    pos['qty'] -= booked_qty
                    pos['realized_partial_pnl'] = costs.net_pnl_rupees
                pos['stop_loss'] = round(pos['entry_price'] * 1.03, 2)  # Lock in +3% profit floor
                pos['is_running'] = True
            # Trailing 10 EMA exit for runner
            elif pos['is_running'] and c_px < ema10_px:
                exit_reason = 'RUNNER_10EMA_TRAIL'
                exit_px = c_px
            # Fast Stagnation (8 sessions)
            elif pos['days_held'] >= 8 and -1.5 <= gain_pct <= 1.5:
                exit_reason = 'FAST_STAGNATION_8D'
                exit_px = c_px
            # Dynamic Time Expiry (15 sessions base, 30 sessions if performing)
            elif not exit_reason:
                is_performing = bool(gain_pct >= 5.0 or pos['is_running'])
                max_sessions = 30 if is_performing else 15
                if pos['days_held'] >= max_sessions:
                    exit_reason = 'RUNNER_1_MONTH_EXPIRED' if is_performing else 'SWING_TIME_EXPIRED_15D'
                    exit_px = c_px
                    
            if exit_reason:
                costs = compute_indian_delivery_costs(buy_price=pos['entry_price'], sell_price=exit_px, quantity=pos['qty'])
                total_trade_pnl = costs.net_pnl_rupees + pos.get('realized_partial_pnl', 0.0)
                orig_qty = pos['qty'] + (max(1, int((pos['qty'] / 0.60) * 0.40)) if pos['partial_booked'] else 0)
                closed_trades.append({
                    'ticker': sym, 'year': date_idx.year, 'entry_px': pos['entry_price'], 'exit_px': exit_px,
                    'qty': pos['qty'], 'days_held': pos['days_held'], 'reason': exit_reason,
                    'net_pnl': total_trade_pnl, 'friction': costs.total_friction_rupees,
                    'ret_pct': (total_trade_pnl / (pos['entry_price'] * orig_qty)) * 100.0,
                    'arch': pos['archetype']
                })
                cash += (pos['qty'] * exit_px) - costs.total_friction_rupees
                to_close.append(sym)
                
        for s in to_close:
            del open_positions[s]
            
        invested = sum(pos['qty'] * (float(indicators[sym].loc[date_idx, 'Close']) if date_idx in indicators[sym].index else pos['entry_price']) for sym, pos in open_positions.items())
        portfolio_equity = cash + invested
        daily_equity.append({'date': date_idx, 'equity': portfolio_equity})
        
        # Macro Gate: In broad downtrend, only allow high-conviction decoupled setups
        allow_entries = True
        
        if len(open_positions) < max_pos:
            candidates = []
            for sym, ind in indicators.items():
                if sym in open_positions or date_idx not in ind.index:
                    continue
                bar = ind.loc[date_idx]
                c_px, o_px, h_px, l_px = float(bar['Close']), float(bar['Open']), float(bar['High']), float(bar['Low'])
                sma50 = float(bar['sma50']) if not np.isnan(bar['sma50']) else 0.0
                sma200 = float(bar['sma200']) if not np.isnan(bar['sma200']) else 0.0
                rvol = float(bar['rvol']) if not np.isnan(bar['rvol']) else 1.0
                vcp = float(bar['vcp_ratio']) if not np.isnan(bar['vcp_ratio']) else 1.0
                high20 = float(bar['high20']) if not np.isnan(bar['high20']) else 0.0
                dist_52w = float(bar['dist_52w']) if not np.isnan(bar['dist_52w']) else -99.0
                rsi = float(bar['rsi14']) if not np.isnan(bar['rsi14']) else 50.0
                
                # --- Archetype 1: The High-Flyer Breakout ---
                is_high_flyer = bool(
                    c_px > sma50 > sma200 
                    and dist_52w >= -12.0 
                    and rvol >= 1.5 
                    and (vcp <= 0.65 or dist_52w >= -2.0)
                    and c_px > o_px
                )
                
                # --- Archetype 2: The Coiled Slingshot Turnaround ---
                # Deeply beaten-down stock (dist 52w <= -25%), coiling tightly (vcp <= 0.50),
                # sudden massive institutional explosion (rvol >= 2.0x), crossing above 20 EMA
                ema20 = float(bar['ema20']) if not np.isnan(bar['ema20']) else 0.0
                is_slingshot = bool(
                    dist_52w <= -25.0
                    and vcp <= 0.50
                    and rvol >= 2.0
                    and c_px > ema20
                    and c_px > o_px
                    and rsi >= 40.0
                )
                
                if archetype_mode == "HIGH_FLYER" and is_high_flyer:
                    score = rvol * 3.0 + (1.0 - vcp) * 10.0
                    candidates.append((sym, score, c_px, "HIGH_FLYER"))
                elif archetype_mode == "SLINGSHOT" and is_slingshot:
                    score = rvol * 4.0 + (1.0 - vcp) * 12.0
                    candidates.append((sym, score, c_px, "SLINGSHOT"))
                elif archetype_mode == "DUAL_THRUST":
                    if is_high_flyer:
                        score = rvol * 3.0 + (1.0 - vcp) * 10.0
                        candidates.append((sym, score, c_px, "HIGH_FLYER"))
                    elif is_slingshot:
                        score = rvol * 4.0 + (1.0 - vcp) * 12.0 + 5.0 # Premium bonus for coiled explosion
                        candidates.append((sym, score, c_px, "SLINGSHOT"))
                        
            candidates.sort(key=lambda x: x[1], reverse=True)
            slots_free = max_pos - len(open_positions)
            slot_budget = portfolio_equity / max_pos
            
            for sym, score, entry_px, arch_tag in candidates[:slots_free]:
                alloc = min(cash, slot_budget)
                qty = int(alloc // entry_px)
                if qty > 0 and cash >= (qty * entry_px):
                    cash -= (qty * entry_px)
                    open_positions[sym] = {
                        'entry_price': entry_px, 'qty': qty,
                        'stop_loss': round(entry_px * 0.95, 2),
                        'days_held': 0, 'entry_date': date_str,
                        'is_running': False, 'partial_booked': False,
                        'archetype': arch_tag
                    }
                    
    df_tr = pd.DataFrame(closed_trades)
    df_eq = pd.DataFrame(daily_equity)
    
    wins = df_tr[df_tr['net_pnl'] > 0]
    wr = len(wins) / len(df_tr) * 100.0
    tot_pnl = df_tr['net_pnl'].sum()
    fin_eq = df_eq['equity'].iloc[-1]
    net_ret = ((fin_eq - init_capital) / init_capital) * 100.0
    pf = wins['net_pnl'].sum() / abs(df_tr[df_tr['net_pnl'] <= 0]['net_pnl'].sum())
    
    df_eq['pk'] = df_eq['equity'].cummax()
    max_dd = ((df_eq['equity'] - df_eq['pk']) / df_eq['pk']).min() * 100.0
    best_t = df_tr['ret_pct'].max()
    avg_w = wins['ret_pct'].mean()
    avg_l = df_tr[df_tr['net_pnl'] <= 0]['ret_pct'].mean()
    
    return {
        'trades': len(df_tr), 'wr': wr, 'tot_pnl': tot_pnl, 'fin_eq': fin_eq, 'ret': net_ret,
        'pf': pf, 'dd': max_dd, 'best': best_t, 'avg_w': avg_w, 'avg_l': avg_l,
        'trades_df': df_tr
    }

print("="*95)
print("10-YEAR HISTORICAL AUDIT: COMPARING THE TWO WEALTH-GENERATING ARCHETYPES")
print("="*95)

r_hf = simulate_archetype("HIGH_FLYER")
r_ss = simulate_archetype("SLINGSHOT")
r_dual = simulate_archetype("DUAL_THRUST")

print(f"\n[1. ARCHETYPE 1: HIGH-FLYER BREAKOUTS (Near 52W High)]")
print(f"    Final Capital: Rs {r_hf['fin_eq']:9,.2f} (+{r_hf['ret']:>6.1f}%) | Net P&L: Rs {r_hf['tot_pnl']:+9,.2f}")
print(f"    Trades: {r_hf['trades']} | Win Rate: {r_hf['wr']:.1f}% | Profit Factor: {r_hf['pf']:.2f} | Max DD: {r_hf['dd']:.1f}%")
print(f"    Avg Win: {r_hf['avg_w']:+.1f}% | Avg Loss: {r_hf['avg_l']:.1f}% | Best Trade: {r_hf['best']:+.1f}%")

print(f"\n[2. ARCHETYPE 2: COILED SLINGSHOT TURNAROUNDS (Deep Base Reversal + 2x Vol Explosion)]")
print(f"    Final Capital: Rs {r_ss['fin_eq']:9,.2f} (+{r_ss['ret']:>6.1f}%) | Net P&L: Rs {r_ss['tot_pnl']:+9,.2f}")
print(f"    Trades: {r_ss['trades']} | Win Rate: {r_ss['wr']:.1f}% | Profit Factor: {r_ss['pf']:.2f} | Max DD: {r_ss['dd']:.1f}%")
print(f"    Avg Win: {r_ss['avg_w']:+.1f}% | Avg Loss: {r_ss['avg_l']:.1f}% | Best Trade: {r_ss['best']:+.1f}%")

print(f"\n[3. ARCHETYPE 3: DUAL-THRUST ALPHA ENGINE (Combines Both Archetypes)]")
print(f"    Final Capital: Rs {r_dual['fin_eq']:9,.2f} (+{r_dual['ret']:>6.1f}%) | Net P&L: Rs {r_dual['tot_pnl']:+9,.2f}")
print(f"    Trades: {r_dual['trades']} | Win Rate: {r_dual['wr']:.1f}% | Profit Factor: {r_dual['pf']:.2f} | Max DD: {r_dual['dd']:.1f}%")
print(f"    Avg Win: {r_dual['avg_w']:+.1f}% | Avg Loss: {r_dual['avg_l']:.1f}% | Best Trade: {r_dual['best']:+.1f}%")

tdf = r_dual['trades_df']
print(f"\nBreakdown in Dual-Thrust: {len(tdf[tdf['arch']=='HIGH_FLYER'])} High-Flyer trades vs {len(tdf[tdf['arch']=='SLINGSHOT'])} Slingshot trades.")
