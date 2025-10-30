"""
Custom indicators for trading strategies.

This module provides custom indicators that follow proper Nautilus Trader patterns.
All indicators inherit from the base Indicator class and implement required methods.
"""

from nautilus_trader.indicators.base import Indicator
from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.indicators import SimpleMovingAverage
from nautilus_trader.indicators import WeightedMovingAverage
from nautilus_trader.indicators import DoubleExponentialMovingAverage
from nautilus_trader.indicators import DirectionalMovement
from nautilus_trader.model.data import Bar


class APO(Indicator):
    """
    Absolute Price Oscillator (APO) indicator.

    Measures the absolute difference between two moving averages.
    APO = Fast MA - Slow MA

    Parameters
    ----------
    fast_period : int
        The period for the fast moving average.
    slow_period : int
        The period for the slow moving average.
    ma_type : int, default 1
        The type of moving average (0=SMA, 1=EMA, 2=WMA, 3=DEMA).
    """

    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        ma_type: int = 1,
    ):
        # Initialize parent with parameters
        super().__init__(params=[fast_period, slow_period, ma_type])

        self.fast_period = fast_period
        self.slow_period = slow_period
        self.ma_type = ma_type

        # Create moving averages based on type
        if ma_type == 0:  # SMA
            self.fast_ma = SimpleMovingAverage(fast_period)
            self.slow_ma = SimpleMovingAverage(slow_period)
        elif ma_type == 1:  # EMA
            self.fast_ma = ExponentialMovingAverage(fast_period)
            self.slow_ma = ExponentialMovingAverage(slow_period)
        elif ma_type == 2:  # WMA
            self.fast_ma = WeightedMovingAverage(fast_period)
            self.slow_ma = WeightedMovingAverage(slow_period)
        elif ma_type == 3:  # DEMA
            self.fast_ma = DoubleExponentialMovingAverage(fast_period)
            self.slow_ma = DoubleExponentialMovingAverage(slow_period)
        else:
            # Default to EMA
            self.fast_ma = ExponentialMovingAverage(fast_period)
            self.slow_ma = ExponentialMovingAverage(slow_period)

        self.value = 0.0

    @property
    def name(self) -> str:
        """Return the name of the indicator."""
        ma_names = {0: "SMA", 1: "EMA", 2: "WMA", 3: "DEMA"}
        ma_name = ma_names.get(self.ma_type, "EMA")
        return f"APO({self.fast_period},{self.slow_period},{ma_name})"

    def has_inputs(self) -> bool:
        """Return whether the indicator has received any inputs."""
        return self.fast_ma.has_inputs and self.slow_ma.has_inputs

    @property
    def initialized(self) -> bool:
        """Return whether the indicator is fully initialized."""
        return self.fast_ma.initialized and self.slow_ma.initialized

    def handle_bar(self, bar: Bar) -> None:
        """
        Update the indicator with a bar.

        Parameters
        ----------
        bar : Bar
            The bar to update with.
        """
        # Update sub-indicators
        self.fast_ma.handle_bar(bar)
        self.slow_ma.handle_bar(bar)

        # Calculate APO value
        if self.initialized:
            self.value = self.fast_ma.value - self.slow_ma.value

    def _reset(self) -> None:
        """Reset the indicator."""
        self.fast_ma.reset()
        self.slow_ma.reset()
        self.value = 0.0


class PPO(Indicator):
    """
    Percentage Price Oscillator (PPO) indicator.

    Measures the percentage difference between two moving averages.
    PPO = ((Fast MA - Slow MA) / Slow MA) * 100

    Parameters
    ----------
    fast_period : int
        The period for the fast moving average.
    slow_period : int
        The period for the slow moving average.
    ma_type : int, default 1
        The type of moving average (0=SMA, 1=EMA, 2=WMA, 3=DEMA).
    """

    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        ma_type: int = 1,
    ):
        # Initialize parent with parameters
        super().__init__(params=[fast_period, slow_period, ma_type])

        self.fast_period = fast_period
        self.slow_period = slow_period
        self.ma_type = ma_type

        # Create moving averages based on type
        if ma_type == 0:  # SMA
            self.fast_ma = SimpleMovingAverage(fast_period)
            self.slow_ma = SimpleMovingAverage(slow_period)
        elif ma_type == 1:  # EMA
            self.fast_ma = ExponentialMovingAverage(fast_period)
            self.slow_ma = ExponentialMovingAverage(slow_period)
        elif ma_type == 2:  # WMA
            self.fast_ma = WeightedMovingAverage(fast_period)
            self.slow_ma = WeightedMovingAverage(slow_period)
        elif ma_type == 3:  # DEMA
            self.fast_ma = DoubleExponentialMovingAverage(fast_period)
            self.slow_ma = DoubleExponentialMovingAverage(slow_period)
        else:
            # Default to EMA
            self.fast_ma = ExponentialMovingAverage(fast_period)
            self.slow_ma = ExponentialMovingAverage(slow_period)

        self.value = 0.0

    @property
    def name(self) -> str:
        """Return the name of the indicator."""
        ma_names = {0: "SMA", 1: "EMA", 2: "WMA", 3: "DEMA"}
        ma_name = ma_names.get(self.ma_type, "EMA")
        return f"PPO({self.fast_period},{self.slow_period},{ma_name})"

    def has_inputs(self) -> bool:
        """Return whether the indicator has received any inputs."""
        return self.fast_ma.has_inputs and self.slow_ma.has_inputs

    @property
    def initialized(self) -> bool:
        """Return whether the indicator is fully initialized."""
        return self.fast_ma.initialized and self.slow_ma.initialized

    def handle_bar(self, bar: Bar) -> None:
        """
        Update the indicator with a bar.

        Parameters
        ----------
        bar : Bar
            The bar to update with.
        """
        # Update sub-indicators
        self.fast_ma.handle_bar(bar)
        self.slow_ma.handle_bar(bar)

        # Calculate PPO value
        if self.initialized and self.slow_ma.value != 0:
            self.value = ((self.fast_ma.value - self.slow_ma.value) / self.slow_ma.value) * 100
        else:
            self.value = 0.0

    def _reset(self) -> None:
        """Reset the indicator."""
        self.fast_ma.reset()
        self.slow_ma.reset()
        self.value = 0.0


class ADX(Indicator):
    """
    Average Directional Index (ADX) indicator.

    Wraps Nautilus DirectionalMovement and adds proper ADX calculation.

    The ADX measures trend strength (not direction):
    - ADX < 25: Weak or absent trend
    - ADX 25-50: Strong trend
    - ADX > 50: Very strong trend

    Parameters
    ----------
    period : int
        The period for the ADX calculation.
    """

    def __init__(self, period: int = 14):
        super().__init__(params=[period])

        self.period = period
        self._dm = DirectionalMovement(period)
        self._dx_values = []
        self._adx_value = 0.0
        self._previous_adx = 0.0

        # Smoothing factor for ADX (Wilder's smoothing)
        self._alpha = 1.0 / period

    @property
    def name(self) -> str:
        """Return the name of the indicator."""
        return f"ADX({self.period})"

    @property
    def pos(self) -> float:
        """Return +DI value."""
        return self._dm.pos

    @property
    def neg(self) -> float:
        """Return -DI value."""
        return self._dm.neg

    @property
    def value(self) -> float:
        """Return ADX value."""
        return self._adx_value

    def has_inputs(self) -> bool:
        """Return whether the indicator has received any inputs."""
        return self._dm.has_inputs

    @property
    def initialized(self) -> bool:
        """Return whether the indicator is fully initialized."""
        # Need enough DX values to calculate initial ADX
        return self._dm.initialized and len(self._dx_values) >= self.period

    def handle_bar(self, bar: Bar) -> None:
        """
        Update the indicator with a bar.

        Parameters
        ----------
        bar : Bar
            The bar to update with.
        """
        # Update underlying DirectionalMovement
        self._dm.handle_bar(bar)

        if not self._dm.initialized:
            return

        # Calculate DX (Directional Index)
        plus_di = self._dm.pos
        minus_di = self._dm.neg

        di_sum = plus_di + minus_di
        if di_sum > 0:
            dx = abs(plus_di - minus_di) / di_sum * 100.0
        else:
            dx = 0.0

        self._dx_values.append(dx)

        # Calculate ADX once we have enough DX values
        if len(self._dx_values) == self.period:
            # Initial ADX is simple average of first 'period' DX values
            self._adx_value = sum(self._dx_values) / self.period
        elif len(self._dx_values) > self.period:
            # Subsequent ADX uses Wilder's smoothing (like EMA)
            # ADX = ((prior ADX * (period - 1)) + current DX) / period
            self._adx_value = (self._previous_adx * (self.period - 1) + dx) / self.period

        # Store for next iteration
        self._previous_adx = self._adx_value

    def _reset(self) -> None:
        """Reset the indicator."""
        self._dm.reset()
        self._dx_values.clear()
        self._adx_value = 0.0
        self._previous_adx = 0.0


# Export all indicators
__all__ = [
    "APO",
    "PPO",
    "ADX",
]
