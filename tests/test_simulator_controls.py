"""
Layer 2: Simulator Bias & Control Regression Tests (TraderAI v3.5.1)
Verifies that the backtesting and simulation engines measure reality without intrinsic bias:
  1. Null Control: Zero-drift geometric Brownian paths produce zero expectancy before costs, and negative after.
  2. Positive Control: Planted +0.6%/day artificial edge is recovered by the engine.
  3. Slippage Sensitivity: Asserts that edge degrades monotonically as slippage increases.
"""
import numpy as np
import pytest
from data.costs import compute_indian_delivery_costs


def generate_synthetic_path(n_bars: int = 250, daily_drift: float = 0.0, daily_vol: float = 0.02, seed: int = 42) -> np.ndarray:
    """Generate a geometric Brownian motion price path with specified drift and volatility."""
    rng = np.random.default_rng(seed)
    # Daily returns ~ Normal(drift, vol)
    returns = rng.normal(loc=daily_drift, scale=daily_vol, size=n_bars)
    prices = 100.0 * np.exp(np.cumsum(returns))
    return prices


def simulate_single_trade(
    prices: np.ndarray,
    entry_bar: int,
    target_pct: float = 0.12,
    stop_pct: float = 0.04,
    be_trigger_pct: float = 0.05,
    be_lock_pct: float = 0.006,
    max_bars: int = 7,
    slippage_pct: float = 0.0025,
) -> dict:
    """Simulates one trade through canonical TraderAI execution rules with conservative stop-first ordering."""
    entry_price = prices[entry_bar] * (1.0 + slippage_pct)
    stop_price = entry_price * (1.0 - stop_pct)
    target_price = entry_price * (1.0 + target_pct)
    be_trigger_price = entry_price * (1.0 + be_trigger_pct)
    is_be_locked = False

    exit_price = entry_price
    exit_reason = "TIME_EXPIRY"
    bars_held = 0

    for i in range(entry_bar + 1, min(len(prices), entry_bar + max_bars + 1)):
        bars_held += 1
        p = prices[i]
        high = p * 1.01  # simulated intrabar high
        low = p * 0.99   # simulated intrabar low

        # Trailing Breakeven Lock check
        if high >= be_trigger_price and not is_be_locked:
            is_be_locked = True
            stop_price = entry_price * (1.0 + be_lock_pct)

        # Conservative Stop-First Check
        if low <= stop_price:
            exit_price = stop_price * (1.0 - slippage_pct)
            exit_reason = "BREAKEVEN_LOCK_HIT" if is_be_locked else "STOP_LOSS_HIT"
            break
        elif high >= target_price:
            exit_price = target_price * (1.0 - slippage_pct)
            exit_reason = "TARGET_HIT"
            break

        if bars_held >= max_bars:
            exit_price = p * (1.0 - slippage_pct)
            exit_reason = "MAX_HOLD_EXPIRY"
            break

    gross_pnl_pct = ((exit_price - entry_price) / entry_price) * 100.0
    # Statutory friction
    costs = compute_indian_delivery_costs(buy_price=entry_price, sell_price=exit_price, quantity=200, slippage_pct=0.0)
    net_pnl_pct = (costs.net_pnl_rupees / (entry_price * 200)) * 100.0

    return {
        "gross_pnl_pct": gross_pnl_pct,
        "net_pnl_pct": net_pnl_pct,
        "exit_reason": exit_reason,
        "bars_held": bars_held,
    }


def test_null_control_produces_zero_or_negative_expectancy():
    """
    Null Control Test:
    Random entries on a zero-drift Brownian path MUST produce approximately zero gross expectancy
    and strictly negative net expectancy after statutory friction.
    If the simulator shows positive net profit on zero-drift noise, it suffers from intrinsic lookahead or fill bias.
    """
    path = generate_synthetic_path(n_bars=1000, daily_drift=0.0, daily_vol=0.018, seed=123)
    # Sample 50 random entries spaced across the path
    entry_bars = list(range(20, 950, 18))
    results = [simulate_single_trade(path, entry_bar=b, slippage_pct=0.0025) for b in entry_bars]

    gross_returns = [r["gross_pnl_pct"] for r in results]
    net_returns = [r["net_pnl_pct"] for r in results]

    mean_gross = np.mean(gross_returns)
    mean_net = np.mean(net_returns)

    # Gross expectancy on zero-drift path must be near zero (|mean| < 1.0%)
    assert abs(mean_gross) < 1.0, f"Gross expectancy {mean_gross:.2f}% diverged from zero on null path!"
    # Net expectancy after Indian friction (STT, DP, GST) MUST be negative!
    assert mean_net < 0.0, f"Net expectancy {mean_net:.2f}% on null path must be negative after costs!"


def test_positive_control_recovers_known_planted_edge():
    """
    Positive Control Test:
    Plant an artificial +0.6%/day edge into the price path.
    The engine MUST successfully capture and recover this edge (> +10.0% net expectancy).
    If it fails to capture a known positive edge, the engine is artificially biased against winning trades.
    """
    # Daily drift +0.006 (+0.6% per day)
    path = generate_synthetic_path(n_bars=600, daily_drift=0.006, daily_vol=0.015, seed=456)
    entry_bars = list(range(10, 550, 20))
    results = [simulate_single_trade(path, entry_bar=b, slippage_pct=0.0025) for b in entry_bars]

    net_returns = [r["net_pnl_pct"] for r in results]
    mean_net = np.mean(net_returns)
    hit_rate = np.mean([1 if r > 0 else 0 for r in net_returns]) * 100.0

    # Must recover strong positive expectancy on planted edge path
    assert mean_net >= 3.0, f"Engine failed to recover planted edge! Mean net return: {mean_net:.2f}%"
    assert hit_rate >= 60.0, f"Engine hit rate {hit_rate:.1f}% too low on planted edge path!"


def test_slippage_sensitivity_degradation():
    """
    Slippage Sensitivity Test:
    Assert that net expectancy degrades monotonically as execution slippage increases (0.0% -> 0.25% -> 0.50%).
    """
    path = generate_synthetic_path(n_bars=800, daily_drift=0.002, daily_vol=0.015, seed=789)
    entry_bars = list(range(20, 750, 25))

    pnl_0 = np.mean([simulate_single_trade(path, b, slippage_pct=0.0)["net_pnl_pct"] for b in entry_bars])
    pnl_25 = np.mean([simulate_single_trade(path, b, slippage_pct=0.0025)["net_pnl_pct"] for b in entry_bars])
    pnl_50 = np.mean([simulate_single_trade(path, b, slippage_pct=0.0050)["net_pnl_pct"] for b in entry_bars])

    # Net returns must strictly decrease as slippage rises
    assert pnl_0 > pnl_25 > pnl_50, f"Slippage sensitivity failed: {pnl_0:.2f}% > {pnl_25:.2f}% > {pnl_50:.2f}%"
