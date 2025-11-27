from dataclasses import dataclass
import uuid
from typing import Optional

from .base import Strategy
from .models import Bar, PositionSide
from .indicators import CommodityChannelIndex
from common.interface_order import Side


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

        # Calculate quantity from notional amount
        quantity = self.notional_amount / close_price

        stop_loss_price = close_price * (1 - self.stop_loss_percent)
        signal_id = str(uuid.uuid4())

        tags = [
            f"signal_id={signal_id}",
            f"cci_mid={self.cci_mid:.2f}",
            f"reason={reason}",
        ]

        # Submit market entry order directly
        ok = self.submit_market_entry(
            side=Side.BUY,
            quantity=quantity,
            price=close_price,
            signal_id=signal_id,
            tags=tags,
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

        # Calculate quantity from notional amount
        quantity = self.notional_amount / close_price

        stop_loss_price = close_price * (1 + self.stop_loss_percent)
        signal_id = str(uuid.uuid4())

        tags = [
            f"signal_id={signal_id}",
            f"cci_mid={self.cci_mid:.2f}",
            f"reason={reason}",
        ]

        # Submit market entry order directly
        ok = self.submit_market_entry(
            side=Side.SELL,
            quantity=quantity,
            price=close_price,
            signal_id=signal_id,
            tags=tags,
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
        ok = self.submit_market_close(
            price=close_price,
            tags=tags,
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
