"""
Main Nautilus Strategy Adapter.

This adapter wraps Nautilus Trader strategies to work seamlessly with your
existing StrategyManager, OrderManager, and PositionManager infrastructure.
"""

import logging
from typing import Callable, List
from common.interface_order import Side, OrderType
from datetime import datetime

from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy as NautilusStrategy

from common.interface_book import OrderBook
from engine.core.strategy import Strategy
from engine.market_data.candle import MidPriceCandle, CandleAggregator
from engine.position.position_manager import PositionManager
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

NOTIONAL_PER_ORDER = 500


class NautilusLoggerAdapter:
    """
    Adapter to redirect Nautilus logger calls to Python's standard logging.

    Nautilus strategies use self.log.info(), self.log.error(), etc.
    This adapter redirects those calls to the standard logging framework.
    """

    def __init__(self, strategy_name: str):
        """Initialize logger adapter with strategy name."""
        self.logger = logging.getLogger(f"nautilus.{strategy_name}")

    def debug(self, msg: str, *args, **kwargs) -> None:
        """Log debug message."""
        self.logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs) -> None:
        """Log info message."""
        self.logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs) -> None:
        """Log warning message."""
        self.logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs) -> None:
        """Log error message."""
        self.logger.error(msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs) -> None:
        """Log critical message."""
        self.logger.critical(msg, *args, **kwargs)


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
            strategy_id=self.name,
            symbol=symbol,
            quantity="1.000",
        )

        # Submit order listeners
        self.submit_order_listeners: List[
            Callable[[str, Side, OrderType, float, float, str, List[str]], bool]
        ] = []

        # Inject adapters into Nautilus strategy
        self._inject_adapters()

        # Track last price for order conversions
        self._last_price = 0.0

        # Track pending stop orders (optional, for future implementation)
        self._pending_stops = []

        # Track registered indicators for manual updates
        self._registered_indicators = []

        logging.info("Initialized %s with bar type %s", self.name, self.bar_type)

    def _inject_adapters(self):
        """Inject adapter components into the Nautilus strategy."""
        # Use instance __dict__ to store our adapters
        # This bypasses property descriptors for internal storage
        self.nautilus_strategy.__dict__["_portfolio_adapter"] = self.portfolio_adapter
        self.nautilus_strategy.__dict__["_cache_adapter"] = self.cache_adapter
        self.nautilus_strategy.__dict__["_order_factory_adapter"] = self.order_factory_adapter

        # Inject our intercepted submit_order method (will be defined later in this method)

        # Redirect Nautilus logger to Python's standard logging
        self._inject_logger()

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
            """
            Intercept order submissions from Nautilus strategies.

            This method is called by Nautilus strategies when they call self.submit_order().
            We redirect this to StrategyManager.on_submit_order().

            Args:
                order: Order object from Nautilus strategy
            """
            try:
                # Extract order details from Nautilus order object
                order_type = (
                    order.get("type")
                    if isinstance(order, dict)
                    else getattr(order, "type", "MARKET")
                )
                order_side = (
                    order.get("side") if isinstance(order, dict) else getattr(order, "side", None)
                )
                quantity = (
                    order.get("quantity")
                    if isinstance(order, dict)
                    else getattr(order, "quantity", None)
                )
                price = (
                    order.get("price") if isinstance(order, dict) else getattr(order, "price", None)
                )
                trigger_price = (
                    order.get("trigger_price")
                    if isinstance(order, dict)
                    else getattr(order, "trigger_price", None)
                )
                tags_str = (
                    order.get("tags") if isinstance(order, dict) else getattr(order, "tags", "")
                )
                # Parse tags string into list (split by | and filter empty strings)
                tags = (
                    [tag.strip() for tag in tags_str.split("|") if tag.strip()] if tags_str else []
                )

                # Convert order side to our Side enum
                from common.interface_order import Side, OrderType

                if order_side == OrderSide.BUY:
                    side = Side.BUY
                elif order_side == OrderSide.SELL:
                    side = Side.SELL
                else:
                    logging.warning(f"Unknown order side: {order_side}, skipping order")
                    return False

                # Determine order type and price
                if order_type == "MARKET":
                    order_type_enum = OrderType.Market
                    order_price = price.as_double() if price else self._last_price
                elif order_type == "STOP_MARKET":
                    order_type_enum = OrderType.StopMarket
                    order_price = trigger_price.as_double() if trigger_price else self._last_price
                elif order_type == "LIMIT":
                    order_type_enum = OrderType.Limit
                    order_price = price.as_double() if price else self._last_price
                else:
                    logging.warning(f"Unknown order type: {order_type}, defaulting to Market")
                    order_type_enum = OrderType.Market
                    order_price = self._last_price

                # Submit order through callbacks
                if self.submit_order_listeners:
                    success = False
                    for callback in self.submit_order_listeners:
                        try:
                            result = callback(
                                strategy_id=self.name,
                                side=side,
                                order_type=order_type_enum,
                                notional=NOTIONAL_PER_ORDER,
                                price=order_price,
                                symbol=self.symbol,
                                tags=tags,
                            )
                            if result:
                                success = True
                                break
                        except Exception as e:
                            logging.error(f"Error in submit order callback: {e}", exc_info=True)

                    if success:
                        logging.info(
                            f"✅ Intercepted order submitted via callback: {order_type} {side.name} {self.symbol} at {order_price}"
                        )
                    else:
                        logging.error(
                            f"❌ Failed to submit intercepted order via callback: {order_type} {side.name} {self.symbol} at {order_price}"
                        )

                    return success
                else:
                    logging.error("No submit order listeners available for order submission")
                    return False

            except Exception as e:
                logging.error(f"Error in intercepted_submit_order: {e}", exc_info=True)
                return False

        # Store the intercepted function as a method and inject it
        self.intercepted_submit_order = intercepted_submit_order
        self.nautilus_strategy.__dict__["submit_order"] = intercepted_submit_order

        # Override other methods that Nautilus strategies might call
        self.nautilus_strategy.cancel_order = lambda order: None
        self.nautilus_strategy.cancel_all_orders = lambda instrument_id: None
        self.nautilus_strategy.close_all_positions = lambda instrument_id: None

        # Mock Nautilus lifecycle methods with indicator tracking
        def register_indicator_for_bars_impl(bar_type, indicator):
            self._registered_indicators.append(indicator)

        self.nautilus_strategy.register_indicator_for_bars = register_indicator_for_bars_impl
        self.nautilus_strategy.subscribe_bars = lambda bar_type: None
        self.nautilus_strategy.unsubscribe_bars = lambda bar_type: None

    def _inject_logger(self):
        """
        Setup logging for Nautilus strategy.

        Inject our NautilusLoggerAdapter to redirect strategy logging to our logging system.
        """
        strategy_class_name = self.nautilus_strategy.__class__.__name__

        # Create logger adapter
        logger_adapter = NautilusLoggerAdapter(strategy_class_name)

        # Inject the logger adapter into the strategy
        # We need to replace the log property on the instance
        self.nautilus_strategy.__dict__["_log_adapter"] = logger_adapter

        # Create a property that returns our logger adapter
        def get_log(instance):
            return instance.__dict__["_log_adapter"]

        # Replace the log property on the instance
        self.nautilus_strategy.__class__.log = property(get_log)

        logging.info(
            "Nautilus strategy initialized: %s (symbol=%s) - using injected logger adapter",
            strategy_class_name,
            self.symbol,
        )

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

    def add_submit_order_listener(
        self,
        callback: Callable[[str, Side, OrderType, float, float, str, List[str]], bool],
    ):
        """Add a submit order listener callback."""
        self.submit_order_listeners.append(callback)

    def start(self):
        """Start the Nautilus strategy."""
        logging.info("🚀 Starting %s", self.name)
        try:
            # Call Nautilus strategy's on_start if it exists
            if hasattr(self.nautilus_strategy, "on_start"):
                self.nautilus_strategy.on_start()
            logging.info("✅ %s started", self.name)
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
