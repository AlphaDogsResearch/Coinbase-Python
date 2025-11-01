"""
Simple Order Test Strategy.

A minimal Nautilus strategy for testing order execution flow.
Alternates between long and short positions every N bars.
"""

from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.enums import OrderSide, PositionSide
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.core.uuid import UUID4


class SimpleOrderTestStrategyConfig(StrategyConfig, frozen=True):
    """Simple Order Test Strategy configuration."""

    instrument_id: str
    bar_type: str

    # Test Parameters
    bars_per_trade: int = 5  # Execute trade every N bars
    quantity: str = "1.000"  # Position size
    stop_loss_percent: float = 2.0  # Stop loss distance


class SimpleOrderTestStrategy(Strategy):
    """
    A simple test strategy that alternates between long and short positions.

    This strategy is designed to test order execution flow without complex logic:
    - Every N bars, it opens a position (alternating between long and short)
    - If a position exists, it closes before opening the next one
    - Includes stop loss orders for risk management testing

    Perfect for validating:
    - Order creation and submission
    - Position tracking
    - Signal emission
    - Stop loss handling
    """

    def __init__(self, config: SimpleOrderTestStrategyConfig):
        """Initialize the test strategy."""
        super().__init__(config)

        # Configuration
        self.bars_per_trade = config.bars_per_trade
        self.quantity = Quantity.from_str(config.quantity)
        self.stop_loss_percent = config.stop_loss_percent

        # State tracking
        self._bar_counter = 0
        self._trade_counter = 0

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

        self.log.info(f"🧪 TEST STRATEGY STARTED: Will trade every {self.bars_per_trade} bars")

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
        """Execute a test trade (alternating long/short)."""
        self._trade_counter += 1

        # Close existing position if any
        if not self.portfolio.is_flat(self.instrument.id):
            self.log.info(f"🧪 TEST Trade #{self._trade_counter}: Closing existing position")
            self._close_position(bar, reason="Test trade cycle")

        # Alternate between long and short
        if self._trade_counter % 2 == 1:
            self.log.info(f"🧪 TEST Trade #{self._trade_counter}: Opening LONG position")
            self._enter_long(bar, reason="Test trade - periodic long entry")
        else:
            self.log.info(f"🧪 TEST Trade #{self._trade_counter}: Opening SHORT position")
            self._enter_short(bar, reason="Test trade - periodic short entry")

    def _enter_long(self, bar: Bar, reason: str):
        """Enter a long position with stop loss."""
        self.log.info(f"📈 Entering LONG: {reason}")

        # Calculate stop loss
        stop_loss_price = bar.close.as_double() * (1 - self.stop_loss_percent / 100)

        # Create market order for entry
        market_order = self.order_factory.market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.BUY,
            quantity=self.quantity,
        )

        # Create stop loss order
        stop_order = self.order_factory.stop_market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.SELL,
            quantity=self.quantity,
            trigger_price=Price(stop_loss_price, precision=self.instrument.price_precision),
        )

        # Submit orders
        self.submit_order(market_order)
        self.submit_order(stop_order)

    def _enter_short(self, bar: Bar, reason: str):
        """Enter a short position with stop loss."""
        self.log.info(f"📉 Entering SHORT: {reason}")

        # Calculate stop loss
        stop_loss_price = bar.close.as_double() * (1 + self.stop_loss_percent / 100)

        # Create market order for entry
        market_order = self.order_factory.market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.SELL,
            quantity=self.quantity,
        )

        # Create stop loss order
        stop_order = self.order_factory.stop_market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.BUY,
            quantity=self.quantity,
            trigger_price=Price(stop_loss_price, precision=self.instrument.price_precision),
        )

        # Submit orders
        self.submit_order(market_order)
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

        # Create market order to close
        close_order = self.order_factory.market(
            instrument_id=self.instrument.id,
            order_side=close_side,
            quantity=position.quantity,
        )

        self.submit_order(close_order)
