import unittest

from common.interface_order import Order, Side, OrderType, OrderStatus, OrderEvent
from engine.management.order_management_system import FCFSOrderManager
from engine.reference_data.reference_price_manager import ReferencePriceManager
from engine.reference_data.reference_data_manager import ReferenceDataManager
from engine.margin.margin_info_manager import MarginInfoManager
from engine.trading_cost.trading_cost_manager import TradingCostManager


class DummyExecutor:
    def __init__(self, order_type: OrderType):
        self.order_type = order_type

    def on_signal(self, order: Order):
        pass


class EntryStopSignalLinkTests(unittest.TestCase):
    def setUp(self):
        self.symbol = "ETHUSDT"
        self.margin_manager = MarginInfoManager()
        self.trading_cost_manager = TradingCostManager()
        self.reference_price_manager = ReferencePriceManager()
        self.reference_data_manager = ReferenceDataManager(self.reference_price_manager)
        self.oms = FCFSOrderManager(DummyExecutor(OrderType.Market), None, self.reference_data_manager)

        # Minimal reference data: mark price for notional->qty approximation if needed
        self.reference_price_manager.mark_price_dict[self.symbol] = 2000.0

    def _fill(self, order: Order, filled_qty: float, filled_price: float):
        evt = OrderEvent(contract_name=self.symbol, order_id=order.order_id, execution_type=None, status=OrderStatus.FILLED, canceled_reason=None, client_order_id=order.order_id, order_type=order.order_type)
        evt.side = order.side.name
        evt.last_filled_price = filled_price
        evt.last_filled_quantity = filled_qty
        self.oms.on_order_event(evt)

    def test_entry_fill_triggers_stop_via_signal_id(self):
        strategy_id = "StratA"
        signal_id = "sig-123"

        # Submit stop ahead of entry with only trigger price and signal_id; qty deferred
        self.oms.submit_stop_market_order(strategy_id, self.symbol, Side.SELL, quantity=None, trigger_price=1950.0, signal_id=signal_id, tags=["STOP_LOSS", f"signal_id={signal_id}"])

        # Submit entry market order with quantity and signal_id via new API
        ok = self.oms.submit_market_order(
            strategy_id=strategy_id,
            symbol=self.symbol,
            side=Side.BUY,
            quantity=1.0,
            price=2000.0,
            signal_id=signal_id,
            tags=["ENTRY", f"signal_id={signal_id}"]
        )
        self.assertTrue(ok)
        # Find the created order object to emit fill
        entry = list(self.oms.orders.values())[-1]

        # Fill entry -> should auto-submit stop using entry qty
        self._fill(entry, 1.0, 2000.0)

        # Ensure a stop order exists in OMS orders cache (submitted)
        has_stop = any(o.order_type == OrderType.StopMarket for o in self.oms.orders.values())
        self.assertTrue(has_stop)


if __name__ == "__main__":
    unittest.main()


