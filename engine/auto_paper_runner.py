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
from data.market_calendar import get_market_status, get_ist_now, is_trading_day

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AutoPaperRunner")


def run_once(market_hours_only: bool = False) -> dict:
    """Run one pass of auditing and updating all active paper trades across all 9 parallel tournament tracks."""
    if market_hours_only:
        from datetime import time as dtime
        now_ist = get_ist_now()
        is_td, reason = is_trading_day(now_ist.date())
        m_status = get_market_status(now_ist)
        in_live_or_close_window = m_status.get("is_open", False) or (
            is_td and dtime(15, 30) <= now_ist.time() <= dtime(15, 45)
        )
        if not in_live_or_close_window:
            logger.info(
                f"⏸️ [Outside Live Window] {now_ist.strftime('%Y-%m-%d %H:%M IST')} ({reason}). "
                "Skipping live audit to prevent delayed/after-hours executions or alerts."
            )
            return compute_dual_summary()

    logger.info("Executing automated 9-way parallel paper trade audit...")
    summary = audit_and_update_dual_tracker()
    
    tracks_dict = summary.get("tracks", {})
    
    print("\n" + "="*80)
    print(f"📊 AUTOMATED 9-WAY PARALLEL PAPER TOURNAMENT — {summary.get('updated_at')}")
    print("="*80)
    print(f"🏆 Overall Leader: {summary.get('winner')}")
    print("-" * 80)

    badges = ["🥇", "🚀", "⚡", "🛡️", "🎯", "💎", "🔥", "👑", "🌊"]

    def _print_track_block(badge: str, track_data: dict):
        name = track_data.get("name", "Track")
        is_silent = "Silent" in name or "Benchmark" in name
        mode = "[SILENT BENCHMARK - ALERTS MUTED]" if is_silent else "[ACTIVE ALPHA - TELEGRAM ARMED]"
        print(f"{badge} {name} {mode}:")
        print(f"   • Pending GTT   : {track_data.get('pending_count', 0)} awaiting trigger")
        print(f"   • Open Trades   : {track_data.get('open_count', 0)} active")
        print(f"   • Closed Trades : {track_data.get('closed_count', 0)} completed")
        print(f"   • Win Rate      : {track_data.get('win_rate', 0.0):.1f}%")
        print(f"   • Profit Factor : {track_data.get('profit_factor', 1.0):.2f}")
        print(f"   • Net P&L (INR) : ₹{track_data.get('total_pnl_inr', 0.0):+,.2f} ({track_data.get('total_pnl_pct', 0.0):+.2f}% on ₹100k, {track_data.get('roc_deployed_pct', 0.0):+.2f}% on deployed)")
        print(f"   • Available Cash: ₹{track_data.get('cash_free', 100000.0):,.2f}")
        if track_data.get("open_trades"):
            print("   Active Positions:")
            for t in track_data["open_trades"]:
                print(f"     - {t['name']:<12} Entry: ₹{t['entry_price']:<9.2f} Cur: ₹{t['current_price']:<9.2f} PnL: {t['pnl_pct']:+.2f}% (₹{t['pnl_rupees']:+,.0f})")

    for idx, (t_key, t_data) in enumerate(tracks_dict.items()):
        badge = badges[idx % len(badges)]
        _print_track_block(badge, t_data)
        print("-" * 80)

    print("="*80 + "\n")
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


def run_hawk_surveillance(
    fast_interval_sec: int = 20,
    scan_interval_min: int = 15,
    session_mode: bool = False,
    session_target: str = "auto",
    max_cycles: Optional[int] = None,
) -> None:
    """
    Hawk Mode:
      - Gear 1 (every 20s): Audits active positions & pending GTT triggers (Dual Tracker).
      - Gear 2 (every 15m during market hours): Sweeps universe for live breakout ignitions.
      - session_mode: Runs continuously during the trading day with relay checkpoints:
          * Morning Relay (09:10 - 12:30 IST): Saves midday snapshot cleanly under 3.5h.
          * Afternoon Relay (12:30 - 15:35 IST): Audits close, dispatches Telegram recap, and commits.
    """
    from datetime import time as dtime
    from bot.telegram_notifier import default_telegram_notifier
    from engine.apex_engine import run_apex_scan
    from engine.dual_tracker import log_today_picks, _load_tracker, _save_tracker
    from data.market_calendar import get_ist_now, is_trading_day, NORMAL_MARKET_CLOSE

    logger.info("🦅 [HAWK MODE ARMED] Starting dual-gear surveillance:")
    logger.info(f"   • Gear 1 (Position Shield): Polling every {fast_interval_sec}s for Breakeven Locks & Exits")
    logger.info(f"   • Gear 2 (Apex Ignition Radar): Sweeping every {scan_interval_min}m for Live Breakout Signals")
    logger.info(f"   • Session Mode: {'ACTIVE (' + session_target + ')' if session_mode else 'Continuous Daemon'}")

    tracker = _load_tracker()
    today_str = datetime.now().strftime("%Y-%m-%d")
    alerted_signals = tracker.setdefault("alerted_buy_signals", {})
    alerted_today: set[str] = {t for t, d in alerted_signals.items() if d == today_str}

    last_scan_time = 0.0
    cycles_run = 0

    while True:
        try:
            now_ist = get_ist_now()
            today_date = now_ist.date()
            today_str = now_ist.strftime("%Y-%m-%d")
            is_td, _ = is_trading_day(today_date)

            # In Session Mode: Check if relay target is reached
            if session_mode:
                if not is_td:
                    logger.info("Today is not a trading day. Exiting without running live audit.")
                    break

                midday_boundary = dtime(12, 30)
                eod_boundary = NORMAL_MARKET_CLOSE  # 15:30

                if session_target == "12:30":
                    target_time = midday_boundary
                    is_eod = False
                elif session_target == "15:30":
                    target_time = eod_boundary
                    is_eod = True
                else:  # auto
                    if now_ist.time() < midday_boundary:
                        target_time = midday_boundary
                        is_eod = False
                    else:
                        target_time = eod_boundary
                        is_eod = True

                if now_ist.time() >= target_time:
                    if is_eod:
                        if now_ist.time() > dtime(16, 15):
                            logger.warning(
                                f"⏸️ [Late Queue Cutoff] Hawk reached EOD past 16:15 IST ({now_ist.strftime('%H:%M IST')}). "
                                "Archiving snapshot without triggering after-hours fills or late Telegram recap."
                            )
                            try:
                                from engine.analytics.evening_collector import archive_evening_snapshot
                                archive_evening_snapshot(perform_audit=False)
                            except Exception as snap_err:
                                logger.error(f"Failed to archive evening snapshot: {snap_err}", exc_info=True)
                            break

                        logger.info("⏰ [MARKET CLOSED] 03:30 PM IST reached. Running final post-market audit & daily recap...")
                        final_summary = run_once(market_hours_only=True)
                        try:
                            from engine.analytics.evening_collector import archive_evening_snapshot
                            logger.info("📦 Archiving evening snapshot & updating local analytics ledger...")
                            archive_evening_snapshot(perform_audit=False)
                        except Exception as snap_err:
                            logger.error(f"Failed to archive evening snapshot: {snap_err}", exc_info=True)

                        latest_tracker = _load_tracker()
                        if latest_tracker.get("daily_recap_sent_date") != today_str:
                            sent = default_telegram_notifier.notify_daily_recap(final_summary)
                            if sent:
                                latest_tracker["daily_recap_sent_date"] = today_str
                                _save_tracker(latest_tracker)
                    else:
                        logger.info("⏰ [MIDDAY CHECKPOINT] 12:30 PM IST reached. Saving midday state cleanly for afternoon runner...")
                        run_once(market_hours_only=True)
                    break

            m_status = get_market_status(now_ist)
            is_open = m_status.get("is_open", False)

            # GEAR 1: Fast Position & Trigger Audit (Strictly only inside live NSE window)
            if is_open:
                run_once(market_hours_only=True)
            else:
                logger.info(f"⏳ Waiting for NSE open ({now_ist.strftime('%H:%M:%S IST')})...")

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
                            sent = default_telegram_notifier.notify_live_buy_signal(
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
                            if sent:
                                alerted_today.add(ticker)
                                alerted_signals[ticker] = today_str
                                fresh_radar.append(p)

                    # Feed any fresh breakout setups into Track B radar for continuous 20s tracking
                    if fresh_radar:
                        log_today_picks(tier1_picks=[], tier2_radar=fresh_radar)
                        tracker["alerted_buy_signals"] = alerted_signals
                        _save_tracker(tracker)
                        logger.info(f"Registered {len(fresh_radar)} fresh ignition picks into live tracking radar.")
                except Exception as scan_err:
                    logger.warning(f"Intraday Apex scan error (will retry next interval): {scan_err}")

        except Exception as e:
            logger.error(f"Error in Hawk surveillance loop: {e}", exc_info=True)

        cycles_run += 1
        if max_cycles and cycles_run >= max_cycles:
            logger.info(f"Reached max_cycles={max_cycles}. Exiting.")
            break

        time.sleep(fast_interval_sec)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TraderAI Autonomous Paper Runner & Hawk Surveillance")
    parser.add_argument("--daemon", action="store_true", help="Run continuously every 5 minutes")
    parser.add_argument("--hawk", action="store_true", help="Run Hawk Mode: fast position tracking + live market sweep")
    parser.add_argument("--session-mode", action="store_true", help="Run continuously until relay target or 15:30 IST market close")
    parser.add_argument("--session-target", type=str, default="auto", choices=["auto", "12:30", "15:30"], help="Session relay target (auto, 12:30, 15:30)")
    parser.add_argument("--fast-interval", type=int, default=20, help="Interval in seconds for fast position check (default: 20s)")
    parser.add_argument("--interval", type=int, default=300, help="Interval in seconds for daemon mode (default: 300 = 5 mins)")
    parser.add_argument("--scan-interval", type=int, default=15, help="Scan interval in minutes for hawk mode (default: 15 mins)")
    parser.add_argument("--max-cycles", type=int, default=None, help="Optional max loop iterations")
    parser.add_argument("--archive", action="store_true", help="Run audit and immediately archive evening snapshot")
    parser.add_argument("--market-hours-only", action="store_true", help="Skip live audit if outside NSE continuous session/close window")
    args = parser.parse_args()

    if args.hawk:
        run_hawk_surveillance(
            fast_interval_sec=args.fast_interval,
            scan_interval_min=args.scan_interval,
            session_mode=args.session_mode,
            session_target=args.session_target,
            max_cycles=args.max_cycles,
        )
    elif args.daemon:
        run_daemon(args.interval)
    else:
        run_once(market_hours_only=args.market_hours_only)
        if args.archive:
            from engine.analytics.evening_collector import archive_evening_snapshot
            archive_evening_snapshot(perform_audit=False)

