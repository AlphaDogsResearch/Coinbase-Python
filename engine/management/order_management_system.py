import logging
import queue
import threading
from abc import ABC
from decimal import Decimal
from queue import Queue
from typing import Dict, Optional
import time

from common.identifier import OrderIdGenerator
from common.interface_order import Order, Side, OrderEvent, OrderStatus, OrderType
from common.time_utils import current_milli_time
from engine.core.order_manager import OrderManager
from engine.core.strategy import Strategy
from engine.execution.executor import Executor
from engine.pool.object_pool import ObjectPool
from engine.reference_data.reference_data_manager import ReferenceDataManager
from engine.risk.risk_manager import RiskManager
from engine.core.sizing import SizingPolicy


class FCFSOrderManager(OrderManager, ABC):
    def __init__(self, executor: Executor, risk_manager: RiskManager, reference_data_manager: ReferenceDataManager):
        self.executor = executor
        # Single queue for ALL strategies - true FCFS
        self.name = "FCFSOrderManager"
        self.order_queue = Queue()
        self.orders: Dict[str, Order] = {}
        self.lock = threading.RLock()
        self.running = False
        self.id_generator = OrderIdGenerator("STRAT")
        self.process_thread = threading.Thread(target=self._process_orders, daemon=True,name=self.name)
        self.risk_manager = risk_manager
        self.reference_data_manager = reference_data_manager
        self.single_asset_strategy_position = {}

        self.order_pool = ObjectPool(create_func=lambda: Order.create_base_order(
            self.id_generator.next()
        ), size=100)

        # Statistics
        self.stats = {
            'total_orders': 0,
            'by_strategy': {}
        }
        self.stats_lock = threading.Lock()

    def add_position_by_strategy(self, strategy_id: str, position: float , side :Side) -> None:
        logging.info(f"New Position for Strategy:{strategy_id}: {position}")
        actual_position = position
        if side == Side.BUY:
            actual_position = actual_position * 1
        elif side == Side.SELL:
            actual_position = actual_position * -1

        if strategy_id not in self.single_asset_strategy_position:
            self.single_asset_strategy_position[strategy_id] = actual_position
        else:
            self.single_asset_strategy_position[strategy_id] += actual_position

    def on_signal(self, strategy_id: str, signal: int, price: float, symbol: str, trade_unit: float) -> bool:

        try:
            order = self.order_pool.acquire()
            logging.info(f"Order ID from object Pool {order.order_id}")
            side = None
            if signal == 1:
                side = Side.BUY
            elif signal == -1:
                side = Side.SELL

            min_effective_qty = self.reference_data_manager.get_effective_min_quantity(self.executor.order_type, symbol)
            logging.info(f"min_effective_qty: {min_effective_qty} {type(min_effective_qty)}")
            logging.info(f"side: {side} {type(side)}")
            logging.info(f"symbol: {symbol} {type(symbol)}")
            logging.info(f"trade_unit: {trade_unit} {type(trade_unit)}")
            trade_unit_in_decimal = Decimal(str(trade_unit))
            logging.info(f"trade_unit_in_decimal: {trade_unit_in_decimal} {type(trade_unit_in_decimal)}")
            size_quantity = min_effective_qty * trade_unit_in_decimal
            logging.info(f"Symbol {symbol} with  min_effective_qty {min_effective_qty}, trade_unit {trade_unit}, size_quantity {size_quantity}")


            order.update_order_fields(side, float(size_quantity), symbol, current_milli_time(), price, strategy_id)

            return self.submit_order_internal(order)
        except Exception as e:
            logging.error("Error Submitting Order on Signal:  %s",e)
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
            self.stats['total_orders'] += 1
            if strategy_id not in self.stats['by_strategy']:
                self.stats['by_strategy'][strategy_id] = 0
            self.stats['by_strategy'][strategy_id] += 1

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
            elif status == OrderStatus.CANCELED:
                order.on_order_cancel_event()
            elif status == OrderStatus.NEW:
                order.on_new_event()
            else:
                logging.error("Unknown order status: {}".format(order_event.status))

        if order.is_in_order_done_state:
            order = self.orders.pop(order_event.client_id,None)
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

                logging.info(f"Processing order {order.order_id} from {order.strategy_id} "
                      f"(wait time: {time.time() - order.timestamp:.3f}s)")

                # Execute immediately
                self.executor.on_signal(order)
                self.add_position_by_strategy(order.strategy_id, order.quantity,order.side)
                self.order_queue.task_done()

            except queue.Empty:
                pass
            except Exception as e:
                logging.error("Exception processing order {order.id} from {order.strategy_id} ",exc_info=e)
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
        for order_id,order in orders_stats.items():
            logging.info(f"Order ID {order_id} : {order}")

    def get_orders_stats(self):
        """Get current orders statistics - thread safe"""
        with self.stats_lock:
            return self.orders.copy()

    def get_strategy_position_stats(self):
        """Get current strategy to position statistics - thread safe"""
        with self.stats_lock:
            return self.single_asset_strategy_position.copy()