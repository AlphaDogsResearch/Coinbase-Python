"""
Nautilus Trader strategies package.

This package contains Nautilus Trader strategy implementations that can be
used with the NautilusStrategyAdapter to integrate with your system.
"""

# Make strategies easily importable
from engine.strategies.nautilus_strategies.roc_mean_reversion_strategy import (
    ROCMeanReversionStrategy,
    ROCMeanReversionStrategyConfig,
)
from engine.strategies.nautilus_strategies.cci_momentum_strategy import (
    CCIMomentumStrategy,
    CCIMomentumStrategyConfig,
)
from engine.strategies.nautilus_strategies.apo_mean_reversion_strategy import (
    APOMeanReversionStrategy,
    APOMeanReversionStrategyConfig,
)
from engine.strategies.nautilus_strategies.ppo_momentum_strategy import (
    PPOMomentumStrategy,
    PPOMomentumStrategyConfig,
)
from engine.strategies.nautilus_strategies.adx_mean_reversion_strategy import (
    ADXMeanReversionStrategy,
    ADXMeanReversionStrategyConfig,
)

__all__ = [
    "ROCMeanReversionStrategy",
    "ROCMeanReversionStrategyConfig",
    "CCIMomentumStrategy",
    "CCIMomentumStrategyConfig",
    "APOMeanReversionStrategy",
    "APOMeanReversionStrategyConfig",
    "PPOMomentumStrategy",
    "PPOMomentumStrategyConfig",
    "ADXMeanReversionStrategy",
    "ADXMeanReversionStrategyConfig",
]
