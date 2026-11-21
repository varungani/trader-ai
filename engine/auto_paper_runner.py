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


def run_daemon(interval_seconds: int = 300) -> None:
    """Continuously audit paper trades every interval (default 5 mins = 300s)."""
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


def run_hawk_surveillance(fast_interval_sec: int = 30, scan_interval_min: int = 15) -> None:
    """
    Hawk Mode:
      - Gear 1 (every 30s): Audits active positions & pending GTT triggers (Dual Tracker).
      - Gear 2 (every 15m during market hours): Sweeps universe for live breakout ignitions.
        Suppresses duplicates so each setup is only alerted once per trading day.
    """
    from bot.telegram_notifier import default_telegram_notifier
    from engine.apex_engine import run_apex_scan
    from engine.dual_tracker import log_today_picks

    logger.info("🦅 [HAWK MODE ARMED] Starting dual-gear surveillance:")
    logger.info(f"   • Gear 1 (Position Shield): Polling every {fast_interval_sec}s for Breakeven Locks & Exits")
    logger.info(f"   • Gear 2 (Apex Ignition Radar): Sweeping every {scan_interval_min}m for Live Breakout Signals")

    alerted_today: set[str] = set()
    current_day = datetime.now().date()
    last_scan_time = 0.0

    while True:
        try:
            now_dt = datetime.now()
            today_date = now_dt.date()

            # Day Rollover: reset alerted tickers for the new day
            if today_date != current_day:
                alerted_today.clear()
                current_day = today_date
                logger.info(f"New trading day detected ({current_day}). Alert memory cleared.")

            m_status = get_market_status()
            is_open = m_status.get("is_open", False)

            # GEAR 1: Fast Position & Trigger Audit (Runs every cycle)
            run_once()

            # GEAR 2: Intraday Apex Breakout Scan (Runs every scan_interval_min during open market hours)
            if is_open and (time.time() - last_scan_time >= scan_interval_min * 60):
                logger.info("🔍 [Gear 2 Pulse] Sweeping Nifty universe for live institutional ignition breakouts...")
                last_scan_time = time.time()
                try:
                    scan_res = run_apex_scan(universe_preset="nifty500")
                    picks = scan_res.get("picks") or scan_res.get("top_picks") or []
                    fresh_radar = []

                    for p in picks:
                        ticker = p.get("ticker", "")
                        if not ticker or ticker in alerted_today:
                            continue

                        cur_px = float(p.get("current_price") or 0.0)
                        pivot = float(p.get("pivot_buy_stop") or cur_px)
                        ceiling = float(p.get("max_buy_zone") or round(pivot * 1.015, 2))
                        target_px = float(p.get("target_price") or round(pivot * 1.12, 2))
                        stop_px = float(p.get("stop_loss") or round(pivot * 0.96, 2))
                        shares = int(p.get("shares") or (20000 // cur_px if cur_px > 0 else 0))

                        # Trigger live buy signal ONLY if price is within the disciplined buy zone [pivot * 0.995, ceiling]
                        if cur_px >= pivot * 0.995 and cur_px <= ceiling:
                            logger.info(f"🚨 [HAWK ALERT] Fresh breakout ignition detected: {ticker} @ ₹{cur_px:.2f}")
                            default_telegram_notifier.notify_live_buy_signal(
                                ticker=ticker,
                                current_price=cur_px,
                                pivot_trigger=pivot,
                                buy_ceiling=ceiling,
                                target_price=target_px,
                                stop_loss=stop_px,
                                shares=shares,
                                sector=p.get("sector", "General"),
                                pattern=p.get("setup_pattern", "INSTITUTIONAL_IGNITION"),
                            )
                            alerted_today.add(ticker)
                            fresh_radar.append(p)

                    # Feed any fresh breakout setups into Track B radar for continuous 30s tracking
                    if fresh_radar:
                        log_today_picks(tier1_picks=[], tier2_radar=fresh_radar)
                        logger.info(f"Registered {len(fresh_radar)} fresh ignition picks into live tracking radar.")
                except Exception as scan_err:
                    logger.warning(f"Intraday Apex scan error (will retry next interval): {scan_err}")

        except Exception as e:
            logger.error(f"Error in Hawk surveillance loop: {e}", exc_info=True)

        time.sleep(fast_interval_sec)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TraderAI Autonomous Paper Runner & Hawk Surveillance")
    parser.add_argument("--daemon", action="store_true", help="Run continuously every 5 minutes")
    parser.add_argument("--hawk", action="store_true", help="Run Hawk Mode: 30s position tracking + 15m live market sweep")
    parser.add_argument("--interval", type=int, default=300, help="Interval in seconds for daemon mode (default: 300 = 5 mins)")
    parser.add_argument("--scan-interval", type=int, default=15, help="Scan interval in minutes for hawk mode (default: 15 mins)")
    args = parser.parse_args()

    if args.hawk:
        run_hawk_surveillance(fast_interval_sec=30, scan_interval_min=args.scan_interval)
    elif args.daemon:
        run_daemon(args.interval)
    else:
        run_once()

