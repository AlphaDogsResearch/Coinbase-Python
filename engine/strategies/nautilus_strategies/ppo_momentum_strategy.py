"""
PPO Momentum Strategy Implementation.

Based on pine_script/ppo_strategy.pine with momentum logic.
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

from .indicators import PPO


class PPOMomentumStrategyConfig(StrategyConfig, frozen=True):
    """PPO Momentum Strategy configuration."""

    instrument_id: str
    bar_type: str

    # PPO Parameters (from Pine Script)
    ppo_fast_period: int = 38
    ppo_slow_period: int = 205
    matype: int = 3  # Moving average type: 0=SMA, 1=EMA, 2=WMA, 3=DEMA
    ppo_upper: float = 1.4  # Upper threshold for momentum
    ppo_lower: float = -0.8  # Lower threshold for momentum
    ppo_mid: float = 0.0  # Midpoint for exit

    # Position Management
    quantity: str = "1.00000000"  # Position size (100%)
    stop_loss_percent: float = 10.4  # Stop loss distance (10.4% as per Pine Script)

    # Risk Management
    max_holding_bars: int = 93  # Max holding period in bars (from Pine Script)
    use_stop_loss: bool = True

    # Trace Mode (for auditing)
    enable_trace: bool = False  # Enable detailed trace logging
    trace_output_dir: str = "reports"  # Directory for trace output


class PPOMomentumStrategy(Strategy):
    """
    PPO Momentum Strategy Implementation

    Momentum Mode:
    - Enter long when PPO crosses above upper threshold (momentum breakout)
    - Enter short when PPO crosses below lower threshold (momentum breakdown)
    - Exit when PPO returns to midpoint
    """

    def __init__(self, config: PPOMomentumStrategyConfig) -> None:
        # Always initialize the parent Strategy class
        super().__init__(config)

        # PPO Parameters
        self.ppo_fast_period = config.ppo_fast_period
        self.ppo_slow_period = config.ppo_slow_period
        self.matype = config.matype
        self.ppo_upper = config.ppo_upper
        self.ppo_lower = config.ppo_lower
        self.ppo_mid = config.ppo_mid

        # Position Management
        self.quantity = Quantity.from_str(config.quantity)
        self.stop_loss_percent = config.stop_loss_percent

        # Risk Management
        self.max_holding_bars = config.max_holding_bars
        self.use_stop_loss = config.use_stop_loss

        # Trace Mode
        self.enable_trace = config.enable_trace
        self.trace_output_dir = config.trace_output_dir
        self._trace_file = None
        self._trace_writer = None

        # Initialize PPO indicator
        self.ppo = PPO(
            fast_period=self.ppo_fast_period, slow_period=self.ppo_slow_period, ma_type=self.matype
        )

        # State tracking
        self._previous_ppo = 0.0
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
        self.register_indicator_for_bars(self.bar_type, self.ppo)

        # Subscribe to bars for the configured bar type
        self.subscribe_bars(self.bar_type)

        # Initialize trace logging if enabled
        if self.enable_trace:
            self._setup_trace_logging()

        # Log strategy initialization
        self.log.info(f"PPOMomentumStrategy started for {self.instrument.id}")
        self.log.info(f"Subscribed to {self.bar_type}")
        if self.enable_trace:
            self.log.info("Trace logging enabled")

    def on_bars_loaded(self, request_id: UUID4):
        """Called when the bars request completes"""
        self.log.info(f"Bars loaded successfully for request {request_id}")

    def on_bar(self, bar: Bar):
        """Handle incoming bar data."""
        # Check readiness states
        if not self.ppo.initialized:
            return

        # Execute momentum strategy
        self._execute_momentum_mode(bar)

        # Log trace
        self._log_trace(bar)

        # Update state for next bar
        self._previous_ppo = self.ppo.value

    def _execute_momentum_mode(self, bar: Bar) -> None:
        """
        Momentum Mode Logic:
        - Enter long when PPO crosses above upper threshold (momentum breakout)
        - Enter short when PPO crosses below lower threshold (momentum breakdown)
        - Exit when PPO returns to midpoint
        """
        current_ppo = self.ppo.value

        # Entry conditions (momentum)
        if self.portfolio.is_flat(self.instrument.id):
            # Long entry: PPO crosses above upper threshold (momentum breakout)
            if self._previous_ppo < self.ppo_upper and current_ppo >= self.ppo_upper:
                self._enter_long(bar, reason="PPO momentum breakout")

            # Short entry: PPO crosses below lower threshold (momentum breakdown)
            elif self._previous_ppo > self.ppo_lower and current_ppo <= self.ppo_lower:
                self._enter_short(bar, reason="PPO momentum breakdown")

        # Exit conditions (midpoint)
        else:
            # Exit long: PPO crosses below midpoint
            if (
                self._previous_ppo > self.ppo_mid
                and current_ppo <= self.ppo_mid
                and self.portfolio.is_net_long(self.instrument.id)
            ):
                self._close_position(bar, "PPO returned to midpoint")

            # Exit short: PPO crosses above midpoint
            elif (
                self._previous_ppo < self.ppo_mid
                and current_ppo >= self.ppo_mid
                and self.portfolio.is_net_short(self.instrument.id)
            ):
                self._close_position(bar, "PPO returned to midpoint")

            # Max holding period exit
            elif self._bars_processed - self._position_entry_bar >= self.max_holding_bars:
                self._close_position(bar, "Max holding period reached")

    def _enter_long(self, bar: Bar, reason: str = "Momentum signal") -> None:
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
        if self.use_stop_loss:
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
            f"   PPO: {self.ppo.value:.2f} | Fast: {self.ppo_fast_period}, Slow: {self.ppo_slow_period}"
        )

        self._position_side = PositionSide.LONG
        self._position_entry_bar = self._bars_processed

        # Log trace
        self._log_trace(
            bar, action_taken="ENTER_LONG", entry_price=float(bar.close), stop_loss_price=stop_price
        )

    def _enter_short(self, bar: Bar, reason: str = "Momentum signal") -> None:
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
        if self.use_stop_loss:
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
            f"   PPO: {self.ppo.value:.2f} | Fast: {self.ppo_fast_period}, Slow: {self.ppo_slow_period}"
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
            self._log_trace(bar, action_taken="EXIT_LONG", exit_price=float(bar.close))
        else:
            self.log.info(f"🟡 SHORT EXIT: {reason} | Price: {float(bar.close):.4f}")
            self._log_trace(bar, action_taken="EXIT_SHORT", exit_price=float(bar.close))

        self._position_side = None

    def _setup_trace_logging(self) -> None:
        """Setup trace logging CSV file."""
        try:
            output_dir = Path(self.trace_output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            trace_filename = f"ppo_momentum_trace_{timestamp}.csv"
            trace_path = output_dir / trace_filename
            self._trace_file = open(trace_path, "w", newline="", encoding="utf-8")
            self._trace_writer = csv.writer(self._trace_file)
            header = [
                "timestamp",
                "bar_index",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "ppo_value",
                "prev_ppo_value",
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
        """Log detailed trace information."""
        if not self.enable_trace or not self._trace_writer:
            return
        try:
            current_ppo = self.ppo.value
            entry_long = self._previous_ppo < self.ppo_upper and current_ppo >= self.ppo_upper
            entry_short = self._previous_ppo > self.ppo_lower and current_ppo <= self.ppo_lower
            exit_long = self._previous_ppo > self.ppo_mid and current_ppo <= self.ppo_mid
            exit_short = self._previous_ppo < self.ppo_mid and current_ppo >= self.ppo_mid
            bars_held = 0
            if self._position_side is not None and self._position_entry_bar is not None:
                bars_held = self._bars_processed - self._position_entry_bar
            max_bars_trigger = bars_held >= self.max_holding_bars if bars_held > 0 else False
            pos_state = "flat"
            if self._position_side == PositionSide.LONG:
                pos_state = "long"
            elif self._position_side == PositionSide.SHORT:
                pos_state = "short"
            trace_row = [
                bar.ts_init,
                self._bars_processed,
                float(bar.open),
                float(bar.high),
                float(bar.low),
                float(bar.close),
                float(bar.volume),
                current_ppo,
                self._previous_ppo,
                pos_state,
                bars_held,
                entry_long,
                entry_short,
                exit_long,
                exit_short,
                max_bars_trigger,
                action_taken,
                entry_price,
                stop_loss_price,
                exit_price,
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
        "instrument_id": "ETHUSDT.BINANCE",
        "bar_type": "ETHUSDT.BINANCE-1-HOUR-LAST-EXTERNAL",
        "ppo_fast_period": 38,
        "ppo_slow_period": 205,
        "matype": 3,  # DEMA
        "ppo_upper": 1.4,
        "ppo_lower": -0.8,
        "ppo_mid": 0.0,
        "quantity": "1.00000000",
        "stop_loss_percent": 10.4,
        "max_holding_bars": 93,
        "use_stop_loss": True,
    }
}
