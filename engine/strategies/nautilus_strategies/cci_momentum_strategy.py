"""
CCI Momentum Strategy Implementation.

Based on pine_script/cci_strategy.pine with momentum logic.
"""

import csv
from pathlib import Path
from datetime import datetime, timezone

from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.enums import OrderSide, PositionSide, TimeInForce
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.objects import Price, Quantity

from nautilus_trader.indicators import CommodityChannelIndex


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
        self.stop_loss_percent = config.stop_loss_percent

        # Risk Management
        self.max_holding_bars = config.max_holding_bars

        # Trace Mode
        self.enable_trace = config.enable_trace
        self.trace_output_dir = config.trace_output_dir
        self._trace_file = None
        self._trace_writer = None

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

        # Initialize trace logging if enabled
        if self.enable_trace:
            self._setup_trace_logging()

        self.log.info(f"CCIMomentumStrategy started for {self.instrument.id}")
        if self.enable_trace:
            self.log.info("Trace logging enabled")

    def on_bar(self, bar: Bar) -> None:
        """Called when a bar is received."""
        # Check if CCI indicator is ready
        if not self.cci.initialized:
            return

        # Execute momentum strategy
        self._execute_momentum_mode(bar)

        # Log trace
        self._log_trace(bar)

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

        # Submit market order
        order = self.order_factory.market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.BUY,
            quantity=self.quantity,
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)

        # Submit stop loss order
        stop_order = self.order_factory.stop_market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.SELL,
            quantity=self.quantity,
            trigger_price=Price.from_str(f"{stop_loss_price:.2f}"),
            time_in_force=TimeInForce.GTC,
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

        # Log trace
        self._log_trace(
            bar,
            action_taken="ENTER_LONG",
            entry_price=float(bar.close),
            stop_loss_price=stop_loss_price,
        )

    def _enter_short(self, bar: Bar, current_cci: float, reason: str) -> None:
        """Enter short position with stop loss."""
        if not self.portfolio.is_flat(self.instrument.id):
            return

        # Calculate stop loss price
        stop_loss_price = bar.close * (1 + self.stop_loss_percent / 100)

        # Submit market order
        order = self.order_factory.market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.SELL,
            quantity=self.quantity,
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)

        # Submit stop loss order
        stop_order = self.order_factory.stop_market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.BUY,
            quantity=self.quantity,
            trigger_price=Price.from_str(f"{stop_loss_price:.2f}"),
            time_in_force=TimeInForce.GTC,
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

        # Log trace
        self._log_trace(
            bar,
            action_taken="ENTER_SHORT",
            entry_price=float(bar.close),
            stop_loss_price=stop_loss_price,
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
            # Close long position
            order = self.order_factory.market(
                instrument_id=self.instrument.id,
                order_side=OrderSide.SELL,
                quantity=position.quantity,
                time_in_force=TimeInForce.GTC,
            )
            self.submit_order(order)
            self.log.info(f"🟡 LONG EXIT: {reason} | Price: {float(bar.close):.4f}")

            # Log trace
            self._log_trace(
                bar,
                action_taken="EXIT_LONG",
                exit_price=float(bar.close),
            )

        elif position.side == PositionSide.SHORT:
            # Close short position
            order = self.order_factory.market(
                instrument_id=self.instrument.id,
                order_side=OrderSide.BUY,
                quantity=position.quantity,
                time_in_force=TimeInForce.GTC,
            )
            self.submit_order(order)
            self.log.info(f"🟡 SHORT EXIT: {reason} | Price: {float(bar.close):.4f}")

            # Log trace
            self._log_trace(
                bar,
                action_taken="EXIT_SHORT",
                exit_price=float(bar.close),
            )

        self._position_side = None

    def _setup_trace_logging(self) -> None:
        """Setup trace logging CSV file."""
        try:
            # Create output directory if it doesn't exist
            output_dir = Path(self.trace_output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

            # Create trace file with UTC timestamp
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            trace_filename = f"cci_momentum_trace_{timestamp}.csv"
            trace_path = output_dir / trace_filename

            self._trace_file = open(trace_path, "w", newline="", encoding="utf-8")
            self._trace_writer = csv.writer(self._trace_file)

            # Write header
            header = [
                "timestamp",
                "bar_index",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "cci_value",
                "prev_cci_value",
                "position_state",
                "bars_held",
                "entry_condition_long",
                "entry_condition_short",
                "exit_condition_long",
                "exit_condition_short",
                "max_bars_triggered",
                "action_taken",
                "entry_price",
                "stop_loss_price",
                "exit_price",
            ]
            self._trace_writer.writerow(header)
            self._trace_file.flush()

            self.log.info(f"Trace logging initialized: {trace_path}")
        except Exception as e:  # noqa: broad-except
            self.log.error(f"Failed to setup trace logging: {e}")
            self.enable_trace = False

    def _log_trace(
        self,
        bar: Bar,
        action_taken: str = "",
        entry_price: float = 0.0,
        stop_loss_price: float = 0.0,
        exit_price: float = 0.0,
    ) -> None:
        """Log detailed trace information for this bar."""
        if not self.enable_trace or not self._trace_writer:
            return

        try:
            current_cci = self.cci.value

            # Calculate entry/exit conditions
            entry_long = self._previous_cci < self.cci_upper and current_cci >= self.cci_upper
            entry_short = self._previous_cci > self.cci_lower and current_cci <= self.cci_lower
            exit_long = self._previous_cci > self.cci_mid and current_cci <= self.cci_mid
            exit_short = self._previous_cci < self.cci_mid and current_cci >= self.cci_mid

            # Calculate bars held
            bars_held = 0
            if self._position_side == PositionSide.LONG and self._long_entry_bar is not None:
                bars_held = self._bars_processed - self._long_entry_bar
            elif self._position_side == PositionSide.SHORT and self._short_entry_bar is not None:
                bars_held = self._bars_processed - self._short_entry_bar

            # Check max bars
            max_bars_trigger = bars_held >= self.max_holding_bars if bars_held > 0 else False

            # Position state
            pos_state = "flat"
            if self._position_side == PositionSide.LONG:
                pos_state = "long"
            elif self._position_side == PositionSide.SHORT:
                pos_state = "short"

            trace_row = [
                bar.ts_init,  # timestamp
                self._bars_processed,  # bar_index
                float(bar.open),  # open
                float(bar.high),  # high
                float(bar.low),  # low
                float(bar.close),  # close
                float(bar.volume),  # volume
                current_cci,  # cci_value
                self._previous_cci,  # prev_cci_value
                pos_state,  # position_state
                bars_held,  # bars_held
                entry_long,  # entry_condition_long
                entry_short,  # entry_condition_short
                exit_long,  # exit_condition_long
                exit_short,  # exit_condition_short
                max_bars_trigger,  # max_bars_triggered
                action_taken,  # action_taken
                entry_price,  # entry_price
                stop_loss_price,  # stop_loss_price
                exit_price,  # exit_price
            ]
            self._trace_writer.writerow(trace_row)
            self._trace_file.flush()
        except Exception as e:  # noqa: broad-except
            self.log.error(f"Failed to write trace log: {e}")

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
