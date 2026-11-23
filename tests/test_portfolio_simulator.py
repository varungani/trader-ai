"""
tests/test_portfolio_simulator.py

Unit tests for the Modular, Object-Oriented PortfolioSimulator Engine.
"""

import pytest
import pandas as pd
import numpy as np
from engine.analytics.simulator import (
    PortfolioSimulator,
    SimulationConfig,
    SimulationResult,
    SimulationPosition,
    SimulationTrade,
)


def test_statutory_costs_calculation():
    sim = PortfolioSimulator()
    # Buy ₹100,000 worth of shares
    buy_costs = sim.compute_statutory_costs(100000.0, is_buy=True)
    # Buy: STT=0, Stamp=15, Turnover=3.45, Brokerage=20, GST=(20+3.45)*0.18=4.22, DP=0 -> ~42.67
    assert 40.0 < buy_costs < 50.0

    # Sell ₹100,000 worth of shares
    sell_costs = sim.compute_statutory_costs(100000.0, is_buy=False)
    # Sell: STT=100, Stamp=0, Turnover=3.45, Brokerage=20, GST=4.22, DP=15.93 -> ~143.60
    assert 140.0 < sell_costs < 150.0


def test_simulation_config_defaults():
    cfg = SimulationConfig()
    assert cfg.starting_cash == 100000.0
    assert cfg.max_slots == 3
    assert cfg.slot_allocations == [0.40, 0.30, 0.30]
    assert cfg.hard_stop_loss_pct == 0.07
    assert cfg.enable_pyramiding is True
    assert cfg.use_weekly_10w_trail is True


def test_simulation_trade_to_dict():
    trade = SimulationTrade(
        symbol="RELIANCE.NS",
        entry_date=pd.Timestamp("2026-01-01"),
        exit_date=pd.Timestamp("2026-02-01"),
        entry_price=2000.0,
        exit_price=2400.0,
        shares=10,
        capital_invested=20000.0,
        borrowed_capital=0.0,
        gross_pnl_inr=4000.0,
        friction_inr=50.0,
        net_pnl_inr=3950.0,
        net_pnl_pct=19.75,
        days_held=21,
        pyramids=0,
        exit_reason="WEEKLY_10W_EMA_TRAIL",
    )
    d = trade.to_dict()
    assert d["symbol"] == "RELIANCE.NS"
    assert d["net_pnl_inr"] == 3950.0
    assert d["net_pnl_pct"] == 19.75
    assert d["exit_reason"] == "WEEKLY_10W_EMA_TRAIL"
