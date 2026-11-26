"""
TraderAI Tournament Execution Service
Orchestrates multi-strategy portfolio accounts, automated audits,
state persistence, and summary analytics.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional, Callable

from engine.domain.models import PortfolioAccount
from engine.strategies.registry import StrategyRegistry, default_registry
from data.market_calendar import get_ist_now, is_trading_day

logger = logging.getLogger(__name__)


class TournamentService:
    """Service managing the live tournament across all registered algorithmic tracks."""

    def __init__(self, registry: Optional[StrategyRegistry] = None):
        self.registry = registry or default_registry
        self.accounts: Dict[str, PortfolioAccount] = {}
        self.updated_at: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.created_at: str = self.updated_at
        self.extra_meta: Dict[str, Any] = {}

    def initialize_default(self) -> None:
        """Initializes empty accounts for all registered strategies."""
        self.accounts.clear()
        for strat in self.registry.all():
            self.accounts[strat.key] = PortfolioAccount(
                name=strat.name,
                description=strat.description,
                capital=100000.0,
                max_slots=getattr(strat, "max_slots", 5),
                slot_capital=strat.slot_capital,
            )

    def load_from_dict(self, data: Dict[str, Any]) -> None:
        """Loads accounts from dictionary structure while preserving top-level metadata."""
        self.updated_at = data.get("updated_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.created_at = data.get("created_at", self.updated_at)
        for meta_key in ("alerted_buy_signals", "daily_recap_sent_date"):
            if meta_key in data and data[meta_key] is not None:
                self.extra_meta[meta_key] = data[meta_key]
        for strat in self.registry.all():
            strat_data = data.get(strat.key)
            if strat_data:
                account = PortfolioAccount.from_dict(strat_data)
                account.name = strat.name
                account.description = strat.description
                account.max_slots = getattr(strat, "max_slots", getattr(account, "max_slots", 5))
                account.slot_capital = strat.slot_capital
                self.accounts[strat.key] = account
            else:
                self.accounts[strat.key] = PortfolioAccount(
                    name=strat.name,
                    description=strat.description,
                    capital=100000.0,
                    max_slots=getattr(strat, "max_slots", 5),
                    slot_capital=strat.slot_capital,
                )

    def to_dict(self) -> Dict[str, Any]:
        """Serializes tournament state to dictionary."""
        d: Dict[str, Any] = {
            "created_at": getattr(self, "created_at", self.updated_at),
            "updated_at": self.updated_at,
        }
        d.update(self.extra_meta)
        for strat in self.registry.all():
            account = self.accounts.get(strat.key)
            if account:
                d[strat.key] = account.to_dict()
        return d

    def save_to_files(self, primary_file: str) -> None:
        """Persists primary tournament file and syncs dedicated per-algo state files."""
        self.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data = self.to_dict()

        os.makedirs(os.path.dirname(primary_file), exist_ok=True)
        with open(primary_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

        # Conflict-free individual state file sync (all 9 primary + 9 legacy twins)
        legacy_filename_map = {
            "option_3": "track_algo1_ignition.json",
            "option_2": "track_algo2_vcp.json",
            "track_c": "track_algo3_velocity.json",
            "track_algo4": "track_algo4_ema_bounce.json",
            "track_algo5": "track_algo5_rs_blast.json",
            "track_apex_compounder": "track_apex_compounder.json",
            "track_conviction_2slot": "track_conviction_2slot.json",
            "track_apex_1slot": "track_apex_1slot.json",
            "track_monthly_swing": "track_monthly_swing.json",
        }
        base_dir = os.path.dirname(primary_file)
        for strat in self.registry.all():
            content = data.get(strat.key, {})
            if not content:
                continue
            fname = legacy_filename_map.get(strat.key, f"track_{strat.key}.json")
            p = os.path.join(base_dir, fname)
            try:
                with open(p, "w", encoding="utf-8") as f:
                    json.dump({"updated_at": self.updated_at, "track": content}, f, indent=2, default=str)
            except Exception as e:
                logger.debug(f"Error saving {fname}: {e}")

    def log_today_picks(
        self,
        tier1_picks: list[dict],
        tier2_radar: list[dict],
        dna_candidates: Optional[list[dict]] = None,
    ) -> None:
        """Route shortlisted radar & picks to all registered strategies."""
        now = get_ist_now()
        today_str = now.strftime("%Y-%m-%d")
        is_td, _ = is_trading_day(now.date())
        now_time = now.time()

        dna_radar = list(dna_candidates or []) + [
            r for r in tier2_radar
            if r.get("ticker") not in {d.get("ticker") for d in (dna_candidates or [])}
        ]
        for strat in self.registry.all():
            account = self.accounts.get(strat.key)
            if account:
                t2_input = dna_radar if (dna_candidates and getattr(strat, "shortlist_mode", "") == "dna") else tier2_radar
                strat.log_picks(account, tier1_picks, t2_input, today_str, is_td, now_time)

    def audit_all(self, force_market_open: bool = False, alert_callback: Optional[Callable[..., Any]] = None) -> None:
        """Run audit across all registered strategies."""
        now = get_ist_now()
        today = now.date()
        today_str = now.strftime("%Y-%m-%d")

        for strat in self.registry.all():
            account = self.accounts.get(strat.key)
            if account:
                strat.audit(account, today_str, today, force_market_open, alert_callback)

    def compute_summary(self) -> Dict[str, Any]:
        """Compute performance stats, win-rates, profit factors, and determine current tournament leader."""
        def _stats(account: PortfolioAccount) -> Dict[str, Any]:
            opens = [p.to_dict() for p in account.positions]
            closed = account.closed_trades
            aborted = account.aborted_trades
            pending = [t.to_dict() for t in account.pending_triggers]
            pending_conf = [t.to_dict() for t in account.pending_confirmations]
            total_pending = len(pending) + len(pending_conf)

            floating_pnl = sum(p.pnl_rupees for p in account.positions)
            realized_partial = sum(p.realized_pnl_inr for p in account.positions)
            realized_closed = sum(float(t.get("net_pnl_inr", 0.0)) for t in closed)
            realized_pnl = round(realized_closed + realized_partial, 2)
            total_pnl = round(floating_pnl + realized_pnl, 2)

            wins = [t for t in closed if float(t.get("net_pnl_inr", 0.0)) > 0]
            losses = [t for t in closed if float(t.get("net_pnl_inr", 0.0)) <= 0]
            win_rate = round(len(wins) / len(closed) * 100.0, 1) if closed else 0.0

            gross_profit = sum(float(t.get("net_pnl_inr", 0.0)) for t in wins) + realized_partial
            gross_loss = abs(sum(float(t.get("net_pnl_inr", 0.0)) for t in losses))
            pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 1.0)

            deployed = sum(p.allocated_rupees for p in account.positions)
            roc_deployed = round(total_pnl / deployed * 100.0, 2) if deployed > 0 else 0.0

            return {
                "name": account.name,
                "description": account.description,
                "open_count": len(opens),
                "closed_count": len(closed),
                "pending_count": total_pending,
                "aborted_count": len(aborted),
                "floating_pnl_inr": round(floating_pnl, 2),
                "realized_pnl_inr": realized_pnl,
                "total_pnl_inr": total_pnl,
                "total_pnl_pct": round(total_pnl / account.capital * 100.0, 2),
                "roc_deployed_pct": roc_deployed,
                "win_rate": win_rate,
                "profit_factor": pf,
                "capital_deployed": round(deployed, 2),
                "cash_free": account.get_free_cash(),
                "open_trades": opens,
                "closed_trades": closed,
                "pending_triggers": pending,
                "pending_confirmations": pending_conf,
                "aborted_trades": aborted,
            }

        track_stats = {}
        pnl_scores = []
        total_closed = 0
        for strat in self.registry.all():
            acc = self.accounts.get(strat.key, PortfolioAccount())
            st = _stats(acc)
            track_stats[strat.key] = st
            pnl_scores.append((strat.name, st["total_pnl_inr"]))
            total_closed += st["closed_count"]

        best = max(pnl_scores, key=lambda x: x[1]) if pnl_scores else ("None", 0.0)
        if best[1] != 0:
            if total_closed == 0:
                winner = f"⚖️ Forward-Testing (MTM Leader: {best[0]} at ₹{best[1]:+,.2f})"
            else:
                winner = f"🏆 {best[0]} Leading ({total_closed} closed trades)"
        else:
            winner = "TIE (Evaluating)"

        return {
            "updated_at": self.updated_at,
            "winner": winner,
            "tracks": track_stats,
            # Backward-compatible keys
            "option_2": track_stats.get("option_2", {}),
            "option_3": track_stats.get("option_3", {}),
            "track_c": track_stats.get("track_c", {}),
            "track_algo4": track_stats.get("track_algo4", {}),
            "track_algo5": track_stats.get("track_algo5", {}),
            "track_apex_compounder": track_stats.get("track_apex_compounder", {}),
            "track_conviction_2slot": track_stats.get("track_conviction_2slot", {}),
            "track_apex_1slot": track_stats.get("track_apex_1slot", {}),
            "track_monthly_swing": track_stats.get("track_monthly_swing", {}),
            # Numbered track aliases (Group B: Quant EDA Shortlist)
            "track_1": track_stats.get("track_algo4", {}),
            "track_2": track_stats.get("option_3", {}),
            "track_3": track_stats.get("track_algo5", {}),
            "track_4": track_stats.get("option_2", {}),
            "track_5": track_stats.get("track_c", {}),
            "track_6": track_stats.get("track_apex_compounder", {}),
            "track_7": track_stats.get("track_conviction_2slot", {}),
            "track_8": track_stats.get("track_apex_1slot", {}),
            "track_9": track_stats.get("track_monthly_swing", {}),
            # Numbered track aliases (Group A: Legacy Shortlist Twins)
            "track_1_legacy": track_stats.get("track_algo4_legacy", {}),
            "track_2_legacy": track_stats.get("option_3_legacy", {}),
            "track_3_legacy": track_stats.get("track_algo5_legacy", {}),
            "track_4_legacy": track_stats.get("option_2_legacy", {}),
            "track_5_legacy": track_stats.get("track_c_legacy", {}),
            "track_6_legacy": track_stats.get("track_apex_compounder_legacy", {}),
            "track_7_legacy": track_stats.get("track_conviction_2slot_legacy", {}),
            "track_8_legacy": track_stats.get("track_apex_1slot_legacy", {}),
            # Group C Challenger Track Aliases (Tracks 10 - 13)
            "track_10": track_stats.get("track_c_dna_1slot", {}),
            "track_11": track_stats.get("track_c_eda_2slot_10d", {}),
            "track_12": track_stats.get("track_c_dna_monthly", {}),
            "track_13": track_stats.get("track_c_dna_2slot_t1", {}),
        }
