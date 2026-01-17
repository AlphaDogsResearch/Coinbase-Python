import csv
import logging
from typing import Optional, TYPE_CHECKING

from common.interface_order import Trade, OrderEvent, OrderStatus, Side
from common.metrics.sharpe_calculator import BinanceFuturesSharpeCalculator

if TYPE_CHECKING:
    from engine.database.database_manager import DatabaseManager


class TradesManager:
    def __init__(
        self,
        sharpe_calculator: BinanceFuturesSharpeCalculator,
        database_manager: "DatabaseManager" = None,
    ):
        self.trades = {}
        self.sharpe_calculator = sharpe_calculator
        self.database_manager = database_manager
        # Track entry orders for PnL calculation
        self._entry_orders = {}  # symbol -> {order_id, price, qty, side, time}

    def load_trades(self, symbol: str, trades: list):
        self.trades[symbol] = trades
        logging.info("Loaded %s trades for %s", len(trades), symbol)
        self.sharpe_calculator.calculate_sharpe(trades)

    def on_order_event(self, order_event: OrderEvent):
        trade = self.create_trade_on_filled_event(order_event)
        if trade is not None:
            self.add_trade(trade.contract_name, trade)
            
            # Persist trade to database
            if self.database_manager:
                try:
                    # For simplicity, we record each fill as a trade
                    # In production, you might want to track entry/exit pairs
                    self.database_manager.insert_trade({
                        "strategy_id": getattr(order_event, "strategy_id", "unknown"),
                        "symbol": trade.contract_name,
                        "side": trade.side.name if trade.side else "UNKNOWN",
                        "quantity": float(trade.size),
                        "entry_price": float(trade.price),
                        "exit_price": None,  # Will be updated on close
                        "pnl": float(trade.realized_pnl),
                        "commission": 0,  # Would need fee info from exchange
                        "entry_time": int(trade.received_time) if trade.received_time else 0,
                        "exit_time": None,
                        "entry_order_id": trade.order_id,
                    })
                except Exception as e:
                    logging.error(f"Failed to persist trade: {e}")

    def add_trade(self, symbol: str, trade: Trade):
        if symbol in self.trades:
            trade_list = self.trades[symbol]
            trade_list.append(trade)

    def create_trade_on_filled_event(self, order_event: OrderEvent) -> Optional[Trade]:
        if order_event.status == OrderStatus.FILLED:
            order_id = order_event.order_id
            qty = order_event.last_filled_quantity
            time = order_event.last_filled_time
            price = order_event.last_filled_price
            symbol = order_event.contract_name
            side = Side[order_event.side]
            trade = Trade(time, symbol, price, qty, side, 0, False)
            trade.order_id = order_id
            return trade
        return None

