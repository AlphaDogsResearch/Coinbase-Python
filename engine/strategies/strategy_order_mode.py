from abc import ABC, abstractmethod
from decimal import Decimal

from common.decimal_utils import round_up_decimal
from common.interface_order import OrderSizeMode

'''
This Class set the order mode of the strategy
Mode Notional -> place order by notional of quote asset
Mode Quantity -> place order by quantity of base asset
'''
class StrategyOrderMode:

    def __init__(self, order_size_mode: OrderSizeMode, notional_value: float = 0, quantity: float =0):
        self.order_size_mode = order_size_mode
        self.notional_value = notional_value
        self.quantity = quantity
        if self.order_size_mode is None:
            raise ValueError("Order SizeMode is None")

        if self.order_size_mode == OrderSizeMode.NOTIONAL and (self.notional_value is None or self.notional_value <= 0):
            raise ValueError("Order SizeMode NOTIONAL ,notional_value cannot be None or notional_value <= 0")

        if self.order_size_mode == OrderSizeMode.QUANTITY and (self.quantity is None or self.quantity <= 0):
            raise ValueError("Order SizeMode QUANTITY ,quantity cannot be None or quantity <= 0")



    def get_order_mode(self) -> OrderSizeMode:
        return self.order_size_mode

    def __str__(self):
        return (
            f"StrategyOrderMode(\n"
            f"  order_size_mode='{self.order_size_mode}',\n"
            f"  notional_value='{self.notional_value}',\n"
            f"  quantity='{self.quantity}',\n"
            f")"
        )

