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
            self.strategies[strategy_id] = strategy
            if strategy.strategy_market_data_type == StrategyMarketDataType.CANDLE:
                candle_agg = strategy.candle_aggregator
                self.remote_market_data_client.add_order_book_listener(
                    strategy.symbol, candle_agg.on_order_book
                )
                candle_agg.add_candle_created_listener(strategy.on_candle_created)
            elif strategy.strategy_market_data_type == StrategyMarketDataType.TICK:
                self.remote_market_data_client.add_order_book_listener(
                    strategy.symbol, strategy.on_update
                )
            logging.info("[Strategy] Added %s" % strategy_id)
            if hasattr(strategy, "add_submit_order_listener"):
                strategy.add_submit_order_listener("ENTRY", self.on_submit_market_entry)
                strategy.add_submit_order_listener("CLOSE", self.on_submit_market_close)
                strategy.add_submit_order_listener("STOP_LOSS", self.on_submit_stop_market_order)
        else:
            logging.info("Strategy already exist, Unable to add Strategy %s" % strategy_id)
            raise ValueError("Strategy already exist, Unable to add Strategy")

    def remove_strategy(self, strategy_id: str):
        self.strategies.pop(strategy_id)
        logging.info("Removed Strategy %s" % strategy_id)

    def add_on_strategy_order_submitted_listener(
        self, callback: Callable[[str, Side, OrderType, float, float, str, List[str]], None]
    ):
        self.on_strategy_order_submitted_listeners.append(callback)

    # --- New pass-through APIs ---
    def on_submit_market_order(
        self,
        strategy_id: str,
        symbol: str,
        side: Side,
        quantity: float,
        price: float,
        signal_id: str | None = None,
        tags: List[str] | None = None,
    ) -> bool:
        try:
            ok = self.order_manager.submit_market_order(
                strategy_id=strategy_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                signal_id=signal_id,
                tags=tags,
            )
            # notify listeners in same shape as before
            for listener in self.on_strategy_order_submitted_listeners:
                listener(
                    strategy_id,
                    side,
                    OrderType.Market,
                    quantity * price if price else 0.0,
                    price,
                    symbol,
                    tags,
                )
            return ok
        except Exception as e:
            logging.error("Error in StrategyManager.on_submit_market_order: %s", e, exc_info=True)
            return False

    def on_submit_stop_market_order(
        self,
        strategy_id: str,
        symbol: str,
        side: Side,
        quantity: float | None,
        trigger_price: float,
        signal_id: str,
        tags: List[str] | None = None,
    ) -> bool:
        try:
            ok = self.order_manager.submit_stop_market_order(
                strategy_id=strategy_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                trigger_price=trigger_price,
                signal_id=signal_id,
                tags=tags,
            )
            for listener in self.on_strategy_order_submitted_listeners:
                listener(strategy_id, side, OrderType.StopMarket, 0.0, trigger_price, symbol, tags)
            return ok
        except Exception as e:
            logging.error(
                "Error in StrategyManager.on_submit_stop_market_order: %s", e, exc_info=True
            )
            return False

    def on_submit_market_entry(
        self,
        strategy_id: str,
        symbol: str,
        side: Side,
        quantity: float,
        price: float,
        signal_id: str,
        tags: list[str] | None = None,
    ) -> bool:
        """
        Submit entry (open) for a single strategy. Passes through to OMS.
        """
        try:
            ok = self.order_manager.submit_market_entry(
                strategy_id, symbol, side, quantity, price, signal_id, tags
            )
            for listener in self.on_strategy_order_submitted_listeners:
                listener(
                    strategy_id,
                    side,
                    OrderType.Market,
                    quantity * price if price else 0.0,
                    price,
                    symbol,
                    tags,
                )
            return ok
        except Exception as e:
            logging.error("Error in StrategyManager.on_submit_market_entry: %s", e, exc_info=True)
            return False

    def on_submit_market_close(
        self,
        strategy_id: str,
        symbol: str,
        price: float,
        tags: list[str] | None = None,
    ) -> bool:
        """
        Close ALL open positions for (strategy_id, symbol).
        This ALWAYS fully flattens the per-strategy exposure, regardless of global symbol netting.
        No partial close is supported.
        """
        try:
            ok = self.order_manager.submit_market_close(strategy_id, symbol, price, tags)
            for listener in self.on_strategy_order_submitted_listeners:
                listener(
                    strategy_id,
                    None,
                    OrderType.Market,
                    0.0,
                    price,
                    symbol,
                    tags,
                )
            return ok
        except Exception as e:
            logging.error("Error in StrategyManager.on_submit_market_close: %s", e, exc_info=True)
            return False
