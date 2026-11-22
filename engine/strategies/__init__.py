"""TraderAI Strategies Package"""
from engine.strategies.base import BaseStrategy, can_trigger_breakout
from engine.strategies.implementations import (
    EMABouncePivotStrategy,
    MorningIgnitionStrategy,
    BreakawayBlastStrategy,
    MinerviniVCPStrategy,
    VelocitySniperStrategy,
)
from engine.strategies.registry import StrategyRegistry, default_registry

__all__ = [
    "BaseStrategy",
    "can_trigger_breakout",
    "EMABouncePivotStrategy",
    "MorningIgnitionStrategy",
    "BreakawayBlastStrategy",
    "MinerviniVCPStrategy",
    "VelocitySniperStrategy",
    "StrategyRegistry",
    "default_registry",
]
