import logging
from dataclasses import dataclass

from common.interface_order import OrderSizeMode
from engine.database.models import build_roc_signal_context

from ..market_data.candle import MidPriceCandle
from .base import Strategy
from .indicators import RateOfChange
from .models import Instrument, PositionSide
from .strategy_action import StrategyAction
from .strategy_order_mode import StrategyOrderMode


@dataclass(frozen=True)
class ROCMeanReversionStrategyConfig:
    """ROC Mean Reversion Strategy configuration."""

    instrument_id: str
    bar_type: str

    # ROC Parameters
    roc_period: int = 6
    roc_upper: float = 4.0
    roc_lower: float = -3.0
    roc_mid: float = 0.0

    # Signal Behavior
    signal_mode: str = "momentum"  # mean_reversion | momentum
    exit_mode: str = "midpoint"  # midpoint | breakout

    # Position Management
    quantity: float = 1.0  # Position size (deprecated, use notional_amount)
    notional_amount: float = 500.0  # Order size in notional value
    stop_loss_percent: float = 0.047

    # Risk Management
    max_holding_bars: int = 20


class ROCMeanReversionStrategy(Strategy):
    """
    ROC Mean Reversion Strategy Implementation
    """

    VALID_SIGNAL_MODES = {"mean_reversion", "momentum"}
    VALID_EXIT_MODES = {"midpoint", "breakout"}

    def __init__(self, config: ROCMeanReversionStrategyConfig) -> None:
        super().__init__(config)

        self.config = config

        # ROC Parameters
        self.roc_period = config.roc_period
        self.roc_upper = config.roc_upper
        self.roc_lower = config.roc_lower
        self.roc_mid = config.roc_mid
        self.signal_mode = config.signal_mode
        if self.signal_mode not in self.VALID_SIGNAL_MODES:
            logging.warning(
                f"Invalid signal_mode={self.signal_mode}, defaulting to momentum"
            )
            self.signal_mode = "momentum"
        self.exit_mode = config.exit_mode
        if self.exit_mode not in self.VALID_EXIT_MODES:
            logging.warning(
                f"Invalid exit_mode={self.exit_mode}, defaulting to midpoint"
            )
            self.exit_mode = "midpoint"

        # Position Management
        self.quantity = config.quantity  # Deprecated, kept for backward compatibility
        self.notional_amount = config.notional_amount
        self.stop_loss_percent = config.stop_loss_percent

        # Risk Management
        self.max_holding_bars = config.max_holding_bars

        # Initialize ROC indicator
        self.roc = RateOfChange(period=self.roc_period)

        # State tracking
        self._previous_roc = 0.0
        self._bars_processed = 0
        self._position_side = None
        self._entry_bar = None
        self._stop_loss_price = None  # Stop loss price for current position
        self._close_queued_this_bar = False

        self.instrument_id = config.instrument_id
        instrument = Instrument(id=self.instrument_id, symbol=self.instrument_id)
        self.cache.add_instrument(instrument)
        self.bar_type = config.bar_type
        self.instrument = None

    def on_start(self) -> None:
        """Initialize strategy on start."""
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument {self.instrument_id} not found in cache\n")
            pass

        self.subscribe_bars(self.bar_type)
        self.log.info(
            f"[SIGNAL] ROCMeanReversionStrategy started for {self.instrument_id} "
            f"(mode={self.signal_mode}, exit={self.exit_mode})"
        )

    def on_candle_created(self, candle: MidPriceCandle):
        # """Handle incoming candle data."""
        # self._bar_counter += 1

        self.roc.handle_bar(candle)

        if not self.roc.initialized:
            return

        self._close_queued_this_bar = False

        if not self.cache.is_flat(self.instrument_id):
            current_side = (
                PositionSide.LONG
                if self.cache.is_net_long(self.instrument_id)
                else PositionSide.SHORT
            )
            self._position_side = current_side
            if self._entry_bar is None:
                self._entry_bar = self._bars_processed
        else:
            self._entry_bar = None
            self._position_side = None

        # Check stop loss first
        self._check_stop_loss(candle)

        self._execute_signal_mode(candle)

        self._previous_roc = self.roc.value * 100
        self._bars_processed += 1

    def _execute_signal_mode(self, candle: MidPriceCandle) -> None:
        """Mode-aware ROC signal logic."""
        current_roc = self.roc.value * 100

        # Entry conditions (mean reversion)
        logging.debug(
            f" [{self.instrument_id}] Cache is Flat {self.cache.is_flat(self.instrument_id)}"
        )

        logging.debug(
            f"Previous ROC: {self._previous_roc} Current ROC: {current_roc} Lower ROC: {self.roc_lower} Upper ROC: {self.roc_upper}"
        )

        mr_long_signal = (
            self._previous_roc < self.roc_lower and current_roc >= self.roc_lower
        )
        mr_short_signal = (
            self._previous_roc > self.roc_upper and current_roc <= self.roc_upper
        )
        mom_long_signal = (
            self._previous_roc < self.roc_upper and current_roc >= self.roc_upper
        )
        mom_short_signal = (
            self._previous_roc > self.roc_lower and current_roc <= self.roc_lower
        )

        if self.signal_mode == "mean_reversion":
            long_entry_signal = mr_long_signal
            short_entry_signal = mr_short_signal
        else:
            long_entry_signal = mom_long_signal
            short_entry_signal = mom_short_signal

        if self.cache.is_flat(self.instrument_id):
            if long_entry_signal:
                self._enter_long(candle, reason="ROC long entry")
            elif short_entry_signal:
                self._enter_short(candle, reason="ROC short entry")
            return

        if self.exit_mode == "midpoint":
            if self.signal_mode == "mean_reversion":
                long_exit_signal = (
                    self._previous_roc < self.roc_mid and current_roc >= self.roc_mid
                )
                short_exit_signal = (
                    self._previous_roc > self.roc_mid and current_roc <= self.roc_mid
                )
            else:
                long_exit_signal = (
                    self._previous_roc > self.roc_mid and current_roc <= self.roc_mid
                )
                short_exit_signal = (
                    self._previous_roc < self.roc_mid and current_roc >= self.roc_mid
                )
        else:
            long_exit_signal = False
            short_exit_signal = False

        if long_exit_signal and self.cache.is_net_long(self.instrument_id):
            self._close_position(candle, "ROC midpoint exit")
        elif short_exit_signal and self.cache.is_net_short(self.instrument_id):
            self._close_position(candle, "ROC midpoint exit")
        elif self._bars_held() >= self.max_holding_bars:
            self._close_position(candle, "Max holding period reached")

    def _enter_long(
        self, candle: MidPriceCandle, reason: str = "Mean reversion signal"
    ) -> None:
        if self.cache.is_net_long(self.instrument_id):
            self.log.warning("Already in long position")
            return

        close_price = candle.close if candle.close is not None else 0.0
        if close_price == 0.0:
            return

        stop_price = close_price * (1 - self.stop_loss_percent)

        # Create strategy order mode with notional
        strategy_order_mode = StrategyOrderMode(
            order_size_mode=OrderSizeMode.NOTIONAL, notional_value=self.notional_amount
        )

        # Build signal context with full indicator snapshot
        current_roc = self.roc.value * 100
        signal_context = build_roc_signal_context(
            reason=reason,
            current_roc=current_roc,
            previous_roc=self._previous_roc,
            roc_upper=self.roc_upper,
            roc_lower=self.roc_lower,
            roc_mid=self.roc_mid,
            roc_period=self.roc_period,
            stop_loss_percent=self.stop_loss_percent,
            max_holding_bars=self.max_holding_bars,
            notional_amount=self.notional_amount,
            candle={
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
            },
            action="ENTRY",
        )

        # Submit order via on_signal
        ok = self.on_signal(
            signal=1,  # BUY
            price=close_price,
            strategy_actions=StrategyAction.OPEN_CLOSE_POSITION,
            strategy_order_mode=strategy_order_mode,
            signal_context=signal_context,
        )

        if ok:
            self._stop_loss_price = stop_price
            self.log.info(
                f"[SIGNAL] LONG ENTRY | {reason} | Price: {close_price:.4f} | SL: {stop_price:.4f}"
            )
        else:
            self.log.error("Failed to submit long entry order")

    def _enter_short(
        self, candle: MidPriceCandle, reason: str = "Mean reversion signal"
    ) -> None:
        if self.cache.is_net_short(self.instrument_id):
            self.log.warning("Already in short position")
            return

        close_price = candle.close if candle.close is not None else 0.0
        if close_price == 0.0:
            return

        stop_price = close_price * (1 + self.stop_loss_percent)

        # Create strategy order mode with notional
        strategy_order_mode = StrategyOrderMode(
            order_size_mode=OrderSizeMode.NOTIONAL, notional_value=self.notional_amount
        )

        # Build signal context with full indicator snapshot
        current_roc = self.roc.value * 100
        signal_context = build_roc_signal_context(
            reason=reason,
            current_roc=current_roc,
            previous_roc=self._previous_roc,
            roc_upper=self.roc_upper,
            roc_lower=self.roc_lower,
            roc_mid=self.roc_mid,
            roc_period=self.roc_period,
            stop_loss_percent=self.stop_loss_percent,
            max_holding_bars=self.max_holding_bars,
            notional_amount=self.notional_amount,
            candle={
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
            },
            action="ENTRY",
        )

        # Submit order via on_signal
        ok = self.on_signal(
            signal=-1,  # SELL
            price=close_price,
            strategy_actions=StrategyAction.OPEN_CLOSE_POSITION,
            strategy_order_mode=strategy_order_mode,
            signal_context=signal_context,
        )

        if ok:
            self._stop_loss_price = stop_price
            self.log.info(
                f"[SIGNAL] SHORT ENTRY | {reason} | Price: {close_price:.4f} | SL: {stop_price:.4f}"
            )
        else:
            self.log.error("Failed to submit short entry order")

    def _bars_held(self) -> int:
        if self._entry_bar is None:
            return 0
        return self._bars_processed - self._entry_bar

    def _close_position(self, candle: MidPriceCandle, reason: str) -> None:
        if self.cache.is_flat(self.instrument_id) or self._close_queued_this_bar:
            return

        close_price = candle.close if candle.close is not None else 0.0
        if close_price == 0.0:
            return

        position = self.cache.position(self.instrument_id)
        if not position:
            return

        tags = [f"reason={reason}"]

        # Submit market close order directly
        ok = self._order_manager.submit_market_close(
            strategy_id=self._strategy_id,
            symbol=self._symbol,
            price=close_price,
            tags=tags,
        )

        if ok:
            self._close_queued_this_bar = True
            self._stop_loss_price = None
            if position.is_long:
                self.log.info(
                    f"[SIGNAL] LONG EXIT | {reason} | Price: {close_price:.4f}"
                )
            else:
                self.log.info(
                    f"[SIGNAL] SHORT EXIT | {reason} | Price: {close_price:.4f}"
                )
        else:
            self.log.error("Failed to submit close order")

    def _candle_low(self, candle: MidPriceCandle) -> float:
        if candle.low == float("inf"):
            return candle.close if candle.close is not None else 0.0
        return candle.low

    def _candle_high(self, candle: MidPriceCandle) -> float:
        if candle.high == float("-inf"):
            return candle.close if candle.close is not None else 0.0
        return candle.high

    def _check_stop_loss(self, candle: MidPriceCandle) -> None:
        """Check if stop loss should be triggered at current bar price (intrabar low/high)."""
        if self._stop_loss_price is None or self.cache.is_flat(self.instrument_id):
            return

        low_price = self._candle_low(candle)
        high_price = self._candle_high(candle)
        close_price = candle.close if candle.close is not None else 0.0
        if close_price == 0.0:
            return

        if (
            self._position_side == PositionSide.LONG
            and low_price <= self._stop_loss_price
        ):
            self._close_position(candle, f"Close Long Position, Stop loss triggered at {low_price:.4f}")

        elif (
            self._position_side == PositionSide.SHORT
            and high_price >= self._stop_loss_price
        ):
            self._close_position(candle, f"Close Short Position, Stop loss triggered at {high_price:.4f}")
