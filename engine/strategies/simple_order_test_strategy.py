from dataclasses import dataclass

from .base import Strategy
from engine.market_data.candle import MidPriceCandle
from common.interface_order import OrderSizeMode
from .strategy_action import StrategyAction
from .strategy_order_mode import StrategyOrderMode


@dataclass(frozen=True)
class SimpleOrderTestStrategyConfig:
    """Simple Order Test Strategy configuration."""

    instrument_id: str
    bar_type: str

    # Test Parameters
    bars_per_trade: int = 20  # Execute trade every N bars
    quantity: float = 1.0  # Position size (deprecated, use notional_amount)
    notional_amount: float = 500.0  # Order size in notional value


class SimpleOrderTestStrategy(Strategy):
    """
    A simple test strategy that follows a specific trading pattern.
    """

    def __init__(self, config: SimpleOrderTestStrategyConfig):
        """Initialize the test strategy."""
        super().__init__(config)

        self.config = config
        self.bars_per_trade = config.bars_per_trade
        self.quantity = config.quantity  # Deprecated, kept for backward compatibility
        self.notional_amount = config.notional_amount

        # State tracking
        self._bar_counter = 0
        self._trade_counter = 0

        self.instrument_id = config.instrument_id
        self.bar_type = config.bar_type
        self.instrument = None

    def on_start(self) -> None:
        """Initialize strategy on start."""
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument {self.instrument_id} not found in cache \n")
            pass

        self.subscribe_bars(self.bar_type)
        self.log.info(
            f"🧪 TEST STRATEGY STARTED: Pattern LONG->CLOSE->SHORT->CLOSE every {self.bars_per_trade} bars"
        )

    def on_candle_created(self, candle: MidPriceCandle):
        """Handle incoming candle data."""
        self._bar_counter += 1

        # Log every bar
        self.log.info(f"🧪 TEST - Bar #{self._bar_counter}")

        # Execute trade every N bars
        if self._bar_counter % self.bars_per_trade == 0:
            self._execute_test_trade(candle)

    def _execute_test_trade(self, candle: MidPriceCandle):
        """Execute a test trade following the pattern: long -> close -> short -> close -> repeat."""
        self._trade_counter += 1

        # Determine action based on trade counter
        if self._trade_counter % 4 == 1:
            # Trade 1, 5, 9, ... -> Open LONG
            if self.cache.is_flat(self.instrument_id):
                self.log.info(f"🧪 TEST Trade #{self._trade_counter}: Opening LONG position")
                self._enter_long(candle, reason="Test trade - periodic long entry")
            else:
                self.log.warning(
                    f"🧪 TEST Trade #{self._trade_counter}: Skipping LONG - position already exists"
                )
        elif self._trade_counter % 4 == 2:
            # Trade 2, 6, 10, ... -> Close LONG
            if not self.cache.is_flat(self.instrument_id) and self.cache.is_net_long(
                self.instrument_id
            ):
                self.log.info(f"🧪 TEST Trade #{self._trade_counter}: Closing LONG position")
                self._close_position(candle, reason="Test trade - close long after n bars")
            else:
                self.log.warning(
                    f"🧪 TEST Trade #{self._trade_counter}: Skipping LONG close - no long position"
                )
        elif self._trade_counter % 4 == 3:
            # Trade 3, 7, 11, ... -> Open SHORT
            if self.cache.is_flat(self.instrument_id):
                self.log.info(f"🧪 TEST Trade #{self._trade_counter}: Opening SHORT position")
                self._enter_short(candle, reason="Test trade - periodic short entry")
            else:
                self.log.warning(
                    f"🧪 TEST Trade #{self._trade_counter}: Skipping SHORT - position already exists"
                )
        else:  # self._trade_counter % 4 == 0
            # Trade 4, 8, 12, ... -> Close SHORT
            if not self.cache.is_flat(self.instrument_id) and self.cache.is_net_short(
                self.instrument_id
            ):
                self.log.info(f"🧪 TEST Trade #{self._trade_counter}: Closing SHORT position")
                self._close_position(candle, reason="Test trade - close short after n bars")
            else:
                self.log.warning(
                    f"🧪 TEST Trade #{self._trade_counter}: Skipping SHORT close - no short position"
                )

    def _enter_long(self, candle: MidPriceCandle, reason: str):
        """Enter a long position."""
        self.log.info(f"📈 Entering LONG: {reason}")

        close_price = candle.close if candle.close is not None else 0.0
        if close_price == 0.0:
            return

        # Create strategy order mode with notional
        strategy_order_mode = StrategyOrderMode(
            order_size_mode=OrderSizeMode.NOTIONAL, notional_value=self.notional_amount
        )

        # Submit order via on_signal
        ok = self.on_signal(
            signal=1,  # BUY
            price=close_price,
            strategy_actions=StrategyAction.OPEN_CLOSE_POSITION,
            strategy_order_mode=strategy_order_mode,
        )

        if not ok:
            self.log.error("Failed to submit long entry order")

    def _enter_short(self, candle: MidPriceCandle, reason: str):
        """Enter a short position."""
        self.log.info(f"📉 Entering SHORT: {reason}")

        close_price = candle.close if candle.close is not None else 0.0
        if close_price == 0.0:
            return

        # Create strategy order mode with notional
        strategy_order_mode = StrategyOrderMode(
            order_size_mode=OrderSizeMode.NOTIONAL, notional_value=self.notional_amount
        )

        # Submit order via on_signal
        ok = self.on_signal(
            signal=-1,  # SELL
            price=close_price,
            strategy_actions=StrategyAction.OPEN_CLOSE_POSITION,
            strategy_order_mode=strategy_order_mode,
        )

        if not ok:
            self.log.error("Failed to submit short entry order")

    def _close_position(self, candle: MidPriceCandle, reason: str):
        """Close the current position."""
        position = self.cache.position(self.instrument_id)
        if position is None:
            return

        self.log.info(f"🔄 Closing position: {reason}")

        close_price = candle.close if candle.close is not None else 0.0
        if close_price == 0.0:
            return

        tags = [
            f"reason={reason}",
            f"bar_count={self._bar_counter}",
            f"trade_count={self._trade_counter}",
        ]

        # Submit market close order directly
        ok = self._order_manager.submit_market_close(
            strategy_id=self._strategy_id, symbol=self._symbol, price=close_price, tags=tags
        )

        if not ok:
            self.log.error("Failed to submit close order")
