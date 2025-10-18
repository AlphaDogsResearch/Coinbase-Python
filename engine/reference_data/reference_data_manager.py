from decimal import Decimal, ROUND_CEILING
from typing import Dict

from _decimal import Decimal

from common.interface_order import OrderType
from common.interface_reference_data import ReferenceData
from engine.reference_data.reference_price_manager import ReferencePriceManager


def round_up_decimal(value:float, step)->Decimal:
    value = Decimal(str(value))
    step = Decimal(str(step))
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step

'''
use Decimal to keep precision
'''
class ReferenceDataManager:
    def __init__(self,reference_price_manager: ReferencePriceManager):
        self.reference_data : Dict[str, ReferenceData] = {}
        self.reference_price_manager = reference_price_manager

    def init_reference_data(self,reference_data: Dict[str, ReferenceData]):
        self.reference_data = reference_data

    def get_effective_min_quantity(self, order_type:OrderType, symbol:str) -> Decimal | None:
        reference = self.reference_data[symbol]
        if reference is not None:
            min_market_lot_size = 0
            if order_type == OrderType.Market:
                min_market_lot_size = reference.min_market_lot_size
            elif order_type == OrderType.Limit:
                min_market_lot_size = reference.min_lot_size
            market_step_size = reference.market_lot_step_size
            min_notional_lot_size = self.get_min_size_by_notional(symbol, market_step_size)
            return max(min_notional_lot_size, min_market_lot_size)
        return None

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



