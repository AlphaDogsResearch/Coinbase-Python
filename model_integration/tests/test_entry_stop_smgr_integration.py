import unittest
from common.interface_order import Side, OrderType, OrderStatus, OrderEvent
from engine.management.order_management_system import FCFSOrderManager
from engine.strategies.strategy_manager import StrategyManager
from engine.reference_data.reference_price_manager import ReferencePriceManager
from engine.reference_data.reference_data_manager import ReferenceDataManager
from engine.margin.margin_info_manager import MarginInfoManager
from engine.trading_cost.trading_cost_manager import TradingCostManager
from engine.remote.remote_market_data_client import RemoteMarketDataClient

class DummyExecutor:
    def __init__(self, order_type: OrderType):
        self.order_type = order_type
    def on_signal(self, order):
        pass

class DummyMarketData(RemoteMarketDataClient):
    pass

class EntryStopStrategyMgrIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.symbol = "ETHUSDT"
        self.margin_manager = MarginInfoManager()
        self.trading_cost_manager = TradingCostManager()
        self.reference_price_manager = ReferencePriceManager()
        self.reference_data_manager = ReferenceDataManager(self.reference_price_manager)
        self.oms = FCFSOrderManager(DummyExecutor(OrderType.Market), None, self.reference_data_manager)
        self.smgr = StrategyManager(DummyMarketData(), self.oms)

    def _fill(self, order, filled_qty, filled_price):
        evt = OrderEvent(contract_name=self.symbol, order_id=order.order_id, execution_type=None, status=OrderStatus.FILLED, canceled_reason=None, client_order_id=order.order_id, order_type=order.order_type)
        evt.side = order.side.name
        evt.last_filled_price = filled_price
        evt.last_filled_quantity = filled_qty
        self.oms.on_order_event(evt)

    def test_full_entry_stop_flow(self):
        strategy_id = "IntegrStrategy"
        signal_id = "sigABC"
        # Pre-place stop (deferred)
        ok_stop = self.smgr.on_submit_stop_market_order(
            strategy_id=strategy_id,
            symbol=self.symbol,
            side=Side.SELL,
            quantity=None,
            trigger_price=1877.42,
            signal_id=signal_id,
            tags=["STOP_LOSS", f"signal_id={signal_id}"]
        )
        self.assertTrue(ok_stop)
        # Place entry market order
        ok_entry = self.smgr.on_submit_market_order(
            strategy_id=strategy_id,
            symbol=self.symbol,
            side=Side.BUY,
            quantity=1.1,
            price=1926.13,
            signal_id=signal_id,
            tags=["ENTRY", f"signal_id={signal_id}"]
        )
        self.assertTrue(ok_entry)
        entry_orders = [o for o in self.oms.orders.values() if o.order_type == OrderType.Market]
        self.assertTrue(len(entry_orders) >= 1)
        entry_order = entry_orders[-1]
        # Filling entry should create a stop-market order
        self._fill(entry_order, 1.1, 1926.13)
        stop_orders = [o for o in self.oms.orders.values() if o.order_type == OrderType.StopMarket]
        self.assertTrue(stop_orders, "Stop order should have been submitted after entry fill")

if __name__ == "__main__":
    unittest.main()
