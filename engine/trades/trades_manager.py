import csv
import logging
from typing import Optional

from common.interface_order import Trade, OrderEvent, OrderStatus, Side
from common.metrics.sharpe_calculator import BinanceFuturesSharpeCalculator


class TradesManager:
    def __init__(self, sharpe_calculator: BinanceFuturesSharpeCalculator):
        self.trades = {}
        self.sharpe_calculator = sharpe_calculator

    def load_trades(self, symbol: str, trades: list):
        self.trades[symbol] = trades
        logging.info("Loaded %s trades for %s", len(trades), symbol)
        self.sharpe_calculator.calculate_sharpe(trades)

    def on_order_event(self, order_event: OrderEvent):
        trade = self.create_trade_on_filled_event(order_event)
        if trade is not None:
            self.add_trade(trade.contract_name, trade)

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

