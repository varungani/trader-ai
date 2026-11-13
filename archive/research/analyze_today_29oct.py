"""
Deep Dive Analysis of Today's Market Tape (Thursday, 29 October 2026)
Inspects:
1. Indian Benchmarks (NIFTY 50, Nifty Bank, India VIX)
2. Open Indian Paper Positions (MPHASIS.NS) & MTM Audit
3. High-Beta Cheetah Momentum Screen (Top 15 Breakouts / Patterns Today)
4. US Market Live Status (SPY, QQQ, NVDA, TSLA, PLTR, QCOM)
5. Pattern Analysis across our top discovered strategies (P7 RSI sweet spot, P9 Stage 2 Pullback, P5 52W High)
"""
import yfinance as yf
import pandas as pd
import numpy as np
import datetime
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.db import get_connection, get_open_paper_trades
from engine.paper_week import mark_to_market
from engine.us_engine import get_us_market_status, fetch_us_realtime_data, analyze_us_market, sync_us_paper_trades

print("="*75)
print("📅 TRADER AI - TODAY'S MARKET DEEP DIVE (29 OCT 2026, 07:45 PM IST)")
print("="*75)

# 1. BENCHMARKS
print("\n--- 1. BENCHMARKS (INDIA & US) ---")
benchmarks = ["^NSEI", "NIFTYBEES.NS", "^INDIAVIX", "SPY", "QQQ"]
bm_data = yf.download(benchmarks, period="5d", progress=False)

for sym in benchmarks:
    try:
        series = bm_data["Close"][sym].dropna()
        if len(series) >= 2:
            last_dt = series.index[-1].strftime("%Y-%m-%d")
            p_today = float(series.iloc[-1])
            p_prev = float(series.iloc[-2])
            pct_chg = (p_today - p_prev) / p_prev * 100.0
            print(f"{sym:<15} : {p_today:10.2f} | 24h: {pct_chg:+6.2f}% | Date: {last_dt}")
    except Exception as e:
        print(f"{sym}: Error {e}")

# 2. AUDIT LIVE OPEN PAPER POSITIONS (NSE)
print("\n--- 2. ACTIVE DEMAT / PAPER POSITIONS AUDIT ---")
mtm = mark_to_market()
conn = get_connection()
try:
    open_trades = get_open_paper_trades(conn)
    marks_map = {m["trade_id"]: m for m in (mtm.get("marks") or [])}
    for t in open_trades:
        m = marks_map.get(t["id"], {})
        sym = t["ticker"]
        entry_px = float(t.get("entry_price") or 0.0)
        cur_px = float(m.get("last") or entry_px)
        qty = int(t.get("quantity") or 1)
        pnl = float(m.get("unrealized_pnl") or ((cur_px - entry_px) * qty))
        pnl_pct = ((cur_px - entry_px) / entry_px * 100.0) if entry_px > 0 else 0.0
        stop_px = float(t.get("stop_loss") or 0.0)
        target_px = float(t.get("target_price") or 0.0)
        days_held = t.get("days_held", 0)
        runner_eligible = t.get("is_runner_candidate", False) or pnl_pct >= 5.0
        
        print(f"Stock: {sym} | Entry: ₹{entry_px:.2f} | Current LTP: ₹{cur_px:.2f} | P&L: ₹{pnl:+.2f} ({pnl_pct:+.2f}%)")
        print(f"   Stop-Loss: ₹{stop_px:.2f} (Lock: {'BREAKEVEN' if stop_px >= entry_px else 'DEFENSIVE'}) | Target: ₹{target_px:.2f}")
        print(f"   Status: {'30-DAY RUNNER ACTIVE' if runner_eligible else '15-DAY SWING'} | Days Held: {days_held}")
finally:
    conn.close()

# 3. HIGH-BETA CHEETAH SCAN (TODAY'S TOP PATTERNS IN INDIA)
print("\n--- 3. HIGH-BETA CHEETAHS SCAN (TODAY'S PATTERNS & MOVERS) ---")
from config import HIGH_VELOCITY_STOCKS, HIGH_BETA_ROCKETS

scan_tickers = sorted(list(set(HIGH_VELOCITY_STOCKS + HIGH_BETA_ROCKETS)))
raw_data = yf.download(scan_tickers, period="30d", progress=False, group_by="ticker")

today_patterns = []

for t in scan_tickers:
    try:
        if t in raw_data.columns.levels[0]:
            df = raw_data[t].dropna(subset=["Close", "Volume"])
            if len(df) < 20:
                continue
            df.columns = [c.lower() for c in df.columns]
            c = df["close"]
            h = df["high"]
            l = df["low"]
            o = df["open"]
            v = df["volume"]
            
            p_today = float(c.iloc[-1])
            p_prev = float(c.iloc[-2])
            day_chg = (p_today - p_prev) / p_prev * 100.0
            
            # Indicators
            ema10 = float(c.ewm(span=10, adjust=False).mean().iloc[-1])
            ema20 = float(c.ewm(span=20, adjust=False).mean().iloc[-1])
            sma20_vol = float(v.rolling(20).mean().iloc[-1])
            rvol = float(v.iloc[-1]) / (sma20_vol + 1e-8)
            h20 = float(h.rolling(20).max().iloc[-2])
            h10 = float(h.rolling(10).max().iloc[-2])
            
            # RSI 14
            delta = c.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / (loss + 1e-8)
            rsi = float((100 - (100 / (1 + rs))).iloc[-1])
            
            # Pattern detectors
            patterns_found = []
            if ema10 > ema20 and 60.0 <= rsi <= 72.0:
                patterns_found.append("🔥 P7_RSI_SWEET_SPOT (60-72)")
            if p_today >= h20 * 0.995:
                patterns_found.append("🚀 20D_DONCHIAN_BREAKOUT")
            if p_today >= h10 * 0.995 and rvol >= 1.25:
                patterns_found.append("⚡ FAST_10D_BREAKOUT")
            if rvol >= 1.75 and day_chg > 0:
                patterns_found.append("🌊 TURBO_VOLUME_SURGE")
            if l.iloc[-1] <= ema20 * 1.01 and p_today > ema20 and p_today > float(o.iloc[-1]):
                patterns_found.append("🎯 STAGE2_20EMA_SPRINGBOARD")
                
            today_patterns.append({
                "ticker": t,
                "price": p_today,
                "day_chg": round(day_chg, 2),
                "rvol": round(rvol, 2),
                "rsi": round(rsi, 1),
                "ema10": round(ema10, 2),
                "ema20": round(ema20, 2),
                "patterns": patterns_found,
            })
    except Exception as e:
        pass

df_p = pd.DataFrame(today_patterns)
df_p = df_p.sort_values(by="day_chg", ascending=False)

print(f"\nTop 10 High-Beta Movers Today ({len(df_p)} Stocks Scanned):")
for idx, r in df_p.head(10).reset_index().iterrows():
    p_str = " | ".join(r["patterns"]) if r["patterns"] else "Consolidating"
    print(f"#{idx+1:02d} {r['ticker']:<15} : ₹{r['price']:8.2f} ({r['day_chg']:+6.2f}%) | RVOL: {r['rvol']:4.2f}x | RSI: {r['rsi']:4.1f} | {p_str}")

# Filter for setups that fired our top quantitative patterns
pattern_firings = [p for p in today_patterns if p["patterns"]]
print(f"\nActive Quantitative Pattern Triggers Today: {len(pattern_firings)}")
for p in pattern_firings[:8]:
    print(f"👉 {p['ticker']:<15} : ₹{p['price']:.2f} ({p['day_chg']:+.2f}%) | RSI: {p['rsi']} | RVOL: {p['rvol']}x | {' + '.join(p['patterns'])}")

# 4. US EQUITIES (LIVE WALL STREET TAPE TONIGHT)
print("\n--- 4. US EQUITIES (LIVE WALL STREET SESSION TONIGHT) ---")
u_stat = get_us_market_status()
print(f"Status: {u_stat['badge']} — {u_stat['detail']}")
u_data = fetch_us_realtime_data()
u_res = analyze_us_market(u_data)
u_sync = sync_us_paper_trades(u_data)

print(f"Macro Regime: {u_res.get('macro', {}).get('regime')} ({u_res.get('macro', {}).get('verdict')})")

print("\nTop US Setups Active Tonight:")
for c in u_res.get("candidates", [])[:6]:
    print(f"🇺🇸 {c['symbol']:<6} ({c['name']:<20}) : ${c['price_usd']:7.2f} (≈₹{c['price_inr']:8.0f}) | 24h: {c['change_24h']:+5.2f}% | Score: {c['score']:4.1f} | Verdict: {c['verdict']} | Action: {c['action']}")

print("\nActive US Paper Positions:")
for ut in u_sync.get("open_trades", []):
    print(f"Trade: {ut['symbol']} ({ut['name']}) | Shares: {ut['shares']:.4f} | Entry: ${ut['entry_price_usd']:.2f} | Current: ${ut['current_price_usd']:.2f} | Floating P&L: ${ut['unrealized_pnl_usd']:+.2f} (₹{ut['unrealized_pnl_inr']:+.2f} / {ut['unrealized_pnl_pct']:+.2f}%)")

print("="*75)
print("DEEP DIVE SCAN COMPLETE.")
print("="*75)
