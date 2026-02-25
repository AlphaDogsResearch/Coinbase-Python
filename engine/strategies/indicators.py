import logging
from abc import ABC, abstractmethod
from collections import deque
from typing import Any, List, Optional

from engine.market_data.candle import MidPriceCandle


class Indicator(ABC):
    def __init__(self, params: List[Any] = None):
        self.params = params or []
        self._initialized = False

    @property
    def initialized(self) -> bool:
        return self._initialized

    @abstractmethod
    def handle_bar(self, candle: MidPriceCandle) -> None:
        """Handle incoming candle data. Note: parameter name kept as 'bar' for compatibility."""
        pass

    @abstractmethod
    def reset(self) -> None:
        pass


class SimpleMovingAverage(Indicator):
    def __init__(self, period: int):
        super().__init__([period])
        self.period = period
        self.buffer = deque(maxlen=period)
        self.value = 0.0

    def handle_bar(self, candle: MidPriceCandle) -> None:
        close_price = candle.close if candle.close is not None else 0.0
        self.buffer.append(close_price)
        if len(self.buffer) == self.period:
            self.value = sum(self.buffer) / self.period
            self._initialized = True
            logging.debug(f"SimpleMovingAverage initialized {self.value}")
        else:
            self._initialized = False
            self.value = 0.0  # Or partial average

    def reset(self) -> None:
        self.buffer.clear()
        self.value = 0.0
        self._initialized = False

    @property
    def has_inputs(self) -> bool:
        return len(self.buffer) > 0


class ExponentialMovingAverage(Indicator):
    def __init__(self, period: int):
        super().__init__([period])
        self.period = period
        self.alpha = 2.0 / (period + 1)
        self.value = 0.0
        self._initialized = False
        self._count = 0

    def handle_bar(self, candle: MidPriceCandle) -> None:
        if not self._initialized:
            # First value is SMA or just the price
            self._count += 1
            close_price = candle.close if candle.close is not None else 0.0
            if self._count == 1:
                self.value = close_price
            else:
                # Simple initialization: just start EMA from first point,
                # or wait for 'period' bars to be accurate.
                # TA-Lib usually waits or uses SMA for first 'period' bars.
                # Here we'll use standard EMA formula from the start but mark initialized after period
                self.value = (close_price - self.value) * self.alpha + self.value

            if self._count >= self.period:
                self._initialized = True
                logging.debug(f"ExponentialMovingAverage initialized {self.value}")
        else:
            close_price = candle.close if candle.close is not None else 0.0
            self.value = (close_price - self.value) * self.alpha + self.value

    def reset(self) -> None:
        self.value = 0.0
        self._initialized = False
        self._count = 0

    @property
    def has_inputs(self) -> bool:
        return self._count > 0


# Placeholder for WMA and DEMA if needed, or map to EMA for simplicity if acceptable
# Using standard EMA logic for accuracy.
# For now, I'll implement WMA and DEMA if I have time, or just aliases if they are complex.
# WMA is weighted sum. DEMA is 2*EMA - EMA(EMA).


class WeightedMovingAverage(Indicator):
    def __init__(self, period: int):
        super().__init__([period])
        self.period = period
        self.buffer = deque(maxlen=period)
        self.value = 0.0
        self.weights = list(range(1, period + 1))
        self.weight_sum = sum(self.weights)

    def handle_bar(self, candle: MidPriceCandle) -> None:
        close_price = candle.close if candle.close is not None else 0.0
        self.buffer.append(close_price)
        if len(self.buffer) == self.period:
            weighted_sum = sum(
                price * weight for price, weight in zip(self.buffer, self.weights)
            )
            self.value = weighted_sum / self.weight_sum
            self._initialized = True
            logging.debug(f"WeightedMovingAverage initialized {self.value}")
        else:
            self._initialized = False

    def reset(self) -> None:
        self.buffer.clear()
        self.value = 0.0
        self._initialized = False


class DoubleExponentialMovingAverage(Indicator):
    def __init__(self, period: int):
        super().__init__([period])
        self.period = period
        self.ema1 = ExponentialMovingAverage(period)
        self.ema2 = ExponentialMovingAverage(period)
        self.value = 0.0

    def handle_bar(self, candle: MidPriceCandle) -> None:
        self.ema1.handle_bar(candle)
        if self.ema1.initialized:
            # We need to feed EMA1 value to EMA2
            # Create a dummy candle with close = ema1.value
            from datetime import datetime

            dummy_candle = MidPriceCandle(start_time=candle.start_time)
            dummy_candle.open = self.ema1.value
            dummy_candle.high = self.ema1.value
            dummy_candle.low = self.ema1.value
            dummy_candle.close = self.ema1.value
            self.ema2.handle_bar(dummy_candle)

            if self.ema2.initialized:
                self.value = 2 * self.ema1.value - self.ema2.value
                self._initialized = True
                logging.debug(
                    f"DoubleExponentialMovingAverage initialized {self.value}"
                )

    def reset(self) -> None:
        self.ema1.reset()
        self.ema2.reset()
        self.value = 0.0
        self._initialized = False


class DirectionalMovement(Indicator):
    def __init__(self, period: int):
        super().__init__([period])
        self.period = period
        self.pos = 0.0  # +DI
        self.neg = 0.0  # -DI
        self.prev_high = None
        self.prev_low = None
        self.prev_close = None

        # Wilder's smoothing for TR, +DM, -DM
        # We need smoothed values
        self.tr_smooth = 0.0
        self.pos_dm_smooth = 0.0
        self.neg_dm_smooth = 0.0
        self._count = 0

    def handle_bar(self, candle: MidPriceCandle) -> None:
        high = candle.high if candle.high != float("-inf") else 0.0
        low = candle.low if candle.low != float("inf") else 0.0
        close = candle.close if candle.close is not None else 0.0

        if self.prev_high is None:
            self.prev_high = high
            self.prev_low = low
            self.prev_close = close
            return

        # Calculate TR
        tr1 = high - low
        tr2 = abs(high - self.prev_close)
        tr3 = abs(low - self.prev_close)
        tr = max(tr1, tr2, tr3)

        # Calculate +DM, -DM
        up_move = high - self.prev_high
        down_move = self.prev_low - low

        pos_dm = 0.0
        neg_dm = 0.0

        if up_move > down_move and up_move > 0:
            pos_dm = up_move
        if down_move > up_move and down_move > 0:
            neg_dm = down_move

        self._count += 1

        # Smoothing (Wilder's)
        # First value is sum
        if self._count <= self.period:
            self.tr_smooth += tr
            self.pos_dm_smooth += pos_dm
            self.neg_dm_smooth += neg_dm

            if self._count == self.period:
                self._initialized = True
                self.pos = (
                    100 * self.pos_dm_smooth / self.tr_smooth
                    if self.tr_smooth != 0
                    else 0
                )
                self.neg = (
                    100 * self.neg_dm_smooth / self.tr_smooth
                    if self.tr_smooth != 0
                    else 0
                )
                logging.debug(f"DirectionalMovement initialized {self.pos}")
        else:
            # Subsequent values: Smooth = Prev - (Prev/N) + Current
            self.tr_smooth = self.tr_smooth - (self.tr_smooth / self.period) + tr
            self.pos_dm_smooth = (
                self.pos_dm_smooth - (self.pos_dm_smooth / self.period) + pos_dm
            )
            self.neg_dm_smooth = (
                self.neg_dm_smooth - (self.neg_dm_smooth / self.period) + neg_dm
            )

            self.pos = (
                100 * self.pos_dm_smooth / self.tr_smooth if self.tr_smooth != 0 else 0
            )
            self.neg = (
                100 * self.neg_dm_smooth / self.tr_smooth if self.tr_smooth != 0 else 0
            )

        self.prev_high = high
        self.prev_low = low
        self.prev_close = close

    def reset(self) -> None:
        self.pos = 0.0
        self.neg = 0.0
        self.prev_high = None
        self.prev_low = None
        self.prev_close = None
        self.tr_smooth = 0.0
        self.pos_dm_smooth = 0.0
        self.neg_dm_smooth = 0.0
        self._count = 0
        self._initialized = False

    @property
    def has_inputs(self) -> bool:
        return self.prev_high is not None


# Copying ADX, APO, PPO from the original file but adapting to new base classes
class APO(Indicator):
    def __init__(self, fast_period: int = 12, slow_period: int = 26, ma_type: int = 1):
        super().__init__([fast_period, slow_period, ma_type])
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.ma_type = ma_type

        if ma_type == 0:
            self.fast_ma, self.slow_ma = (
                SimpleMovingAverage(fast_period),
                SimpleMovingAverage(slow_period),
            )
        elif ma_type == 1:
            self.fast_ma, self.slow_ma = (
                ExponentialMovingAverage(fast_period),
                ExponentialMovingAverage(slow_period),
            )
        elif ma_type == 2:
            self.fast_ma, self.slow_ma = (
                WeightedMovingAverage(fast_period),
                WeightedMovingAverage(slow_period),
            )
        elif ma_type == 3:
            self.fast_ma, self.slow_ma = (
                DoubleExponentialMovingAverage(fast_period),
                DoubleExponentialMovingAverage(slow_period),
            )
        else:
            self.fast_ma, self.slow_ma = (
                ExponentialMovingAverage(fast_period),
                ExponentialMovingAverage(slow_period),
            )

        self.value = 0.0

    def handle_bar(self, candle: MidPriceCandle) -> None:
        self.fast_ma.handle_bar(candle)
        self.slow_ma.handle_bar(candle)

        if self.fast_ma.initialized and self.slow_ma.initialized:
            self.value = self.fast_ma.value - self.slow_ma.value
            self._initialized = True
            logging.debug(f"APO initialized {self.value}")

    def reset(self) -> None:
        self.fast_ma.reset()
        self.slow_ma.reset()
        self.value = 0.0
        self._initialized = False


class PPO(Indicator):
    def __init__(self, fast_period: int = 12, slow_period: int = 26, ma_type: int = 1):
        super().__init__([fast_period, slow_period, ma_type])
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.ma_type = ma_type

        if ma_type == 0:
            self.fast_ma, self.slow_ma = (
                SimpleMovingAverage(fast_period),
                SimpleMovingAverage(slow_period),
            )
        elif ma_type == 1:
            self.fast_ma, self.slow_ma = (
                ExponentialMovingAverage(fast_period),
                ExponentialMovingAverage(slow_period),
            )
        elif ma_type == 2:
            self.fast_ma, self.slow_ma = (
                WeightedMovingAverage(fast_period),
                WeightedMovingAverage(slow_period),
            )
        elif ma_type == 3:
            self.fast_ma, self.slow_ma = (
                DoubleExponentialMovingAverage(fast_period),
                DoubleExponentialMovingAverage(slow_period),
            )
        else:
            self.fast_ma, self.slow_ma = (
                ExponentialMovingAverage(fast_period),
                ExponentialMovingAverage(slow_period),
            )

        self.value = 0.0

    def handle_bar(self, candle: MidPriceCandle) -> None:
        self.fast_ma.handle_bar(candle)
        self.slow_ma.handle_bar(candle)

        if (
            self.fast_ma.initialized
            and self.slow_ma.initialized
            and self.slow_ma.value != 0
        ):
            self.value = (
                (self.fast_ma.value - self.slow_ma.value) / self.slow_ma.value
            ) * 100
            self._initialized = True
            logging.debug(f"PPO initialized {self.value}")

    def reset(self) -> None:
        self.fast_ma.reset()
        self.slow_ma.reset()
        self.value = 0.0
        self._initialized = False


class ADX(Indicator):
    def __init__(self, period: int = 14):
        super().__init__([period])
        self.period = period
        self._dm = DirectionalMovement(period)
        self._dx_values = []
        self._adx_value = 0.0
        self._previous_adx = 0.0
        self._alpha = 1.0 / period

    @property
    def pos(self) -> float:
        return self._dm.pos

    @property
    def neg(self) -> float:
        return self._dm.neg

    @property
    def value(self) -> float:
        return self._adx_value

    def handle_bar(self, candle: MidPriceCandle) -> None:
        self._dm.handle_bar(candle)

        if not self._dm.initialized:
            return

        plus_di = self._dm.pos
        minus_di = self._dm.neg

        di_sum = plus_di + minus_di
        if di_sum > 0:
            dx = abs(plus_di - minus_di) / di_sum * 100.0
        else:
            dx = 0.0

        self._dx_values.append(dx)

        if len(self._dx_values) == self.period:
            self._adx_value = sum(self._dx_values) / self.period
            self._initialized = True
            logging.debug(f"ADX initialized {self.value}")
        elif len(self._dx_values) > self.period:
            self._adx_value = (
                self._previous_adx * (self.period - 1) + dx
            ) / self.period
            self._initialized = True
            logging.debug(f"ADX initialized {self.value}")

        self._previous_adx = self._adx_value

    def reset(self) -> None:
        self._dm.reset()
        self._dx_values.clear()
        self._adx_value = 0.0
        self._previous_adx = 0.0
        self._initialized = False


class RateOfChange(Indicator):
    def __init__(self, period: int = 1):
        super().__init__([period])
        self.period = period
        self.buffer = deque(maxlen=period + 1)
        self.value = 0.0

    def handle_bar(self, candle: MidPriceCandle) -> None:
        close_price = candle.close if candle.close is not None else 0.0
        self.buffer.append(close_price)
        if len(self.buffer) == self.period + 1:
            prev_price = self.buffer[0]
            if prev_price != 0:
                self.value = (close_price - prev_price) / prev_price
            else:
                self.value = 0.0
            self._initialized = True
            logging.debug(f"RateOfChange initialized {self.value}")
        else:
            self.value = 0.0
            self._initialized = False

    def reset(self) -> None:
        self.buffer.clear()
        self.value = 0.0
        self._initialized = False


class RelativeStrengthIndex(Indicator):
    def __init__(self, period: int = 14):
        super().__init__([period])
        self.period = period
        self._prev_close = None
        self._gains = deque(maxlen=period)
        self._losses = deque(maxlen=period)
        self._avg_gain = 0.0
        self._avg_loss = 0.0
        self.value = 0.0

    def _compute_rsi(self) -> float:
        if self._avg_loss == 0.0:
            if self._avg_gain == 0.0:
                return 50.0
            return 100.0
        rs = self._avg_gain / self._avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def handle_bar(self, candle: MidPriceCandle) -> None:
        close_price = candle.close if candle.close is not None else 0.0

        if self._prev_close is None:
            self._prev_close = close_price
            self.value = 0.0
            self._initialized = False
            return

        change = close_price - self._prev_close
        gain = max(change, 0.0)
        loss = max(-change, 0.0)

        if not self._initialized:
            self._gains.append(gain)
            self._losses.append(loss)

            if len(self._gains) == self.period:
                self._avg_gain = sum(self._gains) / self.period
                self._avg_loss = sum(self._losses) / self.period
                self.value = self._compute_rsi()
                self._initialized = True
                logging.debug(f"RelativeStrengthIndex initialized {self.value}")
            else:
                self.value = 0.0
        else:
            self._avg_gain = ((self._avg_gain * (self.period - 1)) + gain) / self.period
            self._avg_loss = ((self._avg_loss * (self.period - 1)) + loss) / self.period
            self.value = self._compute_rsi()

        self._prev_close = close_price

    def reset(self) -> None:
        self._prev_close = None
        self._gains.clear()
        self._losses.clear()
        self._avg_gain = 0.0
        self._avg_loss = 0.0
        self.value = 0.0
        self._initialized = False


class TripleExponentialMovingAverage(Indicator):
    def __init__(self, period: int):
        super().__init__([period])
        self.period = period
        self.ema1 = ExponentialMovingAverage(period)
        self.ema2 = ExponentialMovingAverage(period)
        self.ema3 = ExponentialMovingAverage(period)
        self.value = 0.0

    def _build_derived_candle(
        self, candle: MidPriceCandle, value: float
    ) -> MidPriceCandle:
        derived = MidPriceCandle(start_time=candle.start_time)
        derived.open = value
        derived.high = value
        derived.low = value
        derived.close = value
        return derived

    def handle_bar(self, candle: MidPriceCandle) -> None:
        self.ema1.handle_bar(candle)
        if not self.ema1.initialized:
            self._initialized = False
            self.value = 0.0
            return

        ema1_candle = self._build_derived_candle(candle, self.ema1.value)
        self.ema2.handle_bar(ema1_candle)
        if not self.ema2.initialized:
            self._initialized = False
            self.value = 0.0
            return

        ema2_candle = self._build_derived_candle(candle, self.ema2.value)
        self.ema3.handle_bar(ema2_candle)
        if not self.ema3.initialized:
            self._initialized = False
            self.value = 0.0
            return

        self.value = 3.0 * (self.ema1.value - self.ema2.value) + self.ema3.value
        self._initialized = True
        logging.debug(f"TripleExponentialMovingAverage initialized {self.value}")

    def reset(self) -> None:
        self.ema1.reset()
        self.ema2.reset()
        self.ema3.reset()
        self.value = 0.0
        self._initialized = False


class CommodityChannelIndex(Indicator):
    def __init__(self, period: int = 14):
        super().__init__([period])
        self.period = period
        self.tp_buffer = deque(maxlen=period)
        self.value = 0.0

    def handle_bar(self, candle: MidPriceCandle) -> None:
        high = candle.high if candle.high != float("-inf") else 0.0
        low = candle.low if candle.low != float("inf") else 0.0
        close = candle.close if candle.close is not None else 0.0
        tp = (high + low + close) / 3.0
        self.tp_buffer.append(tp)

        if len(self.tp_buffer) == self.period:
            sma_tp = sum(self.tp_buffer) / self.period
            mean_dev = sum(abs(x - sma_tp) for x in self.tp_buffer) / self.period

            if mean_dev != 0:
                self.value = (tp - sma_tp) / (0.015 * mean_dev)
            else:
                self.value = 0.0
            self._initialized = True
            logging.debug(f"CommodityChannelIndex initialized {self.value}")
        else:
            self.value = 0.0
            self._initialized = False

    def reset(self) -> None:
        self.tp_buffer.clear()
        self.value = 0.0
        self._initialized = False


class BollingerBands(Indicator):
    """
    Bollinger Bands indicator.

    Computes upper, middle, and lower bands using a configurable moving average type:
      0 = SMA, 1 = EMA, 2 = DEMA, 3 = TEMA (default)

    upper  = middle + nbdevup  * std_dev
    middle = MA(close, period)
    lower  = middle - nbdevdn  * std_dev
    """

    def __init__(
        self,
        period: int = 16,
        nbdevup: float = 1.41,
        nbdevdn: float = 2.15,
        matype: int = 3,
    ):
        super().__init__([period, nbdevup, nbdevdn, matype])
        self.period = period
        self.nbdevup = nbdevup
        self.nbdevdn = nbdevdn
        self.matype = matype

        if matype == 0:
            self._ma = SimpleMovingAverage(period)
        elif matype == 1:
            self._ma = ExponentialMovingAverage(period)
        elif matype == 2:
            self._ma = DoubleExponentialMovingAverage(period)
        else:  # matype == 3 (TEMA)
            self._ma = TripleExponentialMovingAverage(period)

        self._close_buffer: deque = deque()
        self.upper = 0.0
        self.middle = 0.0
        self.lower = 0.0
        self.value = 0.0  # alias for middle

    def handle_bar(self, candle: MidPriceCandle) -> None:
        close_price = candle.close if candle.close is not None else 0.0
        self._close_buffer.append(close_price)

        self._ma.handle_bar(candle)
        if not self._ma.initialized:
            self._initialized = False
            self.upper = 0.0
            self.middle = 0.0
            self.lower = 0.0
            self.value = 0.0
            return

        self.middle = self._ma.value
        self.value = self.middle

        # Standard deviation of the last `period` closes
        buf_list = list(self._close_buffer)
        recent = buf_list[-self.period :] if len(buf_list) >= self.period else buf_list
        n = len(recent)
        if n > 1:
            mean = sum(recent) / n
            variance = sum((x - mean) ** 2 for x in recent) / (n - 1)
            std = variance**0.5
        else:
            std = 0.0

        self.upper = self.middle + self.nbdevup * std
        self.lower = self.middle - self.nbdevdn * std
        self._initialized = True
        logging.debug(
            f"BollingerBands middle={self.middle:.4f} upper={self.upper:.4f} lower={self.lower:.4f}"
        )

    def reset(self) -> None:
        self._ma.reset()
        self._close_buffer.clear()
        self.upper = 0.0
        self.middle = 0.0
        self.lower = 0.0
        self.value = 0.0
        self._initialized = False


class ChandeMomentumOscillator(Indicator):
    """
    Chande Momentum Oscillator (CMO).

    CMO = 100 * (sum_up - sum_down) / (sum_up + sum_down)
    where sum_up = sum of gains over period, sum_down = sum of losses over period.
    Range: -100 to +100.
    """

    def __init__(self, period: int = 14):
        super().__init__([period])
        self.period = period
        self._prev_close = None
        self._changes: deque = deque(maxlen=period)
        self.value = 0.0

    def handle_bar(self, candle: MidPriceCandle) -> None:
        close_price = candle.close if candle.close is not None else 0.0

        if self._prev_close is None:
            self._prev_close = close_price
            self._initialized = False
            return

        change = close_price - self._prev_close
        self._changes.append(change)
        self._prev_close = close_price

        if len(self._changes) == self.period:
            sum_up = sum(c for c in self._changes if c > 0)
            sum_down = sum(-c for c in self._changes if c < 0)
            total = sum_up + sum_down
            if total != 0:
                self.value = 100.0 * (sum_up - sum_down) / total
            else:
                self.value = 0.0
            self._initialized = True
            logging.debug(f"ChandeMomentumOscillator initialized {self.value}")
        else:
            self.value = 0.0
            self._initialized = False

    def reset(self) -> None:
        self._prev_close = None
        self._changes.clear()
        self.value = 0.0
        self._initialized = False


class TRIX(Indicator):
    """
    TRIX indicator: 1-period percentage rate of change of EMA(EMA(EMA(close))).

    TRIX = ((ema3[t] - ema3[t-1]) / ema3[t-1]) * 100

    This matches the research notebook (`ta.TRIX`) and Pine reference strategy:
    compute three nested EMAs, then rate-of-change of the third EMA.
    """

    def __init__(self, period: int = 14):
        super().__init__([period])
        self.period = period
        self._ema1 = ExponentialMovingAverage(period)
        self._ema2 = ExponentialMovingAverage(period)
        self._ema3 = ExponentialMovingAverage(period)
        self._prev_ema3 = None
        self.value = 0.0

    def _build_derived_candle(
        self, candle: MidPriceCandle, value: float
    ) -> MidPriceCandle:
        derived = MidPriceCandle(start_time=candle.start_time)
        derived.open = value
        derived.high = value
        derived.low = value
        derived.close = value
        return derived

    def handle_bar(self, candle: MidPriceCandle) -> None:
        self._ema1.handle_bar(candle)
        if not self._ema1.initialized:
            self._initialized = False
            self.value = 0.0
            return

        ema1_candle = self._build_derived_candle(candle, self._ema1.value)
        self._ema2.handle_bar(ema1_candle)
        if not self._ema2.initialized:
            self._initialized = False
            self.value = 0.0
            return

        ema2_candle = self._build_derived_candle(candle, self._ema2.value)
        self._ema3.handle_bar(ema2_candle)
        if not self._ema3.initialized:
            self._initialized = False
            self.value = 0.0
            return

        current_ema3 = self._ema3.value

        if self._prev_ema3 is None:
            self._prev_ema3 = current_ema3
            self._initialized = False
            self.value = 0.0
            return

        if self._prev_ema3 != 0.0:
            self.value = ((current_ema3 - self._prev_ema3) / self._prev_ema3) * 100.0
        else:
            self.value = 0.0

        self._prev_ema3 = current_ema3
        self._initialized = True
        logging.debug(f"TRIX initialized {self.value}")

    def reset(self) -> None:
        self._ema1.reset()
        self._ema2.reset()
        self._ema3.reset()
        self._prev_ema3 = None
        self.value = 0.0
        self._initialized = False


class Momentum(Indicator):
    """Momentum indicator: close - close[period]"""

    def __init__(self, period: int = 10):
        super().__init__([period])
        self.period = period
        self.buffer = deque(maxlen=period + 1)
        self.value = 0.0

    def handle_bar(self, candle: MidPriceCandle) -> None:
        close_price = candle.close if candle.close is not None else 0.0
        self.buffer.append(close_price)
        if len(self.buffer) == self.period + 1:
            self.value = close_price - self.buffer[0]
            self._initialized = True
            logging.debug(f"Momentum initialized {self.value}")
        else:
            self.value = 0.0
            self._initialized = False

    def reset(self) -> None:
        self.buffer.clear()
        self.value = 0.0
        self._initialized = False


class UltimateOscillator(Indicator):
    """
    Ultimate Oscillator (ULTOSC).

    UO = 100 * (4 * AVG(BP/TR, t1) + 2 * AVG(BP/TR, t2) + AVG(BP/TR, t3)) / 7
    where:
      BP = close - min(low, prev_close)
      TR = max(high, prev_close) - min(low, prev_close)
    """

    def __init__(
        self, timeperiod1: int = 7, timeperiod2: int = 14, timeperiod3: int = 28
    ):
        super().__init__([timeperiod1, timeperiod2, timeperiod3])
        self.timeperiod1 = timeperiod1
        self.timeperiod2 = timeperiod2
        self.timeperiod3 = timeperiod3
        self._prev_close = None
        self._bp_buffer = deque(maxlen=timeperiod3)
        self._tr_buffer = deque(maxlen=timeperiod3)
        self.value = 0.0

    def handle_bar(self, candle: MidPriceCandle) -> None:
        high = candle.high if candle.high != float("-inf") else 0.0
        low = candle.low if candle.low != float("inf") else 0.0
        close = candle.close if candle.close is not None else 0.0

        if self._prev_close is None:
            self._prev_close = close
            self.value = 0.0
            self._initialized = False
            return

        bp = close - min(low, self._prev_close)
        tr = max(high, self._prev_close) - min(low, self._prev_close)

        self._bp_buffer.append(bp)
        self._tr_buffer.append(tr)
        self._prev_close = close

        if len(self._bp_buffer) < self.timeperiod3:
            self.value = 0.0
            self._initialized = False
            return

        bp_values = list(self._bp_buffer)
        tr_values = list(self._tr_buffer)

        bp1 = sum(bp_values[-self.timeperiod1 :])
        tr1 = sum(tr_values[-self.timeperiod1 :])
        bp2 = sum(bp_values[-self.timeperiod2 :])
        tr2 = sum(tr_values[-self.timeperiod2 :])
        bp3 = sum(bp_values[-self.timeperiod3 :])
        tr3 = sum(tr_values[-self.timeperiod3 :])

        avg1 = (bp1 / tr1) if tr1 != 0.0 else 0.0
        avg2 = (bp2 / tr2) if tr2 != 0.0 else 0.0
        avg3 = (bp3 / tr3) if tr3 != 0.0 else 0.0

        self.value = 100.0 * ((4.0 * avg1) + (2.0 * avg2) + avg3) / 7.0
        self._initialized = True
        logging.debug(f"UltimateOscillator initialized {self.value}")

    def reset(self) -> None:
        self._prev_close = None
        self._bp_buffer.clear()
        self._tr_buffer.clear()
        self.value = 0.0
        self._initialized = False
