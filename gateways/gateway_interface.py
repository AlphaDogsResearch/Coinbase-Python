import logging

from common.interface_book import OrderBook


class GatewayInterface:

    def get_name(self):
        pass

    """ this gateway is not ready """
    def not_ready(self) -> bool:
        pass

    """ get position exchange """
    def get_position(self, symbol: str) -> float:
        pass

    """ get order book """
    def get_order_book(self, symbol: str) -> OrderBook:
        pass

    """ register a depth callback function takes three argument: 
        (exchange_name:str, contract_name:str, book: OrderBook) """
    def register_depth_callback(self, callback):
        pass

    """ register an execution callback function takes two arguments, 
        an order event: (exchange_name:str, event: OrderEvent, external: bool) """
    def register_execution_callback(self, callback):
        pass

    """ register a position callback whenever position is updated with fill info, takes three argument
            (exchange_name:str, contract_name:str, position: float """
    def register_position_callback(self, callback):
        pass

    """ register a callback to listen to market trades that takes one argument: [Trades] """
    def register_market_trades_callback(self, callback):
        pass

    """ register a mark price callback function takes 2 argument: 
         (self, symbol: str, price: float) """
    def register_mark_price_callback(self, callback):
        pass

    '''
    Order Related
    '''

    def submit_order(self, new_order_single):
        pass

    def get_filled_price(self, initial_er):
        pass

    def _get_wallet_balances(self):
        pass

    def _get_account_info(self):
        pass

    def get_reference_data(self):
        pass

    def _get_margin_tier_info(self):
        pass

    def _get_positions(self):
        pass

    def get_commission_rate(self, symbol):
        pass

    def _get_all_trades(self, symbol):
        pass


class ReadyCheck:
    """ Class to maintain readiness check """
    def __init__(self):
        self.ws_connected = False
        self.snapshot_ready = False
        self.depth_stream_ready = False
        self.orders_stream_ready = False
        self.position_stream_ready = False
        self.circuit_break = False
        self.lost_heartbeat = False

    def streams_ready(self) -> bool:
        """ Return a boolean to indicate streams readiness (True = all ready) or not (False = one or more not ready) """
        return self.snapshot_ready & self.ws_connected & self.depth_stream_ready & self.orders_stream_ready & self.position_stream_ready

    def not_ready(self) -> bool:
        """ Return a boolean to indicate if algo should sleep (True = should not trade) or not (True = ok to trade) """
        return not self.streams_ready() or self.circuit_break or self.lost_heartbeat