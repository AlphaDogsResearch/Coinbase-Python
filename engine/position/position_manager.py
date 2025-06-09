import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List

from common.interface_order import Trade, OrderEvent, OrderStatus
from common.interface_reference_point import MarkPrice
from common.interface_req_res import PositionResponse
from engine.margin.margin_info_manager import MarginInfoManager
from engine.position.position import Position


class PositionManager:
    def __init__(self, margin_manager:MarginInfoManager):
        self.name = "Position Manager"
        self.positions = {}
        self.margin_manager = margin_manager
        self.mark_price_dict={}
        self.unrealized_pnl_listener: List[Callable[[float], None]] = []
        self.maint_margin_listener: List[Callable[[float], None]] = []

        self.executor = ThreadPoolExecutor(max_workers=10,thread_name_prefix="POS")

    def inital_position(self, position_response:PositionResponse):
        all_pos = position_response.positions

        for pos in all_pos:
            symbol = pos['symbol']
            position_amt = float(pos['positionAmt'])
            entry_price = float(pos['entryPrice'])
            unrealized_pnl = float(pos['unRealizedProfit'])
            maint_margin = float(pos['maintMargin'])

            if symbol in self.positions:
                position = self.positions[symbol]
                position.unrealised_pnl = unrealized_pnl
                position.add_trade(position_amt)
            else:
                self.positions[symbol] = Position(symbol,position_amt,entry_price,unrealized_pnl,maint_margin)

        for symbol, pos in self.positions.items():
            logging.info("[%s] Current Position %s", symbol, pos)

    def on_mark_price_event(self,mark_price:MarkPrice):
        symbol = mark_price.symbol
        price = float(mark_price.price)
        self.mark_price_dict[symbol] = price
        pos = self.positions.get(symbol)
        if pos is not None:
            self.update_maint_margin(pos)

    def on_order_event(self,order_event:OrderEvent):
        if order_event.status == OrderStatus.FILLED:
            self.update_or_add_position(order_event)

    def update_or_add_position(self,order_event:OrderEvent):
        symbol = order_event.contract_name
        price = float(order_event.last_filled_price)
        size = float(order_event.last_filled_quantity)
        side = order_event.side

        if symbol in self.positions:
            position = self.positions[symbol]
            current_size = size
            if side == 'SELL':
                current_size = current_size * -1
            position.add_trade(current_size,price)

        else:
            current_size = size
            if side == 'SELL':
                current_size = current_size * -1
            self.positions[symbol] = Position(symbol, current_size, price, price, 0)

        # update_maint_margin
        position = self.positions[symbol]
        self.update_maint_margin(position)


    '''
    update when mark price or position amount change 
    '''
    def update_maint_margin(self,position:Position):

        symbol = position.symbol
        mark_price = self.mark_price_dict[symbol]
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

            #update unrealized_pnl
            self.update_unrealized_pnl(position,mark_price)


    def update_unrealized_pnl(self,position:Position,mark_price:float):
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
                logging.warning(self.name + "[PNL] Listener raised an exception: %s", e)

    def on_update_maint_margin(self):
        maint_margin = 0.0
        for pos in self.positions.values():
            maint_margin += pos.maint_margin

        for listener in self.maint_margin_listener:
            try:
                listener(maint_margin)
            except Exception as e:
                logging.warning(self.name + "[MARGIN] Listener raised an exception: %s", e)

    def add_pnl_listener(self, callback: Callable[[float], None]):
        self.unrealized_pnl_listener.append(callback)


    def add_maint_margin_listener(self, callback: Callable[[float], None]):
        self.maint_margin_listener.append(callback)


