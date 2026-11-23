"""
TraderAI Local Analytics & Evening Archiving Package
"""
from engine.analytics.evening_collector import (
    ensure_analytics_dirs,
    archive_evening_snapshot,
    load_trades_df,
    load_equity_df,
    load_decisions_df,
)
from engine.analytics.simulator import PortfolioSimulator, SimulationConfig, SimulationResult, SimulationPosition, SimulationTrade

__all__ = [
    "run_evening_pipeline",
    "load_trades_df",
    "load_equity_df",
    "PortfolioSimulator",
    "SimulationConfig",
    "SimulationResult",
    "SimulationPosition",
    "SimulationTrade",
]
