import logging
from concurrent.futures import ThreadPoolExecutor
from operator import truediv
from typing import Callable, List, Dict, Set, Optional, Tuple

from common.interface_order import OrderEvent, OrderStatus, OrderType
from common.interface_reference_point import MarkPrice
from common.interface_req_res import PositionResponse
from engine.margin.margin_info_manager import MarginInfoManager
from engine.position.position import Position
from engine.reference_data.reference_price_manager import ReferencePriceManager
from engine.trading_cost.trading_cost_manager import TradingCostManager
from engine.trading_cost.trading_cost import TradingCost


class PositionManager:
    def __init__(
        self,
        margin_manager: MarginInfoManager,
        trading_cost_manager: TradingCostManager,
        reference_price_manager: ReferencePriceManager,
    ):
        self.name = "Position Manager"
        # Aggregate positions by symbol (backward compatible)
        self.positions: Dict[str, Position] = {}
        # Per-strategy positions keyed by (strategy_id, symbol)
        self.positions_by_key: Dict[Tuple[Optional[str], str], Position] = {}
        self.margin_manager = margin_manager
        self.trading_cost_manager = trading_cost_manager
        self.mark_price_dict = {}
        self.unrealized_pnl_listener: List[Callable[[float], None]] = []
        self.maint_margin_listener: List[Callable[[float], None]] = []
        self.realized_pnl_listener: List[Callable[[float], None]] = []
        # New per-symbol listeners
        self.position_amount_listener: List[Callable[[str, float], None]] = []
        self.open_orders_listener: List[Callable[[str, int], None]] = []
        # Track open orders by symbol and order id to avoid double counting
        self._open_orders_by_symbol: Dict[str, Set[str]] = {}
        self.symbol_realized_pnl = {}
        self.reference_price_manager = reference_price_manager
        self.executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="POS")
        # Optional order lookup to resolve strategy_id from order_id/client_id
        self._order_lookup: Optional[Callable[[str], Optional[object]]] = None

    def set_order_lookup(self, lookup_fn: Callable[[str], Optional[object]]):
        """
        Set an order lookup callback which accepts a client_id/order_id and returns
        an Order-like object having a 'strategy_id' attribute.
        """
        self._order_lookup = lookup_fn

    def inital_position(self, position_response: PositionResponse):
        all_pos = position_response.positions

        for pos in all_pos:
            symbol = pos["symbol"]
            position_amt = float(pos["positionAmt"])
            entry_price = float(pos["entryPrice"])
            unrealized_pnl = float(pos["unRealizedProfit"])
            maint_margin = float(pos["maintMargin"])

            # init
            trading_cost = self.trading_cost_manager.get_trading_cost(symbol)

            self.positions[symbol] = Position(
                symbol,
                position_amt,
                entry_price,
                unrealized_pnl,
                maint_margin,
                trading_cost,
                self.on_realized_pnl_update,
            )
            logging.info(f"Init position for symbol {symbol} {self.positions[symbol]}")
            # Emit initial position amount for listeners
            for listener in self.position_amount_listener:
                try:
                    listener(symbol, position_amt)
                except Exception as e:
                    logging.error(
                        self.name + " [POSITION_AMOUNT_INIT] Listener raised an exception: %s", e
                    )
            # trigger callback in another thread
            self.executor.submit(self.on_update_unrealized)

        for symbol, pos in self.positions.items():
            logging.info("[%s] Current Position %s", symbol, pos)

    def on_mark_price_event(self, mark_price: MarkPrice):
        symbol = mark_price.symbol
        price = float(mark_price.price)
        self.mark_price_dict[symbol] = price
        pos = self.positions.get(symbol)
        if pos is not None:
            self.update_maint_margin(pos)

    def on_order_event(self, order_event: OrderEvent):
        symbol = order_event.contract_name
        # Maintain open orders counts using order status
        order_id = getattr(order_event, "order_id", None)
        if order_id:
            s = self._open_orders_by_symbol.setdefault(symbol, set())
            if order_event.status in (
                OrderStatus.PENDING_NEW,
                OrderStatus.NEW,
                OrderStatus.OPEN,
                OrderStatus.PARTIALLY_FILLED,
            ):
                s.add(order_id)
            elif order_event.status in (
                OrderStatus.FILLED,
                OrderStatus.CANCELED,
                OrderStatus.FAILED,
            ):
                s.discard(order_id)
            # Emit open orders count
            count = len(self._open_orders_by_symbol.get(symbol, set()))
            # Update Position object if present
            pos = self.positions.get(symbol)
            if pos is not None:
                try:
                    pos.set_open_orders(count)
                except Exception:
                    logging.debug("Failed to set open orders on Position", exc_info=True)
            for listener in self.open_orders_listener:
                try:
                    listener(symbol, count)
                except Exception as e:
                    logging.error(self.name + " [OPEN_ORDERS] Listener raised an exception: %s", e)

        if order_event.status == OrderStatus.FILLED:
            # Resolve strategy_id via lookup if available
            strategy_id: Optional[str] = None
            try:
                if self._order_lookup is not None and getattr(order_event, "client_id", None):
                    order_obj = self._order_lookup(order_event.client_id)
                    if order_obj is not None:
                        strategy_id = getattr(order_obj, "strategy_id", None)
            except Exception:
                logging.debug("Failed to resolve strategy_id from order lookup", exc_info=True)

            self.update_or_add_position(order_event, strategy_id)

    def update_or_add_position(self, order_event: OrderEvent, strategy_id: Optional[str] = None):
        symbol = order_event.contract_name
        price = float(order_event.last_filled_price)
        size = float(order_event.last_filled_quantity)
        side = order_event.side

        is_taker = True
        if order_event.order_type != OrderType.Market:
            is_taker = False
        # Per-strategy key (None means aggregate bucket)
        key = (strategy_id, symbol)
        position = self.positions_by_key.get(key)
        if position is not None:
            current_size = size
            if side == "SELL":
                current_size = current_size * -1
            position.add_trade(current_size, price, is_taker)
            logging.info("Updating Position %s %s", symbol, position)
        else:
            current_size = size
            if side == "SELL":
                current_size = current_size * -1
            try:
                trading_cost = self.trading_cost_manager.get_trading_cost(symbol)
            except Exception:
                trading_cost = TradingCost(symbol, 0.0, 0.0)
            new_pos = Position(
                symbol,
                strategy_id,
                current_size,
                price,
                price,
                0,
                trading_cost,
                self.on_realized_pnl_update,
            )
            self.positions_by_key[key] = new_pos
            logging.info("Creating new Position %s (strategy=%s) %s", symbol, strategy_id, new_pos)

        # update_maint_margin on per-strategy position
        position = self.positions_by_key[key]
        self.update_maint_margin(position)

        # Maintain aggregate position by symbol for backward compatibility
        self._update_aggregate_position(symbol)
        # Emit position amount update
        try:
            for listener in self.position_amount_listener:
                listener(symbol, position.position_amount)
        except Exception as e:
            logging.error(self.name + " [POSITION_AMOUNT] Listener raised an exception: %s", e)

    # ---- Public APIs ----
    def get_position(self, symbol: str, strategy_id: Optional[str] = None) -> Optional[Position]:
        """
        Get position for a symbol. If strategy_id is provided, return the per-strategy position.
        Otherwise return aggregate position for the symbol.
        """
        if strategy_id is None:
            return self.positions.get(symbol)
        return self.positions_by_key.get((strategy_id, symbol))

    def aggregate_position(self, symbol: str) -> Optional[Position]:
        """Return aggregate position for symbol (alias of get_position without strategy)."""
        return self.get_position(symbol)

    def _update_aggregate_position(self, symbol: str):
        """
        Compute aggregate position for a symbol across all strategies and update self.positions[symbol].
        """
        total_qty = 0.0
        entry_price = 0.0
        realized_pnl = 0.0
        total_trading_cost = 0.0

        # Simple weighted average entry price and sum quantities across all keys for symbol
        for (sid, sym), pos in self.positions_by_key.items():
            if sym != symbol:
                continue
            total_qty += pos.position_amount
            realized_pnl += pos.net_realized_pnl
            total_trading_cost += pos.total_trading_cost

        # Compute aggregate entry price: if net qty non-zero, use mark price from reference or last known
        if abs(total_qty) > 0:
            mark = self.mark_price_dict.get(symbol)
            entry_price = mark.price if mark else 0.0

        existing = self.positions.get(symbol)
        if existing is None:
            try:
                trading_cost = self.trading_cost_manager.get_trading_cost(symbol)
            except Exception:
                trading_cost = TradingCost(symbol, 0.0, 0.0)
            self.positions[symbol] = Position(
                symbol=symbol, strategy_id=None, trading_cost=trading_cost
            )
            existing = self.positions[symbol]
        existing.position_amount = round(total_qty, 7)
        existing.entry_price = entry_price
        existing.net_realized_pnl = realized_pnl
        existing.total_trading_cost = total_trading_cost

    """
    update when mark price or position amount change 
    """

    def update_maint_margin(self, position: Position):

        symbol = position.symbol
        mark_price = self.mark_price_dict.get(symbol)
        if mark_price is not None:
            notional_amount = position.get_notional_amount(mark_price)
            bracket = self.margin_manager.get_margin_bracket_by_notional(symbol, notional_amount)
            if bracket is not None:
                maint_margin_rate = bracket.maintMarginRatio
                maint_amount = bracket.cum
                # update maint margin
                position.update_maintenance_margin(mark_price, maint_margin_rate, maint_amount)

                # trigger callback in another thread
                self.executor.submit(self.on_update_maint_margin)

            # update unrealized_pnl
            self.update_unrealized_pnl(position, mark_price)
        else:
            # No mark price yet in unit tests; skip margin/pnl updates
            pass

    def update_unrealized_pnl(self, position: Position, mark_price: float):
        position.update_unrealised_pnl(mark_price)
        # trigger callback in another thread
        self.executor.submit(self.on_update_unrealized)

    def on_update_unrealized(self):
        unreal = 0.0
        for pos in self.positions.values():
            unreal += pos.unrealised_pnl

        for listener in self.unrealized_pnl_listener:
            try:
                listener(unreal)
            except Exception as e:
                logging.error(self.name + "[UNREALIZED_PNL] Listener raised an exception: %s", e)

    def on_update_maint_margin(self):
        maint_margin = 0.0
        for pos in self.positions.values():
            maint_margin += pos.maint_margin

        for listener in self.maint_margin_listener:
            try:
                listener(maint_margin)
            except Exception as e:
                logging.error(self.name + "[MARGIN] Listener raised an exception: %s", e)

    def on_realized_pnl_update(self, symbol: str, realized_pnl: float):
        logging.info("Updating Realized PNL for %s : %s", symbol, realized_pnl)
        self.symbol_realized_pnl[symbol] = realized_pnl

        # trigger callback in another thread
        def task():
            real_pnl = 0.0
            for net_realized_pnl in self.symbol_realized_pnl.values():
                real_pnl += net_realized_pnl

            for listener in self.realized_pnl_listener:
                try:
                    listener(real_pnl)
                except Exception as e:
                    logging.error(self.name + "[REALIZED_PNL] Listener raised an exception: %s", e)

        self.executor.submit(task)

    def add_unrealized_pnl_listener(self, callback: Callable[[float], None]):
        self.unrealized_pnl_listener.append(callback)

    def add_realized_pnl_listener(self, callback: Callable[[float], None]):
        self.realized_pnl_listener.append(callback)

    def add_maint_margin_listener(self, callback: Callable[[float], None]):
        self.maint_margin_listener.append(callback)

    def add_position_amount_listener(self, callback: Callable[[str, float], None]):
        self.position_amount_listener.append(callback)

    def add_open_orders_listener(self, callback: Callable[[str, int], None]):
        self.open_orders_listener.append(callback)
