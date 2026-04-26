import logging
import re
import time
from collections import defaultdict
from typing import Dict, Optional

from common.interface_req_res import HistoricalCandleResponse
from common.utils.synchronization import SharedLock
from engine.market_data.candle import CandleAggregator
from engine.position.position_manager import PositionManager
from engine.remote.remote_market_data_client import RemoteMarketDataClient
from engine.core.order_manager import OrderManager


def parse_interval_from_bar_type(bar_type: str) -> Optional[float]:
    """
    Parse interval in seconds from bar_type string.

    Examples:
        "ETHUSDT-1h" -> 3600.0
        "ETHUSDT-1m" -> 60.0
        "ETHUSDT-1s" -> 1.0
        "ETHUSDT-5m" -> 300.0
        "ETHUSDT-15m" -> 900.0
        "ETHUSDT-1d" -> 86400.0

    Args:
        bar_type: Bar type string in format "SYMBOL-INTERVAL" or just "INTERVAL"

    Returns:
        Interval in seconds, or None if parsing fails
    """
    if not bar_type:
        return None

    # Extract interval part (after last dash or the whole string if no dash)
    parts = bar_type.split("-")
    interval_str = parts[-1] if len(parts) > 1 else bar_type

    # Match pattern: number followed by unit (s, m, h, d)
    match = re.match(r"^(\d+)([smhd])$", interval_str.lower())
    if not match:
        logging.warning(f"Could not parse interval from bar_type: {bar_type}")
        return None

    value = int(match.group(1))
    unit = match.group(2)

    # Convert to seconds
    unit_multipliers = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
    }

    return float(value * unit_multipliers.get(unit, 1))


def format_seconds_to_interval(seconds: float) -> Optional[str]:
    """
    Convert seconds back into a short interval string.

    Examples:
        3600.0  -> "1h"
        60.0    -> "1m"
        300.0   -> "5m"
        86400.0 -> "1d"
    """
    if seconds is None or seconds <= 0:
        return None

    # Define units from largest to smallest
    units = [
        ("d", 86400),
        ("h", 3600),
        ("m", 60),
        ("s", 1),
    ]

    for unit_char, multiplier in units:
        # Check if the seconds can be represented as a whole number of this unit
        if seconds % multiplier == 0:
            value = int(seconds // multiplier)
            return f"{value}{unit_char}"

    return f"{int(seconds)}s"

class StrategyManager:
    """
    Lightweight StrategyManager that handles strategy wiring and lifecycle.

    Responsibilities:
    - Manages candle aggregators (by interval)
    - Wires strategies to order manager, position manager, and market data
    - Handles portfolio syncing
    - Manages strategy lifecycle (start/stop)
    """

    def __init__(self, order_manager: OrderManager, position_manager: PositionManager,
                 remote_market_data_client: RemoteMarketDataClient, preload_candles:dict):
        self.order_manager = order_manager
        self.position_manager = position_manager
        self.remote_market_data_client = remote_market_data_client

        # Track strategies and their metadata
        self.strategies: Dict[str, dict] = {}  # strategy_id -> {strategy, symbol, candle_agg}
        # Level 1 Key: Symbol (str) -> Level 2 Key: Interval (float) -> Value: Aggregator
        self.candle_aggregators: Dict[str, Dict[float, CandleAggregator]] = {}

        self.historical_request_lock = SharedLock(initially_locked=True)
        self.replay_times = defaultdict(dict) # symbol -> {replay_unit, times}
        if preload_candles:
            self.replay_times=preload_candles

        self.remote_market_data_client.add_historical_price_listener(self.on_historical_candle)

    def add_strategy(self, strategy, strategy_id: str, symbol: str) -> bool:
        """
        Add and wire a strategy.

        Args:
            strategy: Strategy instance
            strategy_id: Unique identifier for the strategy
            symbol: Trading symbol for this strategy

        Returns:
            True if successful, False otherwise
        """
        if strategy_id in self.strategies:
            logging.warning(f"Strategy {strategy_id} already exists")
            return False

        try:
            # Set order manager directly on strategy
            strategy.set_order_manager(self.order_manager, strategy_id, symbol)

            # Sync portfolio with position manager
            self._sync_portfolio(strategy_id, symbol, strategy)

            # Wire position updates to sync portfolio
            position_callback = self._make_position_sync_callback(strategy_id, symbol, strategy)
            self.position_manager.add_position_amount_listener(position_callback)

            # Get interval from strategy's bar_type or config
            interval_seconds = self._get_strategy_interval(strategy)
            if interval_seconds is None:
                logging.error(
                    f"Could not determine interval for strategy {strategy_id}. "
                    f"Strategy must have bar_type attribute or interval_seconds in config."
                )
                return False

            # Get or create candle aggregator for this specific interval
            candle_agg = self._get_or_create_candle_aggregator(symbol,interval_seconds)

            # Wire CandleAggregator to strategy's on_candle_created method
            candle_callback = self._make_candle_callback(strategy, strategy_id)
            candle_agg.add_candle_created_listener(candle_callback)



            # Store strategy metadata
            self.strategies[strategy_id] = {
                "strategy": strategy,
                "symbol": symbol,
                "candle_agg": candle_agg,
                "position_callback": position_callback,
                "candle_callback": candle_callback,
                "interval_seconds": interval_seconds,
            }

            logging.info(
                f"[StrategyManager] Added strategy {strategy_id} for symbol {symbol} "
                f"with interval {interval_seconds}s"
            )
            return True

        except Exception as e:
            logging.error(f"Error adding strategy {strategy_id}: {e}", exc_info=True)
            return False

    def remove_strategy(self, strategy_id: str) -> bool:
        """
        Remove a strategy and clean up its wiring.

        Args:
            strategy_id: Unique identifier for the strategy

        Returns:
            True if successful, False otherwise
        """
        if strategy_id not in self.strategies:
            logging.warning(f"Strategy {strategy_id} not found")
            return False

        try:
            strategy_data = self.strategies[strategy_id]
            strategy = strategy_data["strategy"]
            symbol = strategy_data["symbol"]
            position_callback = strategy_data["position_callback"]
            candle_callback = strategy_data["candle_callback"]
            candle_agg = strategy_data["candle_agg"]

            # Call strategy on_stop if it exists
            if hasattr(strategy, "on_stop"):
                try:
                    strategy.on_stop()
                except Exception as e:
                    logging.error(
                        f"Error calling strategy.on_stop for {strategy_id}: {e}",
                        exc_info=True,
                    )

            # Remove position listener (if position_manager supports it)
            # Note: position_manager may not have remove methods, so we'll just log
            # In a production system, you'd want to implement remove methods

            # Remove candle listener (if candle_agg supports it)
            # Note: CandleAggregator may not have remove methods, so we'll just log

            # Remove market data listener (if remote_market_data_client supports it)
            # Note: remote_market_data_client may not have remove methods

            # Remove from strategies dict
            del self.strategies[strategy_id]

            logging.info(f"[StrategyManager] Removed strategy {strategy_id}")
            return True

        except Exception as e:
            logging.error(f"Error removing strategy {strategy_id}: {e}", exc_info=True)
            return False

    def on_historical_candle(self, historical_candle_response: HistoricalCandleResponse):
        symbol = historical_candle_response.symbol
        interval_unit = historical_candle_response.interval_unit
        candles = historical_candle_response.candles

        # 1. Direct lookup for the symbol
        symbol_aggregators = self.candle_aggregators.get(symbol)
        if not symbol_aggregators:
            logging.warning(f"Received historical candles for unknown symbol: {symbol}")
            return

        # 2. Iterate through intervals for this specific symbol
        for interval, candle_agg in symbol_aggregators.items():
            # Match the interval unit (e.g., '1m') to the numeric interval (e.g., 60.0)
            if interval_unit == format_seconds_to_interval(interval):
                logging.info(f"Loading candles for {symbol} {interval_unit} total {len(candles)} candles")

                count = len(candles)
                if count == 0:
                    return

                if count == 1:
                    item = candles[0]
                    logging.debug(f"Loading single item: {item}")
                    candle_agg.pre_load_current_candle(item)
                else:
                    # Replay all except the last, then pre-load the last one
                    for i, item in enumerate(candles):
                        if i < count - 1:
                            candle_agg.replay_candles(item)
                        else:
                            logging.info(f"Loading last item into current candle: {item}")
                            candle_agg.pre_load_current_candle(item)

                # Since we found the specific aggregator, we can break the interval loop
                break

        self.historical_request_lock.release()
        logging.info("Release Lock after historical candles")


    def pre_start_check(self):

        if self.replay_times:

            logging.info("Attempting to replay candles....")
            for symbol, intervals in self.replay_times.items():
                logging.info(f"Symbol: {symbol}")
                for interval, times in intervals.items():
                    logging.info(f"  - Replaying {interval} interval with {times} times")
                    self.remote_market_data_client.request_for_historical_candle(symbol, interval, times)

            logging.info("Locking For Replay....")
            self.historical_request_lock.acquire(timeout=3)

        for symbol, intervals in self.candle_aggregators.items():
            for interval, candle_agg in intervals.items():
                # Wire market data to candle aggregator
                self.remote_market_data_client.add_order_book_listener(
                    candle_agg.symbol,
                    candle_agg.on_order_book
                )

                # Calculate current listeners for logging
                current_listeners = len(self.remote_market_data_client.order_book_listeners.get(candle_agg.symbol, []))

                logging.info(
                    f"[StrategyManager] Registered order book listener for {symbol} at {interval}s "
                    f"(total listeners for {symbol}: {current_listeners})"
                )


    def start_all(self) -> None:
        """Start all strategies by calling their on_start() method."""
        for strategy_id, strategy_data in self.strategies.items():
            strategy = strategy_data["strategy"]
            try:
                if hasattr(strategy, "on_start"):
                    strategy.on_start()
                    logging.info(f"[StrategyManager] Started strategy {strategy_id}")
            except Exception as e:
                logging.error(f"Error starting strategy {strategy_id}: {e}", exc_info=True)

    def stop_all(self) -> None:
        """Stop all strategies by calling their on_stop() method."""
        for strategy_id, strategy_data in self.strategies.items():
            strategy = strategy_data["strategy"]
            try:
                if hasattr(strategy, "on_stop"):
                    strategy.on_stop()
                    logging.info(f"[StrategyManager] Stopped strategy {strategy_id}")
            except Exception as e:
                logging.error(f"Error stopping strategy {strategy_id}: {e}", exc_info=True)


    def get_bar_type(self,strategy):
        return self.get_strategy_config(strategy, "bar_type")

    def get_strategy_config(self, strategy, config_name:str):
        return getattr(strategy, config_name, None)

    def _get_strategy_interval(self, strategy) -> Optional[float]:
        """
        Get interval in seconds from strategy's bar_type or config.

        Checks in order:
        1. strategy.bar_type (parsed)
        2. strategy.config.bar_type (parsed)
        3. strategy.config.interval_seconds (direct)
        4. strategy.interval_seconds (direct)

        Returns:
            Interval in seconds, or None if not found
        """
        # Try to get from strategy's bar_type attribute
        bar_type = self.get_bar_type(strategy)
        if bar_type:
            interval = parse_interval_from_bar_type(bar_type)
            if interval:
                return interval

        # Try to get from strategy's config.bar_type
        if hasattr(strategy, "config"):
            config = strategy.config
            if hasattr(config, "bar_type"):
                interval = parse_interval_from_bar_type(config.bar_type)
                if interval:
                    return interval

            # Try config.interval_seconds directly
            if hasattr(config, "interval_seconds"):
                return float(config.interval_seconds)

        # Try strategy.interval_seconds directly
        if hasattr(strategy, "interval_seconds"):
            return float(strategy.interval_seconds)

        return None

    def _get_or_create_candle_aggregator(self, symbol: str, interval_seconds: float) -> CandleAggregator:
        """
        Get or create a candle aggregator for the specified symbol and interval.

        Args:
            symbol: The trading pair symbol (e.g., 'BTCUSDT')
            interval_seconds: Interval in seconds for the candle aggregator

        Returns:
            CandleAggregator instance
        """
        # Ensure the symbol level exists in the dictionary
        symbol_aggregators = self.candle_aggregators.setdefault(symbol, {})

        if interval_seconds not in symbol_aggregators:
            symbol_aggregators[interval_seconds] = CandleAggregator(
                symbol=symbol,
                interval_seconds=interval_seconds
            )
            logging.info(
                f"[StrategyManager] Created candle aggregator for "
                f"symbol {symbol} at interval {interval_seconds}s"
            )

        return symbol_aggregators[interval_seconds]

    def _sync_portfolio(self, strategy_id: str, symbol: str, strategy) -> None:
        """Sync strategy portfolio with position manager."""
        pos = self.position_manager.get_position(symbol, strategy_id)
        if pos:
            # Convert system Position to strategy Position model
            from engine.strategies.models import Position as StrategyPosition, PositionSide

            strategy_pos = StrategyPosition(
                instrument_id=symbol,
                side=(
                    PositionSide.LONG
                    if pos.position_amount > 0
                    else (PositionSide.SHORT if pos.position_amount < 0 else PositionSide.FLAT)
                ),
                quantity=abs(pos.position_amount),
                entry_price=pos.entry_price if hasattr(pos, "entry_price") else 0.0,
                unrealized_pnl=(pos.unrealised_pnl if hasattr(pos, "unrealised_pnl") else 0.0),
            )
            strategy.cache.update_position(strategy_pos)

    def _make_position_sync_callback(self, strategy_id: str, symbol: str, strategy):
        """Create a callback to sync portfolio when position updates."""

        def on_position_update(sym, qty):
            if sym == symbol:
                self._sync_portfolio(strategy_id, symbol, strategy)

        return on_position_update

    def _make_candle_callback(self, strategy, strategy_id: str):
        """Create a callback to forward candles to strategy."""
        logging.info("Attaching candle callback for strategy %s", strategy_id)

        def on_candle_created(candle):
            try:
                strategy.on_candle_created(candle)
            except Exception as e:
                logging.error(
                    f"Error in strategy.on_candle_created for {strategy_id}: {e}",
                    exc_info=True,
                )

        return on_candle_created
