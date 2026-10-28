"""
Add Bharti Airtel, Coforge, and BSE to:
1. paper_trades
2. forward_test_log
3. daily_scores
"""
import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from data.db import (
    get_connection,
    create_paper_trade,
    log_forward_trade,
    save_daily_score,
    get_open_paper_trades
)
from engine.validator import _get_live_nifty_price

conn = get_connection()
today_date = "2026-10-27"
now_ts = f"{today_date}T15:30:00"

nifty_px = _get_live_nifty_price() or 259.49

trades_to_add = [
    {
        "ticker": "BHARTIARTL.NS",
        "name": "Bharti Airtel Ltd",
        "timeframe": "short_term",
        "action": "BUY",
        "entry_price": 1978.80,
        "entry_date": today_date,
        "quantity": 1,
        "stop_loss": 1879.86,
        "target_price": 2275.62,
        "final_score": 88.1,
        "technical_score": 85.0,
        "fundamental_score": 70.0,
        "sentiment_score": 75.0,
        "macro_score": 45.5,
        "event_risk_score": 60.0,
        "risk_level": "LOW",
        "reasoning": "Clean 52-week All-Time High breakout with 4.36x volume surge. Relative Strength +9.3% vs Nifty 50.",
        "notes": json.dumps({
            "sleeve": "momentum_breakout",
            "quant_score": 88.1,
            "rvol": 4.36,
            "rs_vs_nifty": "+9.3%",
            "reward_risk": 3.0,
            "paper_week": True,
            "catalyst": "52W All-Time High Volume Surge Breakout"
        })
    },
    {
        "ticker": "COFORGE.NS",
        "name": "Coforge Ltd",
        "timeframe": "short_term",
        "action": "BUY",
        "entry_price": 1997.00,
        "entry_date": today_date,
        "quantity": 1,
        "stop_loss": 1897.15,
        "target_price": 2296.55,
        "final_score": 87.6,
        "technical_score": 84.0,
        "fundamental_score": 72.0,
        "sentiment_score": 70.0,
        "macro_score": 45.5,
        "event_risk_score": 60.0,
        "risk_level": "MEDIUM",
        "reasoning": "IT sector momentum leader. Clean Stage-2 continuation above 20 EMA with +9.5% relative strength vs Nifty.",
        "notes": json.dumps({
            "sleeve": "momentum_breakout",
            "quant_score": 87.6,
            "rvol": 1.46,
            "rs_vs_nifty": "+9.5%",
            "reward_risk": 3.0,
            "paper_week": True,
            "catalyst": "IT Sector Leadership & Stage-2 Continuation"
        })
    },
    {
        "ticker": "BSE.NS",
        "name": "BSE Ltd",
        "timeframe": "short_term",
        "action": "BUY",
        "entry_price": 3441.10,
        "entry_date": today_date,
        "quantity": 1,
        "stop_loss": 3269.05,
        "target_price": 3957.27,
        "final_score": 79.7,
        "technical_score": 80.0,
        "fundamental_score": 75.0,
        "sentiment_score": 65.0,
        "macro_score": 45.5,
        "event_risk_score": 60.0,
        "risk_level": "MEDIUM",
        "reasoning": "Capital markets market share gainer. Breakout from consolidation with +7.2% relative strength.",
        "notes": json.dumps({
            "sleeve": "momentum_breakout",
            "quant_score": 79.7,
            "rvol": 1.06,
            "rs_vs_nifty": "+7.2%",
            "reward_risk": 3.0,
            "paper_week": True,
            "catalyst": "Financial Market Share & Derivatives Growth"
        })
    }
]

existing_opens = {o["ticker"]: o for o in get_open_paper_trades(conn)}

print("=== 1. CREATING PAPER TRADES ===")
for t in trades_to_add:
    ticker = t["ticker"]
    if ticker in existing_opens:
        print(f"⚠️ {ticker} is already OPEN in paper_trades (ID #{existing_opens[ticker]['id']}). Skipping duplicate.")
    else:
        trade_id = create_paper_trade(conn, {
            "ticker": ticker,
            "timeframe": t["timeframe"],
            "action": t["action"],
            "entry_price": t["entry_price"],
            "entry_date": t["entry_date"],
            "quantity": t["quantity"],
            "stop_loss": t["stop_loss"],
            "target_price": t["target_price"],
            "notes": t["notes"]
        })
        print(f"✅ Created Paper Trade ID #{trade_id}: {ticker} (Qty: {t['quantity']} @ Rs {t['entry_price']:,.2f} | Stop: Rs {t['stop_loss']:,.2f} | Target: Rs {t['target_price']:,.2f})")

print("\n=== 2. LOGGING TO FORWARD TEST AUDIT LOG ===")
for t in trades_to_add:
    fwd_id = log_forward_trade(conn, {
        "timestamp": now_ts,
        "date": today_date,
        "ticker": t["ticker"],
        "timeframe": t["timeframe"],
        "action": t["action"],
        "entry_price": t["entry_price"],
        "stop_loss": t["stop_loss"],
        "target_price": t["target_price"],
        "final_score": t["final_score"],
        "technical_score": t["technical_score"],
        "fundamental_score": t["fundamental_score"],
        "sentiment_score": t["sentiment_score"],
        "macro_score": t["macro_score"],
        "event_risk_score": t["event_risk_score"],
        "judge_verdict": "PASS",
        "nifty_entry_price": nifty_px,
    })
    print(f"✅ Logged Forward Test Trade ID #{fwd_id}: {t['ticker']} (Score: {t['final_score']} | NIFTYBEES Entry: Rs {nifty_px:.2f})")

print("\n=== 3. RECORDING IN DAILY SCORES ===")
for t in trades_to_add:
    save_daily_score(conn, {
        "date": today_date,
        "ticker": t["ticker"],
        "timeframe": t["timeframe"],
        "technical_score": t["technical_score"],
        "fundamental_score": t["fundamental_score"],
        "sentiment_score": t["sentiment_score"],
        "macro_score": t["macro_score"],
        "event_risk_score": t["event_risk_score"],
        "final_score": t["final_score"],
        "action": t["action"],
        "reasoning": t["reasoning"],
        "risk_level": t["risk_level"],
        "stop_loss": t["stop_loss"],
        "target_price": t["target_price"]
    })
    print(f"✅ Saved Daily Score for {t['ticker']}: {t['action']} | Score: {t['final_score']}")

conn.close()
print("\nAll 3 momentum breakouts are now actively tracking in Paper Trades!")
