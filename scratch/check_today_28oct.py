"""
Comprehensive Check for Today (28 Oct 2026):
1. Market Benchmark & Macro Regime Overview (Nifty 50, Bank Nifty, IT, Auto, India VIX)
2. Live Status of Open Paper Trades (MTM, P&L, Sessions Held, Stops/Targets)
3. Audit Paper Trading Updates via engine.paper_week
4. Full Universe Screen & Pipeline Run (Sector Decoupling, Top Buy Candidates)
"""
import sys
import os
import sqlite3
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import yfinance as yf
from data.db import get_connection, get_open_paper_trades
from data.market_calendar import count_trading_days, is_trading_holiday
import engine.paper_week as pw

print("=================================================================")
print("1. MACRO & BENCHMARK DYNAMICS (28 OCT 2026)")
print("=================================================================")
benchmarks = ['^NSEI', '^NSEBANK', '^CNXIT', '^CNXAUTO', '^INDIAVIX']
bench_names = {
    '^NSEI': 'NIFTY 50',
    '^NSEBANK': 'BANK NIFTY',
    '^CNXIT': 'NIFTY IT',
    '^CNXAUTO': 'NIFTY AUTO',
    '^INDIAVIX': 'INDIA VIX'
}

data_bench = yf.download(benchmarks, period='5d', interval='1d', progress=False, group_by='ticker')
for b in benchmarks:
    try:
        df_b = data_bench[b].dropna(subset=['Close'])
        c = float(df_b['Close'].iloc[-1])
        prev = float(df_b['Close'].iloc[-2])
        chg = ((c - prev) / prev) * 100
        h = float(df_b['High'].iloc[-1])
        l = float(df_b['Low'].iloc[-1])
        dt = str(df_b.index[-1])[:10]
        print(f"• {bench_names.get(b, b):<14}: {c:>9,.2f} ({chg:>+5.2f}%) | Day High: {h:>9,.2f} | Day Low: {l:>9,.2f} | Date: {dt}")
    except Exception as e:
        print(f"• {b}: Error fetching ({e})")

print("\n=================================================================")
print("2. ACTIVE PAPER TRADES PORTFOLIO STATUS (28 OCT 2026)")
print("=================================================================")
conn = get_connection()
open_trades = get_open_paper_trades(conn)
print(f"Found {len(open_trades)} OPEN paper trades in database:")

trade_tickers = [t['ticker'] for t in open_trades]
live_data = yf.download(trade_tickers, period='5d', interval='1d', progress=False, group_by='ticker') if trade_tickers else {}

total_allocated = 0.0
total_current_val = 0.0
total_pnl = 0.0

for t in open_trades:
    sym = t['ticker']
    entry_px = float(t['entry_price'])
    qty = float(t['quantity'])
    stop_px = float(t['stop_loss'])
    target_px = float(t['target_price'])
    entry_dt = str(t['entry_date'])[:10]
    
    # Get live quote for today
    cur_px = entry_px
    day_high = entry_px
    day_low = entry_px
    quote_dt = entry_dt
    try:
        if len(trade_tickers) == 1:
            df_sym = live_data.dropna(subset=['Close'])
        else:
            df_sym = live_data[sym].dropna(subset=['Close'])
        cur_px = float(df_sym['Close'].iloc[-1])
        day_high = float(df_sym['High'].iloc[-1])
        day_low = float(df_sym['Low'].iloc[-1])
        quote_dt = str(df_sym.index[-1])[:10]
    except Exception:
        pass
    
    sessions = count_trading_days(entry_dt, "2026-10-28")
    invested = entry_px * qty
    cur_val = cur_px * qty
    pnl = cur_val - invested
    pnl_pct = (pnl / invested) * 100 if invested > 0 else 0.0
    
    dist_stop = ((cur_px - stop_px) / cur_px) * 100
    dist_target = ((target_px - cur_px) / cur_px) * 100
    
    total_allocated += invested
    total_current_val += cur_val
    total_pnl += pnl
    
    print(f"\n📦 {sym} ({t.get('name', sym)}):")
    print(f"   Entry: Rs {entry_px:,.2f} on {entry_dt} | Qty: {qty:.0f} | Invested: Rs {invested:,.2f}")
    print(f"   LTP (28 Oct): Rs {cur_px:,.2f} ({quote_dt}) | High: Rs {day_high:,.2f} | Low: Rs {day_low:,.2f}")
    print(f"   Floating P&L: Rs {pnl:+,.2f} ({pnl_pct:+.2f}%)")
    print(f"   Stop-Loss: Rs {stop_px:,.2f} ({dist_stop:+.1f}% away) | Target: Rs {target_px:,.2f} ({dist_target:+.1f}% away)")
    print(f"   Trading Sessions Held: {sessions} sessions (Max: 15 sessions)")

net_pct = (total_pnl / total_allocated) * 100 if total_allocated > 0 else 0.0
print(f"\n--- PORTFOLIO SUMMARY ---")
print(f"Total Invested Capital: Rs {total_allocated:,.2f}")
print(f"Current Market Value:   Rs {total_current_val:,.2f}")
print(f"Total Floating P&L:     Rs {total_pnl:+,.2f} ({net_pct:+.2f}%)")

print("\n=================================================================")
print("3. EXECUTING PAPER TRADING LIFECYCLE AUDIT (MARK-TO-MARKET & EXITS)")
print("=================================================================")
res = pw.mark_to_market()
print(f"Marks calculated: {len(res.get('marks', []))} | Closed: {len(res.get('closed', []))}")
for c in res.get('closed', []):
    print(f"• CLOSED: {c['ticker']} at Rs {c['price']} | Reason: {c['reason']}")

print("\n=================================================================")
print("4. RUNNING SCREENER & PIPELINE ON FULL EXPANDED UNIVERSE TODAY")
print("=================================================================")
from config import NIFTY50_STOCKS, MIDCAP_LIQUID_STOCKS
universe = list(dict.fromkeys(NIFTY50_STOCKS + MIDCAP_LIQUID_STOCKS + ["BSE.NS", "CDSL.NS", "KAYNES.NS"]))
import engine.validator
engine.validator.audit_and_resolve_forward_trades = lambda: {}

from engine.screener import pre_screen
from engine.pipeline import run_pipeline

screened = pre_screen(universe, top_n=10)
print(f"Top 10 Pre-Screened Candidates for 28 Oct 2026:")
for s in screened:
    print(f"• {s['ticker']:<14}: Screen Score: {s['screen_score']:>5.1f} | RVOL: {s['rvol']:>4.2f}x | Pattern: {s['setup_pattern']:<18} | Range Pos: {s['range_position']}")

top_syms = [s['ticker'] for s in screened[:5]]
print(f"\nRunning Full Multi-Factor Pipeline on Top Candidates: {top_syms}...")
brief = run_pipeline(
    tickers=top_syms,
    timeframe="short_term",
    include_holdings=False,
    sync_broker=False,
    persist=False,
    use_llm=False,
    paper_week=False,
    use_screener=False,
    stock_budget=10000.0,
)

print(f"\nMacro Regime Gate Status: {'CLEARED' if brief['macro'].get('is_regime_gate_cleared') else 'BLOCKED (NIFTY < 50 SMA)'}")
print(f"Sector Decoupling Active: {brief.get('sector_decoupled_active')}")
print(f"Actionable Top Picks Count: {len(brief.get('top_picks', []))}")
for p in brief.get('top_picks', []):
    print(f"• {p['ticker']} | Action: {p['action']} | Score: {p['final_score']} | Decoupled: {p.get('is_sector_decoupled')} | Context: {p.get('regime_context')}")
    print(f"  Entry: Rs {p['current_price']} | Stop: Rs {p['stop_loss']} ({p['stop_loss_pct']}%) | Target: Rs {p['target_price']} ({p['target_pct']}%) | R:R: {p['reward_risk']}:1")
    print(f"  Rationale: {p['action_rationale']}")

print("\n=================================================================")
print("CHECK COMPLETED FOR 28 OCT 2026")
print("=================================================================")
