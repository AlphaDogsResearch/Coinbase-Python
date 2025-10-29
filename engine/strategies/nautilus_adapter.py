"""
Main Nautilus Strategy Adapter.

This adapter wraps Nautilus Trader strategies to work seamlessly with your
existing StrategyManager, OrderManager, and PositionManager infrastructure.
"""

import logging
from typing import Callable, List
from datetime import datetime

from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy as NautilusStrategy

from common.interface_book import OrderBook
from common.interface_order import OrderSizeMode
from engine.core.strategy import Strategy
from engine.market_data.candle import MidPriceCandle, CandleAggregator
from engine.position.position_manager import PositionManager
from engine.strategies.strategy_action import StrategyAction
from engine.strategies.nautilus_adapters import (
    NautilusPortfolioAdapter,
    NautilusCacheAdapter,
    NautilusOrderFactoryAdapter,
    NautilusInstrumentAdapter,
)
from engine.strategies.nautilus_converters import (
    convert_candle_to_bar,
    parse_bar_type,
)
from engine.strategies.strategy_order_mode import StrategyOrderMode


class NautilusStrategyAdapter(Strategy):
    """
    Adapter that wraps a Nautilus Trader strategy to work with your system.

    This adapter:
    - Inherits from your Strategy base class
    - Wraps a Nautilus strategy instance
    - Converts MidPriceCandles to Nautilus Bars
    - Intercepts order submissions and converts them to signals
    - Provides portfolio/position state via adapters

    Usage:
        # Create Nautilus strategy
        nautilus_config = ROCMeanReversionStrategyConfig(...)
        nautilus_strat = ROCMeanReversionStrategy(config=nautilus_config)

        # Wrap with adapter
        adapted_strategy = NautilusStrategyAdapter(
            nautilus_strategy_instance=nautilus_strat,
            symbol="ETHUSDT",
            trade_unit=1.0,
            strategy_actions=StrategyAction.OPEN_CLOSE_POSITION,
            candle_aggregator=candle_agg,
            position_manager=position_manager,
            instrument_id="ETHUSDT.BINANCE"
        )

        # Add to StrategyManager
        strategy_manager.add_strategy(adapted_strategy)
    """

    def __init__(
        self,
        nautilus_strategy_instance: NautilusStrategy,
        symbol: str,
        strategy_order_mode: StrategyOrderMode,
        strategy_actions: StrategyAction,
        candle_aggregator: CandleAggregator,
        position_manager: PositionManager,
        instrument_id: str,
        bar_type_spec: str = "1-HOUR-LAST",
        price_precision: int = 2,
        size_precision: int = 8,
    ):
        """
        Initialize the Nautilus strategy adapter.

        Args:
            nautilus_strategy_instance: An instantiated Nautilus strategy
            symbol: Your system's symbol (e.g., "ETHUSDT")
            trade_unit: Trade unit size
            strategy_actions: Strategy action type (OPEN_CLOSE_POSITION or POSITION_REVERSAL)
            candle_aggregator: Candle aggregator for this strategy
            position_manager: Your system's position manager
            instrument_id: Nautilus instrument ID (e.g., "ETHUSDT.BINANCE")
            bar_type_spec: Bar specification (e.g., "1-HOUR-LAST")
            price_precision: Price decimal precision
            size_precision: Size decimal precision
        """
        # Initialize parent Strategy class
        super().__init__(
            symbol=symbol,
            strategy_order_mode=strategy_order_mode,
            strategy_actions=strategy_actions,
            candle_aggregator=candle_aggregator,
        )

        # Store references
        self.nautilus_strategy = nautilus_strategy_instance
        self.position_manager = position_manager
        self.instrument_id_str = instrument_id
        self.instrument_id = InstrumentId.from_str(instrument_id)

        # Set strategy name
        self.name = f"NautilusAdapter({nautilus_strategy_instance.__class__.__name__}:{symbol})"

        # Create bar type for conversions
        self.bar_type = parse_bar_type(instrument_id, bar_type_spec)

        # Create instrument adapter with Binance ETHUSDT reference data values
        self.instrument_adapter = NautilusInstrumentAdapter(
            symbol=symbol,
            instrument_id_str=instrument_id,
            price_precision=2,  # From Binance: price_precision=2, price_tick_size=0.01
            size_precision=3,  # From Binance: quantity_precision=3, lot_step_size=0.001
            min_quantity=0.001,  # From Binance: min_lot_size=0.001
            min_notional=20.0,  # From Binance: min_notional=20.0
        )

        # Create adapters for Nautilus components
        self.portfolio_adapter = NautilusPortfolioAdapter(position_manager)
        self.cache_adapter = NautilusCacheAdapter({instrument_id: self.instrument_adapter})
        self.order_factory_adapter = NautilusOrderFactoryAdapter(
            order_callback=self._on_order_created
        )

        # Signal listeners (inherited from Strategy)
        self.listeners: List[Callable[[str, int, float, str, float, StrategyAction], None]] = []

        # Plot listeners (for compatibility)
        self.plot_signal_listeners: List[Callable[[datetime, int, float], None]] = []

        # Inject adapters into Nautilus strategy
        self._inject_adapters()

        # Track last price for order conversions
        self._last_price = 0.0

        # Track pending stop orders (optional, for future implementation)
        self._pending_stops = []

        # Track registered indicators for manual updates
        self._registered_indicators = []

        logging.info("Initialized %s with bar type %s", self.name, self.bar_type)
        logging.info(
            "Cache has instrument: %s",
            self.cache_adapter.instrument(self.instrument_id) is not None,
        )

    def _inject_adapters(self):
        """Inject adapter components into the Nautilus strategy."""
        # Use instance __dict__ to store our adapters
        # This bypasses property descriptors for internal storage
        self.nautilus_strategy.__dict__["_portfolio_adapter"] = self.portfolio_adapter
        self.nautilus_strategy.__dict__["_cache_adapter"] = self.cache_adapter
        self.nautilus_strategy.__dict__["_order_factory_adapter"] = self.order_factory_adapter

        # Store original property accessors
        original_portfolio = self.nautilus_strategy.__class__.portfolio
        original_cache = self.nautilus_strategy.__class__.cache
        original_order_factory = self.nautilus_strategy.__class__.order_factory

        # Create new properties that return our adapters for this instance
        def get_portfolio(instance):
            if hasattr(instance, "_portfolio_adapter"):
                return instance.__dict__["_portfolio_adapter"]
            return (
                original_portfolio.fget(instance) if hasattr(original_portfolio, "fget") else None
            )

        def get_cache(instance):
            if hasattr(instance, "_cache_adapter"):
                return instance.__dict__["_cache_adapter"]
            return original_cache.fget(instance) if hasattr(original_cache, "fget") else None

        def get_order_factory(instance):
            if hasattr(instance, "_order_factory_adapter"):
                return instance.__dict__["_order_factory_adapter"]
            return (
                original_order_factory.fget(instance)
                if hasattr(original_order_factory, "fget")
                else None
            )

        # Replace properties on the class (affects all instances but checks for adapter first)
        self.nautilus_strategy.__class__.portfolio = property(get_portfolio)
        self.nautilus_strategy.__class__.cache = property(get_cache)
        self.nautilus_strategy.__class__.order_factory = property(get_order_factory)

        # Override submit_order to intercept order submissions
        def intercepted_submit_order(order, **kwargs):  # noqa: unused-argument
            """Intercept order submission."""
            logging.info("Intercepted order submission: %s", order)
            # The order has already been handled by order_factory callback
            # We don't actually submit to Nautilus execution system

        self.nautilus_strategy.submit_order = intercepted_submit_order

        # Override other methods that Nautilus strategies might call
        self.nautilus_strategy.cancel_order = lambda order: logging.info("Cancel order: %s", order)
        self.nautilus_strategy.cancel_all_orders = lambda instrument_id: logging.info(
            "Cancel all orders: %s", instrument_id
        )
        self.nautilus_strategy.close_all_positions = lambda instrument_id: logging.info(
            "Close all positions: %s", instrument_id
        )

        # Mock Nautilus lifecycle methods with indicator tracking
        def register_indicator_for_bars_impl(bar_type, indicator):
            logging.info(
                "🔔 Registered indicator %s for %s", indicator.__class__.__name__, bar_type
            )
            logging.info(
                "Indicator details: period=%s, initialized=%s",
                getattr(indicator, "period", "N/A"),
                getattr(indicator, "initialized", "N/A"),
            )
            self._registered_indicators.append(indicator)
            logging.info("Total registered indicators: %d", len(self._registered_indicators))

        self.nautilus_strategy.register_indicator_for_bars = register_indicator_for_bars_impl
        self.nautilus_strategy.subscribe_bars = lambda bar_type: logging.info(
            "Subscribed to bars: %s", bar_type
        )
        self.nautilus_strategy.unsubscribe_bars = lambda bar_type: logging.info(
            "Unsubscribed from bars: %s", bar_type
        )

    def _on_order_created(self, order: dict):
        """
        Handle order creation from Nautilus strategy.

        This is called by the NautilusOrderFactoryAdapter when the Nautilus
        strategy creates an order. We convert it to a signal and emit.

        Args:
            order: Dictionary containing order details
        """
        order_type = order.get("type")
        order_side = order.get("side")

        logging.info("Processing order: type=%s, side=%s", order_type, order_side)

        # Convert order side to signal
        if order_side == OrderSide.BUY:
            signal = 1
        elif order_side == OrderSide.SELL:
            signal = -1
        else:
            logging.warning("Unknown order side: %s", order_side)
            return

        # Determine price for signal
        price = self._last_price

        # Handle different order types
        if order_type == "MARKET":
            # Emit signal immediately for market orders
            self.on_signal(signal, price)

        elif order_type == "STOP_MARKET":
            # For stop orders, we could track them and trigger later
            # For now, we'll emit the signal immediately
            trigger_price = float(order.get("trigger_price"))
            logging.info("Stop order with trigger price: %s", trigger_price)
            # In a full implementation, you'd track this and trigger when price is hit
            # For simplicity, emit immediately
            self.on_signal(signal, trigger_price)

        elif order_type == "LIMIT":
            # For limit orders, similar to stops
            limit_price = float(order.get("price"))
            logging.info("Limit order with price: %s", limit_price)
            # Emit immediately for simplicity
            self.on_signal(signal, limit_price)

        else:
            logging.warning("Unhandled order type: %s", order_type)

    def on_candle_created(self, candle: MidPriceCandle):
        """
        Handle candle creation from your system.

        This converts the candle to a Nautilus Bar and feeds it to the
        Nautilus strategy's on_bar method.

        Args:
            candle: Your system's MidPriceCandle
        """
        logging.debug("%s on_candle_created: %s", self.name, candle)

        # Update last price
        if candle.close is not None:
            self._last_price = candle.close

        # Convert to Nautilus Bar
        bar = convert_candle_to_bar(candle, self.bar_type)

        if bar is None:
            logging.warning("Failed to convert candle to bar: %s", candle)
            return

        logging.debug(
            "📊 Feeding bar to Nautilus: Bar(O=%s H=%s L=%s C=%s)",
            bar.open,
            bar.high,
            bar.low,
            bar.close,
        )

        # Manually update all registered indicators (Nautilus normally does this automatically)
        for indicator in self._registered_indicators:
            try:
                indicator.handle_bar(bar)
                logging.debug("Updated indicator %s", indicator.__class__.__name__)
            except Exception as e:  # noqa: broad-except
                logging.error("Error updating indicator %s: %s", indicator.__class__.__name__, e)

        # Feed bar to Nautilus strategy
        try:
            self.nautilus_strategy.on_bar(bar)
            logging.debug("✅ Nautilus strategy.on_bar() executed")

            # Log indicator states if available (generic for all indicator types)
            self._log_indicator_states()

        except Exception as e:  # noqa: broad-except
            logging.error("❌ Error in Nautilus strategy on_bar: %s", e, exc_info=True)

    def _log_indicator_states(self):
        """Log all registered indicator states at DEBUG level."""
        if not self._registered_indicators:
            return

        for indicator in self._registered_indicators:
            try:
                indicator_name = indicator.__class__.__name__
                value = getattr(indicator, "value", "N/A")
                initialized = getattr(indicator, "initialized", False)
                period = getattr(indicator, "period", "N/A")

                # Log basic indicator state
                logging.debug(
                    "📈 %s: value=%s, initialized=%s, period=%s",
                    indicator_name,
                    value,
                    initialized,
                    period,
                )

                # Log additional indicator-specific attributes
                if hasattr(indicator, "pos") and hasattr(indicator, "neg"):
                    # Custom ADX indicator (has pos, neg properties and value contains ADX)
                    logging.debug(
                        "   ADX details: adx=%s, +DI=%s, -DI=%s",
                        value,  # value property contains the ADX value
                        indicator.pos,
                        indicator.neg,
                    )
            except Exception as e:  # noqa: broad-except
                logging.debug("Could not log indicator %s: %s", indicator.__class__.__name__, e)

    def on_update(self, order_book: OrderBook):  # noqa: unused-argument
        """
        Handle order book updates (not used for candle-based strategies).

        Args:
            order_book: Order book update (unused for candle strategies)
        """
        # Not used for candle-based Nautilus strategies

    def add_signal_listener(
        self, callback: Callable[[str, int, float, str, float, StrategyAction], None]
    ):
        """
        Add a signal listener (required by Strategy base class).

        Args:
            callback: Signal callback function
        """
        self.listeners.append(callback)

    def on_signal(self, signal: int, price: float):
        """
        Emit a signal to registered listeners.

        This is called when we've converted a Nautilus order to a signal.

        Args:
            signal: Signal value (1=BUY, -1=SELL, 0=HOLD)
            price: Price for the signal
        """
        logging.info("%s emitting signal: %s at price %s", self.name, signal, price)

        for listener in self.listeners:
            try:
                listener(
                    self.name, signal, price, self.symbol, self.trade_unit, self.strategy_actions
                )
            except Exception as e:  # noqa: broad-except
                logging.error("%s signal listener raised an exception: %s", self.name, e)

    def add_plot_signal_listener(self, callback: Callable[[datetime, int, float], None]):
        """
        Add a plot signal listener (for compatibility with your Strategy interface).

        Args:
            callback: Plot callback function
        """
        self.plot_signal_listeners.append(callback)

    def start(self):
        """Start the Nautilus strategy."""
        logging.info("🚀 Starting %s...", self.name)
        try:
            # Call Nautilus strategy's on_start if it exists
            if hasattr(self.nautilus_strategy, "on_start"):
                logging.info("Calling nautilus_strategy.on_start()...")
                self.nautilus_strategy.on_start()
                logging.info("✅ nautilus_strategy.on_start() completed")
            else:
                logging.warning("Nautilus strategy has no on_start method")
            logging.info("✅ %s started successfully", self.name)
        except Exception as e:  # noqa: broad-except
            logging.error("❌ Error starting Nautilus strategy: %s", e, exc_info=True)

    def stop(self):
        """Stop the Nautilus strategy."""
        try:
            # Call Nautilus strategy's on_stop if it exists
            if hasattr(self.nautilus_strategy, "on_stop"):
                self.nautilus_strategy.on_stop()
            logging.info("%s stopped", self.name)
        except Exception as e:  # noqa: broad-except
            logging.error("Error stopping Nautilus strategy: %s", e, exc_info=True)
