"""
TraderAI - Unified Trade Policy (Single Source of Truth)
Defines all trade rules, stop-losses, profit targets, time exits, and resolution precedence.
Consumed identically by:
  - engine/recommender.py (Live recommendation engine)
  - engine/validator.py (Forward-testing validation engine)
  - engine/paper_week.py (Simulated weekly paper portfolio)
  - backtesting/engine.py (Historical backtest simulator)
  - app.py (Dashboard display and GTT tracker)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Literal

logger = logging.getLogger(__name__)

POLICY_VERSION = "3.0.0-apex-super-mover"

# Pure Swing & Performing Runner Constraints (Max 1 Month Holding Period)
DEFAULT_MIN_REWARD_RISK = 2.0  # Minimum 2:1 Reward-to-Risk ratio required for BUY
HARD_STOP_LOSS_PCT = 7.0       # Hard stop-loss ceiling (7.0% Daily Close planned stop risk)
DEFAULT_TARGET_PCT = 20.0      # High-velocity monster swing target (+20.0%)
BASE_HOLDING_DAYS = 21         # Standard swing trading window (Strict 1-Month / 21 sessions)
MAX_RUNNER_HOLDING_DAYS = 21   # Strict 1-Month Maximum Holding Ceiling (21 market sessions / ~30 calendar days)
FAST_STAGNATION_DAYS = 8       # Fast capital recycling if stock flat (+/- 1.5% in 8 sessions)
MIN_ATR_STOP_PCT = 4.5         # Minimum dynamic stop (tight 4.5% on calm large caps)
MAX_ATR_STOP_PCT = 7.0         # Maximum dynamic stop (capped at 7.0%)


@dataclass
class TradeExitLevels:
    entry_price: float
    stop_loss: float
    target_price: float                 # Base Target (T1: +15% to +18%)
    stop_loss_pct: float
    target_pct: float
    reward_risk: float
    breakeven_price: float = 0.0        # +1R Level
    partial_target_price: float = 0.0   # +1.5R Level
    extended_target_price: float = 0.0  # T2 Extended Target (+25% to +35%)
    runner_target_price: float = 0.0    # T3 Multi-Bagger Runner (+50%+)
    extended_target_pct: float = 30.0   # T2 Extended Target %
    runner_target_pct: float = 50.0     # T3 Multi-Bagger Runner %
    time_stop_days: int = BASE_HOLDING_DAYS
    max_runner_days: int = MAX_RUNNER_HOLDING_DAYS
    policy_version: str = POLICY_VERSION


def calculate_trade_levels(
    entry_price: float,
    atr: Optional[float] = None,
    preferred_target_pct: float = DEFAULT_TARGET_PCT,
    timeframe: str = "short_term",
    is_monster_runner: bool = False,
) -> TradeExitLevels:
    """
    Calculate unified dynamic ATR-based stop-loss, breakeven ratchet, and tiered profit targets:
      - T1 Base Target: +15% to +18% (High-velocity swing target)
      - T2 Extended Target: +30% to +35% (Momentum continuation)
      - T3 Multi-Bagger Runner: +50%+ (Catalyst & breakout runners with 10 EMA trailing stop)
    """
    entry_px = float(entry_price or 0.0)
    if entry_px <= 0:
        return TradeExitLevels(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    # Calculate stop loss percentage based on volatility
    if atr and atr > 0:
        atr_pct = (atr / entry_px) * 100.0
        # Dynamic ATR stop: 1.8 * ATR bounded between 4.5% and 7.0%
        stop_pct = round(min(MAX_ATR_STOP_PCT, max(MIN_ATR_STOP_PCT, atr_pct * 1.8)), 2)
    else:
        # Default standard delivery planned stop
        stop_pct = 7.0

    # Target percentage: Aiming for 20.0% explosive 1-month targets
    min_required_target = round(stop_pct * (2.5 if is_monster_runner else DEFAULT_MIN_REWARD_RISK), 2)
    target_pct = max(preferred_target_pct if not is_monster_runner else 20.0, max(20.0, min_required_target))

    stop_loss_price = round(entry_px * (1.0 - (stop_pct / 100.0)), 2)
    target_price = round(entry_px * (1.0 + (target_pct / 100.0)), 2)
    rr_ratio = round((target_price - entry_px) / (entry_px - stop_loss_price), 2) if entry_px > stop_loss_price else 2.0

    # Risk in Rupees (1R)
    one_r = entry_px - stop_loss_price
    breakeven_px = round(entry_px + one_r, 2)
    partial_target_px = round(entry_px + (1.5 * one_r), 2)

    # Tiered Targets for letting winners run (Convexity)
    extended_target_pct = 35.0 if is_monster_runner else round(max(25.0, target_pct * 1.8), 1)
    runner_target_pct = 50.0 if is_monster_runner else round(max(40.0, target_pct * 3.0), 1)
    extended_target_px = round(entry_px * (1.0 + (extended_target_pct / 100.0)), 2)
    runner_target_px = round(entry_px * (1.0 + (runner_target_pct / 100.0)), 2)

    holding_limit = MAX_RUNNER_HOLDING_DAYS if is_monster_runner else BASE_HOLDING_DAYS

    return TradeExitLevels(
        entry_price=round(entry_px, 2),
        stop_loss=stop_loss_price,
        target_price=target_price,
        stop_loss_pct=stop_pct,
        target_pct=target_pct,
        reward_risk=rr_ratio,
        breakeven_price=breakeven_px,
        partial_target_price=partial_target_px,
        extended_target_price=extended_target_px,
        runner_target_price=runner_target_px,
        extended_target_pct=extended_target_pct,
        runner_target_pct=runner_target_pct,
        time_stop_days=holding_limit,
        max_runner_days=MAX_RUNNER_HOLDING_DAYS,
        policy_version=POLICY_VERSION,
    )


@dataclass
class TradeResolution:
    is_closed: bool
    exit_reason: Optional[str]
    exit_price: float
    pnl_pct: float
    days_held: int
    is_partial_booked: bool = False
    effective_stop: float = 0.0
    is_runner: bool = False


def evaluate_trade_exit(
    entry_price: float,
    current_price: float,
    stop_loss: float,
    target_price: float,
    days_held: int,
    high_price: Optional[float] = None,
    low_price: Optional[float] = None,
    peak_price: Optional[float] = None,
    atr: Optional[float] = None,
    partial_booked: bool = False,
    allow_runner: bool = False,
    is_runner: bool = False,
    use_close_for_stops: bool = True,
) -> TradeResolution:
    """
    Unified Trade Exit Evaluation with Dynamic Exits & Uncapped Runner Mode:
    1. Daily-Close Stop-Loss Protection (Prevents intraday wick sweeps in Cash CNC delivery)
    2. Dynamic Breakeven & ATR Trailing Stop on verified runners
    3. Target Hit (+20% impulse moves)
    4. Strict 1-Month Window Expiry (Session 21 / 1 Month Maximum)
    """
    entry_px = float(entry_price or 0.0)
    cur_px = float(current_price or 0.0)
    base_sl_px = float(stop_loss or 0.0)
    tp_px = float(target_price or 0.0)

    if entry_px <= 0 or cur_px <= 0:
        return TradeResolution(False, None, cur_px, 0.0, days_held)

    worst_price = low_price if low_price is not None else cur_px
    best_price = high_price if high_price is not None else cur_px
    peak_px = max(peak_price or entry_px, best_price)

    # Dynamic Stop Management
    initial_risk = entry_px - base_sl_px
    effective_stop = base_sl_px

    # In Runner Mode ONLY (after base target T1 has already been reached):
    # Lock in at least +8% profit floor and trail with 2.0x ATR behind peak
    active_runner = is_runner
    if allow_runner and best_price >= tp_px:
        active_runner = True
        effective_stop = max(effective_stop, round(entry_px * 1.08, 2))
        if atr and atr > 0:
            effective_stop = max(effective_stop, round(peak_px - (2.0 * atr), 2))

    # Priority 1: Stop-Loss (Protection)
    stop_triggered = False
    exit_fill = cur_px
    if use_close_for_stops:
        if cur_px <= effective_stop:
            stop_triggered = True
            exit_fill = cur_px
        elif worst_price <= (effective_stop * 0.96): # Catastrophic intraday crash protection
            stop_triggered = True
            exit_fill = worst_price
    else:
        if worst_price <= effective_stop:
            stop_triggered = True
            exit_fill = min(effective_stop, worst_price)

    if stop_triggered:
        pnl = round(((exit_fill - entry_px) / entry_px) * 100.0, 2)
        if active_runner:
            reason = f"RUNNER_TRAILING_STOP_HIT (+{pnl}%)"
        elif effective_stop > base_sl_px:
            reason = f"TRAILING_STOP_HIT (+{pnl}%)" if pnl >= 0 else f"BREAKEVEN_STOP_HIT ({pnl}%)"
        else:
            reason = f"STOP_LOSS_HIT ({pnl}%)"
        return TradeResolution(
            is_closed=True,
            exit_reason=reason,
            exit_price=exit_fill,
            pnl_pct=pnl,
            days_held=days_held,
            is_partial_booked=partial_booked,
            effective_stop=effective_stop,
            is_runner=active_runner,
        )

    # Priority 2: Target Hit (If not in runner mode, close out)
    if not allow_runner and best_price >= tp_px:
        exit_fill = tp_px
        pnl = round(((exit_fill - entry_px) / entry_px) * 100.0, 2)
        return TradeResolution(
            is_closed=True,
            exit_reason=f"TARGET_HIT (+{round((tp_px - entry_px)/entry_px*100, 1)}%)",
            exit_price=exit_fill,
            pnl_pct=pnl,
            days_held=days_held,
            is_partial_booked=True,
            effective_stop=effective_stop,
            is_runner=False,
        )

    gain_pct = round(((cur_px - entry_px) / entry_px) * 100.0, 2)

    # Priority 3: Momentum Stagnation Exit (Session 8 exit if trade is stagnant between -1.5% and +1.5%)
    # Recycles capital 2x faster to deploy into active high-momentum breakout runners
    if days_held >= FAST_STAGNATION_DAYS and -1.5 <= gain_pct <= 1.5 and not active_runner:
        return TradeResolution(
            is_closed=True,
            exit_reason=f"MOMENTUM_STAGNATION_EXIT ({FAST_STAGNATION_DAYS} Sessions, {gain_pct:+.2f}%)",
            exit_price=cur_px,
            pnl_pct=gain_pct,
            days_held=days_held,
            is_partial_booked=partial_booked,
            effective_stop=effective_stop,
            is_runner=False,
        )

    # Priority 4: Dynamic Time Expiry (15 Sessions baseline, capped strictly at 21 Sessions / 1 Month maximum)
    is_performing = bool(gain_pct >= 5.0 or (active_runner and cur_px > entry_px * 1.05))
    max_days = MAX_RUNNER_HOLDING_DAYS if is_performing else BASE_HOLDING_DAYS
    if days_held >= max_days:
        reason_label = (
            f"MAX_1_MONTH_HOLD_EXPIRED ({MAX_RUNNER_HOLDING_DAYS} Sessions / 1 Month, {gain_pct:+.2f}%)"
            if is_performing
            else f"SWING_TIME_EXPIRED ({BASE_HOLDING_DAYS} Sessions, {gain_pct:+.2f}%)"
        )
        return TradeResolution(
            is_closed=True,
            exit_reason=reason_label,
            exit_price=cur_px,
            pnl_pct=gain_pct,
            days_held=days_held,
            is_partial_booked=partial_booked,
            effective_stop=effective_stop,
            is_runner=active_runner,
        )

    # Check Partial Profit Hit (+1.5R)
    has_hit_partial = partial_booked
    if not has_hit_partial and initial_risk > 0 and best_price >= (entry_px + (1.5 * initial_risk)):
        has_hit_partial = True

    # Position remains open
    pnl = round(((cur_px - entry_px) / entry_px) * 100.0, 2)
    return TradeResolution(
        is_closed=False,
        exit_reason="RUNNER_ACTIVE (Trailing Stop)" if active_runner else ("PARTIAL_PROFIT_BOOKED (+1.5R)" if (has_hit_partial and not partial_booked) else None),
        exit_price=cur_px,
        pnl_pct=pnl,
        days_held=days_held,
        is_partial_booked=has_hit_partial,
        effective_stop=effective_stop,
        is_runner=active_runner,
    )
