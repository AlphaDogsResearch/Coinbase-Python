import logging
import queue
import threading
import time
from abc import ABC
from decimal import Decimal
from queue import Queue
from typing import Dict, Optional, List

from common.decimal_utils import convert_to_decimal, add_numbers
from common.identifier import OrderIdGenerator
from common.interface_order import Order, Side, OrderEvent, OrderStatus, OrderSizeMode, OrderType
from common.time_utils import current_milli_time
from engine.core.order_manager import OrderManager
from engine.execution.executor import Executor
from engine.pool.object_pool import ObjectPool
from engine.reference_data.reference_data_manager import ReferenceDataManager
from engine.risk.risk_manager import RiskManager
from engine.strategies.strategy_action import StrategyAction
from engine.strategies.strategy_order_mode import StrategyOrderMode


class FCFSOrderManager(OrderManager, ABC):
    def __init__(
        self,
        executor: Executor,
        risk_manager: RiskManager,
        reference_data_manager: ReferenceDataManager,
    ):
        self.executor = executor
        # Single queue for ALL strategies - true FCFS
        self.name = "FCFSOrderManager"
        self.order_queue = Queue()
        self.orders: Dict[str, Order] = {}
        self.lock = threading.RLock()
        self.running = False
        # TODO maybe should create a new order id generator for each strat
        self.id_generator = OrderIdGenerator("STRAT")
        self.process_thread = threading.Thread(
            target=self._process_orders, daemon=True, name=self.name
        )
        self.risk_manager = risk_manager
        self.reference_data_manager = reference_data_manager
        self.single_asset_strategy_position = {}

        self.order_pool = ObjectPool(
            create_func=lambda: Order.create_base_order(self.id_generator.next()), size=100
        )

        # Statistics
        self.stats = {"total_orders": 0, "by_strategy": {}}
        self.stats_lock = threading.Lock()

    def add_position_by_strategy(self, strategy_id: str, position: float, side: Side) -> None:
        logging.info(f"New Position for Strategy:{strategy_id}:{side}: {position} ")
        actual_position = position
        if side == Side.BUY:
            actual_position = actual_position * 1
        elif side == Side.SELL:
            actual_position = actual_position * -1

        if strategy_id not in self.single_asset_strategy_position:
            self.single_asset_strategy_position[strategy_id] = actual_position
        else:
            current_pos = self.single_asset_strategy_position[strategy_id]
            self.single_asset_strategy_position[strategy_id] = add_numbers(
                current_pos, actual_position
            )

    def get_single_asset_current_strategy_position(self, strategy_id: str) -> float:
        return self.single_asset_strategy_position.get(strategy_id, 0)

    def on_signal(
        self,
        strategy_id: str,
        signal: int,
        price: float,
        symbol: str,
        strategy_actions: StrategyAction,
        strategy_order_mode: StrategyOrderMode,
    ) -> bool:

        try:
            order = self.order_pool.acquire()
            logging.info(f"Order ID from object Pool {order.order_id}")
            side = None
            if signal == 1:
                side = Side.BUY
            elif signal == -1:
                side = Side.SELL

            order_quantity = 0
            if strategy_order_mode.get_order_mode() == OrderSizeMode.NOTIONAL:
                order_quantity = self.reference_data_manager.get_effective_quantity_by_notional(
                    self.executor.order_type, symbol, strategy_order_mode.notional_value
                )
            elif strategy_order_mode.get_order_mode() == OrderSizeMode.QUANTITY:
                order_quantity = self.reference_data_manager.get_effective_quantity(
                    self.executor.order_type, symbol, strategy_order_mode.quantity
                )
            if order_quantity == 0:
                logging.error(f"Something went wrong order_quantity:{order_quantity}")

            if strategy_actions == StrategyAction.POSITION_REVERSAL:
                current_pos = self.get_single_asset_current_strategy_position(strategy_id)
                logging.info(f"Current position: {current_pos} strategy_id {strategy_id}")
                if current_pos != 0:
                    order_quantity = order_quantity + convert_to_decimal(abs(current_pos))
                    logging.info(f"Final Quantity: {order_quantity}")
            elif strategy_actions == StrategyAction.OPEN_CLOSE_POSITION:
                # normal do nothing since already calculated
                pass
            else:
                # default to OPEN_CLOSE_POSITION
                logging.info("Strategy Action Not Implemented , do nothing")
            self.get_single_asset_current_strategy_position(strategy_id)

            logging.info(
                f"Symbol {symbol} with  "
                f"quantity {strategy_order_mode.quantity}"
                f"notional {strategy_order_mode.notional_value},"
                f"calculated order_quantity {order_quantity} "
                f"strategy_actions {strategy_actions} "
            )

            order.update_order_fields(
                side, float(order_quantity), symbol, current_milli_time(), price, strategy_id
            )

            return self.submit_order_internal(order)
        except Exception as e:
            logging.error("Error Submitting Order on Signal:  %s", exc_info=e)
            return False

    def submit_order(
        self,
        strategy_id: str,
        side: Side,
        order_type: OrderType,
        notional: float,
        price: float,
        symbol: str,
        tags: List[str] = None,
    ) -> bool:
        """
        Submit order with explicit order type control.

        Args:
            strategy_id: Strategy identifier
            side: Order side (BUY/SELL)
            order_type: Order type (Market, Limit, StopMarket, etc.)
            notional: Order notional value
            price: Order price (for limit/stop orders)
            symbol: Trading symbol
            tags: List of order tags (optional, for future use)

        Returns:
            bool: True if order submitted successfully
        """
        try:
            order = self.order_pool.acquire()
            logging.info(f"Order ID from object Pool {order.order_id}")

            # Calculate order quantity based on notional
            order_quantity = self.reference_data_manager.get_effective_quantity_by_notional(
                order_type, symbol, notional
            )

            if order_quantity == 0:
                logging.error(f"Something went wrong order_quantity:{order_quantity}")
                return False

            # Log tags if provided (for future use)
            if tags:
                logging.info(f"Order tags: {tags}")

            logging.info(
                f"Symbol {symbol} with "
                f"notional {notional}, "
                f"calculated order_quantity {order_quantity} "
                f"order_type {order_type}"
            )

            # Update order fields with the specified order type
            order.update_order_fields(
                side, float(order_quantity), symbol, current_milli_time(), price, strategy_id
            )
            order.order_type = order_type  # Set the specific order type

            return self.submit_order_internal(order)
        except Exception as e:
            logging.error("Error Submitting Nautilus Order: %s", exc_info=e)
            return False

    def submit_order_internal(self, order: Order) -> bool:
        """Submit order - true FCFS across all strategies"""
        # Immediate queue insertion - no per-strategy queues

        if self.risk_manager and not self.risk_manager.validate_order(order):
            logging.info(f"Order blocked by risk manager: {order}")
            return False

        self.order_queue.put(order)

        with self.lock:
            self.orders[order.order_id] = order

        strategy_id = order.strategy_id

        # Update statistics
        with self.stats_lock:
            self.stats["total_orders"] += 1
            if strategy_id not in self.stats["by_strategy"]:
                self.stats["by_strategy"][strategy_id] = 0
            self.stats["by_strategy"][strategy_id] += 1

        logging.info(f"Order {order.order_id} from {strategy_id} submitted at {order.timestamp}")

        return True

    def on_order_event(self, order_event: OrderEvent):
        logging.info(f"Order event received {order_event}")
        status = order_event.status

        order = self.orders[order_event.client_id]
        if order is not None:
            if status == OrderStatus.FILLED:
                last_filled_quantity = float(order_event.last_filled_quantity)
                last_filled_price = float(order_event.last_filled_price)
                order.on_filled_event(last_filled_quantity, last_filled_price)
                self.add_position_by_strategy(order.strategy_id, last_filled_quantity, order.side)
            elif status == OrderStatus.CANCELED:
                order.on_order_cancel_event()
            elif status == OrderStatus.NEW:
                order.on_new_event()
            else:
                logging.error("Unknown order status: {}".format(order_event.status))

        if order.is_in_order_done_state:
            order = self.orders.pop(order_event.client_id, None)
            if order is not None:
                self.order_pool.release(order)

        logging.info(f"Normal Stats {self.get_stats()}")
        self.log_order_stats()
        logging.info(f"Strategy Position {self.get_strategy_position_stats()}")

    def start(self):
        """Start order processing"""
        self.running = True
        self.process_thread.start()
        logging.info("FCFS Order Manager started")

    def stop(self):
        """Stop order processing"""
        self.running = False
        if self.process_thread.is_alive():
            self.process_thread.join(timeout=5)
        logging.info("FCFS Order Manager stopped")

    def _process_orders(self):
        """Process orders in strict FCFS order"""
        while self.running:
            try:
                # Block until order arrives - maintains strict ordering
                order = self.order_queue.get(timeout=0.5)
                if order is None:
                    logging.info("Order is None")
                    break

                logging.info(
                    f"Processing order {order.order_id} from {order.strategy_id} "
                    f"(wait time: {current_milli_time() - order.timestamp:.3f}s)"
                )

                # Execute immediately
                self.executor.on_signal(order)
                self.order_queue.task_done()

            except queue.Empty:
                pass
            except Exception as e:
                logging.error(
                    "Exception processing order {order.id} from {order.strategy_id} ", exc_info=e
                )
                # Timeout is expected, other errors should be handled
                if not isinstance(e, Exception):  # Queue.Empty
                    logging.info(f"Order processing error: {e}")

    def get_order_status(self, order_id: str) -> Optional[str]:
        """Get order status - thread safe"""
        with self.lock:
            order = self.orders.get(order_id)
            return order.order_status if order else None

    def get_queue_size(self) -> int:
        """Get current queue size"""
        return self.order_queue.qsize()

    def get_stats(self) -> dict:
        """Get current statistics - thread safe"""
        with self.stats_lock:
            return self.stats.copy()

    def log_order_stats(self):
        """Log order statistics"""
        orders_stats = self.get_orders_stats()
        for order_id, order in orders_stats.items():
            logging.info(f"Order ID {order_id} : {order}")

    def get_orders_stats(self):
        """Get current orders statistics - thread safe"""
        with self.stats_lock:
            return self.orders.copy()

    def get_strategy_position_stats(self):
        """Get current strategy to position statistics - thread safe"""
        with self.stats_lock:
            return self.single_asset_strategy_position.copy()
