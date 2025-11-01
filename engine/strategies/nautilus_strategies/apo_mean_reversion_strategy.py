"""
APO Mean Reversion Strategy Implementation.

Based on pine_script/apo_strategy.pine with mean reversion logic.
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
from nautilus_trader.core.uuid import UUID4

from .indicators import APO


class APOMeanReversionStrategyConfig(StrategyConfig, frozen=True):
    """APO Mean Reversion Strategy configuration."""

    instrument_id: str
    bar_type: str

    # APO Parameters (from Pine Script)
    apo_fast_period: int = 10
    apo_slow_period: int = 122
    matype: int = 1  # Moving average type: 0=SMA, 1=EMA, 2=WMA, 3=DEMA
    apo_upper: float = 38.0  # Upper threshold for mean reversion
    apo_lower: float = -31.0  # Lower threshold for mean reversion
    apo_mid: float = -2.0  # Midpoint for reference

    # Position Management
    quantity: str = "1.00000000"  # Position size (100%)
    stop_loss_percent: float = 7.0  # Stop loss distance (7% as per Pine Script)

    # Risk Management
    max_holding_bars: int = 175  # Max holding period in bars (from Pine Script)

    # Trace Mode (for auditing)
    enable_trace: bool = False  # Enable detailed trace logging
    trace_output_dir: str = "reports"  # Directory for trace output


class APOMeanReversionStrategy(Strategy):
    """
    APO Mean Reversion Strategy Implementation

    Mean Reversion Mode:
    - Enter long when APO crosses above lower threshold (oversold recovery)
    - Enter short when APO crosses below upper threshold (overbought decline)
    - Exit when APO crosses to opposite threshold (breakout mode)
    """

    def __init__(self, config: APOMeanReversionStrategyConfig) -> None:
        # Always initialize the parent Strategy class
        super().__init__(config)

        # APO Parameters
        self.apo_fast_period = config.apo_fast_period
        self.apo_slow_period = config.apo_slow_period
        self.matype = config.matype
        self.apo_upper = config.apo_upper
        self.apo_lower = config.apo_lower
        self.apo_mid = config.apo_mid

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

        # Initialize APO indicator
        self.apo = APO(
            fast_period=self.apo_fast_period, slow_period=self.apo_slow_period, ma_type=self.matype
        )

        # State tracking
        self._previous_apo = 0.0
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
        self.register_indicator_for_bars(self.bar_type, self.apo)

        # Subscribe to bars for the configured bar type
        self.subscribe_bars(self.bar_type)

        # Initialize trace logging if enabled
        if self.enable_trace:
            self._setup_trace_logging()

        # Log strategy initialization
        self.log.info(f"APOMeanReversionStrategy started for {self.instrument.id}")
        self.log.info(f"Subscribed to {self.bar_type}")
        if self.enable_trace:
            self.log.info("Trace logging enabled")

    def on_bars_loaded(self, request_id: UUID4):
        """Called when the bars request completes"""
        self.log.info(f"Bars loaded successfully for request {request_id}")

    def on_bar(self, bar: Bar):
        """Handle incoming bar data."""
        # Check readiness states
        if not self.apo.initialized:
            return

        # Execute mean reversion strategy
        self._execute_mean_reversion_mode(bar)

        # Log trace
        self._log_trace(bar)

        # Update state for next bar
        self._previous_apo = self.apo.value

    def _execute_mean_reversion_mode(self, bar: Bar) -> None:
        """
        Mean Reversion Mode Logic:
        - Enter long when APO crosses above lower threshold (oversold recovery)
        - Enter short when APO crosses below upper threshold (overbought decline)
        - Exit when APO crosses to opposite threshold (breakout mode)
        """
        current_apo = self.apo.value

        # Entry conditions (mean reversion)
        if self.portfolio.is_flat(self.instrument.id):
            # Long entry: APO crosses above lower threshold (oversold recovery)
            if self._previous_apo < self.apo_lower and current_apo >= self.apo_lower:
                self._enter_long(bar, reason="APO oversold recovery")

            # Short entry: APO crosses below upper threshold (overbought decline)
            elif self._previous_apo > self.apo_upper and current_apo <= self.apo_upper:
                self._enter_short(bar, reason="APO overbought decline")

        # Exit conditions (breakout mode - opposite entry signal)
        else:
            # Exit long when short entry signal triggers (APO crosses below upper threshold)
            if (
                self._previous_apo > self.apo_upper
                and current_apo <= self.apo_upper
                and self.portfolio.is_net_long(self.instrument.id)
            ):
                self._close_position(bar, "APO opposite breakout")

            # Exit short when long entry signal triggers (APO crosses above lower threshold)
            elif (
                self._previous_apo < self.apo_lower
                and current_apo >= self.apo_lower
                and self.portfolio.is_net_short(self.instrument.id)
            ):
                self._close_position(bar, "APO opposite breakout")

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
            f"   APO: {self.apo.value:.2f} | Fast: {self.apo_fast_period}, Slow: {self.apo_slow_period}"
        )

        self._position_side = PositionSide.LONG
        self._position_entry_bar = self._bars_processed

        # Log trace
        self._log_trace(
            bar,
            action_taken="ENTER_LONG",
            entry_price=float(bar.close),
            stop_loss_price=stop_price,
        )

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
            f"   APO: {self.apo.value:.2f} | Fast: {self.apo_fast_period}, Slow: {self.apo_slow_period}"
        )

        self._position_side = PositionSide.SHORT
        self._position_entry_bar = self._bars_processed

        # Log trace
        self._log_trace(
            bar,
            action_taken="ENTER_SHORT",
            entry_price=float(bar.close),
            stop_loss_price=stop_price,
        )

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
            # Log trace
            self._log_trace(
                bar,
                action_taken="EXIT_LONG",
                exit_price=float(bar.close),
            )
        else:
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
            trace_filename = f"apo_mean_reversion_trace_{timestamp}.csv"
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
                "apo_value",
                "prev_apo_value",
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
            current_apo = self.apo.value

            # Calculate entry/exit conditions
            entry_long = self._previous_apo < self.apo_lower and current_apo >= self.apo_lower
            entry_short = self._previous_apo > self.apo_upper and current_apo <= self.apo_upper
            exit_long = self._previous_apo < self.apo_mid and current_apo >= self.apo_mid
            exit_short = self._previous_apo > self.apo_mid and current_apo <= self.apo_mid

            # Calculate bars held
            bars_held = 0
            if self._position_side is not None and self._position_entry_bar is not None:
                bars_held = self._bars_processed - self._position_entry_bar

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
                current_apo,  # apo_value
                self._previous_apo,  # prev_apo_value
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
    "mean_reversion": {
        "instrument_id": "ETHUSDT.BINANCE",
        "bar_type": "ETHUSDT.BINANCE-1-HOUR-LAST-EXTERNAL",
        "apo_fast_period": 10,
        "apo_slow_period": 122,
        "matype": 1,  # EMA
        "apo_upper": 38.0,
        "apo_lower": -31.0,
        "apo_mid": -2.0,
        "quantity": "1.00000000",
        "stop_loss_percent": 7.0,
        "max_holding_bars": 175,
    }
}
