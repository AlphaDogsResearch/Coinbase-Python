import logging
from decimal import Decimal, ROUND_CEILING
from typing import Dict, Any

from _decimal import Decimal

from Lib.bdb import effective

from common.decimal_utils import convert_str_to_decimal, convert_to_decimal, round_up_decimal, is_multiple_of
from common.interface_order import OrderType
from common.interface_reference_data import ReferenceData
from engine.reference_data.reference_price_manager import ReferencePriceManager




'''
use Decimal to keep precision
'''
class ReferenceDataManager:
    def __init__(self,reference_price_manager: ReferencePriceManager):
        self.reference_data : Dict[str, ReferenceData] = {}
        self.reference_price_manager = reference_price_manager

    def init_reference_data(self,reference_data: Dict[str, ReferenceData]):
        self.reference_data = reference_data

    def convert_notional_to_quantity(self,notional_value:float, mark_price: float, step_size: float) -> Decimal | None:
        if mark_price is not None:
            converted_quantity = Decimal(notional_value) / Decimal(mark_price)
            return round_up_decimal(converted_quantity, step_size)
        return None

    def get_effective_quantity(self,order_type:OrderType,symbol:str,order_quantity:float) -> Decimal:
        effective_min_quantity = self.get_effective_min_quantity(order_type, symbol)
        _, min_step_size = self.get_quantity_min_step_size(order_type, symbol)
        is_multiple = is_multiple_of(order_quantity,min_step_size)
        if is_multiple:
            logging.info(f"Order quantity {order_quantity} is multiple of minimum step size {min_step_size} effective_min_quantity {effective_min_quantity}")
            return max(effective_min_quantity,convert_to_decimal(order_quantity))
        else:
            logging.info(f"Order quantity {order_quantity} is not a multiple of minimum step size {min_step_size} ")
            next_effective_qty = round_up_decimal(order_quantity, min_step_size)
            logging.info(f"Next effective quantity {next_effective_qty} vs effective_min_quantity{ effective_min_quantity}")
            return max(effective_min_quantity, next_effective_qty)


    def get_effective_quantity_by_notional(self, order_type: OrderType, symbol:str, order_notional:float) -> Decimal:
        effective_min_quantity = self.get_effective_min_quantity(order_type, symbol)
        mark_price = self.reference_price_manager.get_mark_price(symbol)
        _,min_step_size = self.get_quantity_min_step_size(order_type,symbol)
        order_notional_to_qty = self.convert_notional_to_quantity(order_notional,mark_price,min_step_size)
        final_quantity = max(order_notional_to_qty,effective_min_quantity)
        logging.info(f"order_notional{order_notional} | effective_min_quantity:{effective_min_quantity} order_notional_to_qty{order_notional_to_qty} -- > final_quantity:{final_quantity}")
        return final_quantity


    def get_effective_min_quantity(self, order_type:OrderType, symbol:str) -> Decimal | None:
        reference = self.reference_data[symbol]
        if reference is not None:
            min_lot_size ,min_step_size = self.get_quantity_min_step_size(order_type,symbol)
            min_notional_lot_size = self.get_min_size_by_notional(symbol, min_step_size)
            logging.info(f"min_notional_lot_size {min_notional_lot_size}, min_lot_size {min_lot_size}")
            return max(min_notional_lot_size, min_lot_size)
        return None


    def get_quantity_min_step_size(self,order_type:OrderType,symbol:str) -> tuple[Decimal, Decimal | Any] | Decimal:
        reference = self.reference_data[symbol]
        min_lot_size = convert_str_to_decimal("0")
        min_step_size = convert_str_to_decimal("0")
        if reference is not None:
            if order_type == OrderType.Market:
                min_lot_size = convert_to_decimal(reference.min_market_lot_size)
                min_step_size = reference.market_lot_step_size
            elif order_type == OrderType.Limit:
                min_lot_size = convert_to_decimal(reference.min_lot_size)
                min_step_size = reference.lot_step_size
            return min_lot_size,min_step_size
        logging.error("No reference data for symbol {}".format(symbol))
        return min_lot_size

    def min_notional(self,symbol:str) -> float | None:
        rd = self.reference_data[symbol]
        if rd is not None:
            return rd.min_notional
        return None


    def get_min_size_by_notional(self,symbol:str,step_size:float) -> Decimal | None:
        rd = self.reference_data[symbol]
        min_notional = rd.min_notional
        mark_price = self.reference_price_manager.get_mark_price(symbol)
        if min_notional is not None and mark_price is not None:
            min_qty =  Decimal(min_notional) / Decimal(mark_price)
            return round_up_decimal(min_qty, step_size)
        return None



