"""
CCI Momentum Strategy Implementation.

Based on pine_script/cci_strategy.pine with momentum logic.
"""

import uuid
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.enums import OrderSide, PositionSide, TimeInForce
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.objects import Price, Quantity

from nautilus_trader.indicators import CommodityChannelIndex
from engine.strategies.audit_logger import StrategyAuditLogger


class CCIMomentumStrategyConfig(StrategyConfig, frozen=True):
    """CCI Momentum Strategy configuration."""

    instrument_id: str
    bar_type: str

    # CCI Parameters (from Pine Script)
    cci_period: int = 14
    cci_upper: float = 205.0  # Upper threshold for momentum
    cci_lower: float = -101.0  # Lower threshold for momentum
    cci_mid: float = 12.0  # Midpoint for exit

    # Position Management
    quantity: str = "1.000"  # Position size (100%)
    stop_loss_percent: float = 7.4  # Stop loss distance (7.4% as per Pine Script)

    # Risk Management
    max_holding_bars: int = 25  # Max holding period in bars (from Pine Script)

    # Trace Mode (for auditing)
    enable_trace: bool = False  # Enable detailed trace logging
    trace_output_dir: str = "reports"  # Directory for trace output


class CCIMomentumStrategy(Strategy):
    """
    CCI Momentum Strategy Implementation.

    Momentum Mode Logic:
    - Enter long when CCI crosses above upper threshold (momentum breakout)
    - Enter short when CCI crosses below lower threshold (momentum breakdown)
    - Exit when CCI returns to midpoint
    """

    def __init__(self, config: CCIMomentumStrategyConfig) -> None:
        super().__init__(config)

        # Store configuration
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.bar_type = BarType.from_str(config.bar_type)

        # CCI Parameters
        self.cci_period = config.cci_period
        self.cci_upper = config.cci_upper
        self.cci_lower = config.cci_lower
        self.cci_mid = config.cci_mid

        # Position Management
        self.quantity = Quantity.from_str(config.quantity)

        # Initialize audit logger
        self.audit_logger = StrategyAuditLogger(
            strategy_name=self.__class__.__name__, symbol=config.instrument_id.split(".")[0]
        )
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

    def on_start(self) -> None:
        """Called when strategy starts."""
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Could not find instrument for {self.instrument_id}")
            self.stop()
            return

        # Subscribe to bars
        self.subscribe_bars(self.bar_type)

        # Register CCI indicator
        self.register_indicator_for_bars(self.bar_type, self.cci)
        self.log.info(f"CCIMomentumStrategy started for {self.instrument.id}")

    def on_bar(self, bar: Bar) -> None:
        """Called when a bar is received."""
        # Check if CCI indicator is ready
        if not self.cci.initialized:
            return

        # Execute momentum strategy
        self._execute_momentum_mode(bar)

        # Log audit information
        self._log_audit(bar)

        # Update state for next bar
        self._previous_cci = self.cci.value

    def _execute_momentum_mode(self, bar: Bar) -> None:
        """
        Momentum Mode Logic:
        - Enter long when CCI crosses above upper threshold (momentum breakout)
        - Enter short when CCI crosses below lower threshold (momentum breakdown)
        - Exit when CCI returns to midpoint
        """
        # Convert CCI to match Pine Script values (CCI is already in the correct range)
        current_cci = self.cci.value

        # Entry conditions (momentum)
        if self.portfolio.is_flat(self.instrument.id):
            # Long entry: CCI crosses above upper threshold (momentum breakout)
            if self._previous_cci < self.cci_upper and current_cci >= self.cci_upper:
                self._enter_long(bar, current_cci, reason="CCI momentum breakout")

            # Short entry: CCI crosses below lower threshold (momentum breakdown)
            elif self._previous_cci > self.cci_lower and current_cci <= self.cci_lower:
                self._enter_short(bar, current_cci, reason="CCI momentum breakdown")

        # Exit conditions (midpoint)
        if not self.portfolio.is_flat(self.instrument.id):
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
        """Enter long position with stop loss."""
        if not self.portfolio.is_flat(self.instrument.id):
            return

        # Calculate stop loss price
        stop_loss_price = bar.close * (1 - self.stop_loss_percent / 100)

        # Generate signal_id for this trade
        signal_id = str(uuid.uuid4())

        # Prepare indicator values for tags
        bars_held = self._bars_processed - self._long_entry_bar if self._long_entry_bar else 0
        # ENTRY tags:
        tags = [
            f"signal_id={signal_id}",
            f"cci_mid={self.cci_mid:.2f}",
            f"bars_held={bars_held}",
            "action=ENTRY"
        ]

        # Submit market order
        order = self.order_factory.market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.BUY,
            quantity=self.quantity,
            time_in_force=TimeInForce.GTC,
            tags=tags,
        )
        self.submit_order(order)

        # Submit stop loss order
        stop_order = self.order_factory.stop_market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.SELL,
            quantity=self.quantity,
            trigger_price=Price.from_str(f"{stop_loss_price:.2f}"),
            time_in_force=TimeInForce.GTC,
            tags=f"signal_id={signal_id}|action=STOP_LOSS",
        )
        self.submit_order(stop_order)

        # Update state
        self._position_side = PositionSide.LONG
        self._long_entry_bar = self._bars_processed

        self.log.info(
            f"🟢 LONG ENTRY | {reason}\n"
            f"   Price: {float(bar.close):.4f} | Qty: {float(self.quantity):.4f} | SL: {stop_loss_price:.4f}\n"
            f"   CCI: {current_cci:.2f} | CCI Period: {self.cci_period}"
        )


    def _enter_short(self, bar: Bar, current_cci: float, reason: str) -> None:
        """Enter short position with stop loss."""
        if not self.portfolio.is_flat(self.instrument.id):
            return

        # Calculate stop loss price
        stop_loss_price = bar.close * (1 + self.stop_loss_percent / 100)

        # Generate signal_id for this trade
        signal_id = str(uuid.uuid4())

        # Prepare indicator values for tags
        bars_held = self._bars_processed - self._short_entry_bar if self._short_entry_bar else 0
        # ENTRY tags:
        tags = [
            f"signal_id={signal_id}",
            f"cci_mid={self.cci_mid:.2f}",
            f"bars_held={bars_held}",
            "action=ENTRY"
        ]

        # Submit market order
        order = self.order_factory.market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.SELL,
            quantity=self.quantity,
            time_in_force=TimeInForce.GTC,
            tags=tags,
        )
        self.submit_order(order)

        # Submit stop loss order
        stop_order = self.order_factory.stop_market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.BUY,
            quantity=self.quantity,
            trigger_price=Price.from_str(f"{stop_loss_price:.2f}"),
            time_in_force=TimeInForce.GTC,
            tags=f"signal_id={signal_id}|action=STOP_LOSS",
        )
        self.submit_order(stop_order)

        # Update state
        self._position_side = PositionSide.SHORT
        self._short_entry_bar = self._bars_processed

        self.log.info(
            f"🔴 SHORT ENTRY | {reason}\n"
            f"   Price: {float(bar.close):.4f} | Qty: {float(self.quantity):.4f} | SL: {stop_loss_price:.4f}\n"
            f"   CCI: {current_cci:.2f} | CCI Period: {self.cci_period}"
        )


    def _close_position(self, bar: Bar, reason: str) -> None:
        """Close current position and cancel any pending orders."""
        if self.portfolio.is_flat(self.instrument.id):
            return

        # Cancel any pending orders
        self.cancel_all_orders(self.instrument.id)

        # Get the actual position to determine side
        positions = self.cache.positions(instrument_id=self.instrument.id)
        if not positions:
            return

        position = positions[0]
        if position.side == PositionSide.LONG:
            # Prepare indicator values for tags
            current_cci = self.cci.value
            bars_held = self._bars_processed - self._long_entry_bar if self._long_entry_bar else 0
            # CLOSE tags:
            tags = [
                f"reason={reason}",
                f"cci={current_cci:.2f}",
                f"cci_upper={self.cci_upper:.2f}",
                f"cci_lower={self.cci_lower:.2f}",
                f"cci_mid={self.cci_mid:.2f}",
                f"bars_held={bars_held}",
                "action=CLOSE"
            ]

            # Close long position
            order = self.order_factory.market(
                instrument_id=self.instrument.id,
                order_side=OrderSide.SELL,
                quantity=position.quantity,
                time_in_force=TimeInForce.GTC,
                tags=tags,
            )
            self.submit_order(order)
            self.log.info(f"🟡 LONG EXIT: {reason} | Price: {float(bar.close):.4f}")


        elif position.side == PositionSide.SHORT:
            # Prepare indicator values for tags
            current_cci = self.cci.value
            bars_held = self._bars_processed - self._short_entry_bar if self._short_entry_bar else 0
            # CLOSE tags:
            tags = [
                f"reason={reason}",
                f"cci={current_cci:.2f}",
                f"cci_upper={self.cci_upper:.2f}",
                f"cci_lower={self.cci_lower:.2f}",
                f"cci_mid={self.cci_mid:.2f}",
                f"bars_held={bars_held}",
                "action=CLOSE"
            ]

            # Close short position
            order = self.order_factory.market(
                instrument_id=self.instrument.id,
                order_side=OrderSide.BUY,
                quantity=position.quantity,
                time_in_force=TimeInForce.GTC,
                tags=tags,
            )
            self.submit_order(order)
            self.log.info(f"🟡 SHORT EXIT: {reason} | Price: {float(bar.close):.4f}")


        self._position_side = None

    def _log_audit(self, bar: Bar) -> None:
        """Log audit information for this bar."""
        try:
            # Calculate current position state
            position_state = "flat"
            bars_held = 0
            entry_price = 0.0
            stop_loss_price = 0.0

            if not self.portfolio.is_flat(self.instrument.id):
                if self.portfolio.is_net_long(self.instrument.id):
                    position_state = "long"
                else:
                    position_state = "short"
                bars_held = getattr(self, "_bars_processed", 0) - getattr(
                    self, "_position_entry_bar", 0
                )
                entry_price = getattr(self, "_entry_price", 0.0)
                stop_loss_price = getattr(self, "_stop_loss_price", 0.0)

            # Basic indicators (strategy-specific indicators will be added per strategy)
            indicators = {}

            # Basic conditions
            conditions = {
                "max_bars_triggered": bars_held >= getattr(self, "max_holding_bars", 1000)
            }

            # Log to audit logger
            self.audit_logger.log(
                bar=bar,
                action="",  # Will be determined by strategy logic
                indicators=indicators,
                position_state={
                    "state": position_state,
                    "bars_held": bars_held,
                    "entry_price": entry_price,
                    "stop_loss_price": stop_loss_price,
                },
                conditions=conditions,
            )
        except Exception as e:
            self.log.error(f"Error in audit logging: {e}")

    def on_stop(self) -> None:
        """Called when strategy is stopped."""
        # Close trace file
        if self._trace_file:
            try:
                self._trace_file.close()
                self.log.info("Trace logging closed")
            except Exception as e:  # noqa: broad-except
                self.log.error(f"Error closing trace file: {e}")

        # Unsubscribe from bars
        self.unsubscribe_bars(self.bar_type)

        # Cancel all orders
        self.cancel_all_orders(self.instrument.id)

        # Close all positions
        self.close_all_positions(self.instrument.id)

        # Close audit logger
        if self.audit_logger:
            self.audit_logger.close()

        self.log.info(f"Strategy stopped | Bars processed: {self._bars_processed}")


# Default configurations
DEFAULT_CONFIGS = {
    "momentum": {
        "instrument_id": "ETHUSDT-PERP.BINANCE",
        "bar_type": "ETHUSDT-PERP.BINANCE-1-HOUR-LAST-EXTERNAL",
        "cci_period": 14,
        "cci_upper": 205.0,
        "cci_lower": -101.0,
        "cci_mid": 12.0,
        "quantity": "1.000",
        "stop_loss_percent": 7.4,
        "max_holding_bars": 25,
    }
}
