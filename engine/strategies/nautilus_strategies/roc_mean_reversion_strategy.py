"""
ROC Mean Reversion Strategy Implementation.

Based on pine_script/roc_strategy.pine with mean reversion logic.
"""

from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.enums import OrderSide, PositionSide, TimeInForce
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.core.uuid import UUID4

from nautilus_trader.indicators.momentum import RateOfChange
from engine.strategies.audit_logger import StrategyAuditLogger


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

        # Initialize audit logger
        self.audit_logger = StrategyAuditLogger(
            strategy_name=self.__class__.__name__, symbol=config.instrument_id.split(".")[0]
        )

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

        # Log strategy initialization
        self.log.info(f"ROCMeanReversionStrategy started for {self.instrument.id}")
        self.log.info(f"Subscribed to {self.bar_type}")

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

        # Log audit information
        self._log_audit(bar)

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

        # Generate signal_id for this trade
        signal_id = str(uuid.uuid4())

        # Prepare indicator values for tags
        current_roc = self.roc.value * 100
        tags = [
            f"signal_id={signal_id}",
            f"reason={reason}",
            f"roc={current_roc:.2f}",
            f"roc_lower={self.roc_lower:.2f}",
            f"roc_upper={self.roc_upper:.2f}",
            f"roc_mid={self.roc_mid:.2f}",
            f"bars_held={self._bars_processed - self._position_entry_bar if self._position_entry_bar else 0}",
            "action=ENTRY"
        ]

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

        self._position_side = PositionSide.LONG
        self._position_entry_bar = self._bars_processed

    def _enter_short(self, bar: Bar, reason: str = "Mean reversion signal") -> None:
        """Enter short position with stop loss."""
        if self.portfolio.is_net_short(self.instrument.id):
            self.log.warning("Already in short position")
            return

        # Calculate stop loss
        stop_price = float(bar.close) * (1 + self.stop_loss_percent / 100)

        # Prepare indicator values for tags
        current_roc = self.roc.value * 100
        signal_id = str(uuid.uuid4())
        tags = [
            f"signal_id={signal_id}",
            f"reason={reason}",
            f"roc={current_roc:.2f}",
            f"roc_lower={self.roc_lower:.2f}",
            f"roc_upper={self.roc_upper:.2f}",
            f"roc_mid={self.roc_mid:.2f}",
            f"bars_held={self._bars_processed - self._position_entry_bar if self._position_entry_bar else 0}",
            "action=ENTRY"
        ]

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
            trigger_price=Price(stop_price, precision=2),
            time_in_force=TimeInForce.GTC,
            tags=f"signal_id={signal_id}|",
        )
        self.submit_order(stop_order)

        self.log.info(
            f"🔴 SHORT ENTRY | {reason}\n"
            f"   Price: {float(bar.close):.4f} | Qty: {self.quantity.as_double():.4f} | "
            f"SL: {stop_price:.4f}\n"
            f"   ROC: {self.roc.value * 100:.2f} | ROC Period: {self.roc_period}"
        )

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

        # Prepare indicator values for tags
        current_roc = self.roc.value * 100
        bars_held = (
            self._bars_processed - self._position_entry_bar if self._position_entry_bar else 0
        )
        tags = [
            f"reason={reason}",
            f"roc={current_roc:.2f}",
            f"roc_lower={self.roc_lower:.2f}",
            f"roc_upper={self.roc_upper:.2f}",
            f"roc_mid={self.roc_mid:.2f}",
            f"bars_held={bars_held}",
            "action=CLOSE"
        ]

        order = self.order_factory.market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.SELL if position.is_long else OrderSide.BUY,
            quantity=position.quantity,
            time_in_force=TimeInForce.GTC,
            tags=tags,
        )

        self.submit_order(order)

        if position.is_long:
            self.log.info(f"🟡 LONG EXIT: {reason} | Price: {float(bar.close):.4f}")
        else:
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
                bars_held = self._bars_processed - self._position_entry_bar
                entry_price = self._entry_price if hasattr(self, "_entry_price") else 0.0
                stop_loss_price = (
                    self._stop_loss_price if hasattr(self, "_stop_loss_price") else 0.0
                )

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

            # Determine action taken
            action = ""
            if entry_condition_long:
                action = "ENTRY_LONG"
            elif entry_condition_short:
                action = "ENTRY_SHORT"
            elif exit_condition_long or exit_condition_short:
                action = "EXIT"
            elif max_bars_triggered:
                action = "EXIT_MAX_BARS"

            # Log to audit logger
            self.audit_logger.log(
                bar=bar,
                action=action,
                indicators={
                    "roc": current_roc,
                    "roc_lower": self.roc_lower,
                    "roc_upper": self.roc_upper,
                    "roc_mid": self.roc_mid,
                    "roc_period": self.roc_period,
                },
                position_state={
                    "state": position_state,
                    "bars_held": bars_held,
                    "entry_price": entry_price,
                    "stop_loss_price": stop_loss_price,
                },
                conditions={
                    "entry_long": entry_condition_long,
                    "entry_short": entry_condition_short,
                    "exit_long": exit_condition_long,
                    "exit_short": exit_condition_short,
                    "max_bars_triggered": max_bars_triggered,
                },
            )
        except Exception as e:
            self.log.error(f"Error in audit logging: {e}")

    def on_stop(self) -> None:
        """Called when strategy is stopped."""
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
