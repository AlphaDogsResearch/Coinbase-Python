"""
ROC Mean Reversion Strategy Implementation.

Based on pine_script/roc_strategy.pine with mean reversion logic.
"""

import csv
from pathlib import Path

from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.enums import OrderSide, PositionSide, TimeInForce
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.core.uuid import UUID4
from datetime import datetime, timezone

from nautilus_trader.indicators.momentum import RateOfChange


class ROCMeanReversionStrategyConfig(StrategyConfig, frozen=True):
    """ROC Mean Reversion Strategy configuration."""

    instrument_id: str
    bar_type: str

    # ROC Parameters (from Pine Script)
    roc_period: int = 22
    roc_upper: float = 3.4  # Upper threshold for mean reversion
    roc_lower: float = -3.6  # Lower threshold for mean reversion
    roc_mid: float = -2.1  # Midpoint for exit

    # Position Management
    quantity: str = "1.000"  # Position size (100%)
    stop_loss_percent: float = 2.1  # Stop loss distance (2.1% as per Pine Script)

    # Risk Management
    max_holding_bars: int = 100  # Max holding period in bars (from Pine Script)

    # Trace Mode (for debugging)
    enable_trace: bool = False  # Enable detailed trace logging
    trace_output_dir: str = "reports"  # Directory for trace output


class ROCMeanReversionStrategy(Strategy):
    """
    ROC Mean Reversion Strategy Implementation

    Mean Reversion Mode:
    - Enter long when ROC crosses above roc_lower (from below) - oversold recovery
    - Enter short when ROC crosses below roc_upper (from above) - overbought decline
    - Exit when ROC returns to midpoint (roc_mid)
    """

    def __init__(self, config: ROCMeanReversionStrategyConfig) -> None:
        # Always initialize the parent Strategy class
        super().__init__(config)

        # ROC Parameters
        self.roc_period = config.roc_period
        self.roc_upper = config.roc_upper
        self.roc_lower = config.roc_lower
        self.roc_mid = config.roc_mid

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

        # Initialize ROC indicator
        self.roc = RateOfChange(period=self.roc_period)

        # State tracking
        self._previous_roc = 0.0
        self._bars_processed = 0
        self._position_side = None  # Track current position
        self._position_entry_bar = 0  # Track when position was entered

    def on_start(self) -> None:
        """Initialize strategy on start - fetch instruments and subscribe to data."""
        # Parse instrument and bar type from config strings
        self.instrument_id = InstrumentId.from_str(self.config.instrument_id)
        self.bar_type = BarType.from_str(self.config.bar_type)

        # Fetch the instrument
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument {self.instrument_id} not found in cache")
            return

        # Register the indicators for updating
        self.register_indicator_for_bars(self.bar_type, self.roc)

        # Subscribe to bars for the configured bar type
        self.subscribe_bars(self.bar_type)

        # Initialize trace logging if enabled
        if self.enable_trace:
            self._setup_trace_logging()

        # Log strategy initialization
        self.log.info(f"ROCMeanReversionStrategy started for {self.instrument.id}")
        self.log.info(f"Subscribed to {self.bar_type}")
        if self.enable_trace:
            self.log.info("Trace logging enabled")

    def _setup_trace_logging(self) -> None:
        """Setup trace logging CSV file."""
        try:
            # Create output directory if it doesn't exist
            output_dir = Path(self.trace_output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

            # Create trace file with UTC timestamp
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            trace_filename = f"roc_mean_reversion_trace_{timestamp}.csv"
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
                "roc_value",
                "prev_roc_value",
                "position_state",
                "bars_held",
                "entry_condition_long",
                "entry_condition_short",
                "exit_condition_long",
                "exit_condition_short",
                "stop_loss_triggered",
                "max_bars_triggered",
                "action_taken",
                "entry_price",
                "stop_loss_price",
                "exit_price",
            ]
            self._trace_writer.writerow(header)

            self.log.info(f"Trace logging initialized: {trace_path}")

        except Exception as e:
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
            # Calculate current position state
            position_state = "flat"
            bars_held = 0
            if not self.portfolio.is_flat(self.instrument.id):
                if self.portfolio.is_net_long(self.instrument.id):
                    position_state = "long"
                else:
                    position_state = "short"
                bars_held = self._bars_processed - self._position_entry_bar

            # Calculate condition checks
            current_roc = self.roc.value * 100
            entry_condition_long = (
                self._previous_roc < self.roc_lower and current_roc >= self.roc_lower
            )
            entry_condition_short = (
                self._previous_roc > self.roc_upper and current_roc <= self.roc_upper
            )

            exit_condition_long = False
            exit_condition_short = False
            if not self.portfolio.is_flat(self.instrument.id):
                if self.portfolio.is_net_long(self.instrument.id):
                    exit_condition_long = (
                        self._previous_roc > self.roc_mid and current_roc <= self.roc_mid
                    )
                else:
                    exit_condition_short = (
                        self._previous_roc < self.roc_mid and current_roc >= self.roc_mid
                    )

            # Check max bars condition
            max_bars_triggered = bars_held >= self.max_holding_bars

            # Stop loss check (simplified - would need more complex logic for actual stop loss hits)
            stop_loss_triggered = False

            # Write trace row
            trace_row = [
                bar.ts_init,  # timestamp
                self._bars_processed,  # bar_index
                float(bar.open),  # open
                float(bar.high),  # high
                float(bar.low),  # low
                float(bar.close),  # close
                float(bar.volume),  # volume
                current_roc,  # roc_value
                self._previous_roc,  # prev_roc_value
                position_state,  # position_state
                bars_held,  # bars_held
                entry_condition_long,  # entry_condition_long
                entry_condition_short,  # entry_condition_short
                exit_condition_long,  # exit_condition_long
                exit_condition_short,  # exit_condition_short
                stop_loss_triggered,  # stop_loss_triggered
                max_bars_triggered,  # max_bars_triggered
                action_taken,  # action_taken
                entry_price,  # entry_price
                stop_loss_price,  # stop_loss_price
                exit_price,  # exit_price
            ]
            self._trace_writer.writerow(trace_row)
            self._trace_file.flush()

        except Exception as e:
            self.log.error(f"Failed to write trace log: {e}")

    def on_bars_loaded(self, request_id: UUID4):
        """Called when the bars request completes"""
        self.log.info(f"Bars loaded successfully for request {request_id}")

    def on_bar(self, bar: Bar):
        """Handle incoming bar data."""
        # Check readiness states
        if not self.roc.initialized:
            return

        # Execute mean reversion strategy
        self._execute_mean_reversion_mode(bar)

        # Log trace for this bar
        if self.enable_trace:
            self._log_trace(bar)

        # Update state for next bar (convert to percentage)
        self._previous_roc = self.roc.value * 100
        self._bars_processed += 1

    def _execute_mean_reversion_mode(self, bar: Bar) -> None:
        """
        Mean Reversion Mode Logic:
        - Enter long when ROC crosses above roc_lower (oversold recovery)
        - Enter short when ROC crosses below roc_upper (overbought decline)
        - Exit when ROC returns to midpoint
        """
        # Convert ROC to percentage to match Pine Script values
        current_roc = self.roc.value * 100

        # Entry conditions (mean reversion)
        if self.portfolio.is_flat(self.instrument.id):
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
                and self.portfolio.is_net_long(self.instrument.id)
            ):
                self._close_position(bar, "ROC returned to midpoint")

            # Exit short: ROC crosses above midpoint
            elif (
                self._previous_roc < self.roc_mid
                and current_roc >= self.roc_mid
                and self.portfolio.is_net_short(self.instrument.id)
            ):
                self._close_position(bar, "ROC returned to midpoint")

            # Max holding period exit
            elif self._bars_processed - self._position_entry_bar >= self.max_holding_bars:
                self._close_position(bar, "Max holding period reached")

    def _enter_long(self, bar: Bar, reason: str = "Mean reversion signal") -> None:
        """Enter long position with stop loss."""
        if self.portfolio.is_net_long(self.instrument.id):
            self.log.warning("Already in long position")
            return

        # Calculate stop loss
        stop_price = float(bar.close) * (1 - self.stop_loss_percent / 100)

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
            trigger_price=Price(stop_price, precision=2),
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(stop_order)

        self.log.info(
            f"🟢 LONG ENTRY | {reason}\n"
            f"   Price: {float(bar.close):.4f} | Qty: {self.quantity.as_double():.4f} | "
            f"SL: {stop_price:.4f}\n"
            f"   ROC: {self.roc.value * 100:.2f} | ROC Period: {self.roc_period}"
        )

        # Log trace with entry action
        if self.enable_trace:
            self._log_trace(bar, "ENTER_LONG", float(bar.close), stop_price)

        self._position_side = PositionSide.LONG
        self._position_entry_bar = self._bars_processed

    def _enter_short(self, bar: Bar, reason: str = "Mean reversion signal") -> None:
        """Enter short position with stop loss."""
        if self.portfolio.is_net_short(self.instrument.id):
            self.log.warning("Already in short position")
            return

        # Calculate stop loss
        stop_price = float(bar.close) * (1 + self.stop_loss_percent / 100)

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
            trigger_price=Price(stop_price, precision=2),
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(stop_order)

        self.log.info(
            f"🔴 SHORT ENTRY | {reason}\n"
            f"   Price: {float(bar.close):.4f} | Qty: {self.quantity.as_double():.4f} | "
            f"SL: {stop_price:.4f}\n"
            f"   ROC: {self.roc.value * 100:.2f} | ROC Period: {self.roc_period}"
        )

        # Log trace with entry action
        if self.enable_trace:
            self._log_trace(bar, "ENTER_SHORT", float(bar.close), stop_price)

        self._position_side = PositionSide.SHORT
        self._position_entry_bar = self._bars_processed

    def _close_position(self, bar: Bar, reason: str) -> None:
        """Close current position and cancel any pending stop loss orders."""
        if self.portfolio.is_flat(self.instrument.id):
            return

        # Cancel any pending orders
        self.cancel_all_orders(self.instrument.id)

        # Get the actual position to determine side
        positions = self.cache.positions(instrument_id=self.instrument.id)
        if not positions:
            return

        position = positions[0]  # Get first (should be only one per instrument)

        order = self.order_factory.market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.SELL if position.is_long else OrderSide.BUY,
            quantity=position.quantity,
            time_in_force=TimeInForce.GTC,
        )

        self.submit_order(order)

        if position.is_long:
            self.log.info(f"🟡 LONG EXIT: {reason} | Price: {float(bar.close):.4f}")
            # Log trace with exit action
            if self.enable_trace:
                self._log_trace(bar, "EXIT_LONG", 0.0, 0.0, float(bar.close))
        else:
            self.log.info(f"🟡 SHORT EXIT: {reason} | Price: {float(bar.close):.4f}")
            # Log trace with exit action
            if self.enable_trace:
                self._log_trace(bar, "EXIT_SHORT", 0.0, 0.0, float(bar.close))

        self._position_side = None

    def on_stop(self) -> None:
        """Called when strategy is stopped."""
        # Unsubscribe from bars
        self.unsubscribe_bars(self.bar_type)

        # Cancel all orders
        self.cancel_all_orders(self.instrument.id)

        # Close all positions
        self.close_all_positions(self.instrument.id)

        # Close trace file if open
        if self._trace_file:
            self._trace_file.close()
            self.log.info("Trace file closed")

        self.log.info(f"Strategy stopped | Bars processed: {self._bars_processed}")


# Default configurations
DEFAULT_CONFIGS = {
    "mean_reversion": {
        "instrument_id": "ETHUSDT.BINANCE",
        "bar_type": "ETHUSDT.BINANCE-1-HOUR-LAST-EXTERNAL",
        "roc_period": 22,
        "roc_upper": 3.4,
        "roc_lower": -3.6,
        "roc_mid": -2.1,
        "quantity": "1.00000000",
        "stop_loss_percent": 2.1,
        "max_holding_bars": 100,
    }
}
