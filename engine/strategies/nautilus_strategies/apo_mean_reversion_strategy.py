"""
APO Mean Reversion Strategy Implementation.

Based on pine_script/apo_strategy.pine with mean reversion logic.
"""

import uuid
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.enums import OrderSide, PositionSide, TimeInForce
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.core.uuid import UUID4
from engine.strategies.audit_logger import StrategyAuditLogger

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

        # Initialize audit logger
        self.audit_logger = StrategyAuditLogger(
            strategy_name=self.__class__.__name__, symbol=config.instrument_id.split(".")[0]
        )
        self.stop_loss_percent = config.stop_loss_percent

        # Risk Management
        self.max_holding_bars = config.max_holding_bars

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

        # Log strategy initialization
        self.log.info(f"APOMeanReversionStrategy started for {self.instrument.id}")
        self.log.info(f"Subscribed to {self.bar_type}")

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

        # Log audit information
        self._log_audit(bar)

        # Update state for next bar
        self._previous_apo = self.apo.value
        self._bars_processed += 1

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

        # Generate signal_id for this trade
        signal_id = str(uuid.uuid4())

        # Prepare indicator values for tags
        current_apo = self.apo.value
        bars_held = (
            self._bars_processed - self._position_entry_bar if self._position_entry_bar else 0
        )
        tags = [
            f"signal_id={signal_id}",
            f"apo_mid={self.apo_mid:.2f}",
            f"bars_held={bars_held}",
            "action=ENTRY",
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
            tags=f"signal_id={signal_id}|action=STOP_LOSS",
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


    def _enter_short(self, bar: Bar, reason: str = "Mean reversion signal") -> None:
        """Enter short position with stop loss."""
        if self.portfolio.is_net_short(self.instrument.id):
            self.log.warning("Already in short position")
            return

        # Calculate stop loss
        stop_price = float(bar.close) * (1 + self.stop_loss_percent / 100)

        # Generate signal_id for this trade
        signal_id = str(uuid.uuid4())

        # Prepare indicator values for tags
        current_apo = self.apo.value
        bars_held = (
            self._bars_processed - self._position_entry_bar if self._position_entry_bar else 0
        )
        tags = [
            f"signal_id={signal_id}",
            f"apo_mid={self.apo_mid:.2f}",
            f"bars_held={bars_held}",
            "action=ENTRY",
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
            tags=f"signal_id={signal_id}|action=STOP_LOSS",
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
        current_apo = self.apo.value
        bars_held = (
            self._bars_processed - self._position_entry_bar if self._position_entry_bar else 0
        )
        tags = [
            f"reason={reason}",
            f"apo={current_apo:.2f}",
            f"apo_upper={self.apo_upper:.2f}",
            f"apo_lower={self.apo_lower:.2f}",
            f"apo_mid={self.apo_mid:.2f}",
            f"bars_held={bars_held}",
            "action=CLOSE",
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
            current_apo = self.apo.value
            entry_condition_long = (
                self._previous_apo < self.apo_lower and current_apo >= self.apo_lower
            )
            entry_condition_short = (
                self._previous_apo > self.apo_upper and current_apo <= self.apo_upper
            )

            exit_condition_long = False
            exit_condition_short = False
            if not self.portfolio.is_flat(self.instrument.id):
                if self.portfolio.is_net_long(self.instrument.id):
                    exit_condition_long = (
                        self._previous_apo > self.apo_upper and current_apo <= self.apo_upper
                    )
                else:
                    exit_condition_short = (
                        self._previous_apo < self.apo_lower and current_apo >= self.apo_lower
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
                    "apo": current_apo,
                    "apo_lower": self.apo_lower,
                    "apo_upper": self.apo_upper,
                    "apo_mid": self.apo_mid,
                    "apo_fast_period": self.apo_fast_period,
                    "apo_slow_period": self.apo_slow_period,
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
