from dataclasses import dataclass

from engine.strategies.base import Strategy
from engine.strategies.models import Bar, PositionSide
from engine.strategies.indicators import CommodityChannelIndex
from common.interface_order import OrderSizeMode
from engine.strategies.strategy_action import StrategyAction
from engine.strategies.strategy_order_mode import StrategyOrderMode
from engine.database.models import build_cci_signal_context


@dataclass(frozen=True)
class CCIMomentumStrategyConfig:
    """CCI Momentum Strategy configuration."""

    instrument_id: str
    bar_type: str

    # CCI Parameters
    cci_period: int = 14
    cci_upper: float = 205.0  # Upper threshold for momentum
    cci_lower: float = -101.0  # Lower threshold for momentum
    cci_mid: float = 12.0  # Midpoint for exit

    # Position Management
    quantity: float = 1.0  # Position size (deprecated, use notional_amount)
    notional_amount: float = 500.0  # Order size in notional value
    stop_loss_percent: float = 0.074  # Stop loss distance (decimal: 0.074 = 7.4%)

    # Risk Management
    max_holding_bars: int = 25  # Max holding period in bars


class CCIMomentumStrategy(Strategy):
    """
    CCI Momentum Strategy Implementation.
    """

    def __init__(self, config: CCIMomentumStrategyConfig) -> None:
        super().__init__(config)

        self.config = config

        # CCI Parameters
        self.cci_period = config.cci_period
        self.cci_upper = config.cci_upper
        self.cci_lower = config.cci_lower
        self.cci_mid = config.cci_mid

        # Position Management
        self.quantity = config.quantity  # Deprecated, kept for backward compatibility
        self.notional_amount = config.notional_amount
        self.stop_loss_percent = config.stop_loss_percent

        # Risk Management
        self.max_holding_bars = config.max_holding_bars

        # Initialize CCI indicator
        self.cci = CommodityChannelIndex(period=self.cci_period)

        # State tracking
        self._previous_cci = 0.0
        self._position_side = None
        self._bars_processed = 0
        self._long_entry_bar = None
        self._short_entry_bar = None
        self._stop_loss_price = None  # Stop loss price for current position

        self.instrument_id = config.instrument_id
        self.bar_type = config.bar_type
        self.instrument = None

    def on_start(self) -> None:
        """Called when strategy starts."""
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Could not find instrument for {self.instrument_id}")
            pass

        self.subscribe_bars(self.bar_type)
        self.log.info(f"CCIMomentumStrategy started for {self.instrument_id}")

    def on_bar(self, bar: Bar) -> None:
        """Called when a bar is received."""
        self.cci.handle_bar(bar)

        if not self.cci.initialized:
            return

        # Check stop loss first
        self._check_stop_loss(bar)

        self._execute_momentum_mode(bar)

        self._previous_cci = self.cci.value
        self._bars_processed += 1

    def _execute_momentum_mode(self, bar: Bar) -> None:
        """Momentum Mode Logic."""
        current_cci = self.cci.value

        # Entry conditions (momentum)
        if self.cache.is_flat(self.instrument_id):
            # Long entry: CCI crosses above upper threshold (momentum breakout)
            if self._previous_cci < self.cci_upper and current_cci >= self.cci_upper:
                self._enter_long(bar, current_cci, reason="CCI momentum breakout")

            # Short entry: CCI crosses below lower threshold (momentum breakdown)
            elif self._previous_cci > self.cci_lower and current_cci <= self.cci_lower:
                self._enter_short(bar, current_cci, reason="CCI momentum breakdown")

        # Exit conditions (midpoint)
        if not self.cache.is_flat(self.instrument_id):
            # Long exit: CCI crosses below midpoint
            if self._position_side == PositionSide.LONG:
                if self._previous_cci > self.cci_mid and current_cci <= self.cci_mid:
                    self._close_position(bar, "CCI returned to midpoint")

            # Short exit: CCI crosses above midpoint
            elif self._position_side == PositionSide.SHORT:
                if self._previous_cci < self.cci_mid and current_cci >= self.cci_mid:
                    self._close_position(bar, "CCI returned to midpoint")

        # Max holding period exits
        if self._position_side == PositionSide.LONG and self._long_entry_bar is not None:
            if (self._bars_processed - self._long_entry_bar) >= self.max_holding_bars:
                self._close_position(bar, "Max holding period reached")

        if self._position_side == PositionSide.SHORT and self._short_entry_bar is not None:
            if (self._bars_processed - self._short_entry_bar) >= self.max_holding_bars:
                self._close_position(bar, "Max holding period reached")

    def _enter_long(self, bar: Bar, current_cci: float, reason: str) -> None:
        if not self.cache.is_flat(self.instrument_id):
            return

        close_price = bar.close if bar.close is not None else 0.0
        if close_price == 0.0:
            return

        stop_loss_price = close_price * (1 - self.stop_loss_percent)

        # Create strategy order mode with notional
        strategy_order_mode = StrategyOrderMode(
            order_size_mode=OrderSizeMode.NOTIONAL,
            notional_value=self.notional_amount
        )

        # Build signal context with full indicator snapshot
        signal_context = build_cci_signal_context(
            reason=reason,
            cci=current_cci,
            prev_cci=self._previous_cci,
            cci_upper=self.cci_upper,
            cci_lower=self.cci_lower,
            cci_mid=self.cci_mid,
            cci_period=self.cci_period,
            stop_loss_percent=self.stop_loss_percent,
            max_holding_bars=self.max_holding_bars,
            notional_amount=self.notional_amount,
            candle={
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
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
            # Store stop loss price for checking at each bar
            self._stop_loss_price = stop_loss_price
            self._position_side = PositionSide.LONG
            self._long_entry_bar = self._bars_processed
            self.log.info(
                f"🟢 LONG ENTRY | {reason} | Price: {close_price:.4f} | SL: {stop_loss_price:.4f}"
            )
        else:
            self.log.error("Failed to submit long entry order")

    def _enter_short(self, bar: Bar, current_cci: float, reason: str) -> None:
        if not self.cache.is_flat(self.instrument_id):
            return

        close_price = bar.close if bar.close is not None else 0.0
        if close_price == 0.0:
            return

        stop_loss_price = close_price * (1 + self.stop_loss_percent)

        # Create strategy order mode with notional
        strategy_order_mode = StrategyOrderMode(
            order_size_mode=OrderSizeMode.NOTIONAL,
            notional_value=self.notional_amount
        )

        # Build signal context with full indicator snapshot
        signal_context = build_cci_signal_context(
            reason=reason,
            cci=current_cci,
            prev_cci=self._previous_cci,
            cci_upper=self.cci_upper,
            cci_lower=self.cci_lower,
            cci_mid=self.cci_mid,
            cci_period=self.cci_period,
            stop_loss_percent=self.stop_loss_percent,
            max_holding_bars=self.max_holding_bars,
            notional_amount=self.notional_amount,
            candle={
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
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
            # Store stop loss price for checking at each bar
            self._stop_loss_price = stop_loss_price
            self._position_side = PositionSide.SHORT
            self._short_entry_bar = self._bars_processed
            self.log.info(
                f"🔴 SHORT ENTRY | {reason} | Price: {close_price:.4f} | SL: {stop_loss_price:.4f}"
            )
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
