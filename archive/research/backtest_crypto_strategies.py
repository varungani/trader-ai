"""
Comprehensive Quantitative Backtest of Crypto Strategies on 5-Year Dataset (2021-2026).
Simulates Indian Statutory Delivery Friction (1% TDS on sell, 0.20% exchange fee, 0.10% slippage).
Initial Capital: Rs 3,000.
"""
import sys
import os
import pickle
import pandas as pd
import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "cache", "crypto_5y.pkl")
if not os.path.exists(CACHE_FILE):
    print("Cache file not found!")
    sys.exit(1)

with open(CACHE_FILE, "rb") as f:
    crypto_data = pickle.load(f)

print(f"Loaded {len(crypto_data)} crypto assets for backtesting.")

# BTC is the macro regime benchmark
btc_df = crypto_data.get("BTC-USD")
if btc_df is None:
    print("BTC-USD not in data!")
    sys.exit(1)

# Precalculate indicators
def compute_crypto_indicators(df, btc_df):
    d = df.copy()
    close = d['close']
    d['ema10'] = close.ewm(span=10, adjust=False).mean()
    d['ema20'] = close.ewm(span=20, adjust=False).mean()
    d['ema50'] = close.ewm(span=50, adjust=False).mean()
    d['ema200'] = close.ewm(span=200, adjust=False).mean()
    d['sma20_vol'] = d['volume'].rolling(20).mean()
    d['rvol'] = d['volume'] / (d['sma20_vol'] + 1e-8)
    
    # ATR & VCP
    tr1 = d['high'] - d['low']
    tr2 = (d['high'] - close.shift(1)).abs()
    tr3 = (d['low'] - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    d['atr5'] = tr.rolling(5).mean()
    d['atr20'] = tr.rolling(20).mean()
    d['vcp_ratio'] = d['atr5'] / (d['atr20'] + 1e-8)
    
    # 20-day high
    d['high20'] = d['high'].rolling(20).max().shift(1)
    
    # Mansfield Relative Strength vs BTC
    aligned_btc = btc_df['close'].reindex(d.index).ffill()
    base_ratio = close / (aligned_btc + 1e-8)
    sma_base = base_ratio.rolling(50).mean()
    d['mansfield_rs'] = ((base_ratio / (sma_base + 1e-8)) - 1.0) * 100.0
    
    return d

processed_data = {}
for sym, df in crypto_data.items():
    processed_data[sym] = compute_crypto_indicators(df, btc_df)

# Align all timestamps
all_dates = sorted(btc_df.index)

# Simulation Engine with Indian Crypto Friction (1% TDS + 0.2% Fee + 0.1% Slippage)
def run_crypto_simulation(strategy_name, max_slots=2, initial_capital=3000.0, stop_pct=0.06, pt_pct=0.18, trail_ema=True):
    capital = initial_capital
    active_positions = {} # sym -> {entry_price, entry_date, shares, highest_price, partial_booked}
    closed_trades = []
    daily_equity = []
    
    slot_size = capital / max_slots
    
    for dt in all_dates:
        # Check BTC macro regime: Bull if BTC close > 50 EMA and 20 EMA > 50 EMA
        btc_bar = processed_data["BTC-USD"].loc[dt] if dt in processed_data["BTC-USD"].index else None
        if btc_bar is None or pd.isna(btc_bar['ema50']):
            continue
            
        btc_bull = (btc_bar['close'] > btc_bar['ema50']) and (btc_bar['ema20'] > btc_bar['ema50'])
        
        # 1. Manage Active Positions
        exits_to_make = []
        for sym, pos in list(active_positions.items()):
            if dt not in processed_data[sym].index:
                continue
            bar = processed_data[sym].loc[dt]
            curr_close = bar['close']
            curr_low = bar['low']
            curr_high = bar['high']
            
            # Update highest price
            if curr_high > pos['highest_price']:
                pos['highest_price'] = curr_high
                
            entry_p = pos['entry_price']
            gain_pct = (curr_close - entry_p) / entry_p
            low_pct = (curr_low - entry_p) / entry_p
            
            exit_price = None
            exit_reason = None
            
            # Hard stop
            if low_pct <= -stop_pct:
                exit_price = entry_p * (1.0 - stop_pct)
                exit_reason = "Hard Stop (-6%)"
            # Partial profit scale-out at +18%
            elif gain_pct >= pt_pct and not pos['partial_booked']:
                pos['partial_booked'] = True
                # Move stop to breakeven + 2%
                pos['stop_price'] = entry_p * 1.02
            # Trailing stop: close below daily 10 EMA (if trailing enabled and in profit)
            elif trail_ema and pos['partial_booked'] and curr_close < bar['ema10']:
                exit_price = curr_close
                exit_reason = "10 EMA Trailing Exit"
            # Emergency exit if BTC regime breaks into severe bear
            elif not btc_bull and (curr_close < bar['ema20']):
                exit_price = curr_close
                exit_reason = "BTC Macro Veto Exit"
                
            if exit_price is not None:
                exits_to_make.append((sym, exit_price, exit_reason))
                
        # Process exits
        for sym, ex_price, reason in exits_to_make:
            pos = active_positions.pop(sym)
            shares = pos['shares']
            gross_val = shares * ex_price
            
            # Indian Friction: 0.20% fee + 0.10% slippage + 1.00% Indian TDS on sell
            fee = gross_val * 0.0020
            slippage = gross_val * 0.0010
            tds = gross_val * 0.0100
            net_proceeds = gross_val - fee - slippage - tds
            
            trade_pnl = net_proceeds - pos['cost_basis']
            trade_ret = (trade_pnl / pos['cost_basis']) * 100.0
            capital += net_proceeds
            
            closed_trades.append({
                'symbol': sym,
                'entry_date': pos['entry_date'],
                'exit_date': dt,
                'entry_price': pos['entry_price'],
                'exit_price': ex_price,
                'pnl': trade_pnl,
                'ret_pct': trade_ret,
                'reason': reason,
                'duration': (dt - pos['entry_date']).days
            })
            
        # 2. Look for Entries (Only if BTC is Bullish and we have open slots)
        open_slots = max_slots - len(active_positions)
        if open_slots > 0 and btc_bull:
            candidates = []
            
            for sym, df in processed_data.items():
                if sym in active_positions or dt not in df.index:
                    continue
                bar = df.loc[dt]
                if pd.isna(bar['ema50']) or pd.isna(bar['rvol']):
                    continue
                    
                close = bar['close']
                ema10 = bar['ema10']
                ema20 = bar['ema20']
                ema50 = bar['ema50']
                rvol = bar['rvol']
                vcp = bar['vcp_ratio']
                m_rs = bar['mansfield_rs']
                
                signal = False
                score = 0
                
                if strategy_name == "super_confluence":
                    # Super Confluence: Stage 2 + Mansfield RS > 0 + VCP Contraction <= 0.75 + RVOL >= 1.5 + Close > 20 EMA
                    if close > ema20 and ema20 > ema50 and m_rs > 0 and vcp <= 0.75 and rvol >= 1.5:
                        signal = True
                        score = m_rs + (rvol * 5)
                elif strategy_name == "donchian_breakout":
                    # 20-day high breakout with RVOL >= 1.8
                    if close > bar['high20'] and rvol >= 1.8:
                        signal = True
                        score = rvol
                elif strategy_name == "btc_eth_trend":
                    # BTC and ETH only - buy on 20 EMA bounce
                    if sym in ["BTC-USD", "ETH-USD", "SOL-USD"] and close > ema20 and ema20 > ema50 and rvol >= 1.2:
                        signal = True
                        score = m_rs
                        
                if signal:
                    candidates.append((sym, score, close))
                    
            # Sort and pick top candidates
            candidates.sort(key=lambda x: x[1], reverse=True)
            for sym, score, close in candidates[:open_slots]:
                current_equity = capital + sum(p['shares'] * processed_data[s].loc[dt]['close'] for s, p in active_positions.items() if dt in processed_data[s].index)
                alloc = (current_equity / max_slots)
                alloc = min(alloc, capital)
                if alloc < 200:
                    continue
                    
                # Friction on entry: 0.20% fee + 0.10% slippage
                eff_entry_price = close * 1.0010
                fee = alloc * 0.0020
                investable = alloc - fee
                shares = investable / eff_entry_price
                capital -= alloc
                
                active_positions[sym] = {
                    'entry_price': eff_entry_price,
                    'entry_date': dt,
                    'shares': shares,
                    'cost_basis': alloc,
                    'highest_price': close,
                    'partial_booked': False,
                    'stop_price': eff_entry_price * (1.0 - stop_pct)
                }
                
        # Calculate daily portfolio equity
        holdings_val = sum(p['shares'] * processed_data[s].loc[dt]['close'] for s, p in active_positions.items() if dt in processed_data[s].index)
        daily_equity.append({'date': dt, 'equity': capital + holdings_val})
        
    eq_df = pd.DataFrame(daily_equity)
    eq_df['peak'] = eq_df['equity'].cummax()
    eq_df['dd'] = (eq_df['equity'] - eq_df['peak']) / eq_df['peak']
    max_dd = eq_df['dd'].min() * 100.0
    
    final_eq = eq_df['equity'].iloc[-1]
    net_pnl = final_eq - initial_capital
    net_ret = (net_pnl / initial_capital) * 100.0
    
    trades_df = pd.DataFrame(closed_trades)
    if not trades_df.empty:
        n_trades = len(trades_df)
        wins = trades_df[trades_df['pnl'] > 0]
        losses = trades_df[trades_df['pnl'] <= 0]
        wr = (len(wins) / n_trades) * 100.0
        gross_profit = wins['pnl'].sum() if len(wins) > 0 else 0
        gross_loss = abs(losses['pnl'].sum()) if len(losses) > 0 else 1e-8
        pf = gross_profit / gross_loss
        avg_win = wins['ret_pct'].mean() if len(wins) > 0 else 0
        avg_loss = losses['ret_pct'].mean() if len(losses) > 0 else 0
        best_trade = trades_df['ret_pct'].max()
    else:
        n_trades = 0
        wr = 0
        pf = 0
        avg_win = 0
        avg_loss = 0
        best_trade = 0
        
    return {
        'strategy': strategy_name,
        'final_equity': final_eq,
        'net_pnl': net_pnl,
        'net_ret': net_ret,
        'max_dd': max_dd,
        'n_trades': n_trades,
        'win_rate': wr,
        'profit_factor': pf,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'best_trade': best_trade
    }

print("\n" + "="*80)
print(f"5-YEAR QUANT CRYPTO BACKTEST RESULTS (2021-2026)")
print(f"Starting Capital: Rs 3,000 | Friction: 1% Indian TDS + 0.2% Fee + 0.1% Slippage")
print("="*80)

strategies = ["super_confluence", "donchian_breakout", "btc_eth_trend"]
configs = [
    ("super_confluence", 1, "Super-Confluence (1 Slot - Rs 3,000)"),
    ("super_confluence", 2, "Super-Confluence (2 Slots - Rs 1,500 each)"),
    ("donchian_breakout", 2, "Donchian 20D Breakout (2 Slots)"),
    ("btc_eth_trend", 1, "BTC/ETH/SOL Bluechips Only (1 Slot)")
]

results = []
for strat, slots, desc in configs:
    res = run_crypto_simulation(strat, max_slots=slots, initial_capital=3000.0)
    res['desc'] = desc
    results.append(res)
    print(f"\n>> {desc}")
    print(f"   Final Equity: Rs {res['final_equity']:.2f} ({res['net_ret']:+.1f}%)")
    print(f"   Net P&L:      Rs {res['net_pnl']:+.2f}")
    print(f"   Total Trades: {res['n_trades']} | Win Rate: {res['win_rate']:.1f}%")
    print(f"   Profit Factor: {res['profit_factor']:.2f} | Max Drawdown: {res['max_dd']:.1f}%")
    print(f"   Avg Win: {res['avg_win']:+.1f}% | Avg Loss: {res['avg_loss']:.1f}% | Best Trade: {res['best_trade']:+.1f}%")

# Compute Buy & Hold for comparison
print("\n" + "-"*80)
print("BENCHMARK BUY & HOLD (Rs 3,000 invested on Oct 24, 2021):")
for sym in ["BTC-USD", "ETH-USD", "SOL-USD"]:
    df = processed_data[sym]
    start_p = df['close'].iloc[0]
    end_p = df['close'].iloc[-1]
    bh_ret = ((end_p - start_p) / start_p) * 100.0
    bh_val = 3000.0 * (1.0 + bh_ret / 100.0)
    # Peak to trough drawdown
    peak = df['close'].cummax()
    dd = (df['close'] - peak) / peak
    bh_dd = dd.min() * 100.0
    print(f"   {sym:10s}: Rs {bh_val:8.2f} ({bh_ret:+.1f}%) | Max Drawdown: {bh_dd:.1f}%")
print("="*80)
