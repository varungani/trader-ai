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
    HyperDNA1SlotStrategy,
    EDA2SlotDeadCutStrategy,
    DNAMonthlySwingStrategy,
    DNA2SlotHighWinStrategy,
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
        core_classes = [
            EMABouncePivotStrategy,
            MorningIgnitionStrategy,
            BreakawayBlastStrategy,
            MinerviniVCPStrategy,
            VelocitySniperStrategy,
            ApexCompounderStrategy,
            Conviction2SlotStrategy,
            ApexMonster1SlotStrategy,
            SuperchargedMonthlySwingStrategy,
        ]
        # Technique B: Quant EDA Shortlist (Tracks 1 - 9, primary keys preserved)
        for strat_cls in core_classes:
            reg.register(strat_cls(legacy_mode=False))

        # Technique A: Legacy Shortlist Twins (Tracks 1A - 9A, 100% Telegram-muted A/B benchmarks)
        for strat_cls in core_classes:
            reg.register(strat_cls(legacy_mode=True))

        # Technique C: Part-A DNA, Dip/Runaway GTT Hygiene, EP & Day-10 Challengers (Tracks 10 - 13, Muted)
        for challenger_cls in (
            HyperDNA1SlotStrategy,
            EDA2SlotDeadCutStrategy,
            DNAMonthlySwingStrategy,
            DNA2SlotHighWinStrategy,
        ):
            reg.register(challenger_cls(legacy_mode=False))

        return reg


# Default global instance
default_registry = StrategyRegistry.create_default()
