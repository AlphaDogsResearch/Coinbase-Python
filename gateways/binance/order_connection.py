import logging

from common.interface_order import Order, NewOrderSingle, Trade
from common.subscription.single_pair_connection.single_pair import PairConnection

from gateways.binance.binance_gateway import BinanceGateway


def convert_order_to_new_order_single(order: Order) -> NewOrderSingle:
    symbol = order.symbol
    type = order.type
    price = order.price
    side = order.side
    qty = order.leaves_qty
    return NewOrderSingle(symbol, side, qty, type, price)


class OrderConnection:
    def __init__(self, port: int, gateway: BinanceGateway):
        self.order_listener_server = PairConnection(port, True, "Binance Order Listener")
        self.order_listener_server.start_receiving(self.submit_order)
        self.gateway = gateway
        # TODO add when we need trade
        # self.gateway.register_market_trades_callback(self.on_trade_event)

    ## should change to event
    def submit_order(self, order: Order):
        logging.info("order %s " % order)
        new_order_single = convert_order_to_new_order_single(order)
        logging.info("Order Submitted %s", new_order_single)
        order_id = self.gateway.submit_order(new_order_single)
        if order_id is not None:
            try:
                self.order_listener_server.send(order_id)
            except:
                print("Unable to send done trade order id back", order_id)

    def on_trade_event(self,trade :Trade):
        logging.info("Received Trade event %s" % trade)
        self.order_listener_server.send_trade(trade)

