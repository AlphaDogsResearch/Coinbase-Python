import logging

from common.interface_order import Order, NewOrderSingle, Trade
from common.interface_req_res import WalletRequest, AccountRequest, PositionRequest
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
        self.order_listener_server.start_receiving(self.on_event)
        self.gateway = gateway
        # TODO add when we need trade
        # self.gateway.register_market_trades_callback(self.on_trade_event)


    def on_event(self,obj :object):
        if isinstance(obj, Order):
            self.submit_order(obj)
        elif isinstance(obj,WalletRequest):
            self.get_and_send_wallet(obj)
        elif isinstance(obj,AccountRequest):
            self.get_account_info(obj)
        elif isinstance(obj,PositionRequest):
            self.get_position_info(obj)

    def submit_order(self, order: Order):
        logging.info("order %s " % order)
        new_order_single = convert_order_to_new_order_single(order)
        logging.info("Order Submitted %s", new_order_single)
        order_id = self.gateway.submit_order(new_order_single)
        logging.info("Order ID %s",order_id)
        if order_id is not None:
            try:
                self.order_listener_server.send(str(order_id))
            except:
                print("Unable to send done trade order id back", order_id)

    def on_trade_event(self,trade :Trade):
        logging.info("Received Trade event %s" % trade)
        self.order_listener_server.send_trade(trade)

    def get_and_send_wallet(self,wallet_request :WalletRequest):
        balance = self.gateway._get_wallet_balances()
        wallet_balance = wallet_request.handle(balance)
        self.order_listener_server.send_wallet_response(wallet_balance)

    def get_account_info(self,account_request : AccountRequest):
        account_info = self.gateway._get_account_info()
        wallet_balance = account_info['totalWalletBalance']
        margin_balance = account_info['totalMarginBalance']
        unreal_pnl = account_info['totalUnrealizedProfit']
        maint_margin = account_info['totalMaintMargin']
        account = account_request.handle(wallet_balance,margin_balance,unreal_pnl,maint_margin)
        self.order_listener_server.send_account_response(account)

    def get_position_info(self,position_request : PositionRequest):
        account_position = self.gateway._get_positions()
        positions = position_request.handle(account_position)
        self.order_listener_server.send_position_response(positions)


