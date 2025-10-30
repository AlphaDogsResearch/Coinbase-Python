import logging
from typing import List, Callable

from engine.core.order_manager import OrderManager
from engine.core.strategy import Strategy, StrategyMarketDataType
from common.interface_order import Side, OrderType
from engine.execution.executor import Executor
from engine.remote.remote_market_data_client import RemoteMarketDataClient


class StrategyManager:
    def __init__(
        self, remote_market_data_client: RemoteMarketDataClient, order_manager: OrderManager
    ):
        self.strategies = {}
        self.name = "StrategyManager"
        # todo should change to support different venue
        self.remote_market_data_client = remote_market_data_client

        self.order_manager = order_manager

        self.on_strategy_order_submitted_listeners = []

    def add_strategy(self, strategy: Strategy):
        strategy_id = strategy.name
        if self.strategies.get(strategy_id) is None:
            # add strategy
            self.strategies[strategy_id] = strategy
            strategy.add_submit_order_listener(self.on_submit_order)

            if strategy.strategy_market_data_type == StrategyMarketDataType.CANDLE:
                candle_agg = strategy.candle_aggregator
                # add tick listener to candle aggregator
                self.remote_market_data_client.add_order_book_listener(
                    strategy.symbol, candle_agg.on_order_book
                )
                # add candle agg to strategy listener
                candle_agg.add_candle_created_listener(strategy.on_candle_created)
            elif strategy.strategy_market_data_type == StrategyMarketDataType.TICK:
                # add tick listener to strategy directly
                self.remote_market_data_client.add_order_book_listener(
                    strategy.symbol, strategy.on_update
                )

            logging.info("Added Strategy %s" % strategy_id)
        else:
            logging.info("Strategy already exist, Unable to add Strategy %s" % strategy_id)
            raise ValueError("Strategy already exist, Unable to add Strategy")

    def remove_strategy(self, strategy_id: str):
        self.strategies.pop(strategy_id)
        logging.info("Removed Strategy %s" % strategy_id)

    def on_submit_order(
        self,
        strategy_id: str,
        side,
        order_type,
        notional: float,
        price: float,
        symbol: str,
        tags: List[str] = None,
    ) -> bool:
        """
        Handle order submission through StrategyManager.

        This method is called by strategies when they want to submit orders.
        It calls order_manager.submit_order() directly.

        Args:
            strategy_id: Strategy that submitted the order
            side: Order side (BUY/SELL)
            order_type: Order type (Market, Limit, StopMarket, etc.)
            notional: Order notional value
            price: Order price
            symbol: Trading symbol
            tags: List of order tags (including signal_id)

        Returns:
            bool: True if order submitted successfully
        """
        try:
            # Call order_manager.submit_order directly
            success = self.order_manager.submit_order(
                strategy_id=strategy_id,
                side=side,
                order_type=order_type,
                notional=notional,
                price=price,
                symbol=symbol,
                tags=tags,
            )

            for listener in self.on_strategy_order_submitted_listeners:
                listener(strategy_id, side, order_type, notional, price, symbol, tags)

            if success:
                tags_info = f" (tags: {tags})" if tags else ""
                logging.info(
                    f"Order submitted through StrategyManager: {strategy_id} {side.name} {symbol} at {price}{tags_info}"
                )
            else:
                tags_info = f" (tags: {tags})" if tags else ""
                logging.warning(
                    f"Order submission failed through StrategyManager: {strategy_id} {side.name} {symbol} at {price}{tags_info}"
                )

            return success

        except Exception as e:
            logging.error(f"Error in StrategyManager.on_submit_order: {e}", exc_info=True)
            return False

    def add_on_strategy_order_submitted_listener(
        self, callback: Callable[[str, Side, OrderType, float, float, str, List[str]], None]
    ):
        self.on_strategy_order_submitted_listeners.append(callback)
