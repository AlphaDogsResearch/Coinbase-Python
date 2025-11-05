"""
Simple Order Test Strategy.

A minimal Nautilus strategy for testing order execution flow.
Alternates between long and short positions every N bars.
"""

import uuid
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.enums import OrderSide, PositionSide, TimeInForce
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.objects import Quantity, Price
from nautilus_trader.core.uuid import UUID4
from engine.strategies.audit_logger import StrategyAuditLogger


class SimpleOrderTestStrategyConfig(StrategyConfig, frozen=True):
    """Simple Order Test Strategy configuration."""

    instrument_id: str
    bar_type: str

    # Test Parameters
    bars_per_trade: int = 20  # Execute trade every N bars
    quantity: str = "1.000"  # Position size


class SimpleOrderTestStrategy(Strategy):
    """
    A simple test strategy that follows a specific trading pattern.

    This strategy is designed to test order execution flow with a predictable pattern:
    - Bar 20: Open LONG position
    - Bar 40: Close LONG position
    - Bar 60: Open SHORT position
    - Bar 80: Close SHORT position
    - Bar 100: Open LONG position (repeat cycle)

    Pattern: LONG -> CLOSE -> SHORT -> CLOSE -> repeat every N bars

    Perfect for validating:
    - Order creation and submission
    - Position tracking
    - Signal emission
    - Stop loss handling
    - Position closing logic
    """

    def __init__(self, config: SimpleOrderTestStrategyConfig):
        """Initialize the test strategy."""
        super().__init__(config)

        # Configuration
        self.bars_per_trade = config.bars_per_trade
        self.quantity = Quantity.from_str(config.quantity)

        # Initialize audit logger
        self.audit_logger = StrategyAuditLogger(
            strategy_name=self.__class__.__name__, symbol=config.instrument_id.split(".")[0]
        )
        # State tracking
        self._bar_counter = 0
        self._trade_counter = 0

        # Initialize attributes that will be set in on_start
        self.instrument_id = None
        self.bar_type = None
        self.instrument = None

    def on_start(self) -> None:
        """Initialize strategy on start."""
        # Parse instrument and bar type from config strings
        self.instrument_id = InstrumentId.from_str(self.config.instrument_id)
        self.bar_type = BarType.from_str(self.config.bar_type)

        # Fetch the instrument
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument {self.instrument_id} not found in cache")
            return

        # Subscribe to bars
        self.subscribe_bars(self.bar_type)

        self.log.info(
            f"🧪 TEST STRATEGY STARTED: Pattern LONG->CLOSE->SHORT->CLOSE every {self.bars_per_trade} bars"
        )

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
        """Cleanup on strategy stop."""
        self.log.info(
            f"🧪 TEST STRATEGY STOPPED: Processed {self._bar_counter} bars, "
            f"executed {self._trade_counter} trades"
        )

        # Close any open positions
        if not self.portfolio.is_flat(self.instrument.id):
            self.log.info("Closing open positions on stop")
            self.close_all_positions(self.instrument.id)

    def on_bars_loaded(self, request_id: UUID4):
        """Called when the bars request completes."""
        self.log.info(f"Bars loaded successfully for request {request_id}")

    def on_bar(self, bar: Bar):
        """Handle incoming bar data."""
        self._bar_counter += 1

        # Log every bar
        self.log.info(f"🧪 TEST - Bar #{self._bar_counter}")

        # Execute trade every N bars
        if self._bar_counter % self.bars_per_trade == 0:
            self._execute_test_trade(bar)

    def _execute_test_trade(self, bar: Bar):
        """Execute a test trade following the pattern: long -> close -> short -> close -> repeat."""
        self._trade_counter += 1

        # Determine action based on trade counter
        if self._trade_counter % 4 == 1:
            # Trade 1, 5, 9, ... -> Open LONG
            if self.portfolio.is_flat(self.instrument.id):
                self.log.info(f"🧪 TEST Trade #{self._trade_counter}: Opening LONG position")
                self._enter_long(bar, reason="Test trade - periodic long entry")
            else:
                self.log.warning(
                    f"🧪 TEST Trade #{self._trade_counter}: Skipping LONG - position already exists"
                )
        elif self._trade_counter % 4 == 2:
            # Trade 2, 6, 10, ... -> Close LONG
            if not self.portfolio.is_flat(self.instrument.id) and self.portfolio.is_net_long(
                self.instrument.id
            ):
                self.log.info(f"🧪 TEST Trade #{self._trade_counter}: Closing LONG position")
                self._close_position(bar, reason="Test trade - close long after n bars")
            else:
                self.log.warning(
                    f"🧪 TEST Trade #{self._trade_counter}: Skipping LONG close - no long position"
                )
        elif self._trade_counter % 4 == 3:
            # Trade 3, 7, 11, ... -> Open SHORT
            if self.portfolio.is_flat(self.instrument.id):
                self.log.info(f"🧪 TEST Trade #{self._trade_counter}: Opening SHORT position")
                self._enter_short(bar, reason="Test trade - periodic short entry")
            else:
                self.log.warning(
                    f"🧪 TEST Trade #{self._trade_counter}: Skipping SHORT - position already exists"
                )
        else:  # self._trade_counter % 4 == 0
            # Trade 4, 8, 12, ... -> Close SHORT
            if not self.portfolio.is_flat(self.instrument.id) and self.portfolio.is_net_short(
                self.instrument.id
            ):
                self.log.info(f"🧪 TEST Trade #{self._trade_counter}: Closing SHORT position")
                self._close_position(bar, reason="Test trade - close short after n bars")
            else:
                self.log.warning(
                    f"🧪 TEST Trade #{self._trade_counter}: Skipping SHORT close - no short position"
                )

    def _enter_long(self, bar: Bar, reason: str):
        """Enter a long position."""
        self.log.info(f"📈 Entering LONG: {reason}")

        # Generate signal_id for this trade
        signal_id = str(uuid.uuid4())

        # Prepare tags for test strategy
        tags = [
            f"signal_id={signal_id}",
            f"reason={reason}",
            f"bar_count={self._bar_counter}",
            f"trade_count={self._trade_counter}",
            "action=ENTRY"
        ]

        # Create market order for entry
        market_order = self.order_factory.market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.BUY,
            quantity=self.quantity,
            tags=tags,
        )

        # Submit market order
        self.submit_order(market_order)

        # Submit stop loss order at 1% below entry price
        stop_price = bar.close.as_double() * 0.99  # 1% stop loss
        stop_order = self.order_factory.stop_market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.SELL,
            quantity=self.quantity,
            trigger_price=Price(stop_price, precision=2),
            time_in_force=TimeInForce.GTC,
            tags=f"signal_id={signal_id}|action=STOP_LOSS",
        )
        self.submit_order(stop_order)

    def _enter_short(self, bar: Bar, reason: str):
        """Enter a short position."""
        self.log.info(f"📉 Entering SHORT: {reason}")

        # Generate signal_id for this trade
        signal_id = str(uuid.uuid4())

        # Prepare tags for test strategy
        tags = [
            f"signal_id={signal_id}",
            f"reason={reason}",
            f"bar_count={self._bar_counter}",
            f"trade_count={self._trade_counter}",
            "action=ENTRY"
        ]

        # Create market order for entry
        market_order = self.order_factory.market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.SELL,
            quantity=self.quantity,
            tags=tags,
        )

        # Submit market order
        self.submit_order(market_order)

        # Submit stop loss order at 1% above entry price
        stop_price = bar.close.as_double() * 1.01  # 1% stop loss
        stop_order = self.order_factory.stop_market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.BUY,
            quantity=self.quantity,
            trigger_price=Price(stop_price, precision=2),
            time_in_force=TimeInForce.GTC,
            tags=f"signal_id={signal_id}|action=STOP_LOSS",
        )
        self.submit_order(stop_order)

    def _close_position(self, bar: Bar, reason: str):  # noqa: unused-argument
        """Close the current position."""
        position = self.portfolio.position(self.instrument.id)
        if position is None:
            return

        self.log.info(f"🔄 Closing position: {reason}")

        # Determine side to close
        if position.side == PositionSide.LONG:
            close_side = OrderSide.SELL
        else:
            close_side = OrderSide.BUY

        # Prepare tags for close
        tags = [
            f"reason={reason}",
            f"bar_count={self._bar_counter}",
            f"trade_count={self._trade_counter}",
            "action=CLOSE"
        ]

        # Create market order to close
        close_order = self.order_factory.market(
            instrument_id=self.instrument.id,
            order_side=close_side,
            quantity=position.quantity,
            tags=tags,
        )

        self.submit_order(close_order)
