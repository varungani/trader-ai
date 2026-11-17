"""
TraderAI - Automated Paper Trading Runner (Every 30 Mins)
Autonomous execution runner that audits active paper trades, checks GTT triggers,
deducts statutory Indian friction, and updates data/dual_tracker.json.

Can be run:
  1. Once (e.g. from GitHub Actions cron every 30m): python engine/auto_paper_runner.py
  2. As a continuous background daemon during market hours: python engine/auto_paper_runner.py --daemon
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine.dual_tracker import audit_and_update_dual_tracker, compute_dual_summary, _load_tracker
from data.market_calendar import get_market_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AutoPaperRunner")


def run_once() -> dict:
    """Run one pass of auditing and updating all active paper trades."""
    logger.info("Executing automated paper trade audit...")
    summary = audit_and_update_dual_tracker()
    
    o2 = summary["option_2"]
    o3 = summary["option_3"]
    oc = summary.get("track_c", {})
    
    print("\n" + "="*70)
    print(f"📊 AUTOMATED 3-WAY PAPER TOURNAMENT — {summary.get('updated_at')}")
    print("="*70)
    print(f"🏆 Current Performance Leader: {summary.get('winner')}")
    print("-" * 70)
    print(f"🟢 Track A: Option 2 (9:20 AM Confirmation):")
    print(f"   • Open Trades   : {o2['open_count']} active")
    print(f"   • Closed Trades : {o2['closed_count']} completed")
    print(f"   • Win Rate      : {o2['win_rate']:.1f}%")
    print(f"   • Profit Factor : {o2['profit_factor']:.2f}")
    print(f"   • Net P&L (INR) : ₹{o2['total_pnl_inr']:+,.2f} ({o2['total_pnl_pct']:+.2f}%)")
    if o2["open_trades"]:
        print("   Active Positions:")
        for t in o2["open_trades"]:
            print(f"     - {t['name']:<12} Entry: ₹{t['entry_price']:<9.2f} Cur: ₹{t['current_price']:<9.2f} PnL: {t['pnl_pct']:+.2f}% (₹{t['pnl_rupees']:+,.0f})")
            
    print("-" * 70)
    print(f"🔵 Track B: Option 3 (GTT Buy-Stop Pivot Trigger):")
    print(f"   • Pending GTT   : {o3['pending_count']} awaiting breakout")
    print(f"   • Open Trades   : {o3['open_count']} triggered & active")
    print(f"   • Closed Trades : {o3['closed_count']} completed")
    print(f"   • Win Rate      : {o3['win_rate']:.1f}%")
    print(f"   • Profit Factor : {o3['profit_factor']:.2f}")
    print(f"   • Net P&L (INR) : ₹{o3['total_pnl_inr']:+,.2f} ({o3['total_pnl_pct']:+.2f}%)")
    if o3["open_trades"]:
        print("   Active Positions:")
        for t in o3["open_trades"]:
            print(f"     - {t['name']:<12} Entry: ₹{t['entry_price']:<9.2f} Cur: ₹{t['current_price']:<9.2f} PnL: {t['pnl_pct']:+.2f}% (₹{t['pnl_rupees']:+,.0f})")

    if oc:
        print("-" * 70)
        print(f"⚡ Track C: Benchmark Velocity Sniper (Target +25%, SL -6%, 72h Gate):")
        print(f"   • Pending GTT   : {oc.get('pending_count', 0)} awaiting breakout")
        print(f"   • Open Trades   : {oc.get('open_count', 0)} triggered & active")
        print(f"   • Closed Trades : {oc.get('closed_count', 0)} completed")
        print(f"   • Win Rate      : {oc.get('win_rate', 0.0):.1f}%")
        print(f"   • Profit Factor : {oc.get('profit_factor', 1.0):.2f}")
        print(f"   • Net P&L (INR) : ₹{oc.get('total_pnl_inr', 0.0):+,.2f} ({oc.get('total_pnl_pct', 0.0):+.2f}%)")
        if oc.get("open_trades"):
            print("   Active Positions:")
            for t in oc["open_trades"]:
                print(f"     - {t['name']:<12} Entry: ₹{t['entry_price']:<9.2f} Cur: ₹{t['current_price']:<9.2f} PnL: {t['pnl_pct']:+.2f}% (₹{t['pnl_rupees']:+,.0f})")
    print("="*70 + "\n")
    return summary


def run_daemon(interval_seconds: int = 1800) -> None:
    """Continuously audit paper trades every interval (default 30 mins = 1800s)."""
    logger.info(f"Starting paper trade daemon. Audit cycle every {interval_seconds // 60} minutes.")
    while True:
        try:
            m_status = get_market_status()
            logger.info(f"Market Status: {m_status.get('badge')} ({m_status.get('detail')})")
            run_once()
        except Exception as e:
            logger.error(f"Error during audit cycle: {e}", exc_info=True)
            
        logger.info(f"Sleeping for {interval_seconds}s (next run at {(datetime.now().timestamp() + interval_seconds)})...")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TraderAI Autonomous Paper Runner")
    parser.add_argument("--daemon", action="store_true", help="Run continuously every 30 minutes")
    parser.add_argument("--interval", type=int, default=1800, help="Interval in seconds (default: 1800)")
    args = parser.parse_args()

    if args.daemon:
        run_daemon(args.interval)
    else:
        run_once()

