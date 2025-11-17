import logging

from common.interface_order import Order, NewOrderSingle, Trade, ExecutionType, OrderEvent, OrderStatus, OrderType, Side
from common.interface_reference_data import ReferenceData
from common.interface_req_res import WalletRequest, AccountRequest, PositionRequest, MarginInfoRequest, \
    CommissionRateRequest, TradesRequest, ReferenceDataRequest
from common.subscription.single_pair_connection.single_pair import PairConnection
from gateways.gateway_interface import GatewayInterface


def convert_order_to_new_order_single(order: Order) -> NewOrderSingle:
    symbol = order.symbol
    type = order.order_type
    price = order.price
    side = order.side
    qty = order.leaves_qty
    client_id = order.order_id
    return NewOrderSingle(client_id, symbol, side, qty, type, price)


class OrderConnection:
    def __init__(self,name :str, port: int, gateway: GatewayInterface):
        self.order_listener_server = PairConnection(port, True, name+" Order Listener")
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
        elif isinstance(obj, CommissionRateRequest):
            self.get_commission_rates(obj)
        elif isinstance(obj, TradesRequest):
            self.get_trades(obj)
        elif isinstance(obj, ReferenceDataRequest):
            self.get_reference_data(obj)

    def submit_order(self, order: Order):
        logging.info("Submitted Order %s " % order)
        new_order_single = convert_order_to_new_order_single(order)
        logging.info("New Order Single %s" % new_order_single)
        initial_er = self.gateway.submit_order(new_order_single)
        order_event = self.on_execution_report(initial_er)
        logging.info("Order Event %s" % order_event)
        if order_event is not None:
            self.order_listener_server.publish_order_event(order_event)
            if order_event.status == OrderStatus.NEW:
                filled_er = self.gateway.get_filled_price(initial_er)
                filled_order_event = self.on_execution_report(filled_er)
                self.order_listener_server.publish_order_event(filled_order_event)

    def on_execution_report(self, execution_report: dict) -> OrderEvent:
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

            type = execution_report.get('type')
            order_type_type = OrderType.Market
            if type == "MARKET":
                order_type_type = OrderType.Market

            order_event = OrderEvent(symbol, external_order_id, ExecutionType.TRADE, OrderStatus.FILLED, None,
                                     client_order_id, order_type_type)
            order_event.side = side
            order_event.last_filled_quantity = float(last_filled_quantity)
            order_event.last_filled_price = float(last_filled_price)
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
        logging.info("Received Account Info Request %s" % account_request)
        account_info = self.gateway._get_account_info()
        wallet_balance = account_info['totalWalletBalance']
        margin_balance = account_info['totalMarginBalance']
        unreal_pnl = account_info['totalUnrealizedProfit']
        maint_margin = account_info['totalMaintMargin']
        account = account_request.handle(wallet_balance, margin_balance, unreal_pnl, maint_margin)
        self.order_listener_server.send_account_response(account)

    def get_reference_data(self, reference_data_request: ReferenceDataRequest):
        global min_price, max_price, price_tick_size, min_lot_size, max_lot_size, lot_step_size, min_market_lot_size, max_market_lot_size, market_lot_step_size, min_notional
        logging.info("Received Reference Data Request %s" % reference_data_request)
        gateway_reference_data = self.gateway.get_reference_data()
        if gateway_reference_data is None:
            logging.error("Reference Data Request Error")
        else:
            symbols = gateway_reference_data['symbols']
            reference_data_dict = {}
            for data in symbols:
                symbol = data['symbol']
                status = data['status']
                base_asset = data['baseAsset']
                quote_asset = data['quoteAsset']
                price_precision = data['pricePrecision']
                quantity_precision = data['quantityPrecision']
                filters = data['filters']
                if filters is not None:
                    for f in filters:
                        filter_type = f['filterType']
                        if filter_type == 'PRICE_FILTER':
                            min_price = f['minPrice']
                            max_price = f['maxPrice']
                            price_tick_size = f['tickSize']
                        elif filter_type == 'LOT_SIZE':
                            min_lot_size = f['minQty']
                            max_lot_size = f['maxQty']
                            lot_step_size = f['stepSize']
                        elif filter_type == 'MARKET_LOT_SIZE':
                            min_market_lot_size = f['minQty']
                            max_market_lot_size = f['maxQty']
                            market_lot_step_size = f['stepSize']
                        elif filter_type == 'MIN_NOTIONAL':
                            min_notional = f['notional']

                reference_data = ReferenceData(symbol,
                                               status,
                                               base_asset,
                                               quote_asset,
                                               price_precision,
                                               quantity_precision,
                                               min_price,
                                               max_price,
                                               price_tick_size,
                                               min_lot_size,
                                               max_lot_size,
                                               lot_step_size,
                                               min_market_lot_size,
                                               max_market_lot_size,
                                               market_lot_step_size,
                                               min_notional)
                reference_data_dict[symbol] = reference_data

            reference_data_response = reference_data_request.handle(reference_data_dict)
            self.order_listener_server.send_reference_data_response(reference_data_response)

    def get_margin_info(self, margin_info_request: MarginInfoRequest):
        request_symbol = margin_info_request.symbol

        if request_symbol not in self.margin_infos:
            margin_data = self.gateway._get_margin_tier_info()
            for md in margin_data:
                symbol = md['symbol']
                bracket = md['brackets']
                self.margin_infos[symbol] = bracket

        margin_i = self.margin_infos.get(request_symbol, None)

        mi_res = margin_info_request.handle(request_symbol, margin_i)
        self.order_listener_server.send_margin_info_response(mi_res)

    def get_position_info(self, position_request: PositionRequest):
        account_position = self.gateway._get_positions()
        positions = position_request.handle(account_position)
        self.order_listener_server.send_position_response(positions)

    def get_commission_rates(self, commission_rate_request: CommissionRateRequest):
        symbol = commission_rate_request.symbol
        commission_rate_data = self.gateway.get_commission_rate(symbol)
        if commission_rate_data is not None:
            returned_symbol = commission_rate_data['symbol']
            maker_trading_cost = commission_rate_data['makerCommissionRate']
            taker_trading_cost = commission_rate_data['takerCommissionRate']
            commission_rate = commission_rate_request.handle(returned_symbol, maker_trading_cost, taker_trading_cost)
            self.order_listener_server.send_commission_rate_response(commission_rate)

    def get_trades(self, trades_request: TradesRequest):
        logging.info("Received Trades Request %s" % trades_request)
        symbol = trades_request.symbol
        trades = self.gateway._get_all_trades(symbol)
        all_trades = []

        if trades is not None:
            for trade in trades:
                symbol = trade['symbol']
                side = trade['side']
                time = trade['time']
                order_id = trade['orderId']
                price = trade['price']
                qty = trade['qty']
                realized_pnl = trade['realizedPnl']

                trade_obj = Trade(time, symbol, price, qty, Side[side.upper()], realized_pnl, False)
                trade_obj.order_id = order_id

                all_trades.append(trade_obj)

        trade_response = trades_request.handle(symbol, all_trades)
        self.order_listener_server.send_trades_response(trade_response)
