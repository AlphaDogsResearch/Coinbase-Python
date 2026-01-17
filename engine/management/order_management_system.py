import logging
import queue
import threading
import time
from abc import ABC
from decimal import Decimal
from queue import Queue
from typing import Dict, Optional, List, TYPE_CHECKING

from common.decimal_utils import convert_to_decimal, add_numbers
from common.identifier import IdGenerator
from common.interface_order import Order, Side, OrderEvent, OrderStatus, OrderSizeMode, OrderType
from common.time_utils import current_milli_time
from engine.core.order_manager import OrderManager
from engine.execution.executor import Executor
from engine.pool.object_pool import ObjectPool
from engine.reference_data.reference_data_manager import ReferenceDataManager
from engine.risk.risk_manager import RiskManager
from engine.strategies.strategy_action import StrategyAction
from engine.strategies.strategy_order_mode import StrategyOrderMode

if TYPE_CHECKING:
    from engine.database.database_manager import DatabaseManager
    from engine.database.models import SignalContext


class FCFSOrderManager(OrderManager, ABC):
    def __init__(
        self,
        executor: Executor,
        risk_manager: RiskManager,
        reference_data_manager: ReferenceDataManager,
        database_manager: "DatabaseManager" = None,
    ):
        self.executor = executor
        # Single queue for ALL strategies - true FCFS
        self.name = "FCFSOrderManager"
        self.order_queue = Queue()
        self.orders: Dict[str, Order] = {}
        self.lock = threading.RLock()
        self.running = False
        # TODO maybe should create a new order id generator for each strat
        self.id_generator = IdGenerator("STGY")
        self.process_thread = threading.Thread(
            target=self._process_orders, daemon=True, name=self.name
        )
        self.risk_manager = risk_manager
        self.reference_data_manager = reference_data_manager
        self.single_asset_strategy_position = {}

        self.order_pool = ObjectPool(
            create_func=lambda: Order.create_base_order(""), size=100
        )

        # Statistics
        self.stats = {"total_orders": 0, "by_strategy": {}}
        self.stats_lock = threading.Lock()

        # --- Entry/Stop signal linkage ---
        # order_id -> { 'signal_id': str|None, 'action': str|None, 'trigger_price': float|None }
        self.order_meta: Dict[str, dict] = {}
        # (strategy_id, symbol, signal_id) -> entry info { 'qty': float, 'side': Side, 'price': float }
        self._entry_by_signal: Dict[tuple, dict] = {}
        # (strategy_id, symbol, signal_id) -> pending stop info { 'side': Side, 'trigger_price': float, 'tags': List[str]|None }
        self._pending_stop_by_signal: Dict[tuple, dict] = {}
        
        # Database manager for persistence (optional)
        self.database_manager = database_manager

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
        tags: List[str] = None,
        signal_context: "SignalContext" = None,
    ) -> bool:

        try:
            order = self.order_pool.acquire()
            order.initialize(self.id_generator.next())
            logging.info(f"Order ID from object Pool {order.order_id}")
            side = None
            side_str = "UNKNOWN"
            if signal == 1:
                side = Side.BUY
                side_str = "BUY"
            elif signal == -1:
                side = Side.SELL
                side_str = "SELL"

            # Log signal and tags
            logging.info(
                f"Signal: {signal} ({side_str}) for {strategy_id} {symbol} at price {price}"
            )
            if tags:
                logging.info(f"Tags: {tags}")
            
            # Persist signal to database if context provided
            if self.database_manager and signal_context:
                try:
                    self.database_manager.insert_signal(
                        strategy_id=strategy_id,
                        symbol=symbol,
                        signal=signal,
                        price=price,
                        reason=signal_context.reason,
                        indicators=signal_context.indicators,
                        action=signal_context.action,
                        config=signal_context.config,
                        candle=signal_context.candle,
                        order_id=order.order_id,
                    )
                except Exception as e:
                    logging.error(f"Failed to persist signal: {e}")

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
                f"quantity {strategy_order_mode.quantity} "
                f"notional {strategy_order_mode.notional_value}, "
                f"calculated order_quantity {order_quantity} "
                f"strategy_actions {strategy_actions} "
                f"signal {signal} ({side_str})"
                f"{' tags ' + str(tags) if tags else ''}"
            )

            order.update_order_fields(
                side, float(order_quantity), symbol, current_milli_time(), price, strategy_id
            )

            # Store tags in order metadata
            action = None
            if tags:
                for t in tags:
                    if t in ("ENTRY", "CLOSE"):
                        action = t
                        break
            self.order_meta[order.order_id] = {
                "signal_id": None,
                "action": action,
                "trigger_price": None,
                "tags": tags,
            }

            return self.submit_order_internal(order)
        except Exception as e:
            logging.error("Error Submitting Order on Signal:  %s", exc_info=e)
            return False

    # ===== New explicit submission APIs =====
    def submit_market_order(
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
            order = self.order_pool.acquire()
            order.initialize(self.id_generator.next())
            # Normalize quantity to exchange step size using Market rules
            try:
                effective_qty = self.reference_data_manager.get_effective_quantity(
                    OrderType.Market, symbol, quantity
                )
            except Exception:
                effective_qty = quantity
            order.update_order_fields(
                side, float(effective_qty), symbol, current_milli_time(), price, strategy_id
            )
            order.order_type = OrderType.Market

            # Attach meta
            action = None
            if tags:
                for t in tags:
                    if t in ("ENTRY", "CLOSE"):
                        action = t
                        break
            self.order_meta[order.order_id] = {
                "signal_id": signal_id,
                "action": action,
                "trigger_price": None,
            }

            return self.submit_order_internal(order)
        except Exception as e:
            logging.error("Error submit_market_order: %s", exc_info=e)
            return False

    def submit_stop_market_order(
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
            key = (strategy_id, symbol, signal_id)

            # If an entry already exists and quantity provided is None/0, use entry qty
            qty_to_use: float | None = None
            if quantity and float(quantity) > 0:
                # Normalize using StopMarket rules (treated like Market for lot sizing)
                try:
                    qty_to_use = float(
                        self.reference_data_manager.get_effective_quantity(
                            OrderType.Market, symbol, quantity
                        )
                    )
                except Exception:
                    qty_to_use = float(quantity)
            else:
                entry = self._entry_by_signal.get(key)
                if entry is not None:
                    try:
                        qty_to_use = float(
                            self.reference_data_manager.get_effective_quantity(
                                OrderType.Market, symbol, entry["qty"]
                            )
                        )
                    except Exception:
                        qty_to_use = float(entry["qty"])

            if qty_to_use is None:
                # Defer until entry is filled; store pending stop request
                self._pending_stop_by_signal[key] = {
                    "side": side,
                    "trigger_price": trigger_price,
                    "tags": tags,
                }
                logging.info(f"Pending StopMarket recorded for key={key} trigger={trigger_price}")
                return True

            # Submit immediately
            order = self.order_pool.acquire()
            order.initialize(self.id_generator.next())
            order.update_order_fields(
                side, qty_to_use, symbol, current_milli_time(), trigger_price, strategy_id
            )
            order.order_type = OrderType.StopMarket

            # Attach meta
            self.order_meta[order.order_id] = {
                "signal_id": signal_id,
                "action": "STOP_LOSS",
                "trigger_price": trigger_price,
            }

            return self.submit_order_internal(order)
        except Exception as e:
            logging.error("Error submit_stop_market_order: %s", exc_info=e)
            return False

    def submit_market_entry(
        self,
        strategy_id: str,
        symbol: str,
        side: Side,
        quantity: float,
        price: float,
        signal_id: str | None = None,
        tags: list[str] | None = None,
    ) -> bool:
        try:
            order = self.order_pool.acquire()
            order.initialize(self.id_generator.next())
            try:
                effective_qty = self.reference_data_manager.get_effective_quantity(
                    OrderType.Market, symbol, quantity
                )
            except Exception:
                effective_qty = quantity
            order.update_order_fields(
                side, float(effective_qty), symbol, current_milli_time(), price, strategy_id
            )
            order.order_type = OrderType.Market
            action = None
            if tags:
                for t in tags:
                    if t == "ENTRY":
                        action = t
            self.order_meta[order.order_id] = {
                "signal_id": signal_id,
                "action": action,
                "trigger_price": None,
            }
            return self.submit_order_internal(order)
        except Exception as e:
            logging.error("Error submit_market_entry: %s", exc_info=e)
            return False

    def submit_market_close(
        self,
        strategy_id: str,
        symbol: str,
        price: float,
        tags: list[str] | None = None,
    ) -> bool:
        # Flatten only the per-strategy position
        pos = None
        if hasattr(self, "position_manager"):
            pos = self.position_manager.get_position(symbol, strategy_id)
        if pos is None or not hasattr(pos, "position_amount") or abs(pos.position_amount) < 1e-8:
            logging.info(f"No open position to close for {strategy_id} {symbol}")
            return True
        qty = abs(pos.position_amount)
        if pos.position_amount > 0:
            close_side = Side.SELL
        else:
            close_side = Side.BUY
        # Normalization as for entry
        try:
            effective_qty = self.reference_data_manager.get_effective_quantity(
                OrderType.Market, symbol, qty
            )
        except Exception:
            effective_qty = qty
        order = self.order_pool.acquire()
        order.initialize(self.id_generator.next())
        order.update_order_fields(
            close_side, float(effective_qty), symbol, current_milli_time(), price, strategy_id
        )
        order.order_type = OrderType.Market
        action = None
        if tags:
            for t in tags:
                if t == "CLOSE":
                    action = t
        self.order_meta[order.order_id] = {
            "signal_id": None,
            "action": action,
            "trigger_price": None,
        }
        return self.submit_order_internal(order)

    def submit_order_internal(self, order: Order) -> bool:
        """Submit order - true FCFS across all strategies"""
        # Immediate queue insertion - no per-strategy queues

        if not order.is_id_init:
            logging.error(f"Order id not initialized ,unable to submit {order}")
            return False

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

        # Persist order to database
        if self.database_manager:
            try:
                meta = self.order_meta.get(order.order_id, {})
                self.database_manager.insert_order({
                    "order_id": order.order_id,
                    "strategy_id": order.strategy_id,
                    "symbol": order.symbol,
                    "side": order.side.name if order.side else "UNKNOWN",
                    "order_type": order.order_type.name if order.order_type else "Market",
                    "quantity": order.quantity,
                    "price": order.price,
                    "stop_price": meta.get("trigger_price"),
                    "status": order.order_status.name if order.order_status else "PENDING_NEW",
                    "action": meta.get("action"),
                    "tags": meta.get("tags"),
                    "timestamp": order.timestamp,
                })
            except Exception as e:
                logging.error(f"Failed to persist order: {e}")

        return True

    def on_order_event(self, order_event: OrderEvent):
        logging.info(f"Order event received {order_event}")
        status = order_event.status

        order = self.orders[order_event.client_order_id]
        if order is not None:
            if status == OrderStatus.FILLED:
                last_filled_quantity = float(order_event.last_filled_quantity)
                last_filled_price = float(order_event.last_filled_price)
                order.on_filled_event(last_filled_quantity, last_filled_price)
                self.add_position_by_strategy(order.strategy_id, last_filled_quantity, order.side)

                # Persist order event to database
                if self.database_manager:
                    try:
                        self.database_manager.insert_order_event(
                            order_id=order.order_id,
                            event_type="FILL",
                            status=status.name,
                            exchange_order_id=order_event.order_id,
                            filled_qty=last_filled_quantity,
                            filled_price=last_filled_price,
                        )
                        # Update order status in database
                        self.database_manager.update_order_status(
                            order_id=order.order_id,
                            status=order.order_status.name,
                            exchange_order_id=order_event.order_id,
                            filled_qty=order.filled_qty,
                            avg_price=order.avg_filled_price,
                        )
                    except Exception as e:
                        logging.error(f"Failed to persist order event: {e}")

                # Handle entry fill -> auto-place stop by signal_id if pending
                meta = self.order_meta.get(order.order_id)
                if meta and meta.get("signal_id") and (meta.get("action") == "ENTRY"):
                    key = (order.strategy_id, order.symbol, meta["signal_id"])
                    # Record entry info (final filled qty)
                    self._entry_by_signal[key] = {
                        "qty": order.filled_qty,
                        "side": order.side,
                        "price": order.avg_filled_price,
                    }
                    pending = self._pending_stop_by_signal.pop(key, None)
                    if pending:
                        # Derive stop side if not provided correctly: close the position
                        stop_side = pending["side"]
                        # If entry is BUY, stop should be SELL; if entry is SELL, stop should be BUY
                        try:
                            if order.side == Side.BUY:
                                stop_side = Side.SELL
                            elif order.side == Side.SELL:
                                stop_side = Side.BUY
                        except Exception:
                            pass
                        try:
                            qty = float(
                                self.reference_data_manager.get_effective_quantity(
                                    OrderType.Market, order.symbol, order.filled_qty
                                )
                            )
                        except Exception:
                            qty = float(order.filled_qty)
                        self.submit_stop_market_order(
                            strategy_id=order.strategy_id,
                            symbol=order.symbol,
                            side=stop_side,
                            quantity=qty,
                            trigger_price=float(pending["trigger_price"]),
                            signal_id=meta["signal_id"],
                            tags=pending.get("tags"),
                        )
            elif status == OrderStatus.CANCELED:
                order.on_order_cancel_event()
                # Persist cancel event to database
                if self.database_manager:
                    try:
                        self.database_manager.insert_order_event(
                            order_id=order.order_id,
                            event_type="CANCEL",
                            status=status.name,
                            exchange_order_id=order_event.order_id,
                        )
                        self.database_manager.update_order_status(
                            order_id=order.order_id,
                            status="CANCELED",
                            exchange_order_id=order_event.order_id,
                        )
                    except Exception as e:
                        logging.error(f"Failed to persist cancel event: {e}")
            elif status == OrderStatus.NEW:
                order.on_new_event()
                # Persist new order acknowledgement to database
                if self.database_manager:
                    try:
                        self.database_manager.insert_order_event(
                            order_id=order.order_id,
                            event_type="NEW",
                            status=status.name,
                            exchange_order_id=order_event.order_id,
                        )
                        self.database_manager.update_order_status(
                            order_id=order.order_id,
                            status="NEW",
                            exchange_order_id=order_event.order_id,
                        )
                    except Exception as e:
                        logging.error(f"Failed to persist new event: {e}")
            else:
                logging.error(f"Unknown order status: {order_event.status} {type(order_event.status)}")

        if order.is_in_order_done_state:
            order = self.orders.pop(order_event.client_order_id, None)
            logging.info(f"Order is done: {order}")
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
