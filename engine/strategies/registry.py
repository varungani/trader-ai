"""
TraderAI Strategy Registry
Manages active tournament strategies with dynamic plug-and-play registration.
"""
from __future__ import annotations

from typing import Dict, List, Optional
from engine.strategies.base import BaseStrategy
from engine.strategies.implementations import (
    EMABouncePivotStrategy,
    MorningIgnitionStrategy,
    BreakawayBlastStrategy,
    MinerviniVCPStrategy,
    VelocitySniperStrategy,
    ApexCompounderStrategy,
    Conviction2SlotStrategy,
    ApexMonster1SlotStrategy,
    SuperchargedMonthlySwingStrategy,
)


class StrategyRegistry:
    """Registry maintaining active algorithmic strategies for the tournament."""

    def __init__(self):
        self._strategies: Dict[str, BaseStrategy] = {}

    def register(self, strategy: BaseStrategy) -> None:
        self._strategies[strategy.key] = strategy

    def get(self, key: str) -> Optional[BaseStrategy]:
        return self._strategies.get(key)

    def all(self) -> List[BaseStrategy]:
        return list(self._strategies.values())

    @classmethod
    def create_default(cls) -> StrategyRegistry:
        reg = cls()
        # Benchmark Tracks (Tracks 1 - 5)
        reg.register(EMABouncePivotStrategy())
        reg.register(MorningIgnitionStrategy())
        reg.register(BreakawayBlastStrategy())
        reg.register(MinerviniVCPStrategy())
        reg.register(VelocitySniperStrategy())

        # Audited High-Alpha Empirical Compounders (Tracks 6 - 9)
        reg.register(ApexCompounderStrategy())
        reg.register(Conviction2SlotStrategy())
        reg.register(ApexMonster1SlotStrategy())
        reg.register(SuperchargedMonthlySwingStrategy())
        return reg


# Default global instance
default_registry = StrategyRegistry.create_default()
