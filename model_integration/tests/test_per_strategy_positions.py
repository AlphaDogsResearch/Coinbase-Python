import unittest

from common.interface_order import Order, Side, OrderType, OrderStatus, OrderEvent
from engine.management.order_management_system import FCFSOrderManager
from engine.reference_data.reference_data_manager import ReferenceDataManager
from engine.position.position_manager import PositionManager
from engine.margin.margin_info_manager import MarginInfoManager
from engine.trading_cost.trading_cost_manager import TradingCostManager
from engine.reference_data.reference_price_manager import ReferencePriceManager


class DummyExecutor:
    def __init__(self, order_type: OrderType):
        self.order_type = order_type

    def on_signal(self, order: Order):
        # Do nothing; tests will inject fills directly via OrderEvent
        pass


class PerStrategyPositionTests(unittest.TestCase):
    def setUp(self):
        self.symbol = "ETHUSDT"
        self.margin_manager = MarginInfoManager()
        self.trading_cost_manager = TradingCostManager()
        self.reference_price_manager = ReferencePriceManager()
        self.position_manager = PositionManager(
            self.margin_manager, self.trading_cost_manager, self.reference_price_manager
        )
        self.reference_data_manager = ReferenceDataManager(self.reference_price_manager)
        self.order_manager = FCFSOrderManager(
            executor=DummyExecutor(OrderType.Market),
            risk_manager=None,
            reference_data_manager=self.reference_data_manager,
        )
        # <-- Wire OMS to PositionManager for close lookup -->
        self.order_manager.position_manager = self.position_manager
        self.position_manager.set_order_lookup(lambda cid: self.order_manager.orders.get(cid))

    def _submit_order(self, strategy_id: str, side: Side, quantity: float, price: float) -> Order:
        order = self.order_manager.order_pool.acquire()
        order.update_order_fields(side, quantity, self.symbol, 0, price, strategy_id)
        # mimic submit (adds to orders cache)
        self.order_manager.submit_order_internal(order)
        return order

    def _fill(self, order: Order, filled_qty: float, filled_price: float):
        # Create an OrderEvent as delivered by remote
        evt = OrderEvent(
            contract_name=self.symbol,
            order_id=order.order_id,
            execution_type=None,
            status=OrderStatus.FILLED,
            canceled_reason=None,
            client_order_id=order.order_id,
            order_type=order.order_type,
        )
        evt.side = order.side.name
        evt.last_filled_price = filled_price
        evt.last_filled_quantity = filled_qty
        # Route to PositionManager
        self.position_manager.on_order_event(evt)

    def test_isolated_positions_by_strategy(self):
        # Strategy A buys 1
        a_order = self._submit_order("StratA", Side.BUY, 1.0, 2000.0)
        self._fill(a_order, 1.0, 2000.0)

        # Strategy B sells 0.5
        b_order = self._submit_order("StratB", Side.SELL, 0.5, 2100.0)
        self._fill(b_order, 0.5, 2100.0)

        # Verify isolation
        pos_a = self.position_manager.get_position(self.symbol, "StratA")
        pos_b = self.position_manager.get_position(self.symbol, "StratB")
        self.assertIsNotNone(pos_a)
        self.assertIsNotNone(pos_b)
        self.assertAlmostEqual(pos_a.position_amount, 1.0, places=7)
        self.assertAlmostEqual(pos_b.position_amount, -0.5, places=7)

        # Aggregate should be net 0.5
        agg = self.position_manager.aggregate_position(self.symbol)
        self.assertIsNotNone(agg)
        self.assertAlmostEqual(agg.position_amount, 0.5, places=7)

    def test_strategy_specific_close_behaviour(self):
        # Both Strats open
        a_order = self._submit_order("StratA", Side.BUY, 1.0, 2000.0)
        self._fill(a_order, 1.0, 2000.0)
        b_order = self._submit_order("StratB", Side.BUY, 2.0, 2000.0)
        self._fill(b_order, 2.0, 2000.0)

        # CLOSE only StratA
        oms = self.order_manager
        pos_a_before = self.position_manager.get_position(self.symbol, "StratA")
        pos_b_before = self.position_manager.get_position(self.symbol, "StratB")
        self.assertAlmostEqual(pos_a_before.position_amount, 1.0)
        self.assertAlmostEqual(pos_b_before.position_amount, 2.0)

        # Use the new flatten close
        ok = oms.submit_market_close("StratA", self.symbol, 2100.0)
        self.assertTrue(ok)

        # DEBUG: print all orders for this symbol
        print("ALL OMS ORDERS:")
        for o in oms.orders.values():
            print(
                f"oid={o.order_id} sid={getattr(o, 'strategy_id', None)} type={getattr(o, 'order_type', None)} side={getattr(o, 'side', None)} qty={getattr(o, 'quantity', None)}"
            )

        close_orders = [
            o
            for o in oms.orders.values()
            if getattr(o, "order_type", None) is not None
            and getattr(o.order_type, "name", None) == "Market"
            and o.side == Side.SELL
            and getattr(o, "strategy_id", None) == "StratA"
        ]
        self.assertTrue(close_orders)
        close_order = close_orders[-1]
        self._fill(close_order, 1.0, 2100.0)

        pos_a_after = self.position_manager.get_position(self.symbol, "StratA")
        pos_b_after = self.position_manager.get_position(self.symbol, "StratB")

        self.assertAlmostEqual(pos_a_after.position_amount, 0.0)
        self.assertAlmostEqual(pos_b_after.position_amount, 2.0, places=7)

    def test_open_close_and_stop_loss_flow(self):
        # Strategy A enters long 1 at 2000
        a_entry = self._submit_order("StratA", Side.BUY, 1.0, 2000.0)
        self._fill(a_entry, 1.0, 2000.0)

        pos_a = self.position_manager.get_position(self.symbol, "StratA")
        self.assertIsNotNone(pos_a)
        self.assertAlmostEqual(pos_a.position_amount, 1.0, places=7)

        # Strategy A closes with market sell 1 at 2100 (profit)
        a_close = self._submit_order("StratA", Side.SELL, 1.0, 2100.0)
        self._fill(a_close, 1.0, 2100.0)

        pos_a_after = self.position_manager.get_position(self.symbol, "StratA")
        self.assertIsNotNone(pos_a_after)
        self.assertAlmostEqual(pos_a_after.position_amount, 0.0, places=7)
        # Realized PnL positive (fees ignored in test default)
        self.assertGreaterEqual(pos_a_after.net_realized_pnl, 0.0)

        # Strategy B enters long 1 at 2100
        b_entry = self._submit_order("StratB", Side.BUY, 1.0, 2100.0)
        self._fill(b_entry, 1.0, 2100.0)

        # Strategy B gets stopped out via StopMarket sell at 2050
        b_sl = self._submit_order("StratB", Side.SELL, 1.0, 2050.0)
        # Mark this order as stop market for event
        b_sl.order_type = OrderType.StopMarket
        self._fill(b_sl, 1.0, 2050.0)

        pos_b_after = self.position_manager.get_position(self.symbol, "StratB")
        self.assertIsNotNone(pos_b_after)
        self.assertAlmostEqual(pos_b_after.position_amount, 0.0, places=7)
        # Realized PnL negative (stopped below entry)
        self.assertLessEqual(pos_b_after.net_realized_pnl, 0.0)

        # Aggregate should be flat after both strategies closed
        agg = self.position_manager.aggregate_position(self.symbol)
        self.assertIsNotNone(agg)
        self.assertAlmostEqual(agg.position_amount, 0.0, places=7)


if __name__ == "__main__":
    unittest.main()
