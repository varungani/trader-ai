"""
Check real-time US market status and candidate scores at 07:13 PM IST.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from engine.us_engine import get_us_market_status, fetch_us_realtime_data, analyze_us_market

status = get_us_market_status()
print("=== 1. US MARKET SESSION STATUS ===")
print("Badge :", status["badge"])
print("Detail:", status["detail"])
print("Is Live Regular Open?:", status["is_open"])
print("EST Time:", status["time_est_str"])
print("IST Time:", status["time_ist_str"])

print("\n=== 2. FETCHING LIVE DATA & RUNNING QUANT SCANNER ===")
data = fetch_us_realtime_data()
analysis = analyze_us_market(data)

macro = analysis["macro"]
print("\n=== 3. MACRO GATE STATUS ===")
print(f"Regime      : {macro['regime']}")
print(f"SPY Price   : ${macro['spy_price']:.2f} (50 SMA: ${macro['spy_sma50']:.2f}) -> Pass: {macro['spy_pass']}")
print(f"QQQ Price   : ${macro['qqq_price']:.2f} (50 SMA: ${macro['qqq_sma50']:.2f}) -> Pass: {macro['qqq_pass']}")
print(f"Verdict     : {macro['verdict']}")
print(f"Entries Ok? : {macro['entries_allowed']}")

candidates = analysis["candidates"]
print(f"\n=== 4. CANDIDATES SCORED ({len(candidates)}) ===")
print("Top 10 Candidates by Score:")
for c in candidates[:10]:
    print(f"• {c['symbol']:<5} ({c['name']:<22}) | Score: {c['score']:>4.1f} | {c['verdict']} | {c['action']}")
    print(f"  Price: ${c['price_usd']:.2f} (Rs {c['price_inr']:,.2f}) | 24h: {c['change_24h']:+.2f}% | RVOL: {c['rvol']}x | RS: {c['mansfield_rs']:+.1f}% | Stop: ${c['stop_loss_usd']:.2f} | T1: ${c['target1_usd']:.2f}")
