from dataclasses import dataclass

from .base import Strategy
from .models import Bar, PositionSide
from .indicators import RateOfChange
from common.interface_order import OrderSizeMode
from .strategy_action import StrategyAction
from .strategy_order_mode import StrategyOrderMode


@dataclass(frozen=True)
class ROCMeanReversionStrategyConfig:
    """ROC Mean Reversion Strategy configuration."""

    instrument_id: str
    bar_type: str

    # ROC Parameters
    roc_period: int = 22
    roc_upper: float = 3.4  # Upper threshold for mean reversion
    roc_lower: float = -3.6  # Lower threshold for mean reversion
    roc_mid: float = -2.1  # Midpoint for exit

    # Position Management
    quantity: float = 1.0  # Position size (deprecated, use notional_amount)
    notional_amount: float = 500.0  # Order size in notional value
    stop_loss_percent: float = 0.021  # Stop loss distance (decimal: 0.021 = 2.1%)

    # Risk Management
    max_holding_bars: int = 100  # Max holding period in bars


class ROCMeanReversionStrategy(Strategy):
    """
    ROC Mean Reversion Strategy Implementation
    """

    def __init__(self, config: ROCMeanReversionStrategyConfig) -> None:
        super().__init__(config)

        self.config = config

        # ROC Parameters
        self.roc_period = config.roc_period
        self.roc_upper = config.roc_upper
        self.roc_lower = config.roc_lower
        self.roc_mid = config.roc_mid

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
        self._position_entry_bar = 0
        self._stop_loss_price = None  # Stop loss price for current position

        self.instrument_id = config.instrument_id
        self.bar_type = config.bar_type
        self.instrument = None

    def on_start(self) -> None:
        """Initialize strategy on start."""
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument {self.instrument_id} not found in cache")
            pass

        self.subscribe_bars(self.bar_type)
        self.log.info(f"ROCMeanReversionStrategy started for {self.instrument_id}")

    def on_bar(self, bar: Bar):
        """Handle incoming bar data."""
        self.roc.handle_bar(bar)

        if not self.roc.initialized:
            return

        # Check stop loss first
        self._check_stop_loss(bar)

        self._execute_mean_reversion_mode(bar)

        self._previous_roc = self.roc.value * 100
        self._bars_processed += 1

    def _execute_mean_reversion_mode(self, bar: Bar) -> None:
        """Mean Reversion Mode Logic."""
        current_roc = self.roc.value * 100

        # Entry conditions (mean reversion)
        if self.cache.is_flat(self.instrument_id):
            # Long entry: ROC crosses above lower threshold (oversold recovery)
            if self._previous_roc < self.roc_lower and current_roc >= self.roc_lower:
                self._enter_long(bar, reason="ROC oversold recovery")

            # Short entry: ROC crosses below upper threshold (overbought decline)
            elif self._previous_roc > self.roc_upper and current_roc <= self.roc_upper:
                self._enter_short(bar, reason="ROC overbought decline")

        # Exit conditions (midpoint)
        else:
            # Exit long: ROC crosses below midpoint
            if (
                self._previous_roc > self.roc_mid
                and current_roc <= self.roc_mid
                and self.cache.is_net_long(self.instrument_id)
            ):
                self._close_position(bar, "ROC returned to midpoint")

            # Exit short: ROC crosses above midpoint
            elif (
                self._previous_roc < self.roc_mid
                and current_roc >= self.roc_mid
                and self.cache.is_net_short(self.instrument_id)
            ):
                self._close_position(bar, "ROC returned to midpoint")

            # Max holding period exit
            elif self._bars_processed - self._position_entry_bar >= self.max_holding_bars:
                self._close_position(bar, "Max holding period reached")

    def _enter_long(self, bar: Bar, reason: str = "Mean reversion signal") -> None:
        if self.cache.is_net_long(self.instrument_id):
            self.log.warning("Already in long position")
            return

        close_price = bar.close if bar.close is not None else 0.0
        if close_price == 0.0:
            return

        stop_price = close_price * (1 - self.stop_loss_percent)

        # Create strategy order mode with notional
        strategy_order_mode = StrategyOrderMode(
            order_size_mode=OrderSizeMode.NOTIONAL,
            notional_value=self.notional_amount
        )

        # Submit order via on_signal
        ok = self.on_signal(
            signal=1,  # BUY
            price=close_price,
            strategy_actions=StrategyAction.OPEN_CLOSE_POSITION,
            strategy_order_mode=strategy_order_mode,
        )

        if ok:
            # Store stop loss price for checking at each bar
            self._stop_loss_price = stop_price
            self.log.info(
                f"🟢 LONG ENTRY | {reason} | Price: {close_price:.4f} | SL: {stop_price:.4f}"
            )
            self._position_side = PositionSide.LONG
            self._position_entry_bar = self._bars_processed
        else:
            self.log.error("Failed to submit long entry order")

    def _enter_short(self, bar: Bar, reason: str = "Mean reversion signal") -> None:
        if self.cache.is_net_short(self.instrument_id):
            self.log.warning("Already in short position")
            return

        close_price = bar.close if bar.close is not None else 0.0
        if close_price == 0.0:
            return

        stop_price = close_price * (1 + self.stop_loss_percent)

        # Create strategy order mode with notional
        strategy_order_mode = StrategyOrderMode(
            order_size_mode=OrderSizeMode.NOTIONAL,
            notional_value=self.notional_amount
        )

        # Submit order via on_signal
        ok = self.on_signal(
            signal=-1,  # SELL
            price=close_price,
            strategy_actions=StrategyAction.OPEN_CLOSE_POSITION,
            strategy_order_mode=strategy_order_mode,
        )

        if ok:
            # Store stop loss price for checking at each bar
            self._stop_loss_price = stop_price
            self.log.info(
                f"🔴 SHORT ENTRY | {reason} | Price: {close_price:.4f} | SL: {stop_price:.4f}"
            )
            self._position_side = PositionSide.SHORT
            self._position_entry_bar = self._bars_processed
        else:
            self.log.error("Failed to submit short entry order")

    def _close_position(self, bar: Bar, reason: str) -> None:
        if self.cache.is_flat(self.instrument_id):
            return

        close_price = bar.close if bar.close is not None else 0.0
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
            tags=tags
        )

        if ok:
            # Clear stop loss tracking
            self._stop_loss_price = None
            if position.is_long:
                self.log.info(f"🟡 LONG EXIT: {reason} | Price: {close_price:.4f}")
            else:
                self.log.info(f"🟡 SHORT EXIT: {reason} | Price: {close_price:.4f}")
        else:
            self.log.error("Failed to submit close order")

    def _check_stop_loss(self, bar: Bar) -> None:
        """Check if stop loss should be triggered at current bar price."""
        if self._stop_loss_price is None or self.cache.is_flat(self.instrument_id):
            return

        close_price = bar.close if bar.close is not None else 0.0
        if close_price == 0.0:
            return

        # Check stop loss for long position
        if self._position_side == PositionSide.LONG and close_price <= self._stop_loss_price:
            self._close_position(bar, f"Stop loss triggered at {close_price:.4f}")

        # Check stop loss for short position
        elif self._position_side == PositionSide.SHORT and close_price >= self._stop_loss_price:
            self._close_position(bar, f"Stop loss triggered at {close_price:.4f}")

        self._position_side = None
