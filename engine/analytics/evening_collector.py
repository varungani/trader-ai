"""
TraderAI - Automated Evening Analytics & Decision Archiver
Collects, archives, and exports all 5 tournament tracks locally every evening:
  1. Full Frozen EOD JSON Snapshot: data/analytics/snapshots/snapshot_YYYY-MM-DD.json
  2. Tabular Equity History (CSV): data/analytics/track_daily_equity.csv
  3. Closed Trades History (CSV): data/analytics/closed_trades_history.csv
  4. Active Open Positions (CSV): data/analytics/active_positions_snapshot.csv
  5. Immutable Decisions Ledger (JSONL): data/analytics/decisions_ledger.jsonl

Provides instant pandas loaders for offline EDA & quantitative verification:
  - load_trades_df()
  - load_equity_df()
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime, date, time as dtime, timedelta
from typing import Dict, Any, List, Optional
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from data.market_calendar import get_ist_now, is_trading_day
from engine.dual_tracker import audit_and_update_dual_tracker, compute_dual_summary, _load_tracker

logger = logging.getLogger("EveningCollector")
DEFAULT_ANALYTICS_DIR = os.path.join(ROOT, "data", "analytics")


def ensure_analytics_dirs(base_dir: str = DEFAULT_ANALYTICS_DIR) -> Dict[str, str]:
    """Ensures that analytics folders exist."""
    snapshots_dir = os.path.join(base_dir, "snapshots")
    os.makedirs(snapshots_dir, exist_ok=True)
    return {
        "base": base_dir,
        "snapshots": snapshots_dir,
        "equity_csv": os.path.join(base_dir, "track_daily_equity.csv"),
        "trades_csv": os.path.join(base_dir, "closed_trades_history.csv"),
        "positions_csv": os.path.join(base_dir, "active_positions_snapshot.csv"),
        "ledger_jsonl": os.path.join(base_dir, "decisions_ledger.jsonl"),
    }


def archive_evening_snapshot(
    output_dir: str = DEFAULT_ANALYTICS_DIR,
    perform_audit: bool = True,
    custom_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executes a comprehensive evening data collection pass across all 5 tracks:
      - Audits live prices and MTM.
      - Saves daily immutable JSON snapshot.
      - Appends to track equity curve CSV.
      - Appends new closed trades to closed_trades_history.csv.
      - Updates active positions table.
      - Appends decision entries to decisions_ledger.jsonl.
    """
    paths = ensure_analytics_dirs(output_dir)
    now_ist = get_ist_now()
    today_str = custom_date or now_ist.strftime("%Y-%m-%d")

    # 1. Audit latest prices & MTM if requested
    if perform_audit:
        logger.info("Executing EOD audit across all 5 tournament tracks...")
        summary = audit_and_update_dual_tracker()
    else:
        summary = compute_dual_summary()

    raw_tracker = _load_tracker()

    # 2. Save daily frozen JSON snapshot
    snapshot_filename = f"snapshot_{today_str}.json"
    snapshot_path = os.path.join(paths["snapshots"], snapshot_filename)
    snapshot_payload = {
        "snapshot_date": today_str,
        "archived_at": now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
        "summary": summary,
        "raw_tracker": raw_tracker,
    }
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(snapshot_payload, f, indent=2, default=str)
    logger.info(f"Saved EOD JSON snapshot -> {snapshot_path}")

    # Track metadata mapping (dynamically sourced from StrategyRegistry)
    from engine.strategies.registry import default_registry
    track_meta = [
        (strat.track_id, strat.key, strat.name)
        for strat in default_registry.all()
    ]

    # 3. Update track_daily_equity.csv
    equity_rows = []
    for track_id, track_key, track_name in track_meta:
        t_data = summary.get(track_key, summary.get(f"track_{track_id}", {}))
        equity_rows.append({
            "date": today_str,
            "track_id": track_id,
            "track_key": track_key,
            "track_name": track_name,
            "available_cash": t_data.get("cash_free", 100000.0),
            "capital_deployed": t_data.get("capital_deployed", 0.0),
            "floating_mtm_inr": t_data.get("floating_pnl_inr", 0.0),
            "realized_pnl_inr": t_data.get("realized_pnl_inr", 0.0),
            "total_net_pnl_inr": t_data.get("total_pnl_inr", 0.0),
            "total_net_pnl_pct": t_data.get("total_pnl_pct", 0.0),
            "roc_on_deployed_pct": t_data.get("roc_deployed_pct", 0.0),
            "open_positions_count": t_data.get("open_count", 0),
            "pending_triggers_count": t_data.get("pending_count", 0),
            "closed_trades_count": t_data.get("closed_count", 0),
            "win_rate": t_data.get("win_rate", 0.0),
            "profit_factor": t_data.get("profit_factor", 1.0),
        })

    _upsert_csv(paths["equity_csv"], equity_rows, key_cols=["date", "track_id"])
    logger.info(f"Updated Track Daily Equity -> {paths['equity_csv']}")

    # 4. Update closed_trades_history.csv
    all_closed_trades = []
    for track_id, track_key, track_name in track_meta:
        t_raw = raw_tracker.get(track_key, {})
        closed_list = t_raw.get("closed_trades", [])
        for c in closed_list:
            all_closed_trades.append({
                "track_id": track_id,
                "track_key": track_key,
                "track_name": track_name,
                "ticker": c.get("ticker", ""),
                "name": c.get("name", c.get("ticker", "").replace(".NS", "")),
                "sector": c.get("sector", "General"),
                "pattern": c.get("pattern", "BREAKOUT"),
                "shortlist_date": c.get("shortlist_date", ""),
                "entry_date": c.get("entry_date", ""),
                "exit_date": c.get("exit_date", today_str),
                "days_held": c.get("days_held", 0),
                "entry_price": float(c.get("entry_price", 0.0)),
                "exit_price": float(c.get("exit_price", 0.0)),
                "shares": int(c.get("shares", c.get("orig_shares", 0))),
                "allocated_rupees": float(c.get("allocated_rupees", 0.0)),
                "net_pnl_inr": float(c.get("net_pnl_inr", 0.0)),
                "net_pnl_pct": float(c.get("net_pnl_pct", 0.0)),
                "friction_inr": float(c.get("friction_inr", 0.0)),
                "exit_reason": c.get("exit_reason", ""),
                "t1_harvested": bool(c.get("t1_harvested", False)),
            })

    if all_closed_trades:
        _upsert_csv(paths["trades_csv"], all_closed_trades, key_cols=["track_id", "ticker", "entry_date", "exit_date", "exit_reason"])
        logger.info(f"Updated Closed Trades History ({len(all_closed_trades)} trades) -> {paths['trades_csv']}")

    # 5. Export active_positions_snapshot.csv
    active_rows = []
    for track_id, track_key, track_name in track_meta:
        t_raw = raw_tracker.get(track_key, {})
        positions = t_raw.get("open_trades", [])
        for p in positions:
            active_rows.append({
                "as_of_date": today_str,
                "track_id": track_id,
                "track_key": track_key,
                "track_name": track_name,
                "ticker": p.get("ticker", ""),
                "name": p.get("name", ""),
                "entry_date": p.get("entry_date", ""),
                "fill_date": p.get("fill_date", ""),
                "entry_price": float(p.get("entry_price", 0.0)),
                "current_price": float(p.get("current_price", 0.0)),
                "target_price": float(p.get("target_price", 0.0)),
                "stop_loss": float(p.get("stop_loss", 0.0)),
                "breakeven_lock": float(p.get("breakeven_lock", 0.0)),
                "is_breakeven_locked": bool(p.get("is_breakeven_locked", False)),
                "shares": int(p.get("shares", 0)),
                "orig_shares": int(p.get("orig_shares", 0)),
                "allocated_rupees": float(p.get("allocated_rupees", 0.0)),
                "pnl_pct": float(p.get("pnl_pct", 0.0)),
                "pnl_rupees": float(p.get("pnl_rupees", 0.0)),
                "days_held": int(p.get("days_held", 0)),
                "pattern": p.get("pattern", ""),
                "sector": p.get("sector", "General"),
            })

    df_pos = pd.DataFrame(active_rows)
    df_pos.to_csv(paths["positions_csv"], index=False)
    logger.info(f"Updated Active Positions Snapshot ({len(active_rows)} open) -> {paths['positions_csv']}")

    # 6. Append audit entries to decisions_ledger.jsonl
    _record_decisions_ledger(paths["ledger_jsonl"], today_str, now_ist, raw_tracker, track_meta)
    logger.info(f"Recorded decisions to ledger -> {paths['ledger_jsonl']}")

    return {
        "status": "SUCCESS",
        "date": today_str,
        "snapshot_path": snapshot_path,
        "paths": paths,
        "summary": summary,
    }


def _record_decisions_ledger(ledger_path: str, today_str: str, now_ist: datetime, raw_tracker: dict, track_meta: list) -> None:
    """Appends structured audit decisions to an immutable JSON Lines ledger."""
    existing_events = set()
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        item = json.loads(line)
                        existing_events.add(item.get("event_hash"))
        except Exception as e:
            logger.debug(f"Ledger read warning: {e}")

    new_entries = []
    ts = now_ist.isoformat()

    for track_id, track_key, track_name in track_meta:
        t_raw = raw_tracker.get(track_key, {})
        
        # 1. Closed Trades Decisions
        for c in t_raw.get("closed_trades", []):
            h_key = f"CLOSE_{track_id}_{c.get('ticker')}_{c.get('entry_date')}_{c.get('exit_date')}_{c.get('exit_reason')}"
            if h_key not in existing_events:
                new_entries.append({
                    "event_hash": h_key,
                    "timestamp": ts,
                    "date": today_str,
                    "track_id": track_id,
                    "track_name": track_name,
                    "event_type": "POSITION_CLOSED",
                    "ticker": c.get("ticker"),
                    "shares": c.get("shares"),
                    "entry_price": c.get("entry_price"),
                    "exit_price": c.get("exit_price"),
                    "net_pnl_inr": c.get("net_pnl_inr"),
                    "net_pnl_pct": c.get("net_pnl_pct"),
                    "exit_reason": c.get("exit_reason"),
                    "friction_inr": c.get("friction_inr"),
                })

        # 2. Open Positions Active Decisions
        for p in t_raw.get("open_trades", []):
            h_key = f"FILL_{track_id}_{p.get('ticker')}_{p.get('fill_date')}"
            if h_key not in existing_events:
                new_entries.append({
                    "event_hash": h_key,
                    "timestamp": ts,
                    "date": today_str,
                    "track_id": track_id,
                    "track_name": track_name,
                    "event_type": "BREAKOUT_TRIGGERED_ACTIVE",
                    "ticker": p.get("ticker"),
                    "shares": p.get("shares"),
                    "entry_price": p.get("entry_price"),
                    "target_price": p.get("target_price"),
                    "stop_loss": p.get("stop_loss"),
                    "breakeven_lock": p.get("breakeven_lock"),
                    "pattern": p.get("pattern"),
                    "sector": p.get("sector"),
                })

        # 3. Aborted Trades Decisions
        for a in t_raw.get("aborted_trades", []):
            h_key = f"ABORT_{track_id}_{a.get('ticker')}_{a.get('abort_date', today_str)}_{a.get('reason', '')}"
            if h_key not in existing_events:
                new_entries.append({
                    "event_hash": h_key,
                    "timestamp": ts,
                    "date": today_str,
                    "track_id": track_id,
                    "track_name": track_name,
                    "event_type": "TRADE_ABORTED",
                    "ticker": a.get("ticker"),
                    "abort_price": a.get("abort_price", a.get("open_price", 0.0)),
                    "gap_pct": a.get("gap_pct", 0.0),
                    "reason": a.get("reason", a.get("abort_reason", "")),
                })

        # 4. Pending Shortlisted Radar Decisions
        for pnd in t_raw.get("pending_triggers", []) + t_raw.get("pending_confirmations", []):
            h_key = f"RADAR_{track_id}_{pnd.get('ticker')}_{pnd.get('shortlist_date', today_str)}_{pnd.get('pivot_trigger', 0)}"
            if h_key not in existing_events:
                new_entries.append({
                    "event_hash": h_key,
                    "timestamp": ts,
                    "date": today_str,
                    "track_id": track_id,
                    "track_name": track_name,
                    "event_type": "RADAR_SHORTLIST",
                    "ticker": pnd.get("ticker"),
                    "scan_price": pnd.get("scan_price"),
                    "pivot_trigger": pnd.get("pivot_trigger"),
                    "target_price": pnd.get("target_price"),
                    "stop_loss": pnd.get("stop_loss"),
                    "pattern": pnd.get("pattern"),
                    "sector": pnd.get("sector"),
                })

    if not os.path.exists(ledger_path):
        with open(ledger_path, "w", encoding="utf-8") as f:
            pass

    if new_entries:
        with open(ledger_path, "a", encoding="utf-8") as f:
            for entry in new_entries:
                f.write(json.dumps(entry, default=str) + "\n")


def _upsert_csv(csv_path: str, rows: List[Dict[str, Any]], key_cols: List[str]) -> None:
    """Updates existing rows by key or appends new rows cleanly."""
    if not rows:
        return
    fieldnames = list(rows[0].keys())

    existing_rows = []
    existing_keys = set()
    if os.path.exists(csv_path):
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    k = tuple(str(r.get(c, "")) for c in key_cols)
                    existing_keys.add(k)
                    existing_rows.append(r)
        except Exception as e:
            logger.debug(f"Error reading existing {csv_path}: {e}")

    # Replace existing or append
    rows_map = {tuple(str(r.get(c, "")) for c in key_cols): r for r in rows}
    final_rows = []
    for r in existing_rows:
        k = tuple(str(r.get(c, "")) for c in key_cols)
        if k in rows_map:
            final_rows.append(rows_map.pop(k))
        else:
            final_rows.append(r)
    # Remaining are new rows
    final_rows.extend(rows_map.values())

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in final_rows:
            writer.writerow({k: r.get(k, "") for k in fieldnames})


# ─── Instant EDA Data Loaders ────────────────────────────────────────────────
def load_trades_df(base_dir: str = DEFAULT_ANALYTICS_DIR) -> pd.DataFrame:
    """Loads closed trades history into a clean Pandas DataFrame for statistical EDA."""
    csv_p = os.path.join(base_dir, "closed_trades_history.csv")
    if os.path.exists(csv_p):
        return pd.read_csv(csv_p)
    return pd.DataFrame()


def load_equity_df(base_dir: str = DEFAULT_ANALYTICS_DIR) -> pd.DataFrame:
    """Loads daily track performance into a Pandas DataFrame for equity curve charting."""
    csv_p = os.path.join(base_dir, "track_daily_equity.csv")
    if os.path.exists(csv_p):
        return pd.read_csv(csv_p)
    return pd.DataFrame()


def load_decisions_df(base_dir: str = DEFAULT_ANALYTICS_DIR) -> pd.DataFrame:
    """Loads the decisions ledger into a Pandas DataFrame."""
    jsonl_p = os.path.join(base_dir, "decisions_ledger.jsonl")
    if os.path.exists(jsonl_p):
        records = []
        with open(jsonl_p, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    records.append(json.loads(line))
        return pd.DataFrame(records)
    return pd.DataFrame()


# ─── Scheduled Daemon ────────────────────────────────────────────────────────
def run_evening_daemon(scheduled_time: str = "15:40", poll_interval_sec: int = 60) -> None:
    """
    Runs continuously as a local background daemon.
    Every market trading day, it wakes up at scheduled_time (e.g. 15:40 IST),
    performs the EOD audit, archives all metrics, and sleeps until the next session.
    """
    logger.info(f"🦅 [EVENING ANALYTICS DAEMON ARMED] Scheduled for {scheduled_time} IST every trading day.")
    target_hour, target_min = map(int, scheduled_time.split(":"))
    target_dtime = dtime(target_hour, target_min)

    last_archived_date: Optional[str] = None

    while True:
        try:
            now_ist = get_ist_now()
            today_date = now_ist.date()
            today_str = now_ist.strftime("%Y-%m-%d")
            is_td, day_reason = is_trading_day(today_date)

            if is_td and now_ist.time() >= target_dtime and last_archived_date != today_str:
                logger.info(f"⏰ Reached {scheduled_time} IST on trading day {today_str}. Running automated EOD archiving...")
                res = archive_evening_snapshot()
                last_archived_date = today_str
                print("\n" + "="*70)
                print(f"📊 AUTOMATED EVENING ARCHIVING COMPLETE — {today_str}")
                print(f"Saved snapshot: {res['snapshot_path']}")
                print("="*70 + "\n")
        except Exception as e:
            logger.error(f"Error during evening daemon run: {e}", exc_info=True)

        time.sleep(poll_interval_sec)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TraderAI Evening Analytics & Decisions Archiver")
    parser.add_argument("--run-now", action="store_true", help="Run immediate archiving and export right now")
    parser.add_argument("--daemon", action="store_true", help="Run as continuous daemon waiting for EOD (15:40 IST)")
    parser.add_argument("--time", default="15:40", help="Time of day to run archiving in daemon mode (HH:MM IST)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.daemon:
        run_evening_daemon(scheduled_time=args.time)
    else:
        print("Executing immediate local evening data collection pass...")
        res = archive_evening_snapshot()
        print("\n" + "="*75)
        print("✅ EVENING DATA COLLECTION & LOCAL ARCHIVING COMPLETE")
        print("="*75)
        print(f"📁 JSON Snapshot : {res['snapshot_path']}")
        print(f"📊 Daily Equity  : {res['paths']['equity_csv']}")
        print(f"📜 Closed Trades : {res['paths']['trades_csv']}")
        print(f"💼 Open Positions: {res['paths']['positions_csv']}")
        print(f"🛡️ Audit Ledger  : {res['paths']['ledger_jsonl']}")
        print("="*75 + "\n")
