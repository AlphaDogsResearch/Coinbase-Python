import logging

from common.interface_order import Order, NewOrderSingle, Trade, ExecutionType, OrderEvent, OrderStatus
from common.interface_req_res import WalletRequest, AccountRequest, PositionRequest, MarginInfoRequest
from common.subscription.single_pair_connection.single_pair import PairConnection
from gateways.binance.binance_gateway import BinanceGateway


def convert_order_to_new_order_single(order: Order) -> NewOrderSingle:
    symbol = order.symbol
    type = order.type
    price = order.price
    side = order.side
    qty = order.leaves_qty
    client_id = order.order_id
    return NewOrderSingle(client_id, symbol, side, qty, type, price)


class OrderConnection:
    def __init__(self, port: int, gateway: BinanceGateway):
        self.order_listener_server = PairConnection(port, True, "Binance Order Listener")
        self.order_listener_server.start_receiving(self.on_event)
        self.gateway = gateway
        self.margin_infos = {}

    def on_event(self, obj: object):
        if isinstance(obj, Order):
            self.submit_order(obj)
        elif isinstance(obj, WalletRequest):
            self.get_and_send_wallet(obj)
        elif isinstance(obj, AccountRequest):
            self.get_account_info(obj)
        elif isinstance(obj, PositionRequest):
            self.get_position_info(obj)
        elif isinstance(obj, MarginInfoRequest):
            self.get_margin_info(obj)

    def submit_order(self, order: Order):
        logging.info("Submitted Order %s " % order)
        new_order_single = convert_order_to_new_order_single(order)
        logging.info("New Order Single %s" % new_order_single)
        initial_er = self.gateway.submit_order(new_order_single)
        order_event = self.on_execution_report(initial_er)
        if order_event is not None:
            self.order_listener_server.publish_order_event(order_event)
            if order_event.status == OrderStatus.NEW:
                filled_er = self.gateway._get_filled_price(initial_er)
                filled_order_event = self.on_execution_report(filled_er)
                self.order_listener_server.publish_order_event(filled_order_event)

    def on_execution_report(self, execution_report: dict)->OrderEvent:
        logging.info("Execution Report %s" % execution_report)
        code = execution_report.get('code')
        msg = execution_report.get('msg')
        if code is not None:
            logging.error("Error Code: %s Message: %s", code, msg)

        status = execution_report.get('status')
        external_order_id = execution_report.get('orderId')
        client_order_id = execution_report.get('clientOrderId')
        symbol = execution_report.get('symbol')
        order_event = None
        if status == 'NEW':
            order_event = OrderEvent(symbol, external_order_id, ExecutionType.NEW, OrderStatus.NEW, None,
                                     client_order_id)

        elif status == 'FILLED':
            last_filled_price = execution_report.get('avgPrice')
            last_filled_quantity = execution_report.get('executedQty')
            last_filled_time = execution_report.get('updateTime')
            side = execution_report.get('side')
            order_event = OrderEvent(symbol, external_order_id, ExecutionType.TRADE, OrderStatus.FILLED, None,
                                     client_order_id)
            order_event.side  = side
            order_event.last_filled_quantity = last_filled_quantity
            order_event.last_filled_price = last_filled_price
            order_event.last_filled_time = last_filled_time

        else:
            logging.error("Unknown status %s", status)

        return order_event

    def on_trade_event(self, trade: Trade):
        logging.info("Received Trade event %s" % trade)
        self.order_listener_server.send_trade(trade)

    def get_and_send_wallet(self, wallet_request: WalletRequest):
        balance = self.gateway._get_wallet_balances()
        wallet_balance = wallet_request.handle(balance)
        self.order_listener_server.send_wallet_response(wallet_balance)

    def get_account_info(self, account_request: AccountRequest):
        account_info = self.gateway._get_account_info()
        wallet_balance = account_info['totalWalletBalance']
        margin_balance = account_info['totalMarginBalance']
        unreal_pnl = account_info['totalUnrealizedProfit']
        maint_margin = account_info['totalMaintMargin']
        account = account_request.handle(wallet_balance, margin_balance, unreal_pnl, maint_margin)
        self.order_listener_server.send_account_response(account)

    def get_margin_info(self,margin_info_request:MarginInfoRequest):
        request_symbol = margin_info_request.symbol

        if request_symbol not in self.margin_infos:
            margin_data = self.gateway._get_margin_tier_info()
            for md in margin_data:
                symbol = md['symbol']
                bracket = md['brackets']
                self.margin_infos[symbol] = bracket


        margin_i = self.margin_infos.get(request_symbol, None)

        mi_res= margin_info_request.handle(request_symbol,margin_i)
        self.order_listener_server.send_margin_info_response(mi_res)


    def get_position_info(self, position_request: PositionRequest):
        account_position = self.gateway._get_positions()
        positions = position_request.handle(account_position)
        self.order_listener_server.send_position_response(positions)

