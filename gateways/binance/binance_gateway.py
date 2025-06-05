"""
Binance gateway implementation using library https://github.com/sammchardy/python-binance
"""
import asyncio
import hashlib
import hmac
import logging
import sys
import time
from enum import Enum
from threading import Thread
from urllib.parse import urlencode

import requests
from binance import AsyncClient, BinanceSocketManager, DepthCacheManager
from binance import FuturesDepthCacheManager
from binance.client import Client
from binance.enums import FuturesType

from common.callback_utils import assert_param_counts
from common.interface_book import VenueOrderBook, PriceLevel, OrderBook
from common.interface_order import Trade, Side, NewOrderSingle, OrderType
from gateways.gateway_interface import GatewayInterface, ReadyCheck


class ProductType(Enum):
    SPOT = 0
    FUTURE = 1  # USD_M, settle in USDT or BUSD


def sign_url(secret: str, api_url, params: {}):
    # create query string
    query_string = urlencode(params)
    # signature
    signature = hmac.new(secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()

    # url
    return 'https://testnet.binancefuture.com' + api_url + "?" + query_string + "&signature=" + signature


class BinanceGateway(GatewayInterface):
    def __init__(self, symbol: str, api_key=None, api_secret=None, product_type=ProductType.SPOT, name='Binance'):
        self._api_key = api_key
        self._api_secret = api_secret
        self._exchange_name = name
        self._symbol = symbol
        self._product_type = product_type
        # Base URLs
        self.BASE_URL = 'https://testnet.binancefuture.com'

        # Connect to Futures Testnet

        self.api_client = Client(self._api_key, self._api_secret)
        self.api_client.FUTURES_URL = 'https://testnet.binancefuture.com/fapi'  # Point to Futures Testnet

        # binance async client
        self._client = None
        self._bm = None  # binance socket manager
        self._dcm = None  # depth cache, which implements the logic to manage a local order book
        self._dws = None  # depth async WebSocket session
        self._ts = None  # trade socket
        self._tws = None  # trade async WebSocket session

        # depth cache
        self._depth_cache = None

        # this is a loop and dedicated thread to run all async concurrent tasks
        self._loop = asyncio.new_event_loop()
        self._loop_thread = Thread(target=self._run_async_tasks, daemon=True, name=name)

        # readiness and circuit breaker flag
        self._ready_check = ReadyCheck()
        self._signal_reconnect = False

        # callbacks
        self._depth_callbacks = []
        self._market_trades_callbacks = []

    def connect(self):
        logging.info('Initializing connection')

        # get instrument static data
        self._get_static()

        self._loop.run_until_complete(self._reconnect_ws())

        logging.info("starting event loop thread")
        self._loop_thread.start()

    def _run_async_tasks(self):
        """ Run the following tasks concurrently in the current thread """
        self._loop.create_task(self._listen_depth_forever())
        self._loop.create_task(self._listen_trade_forever())
        self._loop.create_task(self._listen_private_forever())
        self._loop.run_forever()

    def _has_keys(self) -> bool:
        return self._api_key and self._api_secret

    async def _reconnect_ws(self):
        logging.info("reconnecting")
        self._ready_check = ReadyCheck()

        # initialize cache
        self._init_cache()

        # ws connect and authenticate
        await self._connect_authenticate_ws()

    def _init_cache(self):
        logging.info("initializing cache")
        if self._has_keys():
            self._get_positions()
            self._get_wallet_balances()
            self._get_orders()
            self._get_account_info()

        self._ready_check.snapshot_ready = True

    async def _connect_authenticate_ws(self):
        logging.info("connecting to ws")
        self._client = await AsyncClient.create(self._api_key, self._api_secret)
        self._bm = BinanceSocketManager(self._client)
        # connected
        self._ready_check.ws_connected = True

    async def _listen_depth_forever(self):
        logging.info("start subscribing and listen to depth events")
        while True:
            if not self._dws:
                logging.info("depth socket not connected, reconnecting")
                if self._product_type == ProductType.SPOT:
                    self._dcm = DepthCacheManager(self._client, symbol=self._symbol, bm=self._bm, ws_interval=100)
                elif self._product_type == ProductType.FUTURE:
                    self._dcm = FuturesDepthCacheManager(self._client, symbol=self._symbol, bm=self._bm)
                else:
                    sys.exit('Unrecognized product type: '.format(self._product_type))

                self._dws = await self._dcm.__aenter__()
                self._ready_check.depth_stream_ready = True

            # wait for depth update
            try:
                self._depth_cache = await self._dws.recv()

                if self._depth_callbacks:
                    for _cb in self._depth_callbacks:
                        _cb(self._exchange_name, VenueOrderBook(self._exchange_name, self._get_order_book()))

            except Exception as e:
                await self._handle_exception(e, 'encountered issue in depth processing')

    async def _listen_trade_forever(self):
        logging.info("start subscribing and listen to trade events")
        while True:
            if not self._tws:
                logging.info("trade socket not connected, reconnecting")
                if self._product_type == ProductType.SPOT:
                    self._ts = self._bm.aggtrade_socket(self._symbol)
                elif self._product_type == ProductType.FUTURE:
                    self._ts = self._bm.aggtrade_futures_socket(symbol=self._symbol, futures_type=FuturesType.USD_M)
                else:
                    sys.exit('Unrecognized product type: '.format(self._product_type))

                self._tws = await self._ts.__aenter__()

            # wait for trade message
            try:
                """
                {
                    "e": "trade",     // Event type
                    "E": 123456789,   // Event time
                    "s": "BNBBTC",    // Symbol
                    "t": 12345,       // Trade ID
                    "p": "0.001",     // Price
                    "q": "100",       // Quantity
                    "b": 88,          // Buyer order ID
                    "a": 50,          // Seller order ID
                    "T": 123456785,   // Trade time
                    "m": true,        // Is the buyer the market maker?
                    "M": true         // Ignore
                }                
                """
                message = await self._tws.recv()

                if self._market_trades_callbacks:
                    data = message['data']
                    trade = Trade(received_time=data['T'],
                                  contract_name=data['s'],
                                  price=float(data['p']),
                                  size=float(data['q']),
                                  side=Side.SELL if data['m'] is True else Side.BUY,
                                  liquidation=False)
                    for _cb in self._market_trades_callbacks:
                        _cb([trade])

            except Exception as e:
                await self._handle_exception(e, 'encountered issue in trade processing')

    async def _listen_private_forever(self):
        if not self._has_keys():
            logging.info('WS - Not subscribing to user events due to missing keys')
            self._ready_check.orders_stream_ready = True
            self._ready_check.position_stream_ready = True
            return

        # subscribe to user socket, which provides 3 events - account, order and trade updates
        self._ready_check.orders_stream_ready = True
        self._ready_check.position_stream_ready = True

    async def _handle_exception(self, e: Exception, msg: str):
        self._ready_check.ws_connected = False
        logging.exception(msg)
        # reset all sockets
        self._dws = None
        self._tws = None
        # reconnect client
        await self._reconnect_ws()

    def _get_order_book(self) -> OrderBook:
        bids = [PriceLevel(price=p, size=s) for (p, s) in self._depth_cache.get_bids()[:5]]
        asks = [PriceLevel(price=p, size=s) for (p, s) in self._depth_cache.get_asks()[:5]]
        return OrderBook(timestamp=self._depth_cache.update_time, contract_name=self._symbol, bids=bids, asks=asks)

    """ ----------------------------------- """
    """             REST API                """
    """ ----------------------------------- """

    def _get_static(self):
        logging.info('REST - Getting static data')

    def _get_positions(self):
        logging.info('REST - Getting position')
        positions = self.api_client.futures_position_information()

        for pos in positions:
            symbol = pos['symbol']
            position_amt = float(pos['positionAmt'])
            entry_price = float(pos['entryPrice'])
            unrealized_pnl = float(pos['unRealizedProfit'])
            maint_margin = float(pos['maintMargin'])
            if position_amt != 0:
                print(
                    f"Symbol: {symbol}, Position Amount: {position_amt}, Entry Price: {entry_price}, Unrealized PnL: {unrealized_pnl} Maintenance Margin {maint_margin}")

        return positions

    def _get_account_info(self):
        logging.info('REST - Getting account info')
        account_info = self.api_client.futures_account()
        print(f"Total Wallet Balance     : {account_info['totalWalletBalance']}")
        print(f"Total Margin Balance     : {account_info['totalMarginBalance']}")
        print(f"Total Unrealized PnL     : {account_info['totalUnrealizedProfit']}")
        print(f"Total Maintenance Margin : {account_info['totalMaintMargin']}")

        return account_info

    def _get_wallet_balances(self):
        logging.info('REST - Getting wallet balances')
        # Fetch account balance (Futures)
        futures_balance = self.api_client.futures_account_balance()

        wallet = {}

        # Print non-zero balances
        for asset in futures_balance:
            asset_name = asset['asset']
            balance = float(asset['balance'])
            if balance != 0:
                print(f"{asset_name}: {balance}")
                wallet[asset_name] = balance

        return wallet

    def _get_orders(self):
        logging.info('REST - Getting open orders')
        open_orders = self.api_client.futures_get_open_orders()

        for order in open_orders:
            symbol = order['symbol']
            order_id = order['orderId']
            price = order['price']
            qty = order['origQty']
            side = order['side']
            status = order['status']
            print(f"Order ID: {order_id}, Symbol: {symbol}, Side: {side}, Qty: {qty}, Price: {price}, Status: {status}")

    #############################################
    ##               Interface                 ##
    #############################################

    def get_name(self):
        return self._exchange_name

    def not_ready(self) -> bool:
        return self._ready_check is not None and self._ready_check.not_ready()

    def get_position(self, symbol: str) -> float:
        return 0

    def get_order_book(self, contract_name: str) -> OrderBook:
        return self._get_order_book()

    def register_depth_callback(self, callback):
        """ a depth callback function takes two argument: (exchange_name:str, book: VenueOrderBook) """
        assert_param_counts(callback, 2)
        self._depth_callbacks.append(callback)

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
        assert_param_counts(callback, 1)
        self._market_trades_callbacks.append(callback)

    def reconnect(self):
        """ A signals to reconnect """
        self._signal_reconnect = True

    def check_side(self, order: NewOrderSingle):
        return order.side == Side.BUY

    def submit_order(self, new_order: NewOrderSingle):
        order_type = new_order.type
        side = True
        if new_order.side == Side.SELL:
            side = False

        symbol = new_order.symbol
        quantity = new_order.quantity
        order_type = new_order.type
        price = new_order.price
        return self.send_order(self._api_key, self._api_secret, symbol, quantity, side, order_type, price)

    def send_order(self, key: str, secret: str, symbol: str, quantity: float, side: bool, order_type: OrderType,
                   price: float):
        # order parameters
        timestamp = int(time.time() * 1000)

        params = {
            "symbol": symbol,
            "side": "BUY" if side else "SELL",
            "type": "MARKET",
            "quantity": quantity,
            'timestamp': timestamp
        }

        if order_type == OrderType.Limit:
            params = {
                "symbol": symbol,  # e.g. "BTCUSDT"
                "side": "BUY" if side else "SELL",  # BUY or SELL
                "type": "LIMIT",  # Order type
                "timeInForce": "FOK",  # Time in Force (required for LIMIT) IOC/FOK/GTC
                "quantity": quantity,  # Order quantity
                "price": price,  # Limit price (must be string or float)
                "timestamp": timestamp  # Current timestamp in ms
            }

        # create query string
        query_string = urlencode(params)
        logging.info('Query string: {}'.format(query_string))

        # signature
        signature = hmac.new(secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()

        # url
        url = self.BASE_URL + '/fapi/v1/order' + "?" + query_string + "&signature=" + signature

        # post request
        session = requests.Session()
        session.headers.update(
            {"Content-Type": "application/json;charset=utf-8", "X-MBX-APIKEY": key}
        )
        response = session.post(url=url, params={})

        # get order id
        response_map = response.json()

        code = response_map.get('code')
        msg = response_map.get('msg')
        if code is not None:
            logging.error("Error Code: %s Message: %s", code, msg)
        order_id = response_map.get('orderId')

        return order_id

    def place_orders(self, order: dict):
        """
        Place orders using the specified execution strategy.

        :param order: A dictionary of order to be executed.
        """

        # order parameters
        timestamp = int(time.time() * 1000)
        self._signature = hmac.new(self._api_secret.encode("utf-8"), urlencode(order).encode("utf-8"),
                                   hashlib.sha256).hexdigest()

        logging.info(
            'Sending market order: Symbol: {}, Side: {}, Quantity: {}'.
            format(order['symbol'], order['side'], order['quantity'])
        )

        # new order url
        url = sign_url(self._api_secret, '/fapi/v1/order', order)

        # POST order request
        session = requests.Session()
        session.headers.update(
            {"Content-Type": "application/json;charset=utf-8", "X-MBX-APIKEY": self._api_key}
        )
        post_response = session.post(url=url, params={})
        post_response_data = post_response.json()
        logging.info(post_response_data)

        return post_response_data

    def query_order(self, symbol: str, order_id: str):
        """
        Query open orders for a given symbol.

        :param symbol: The trading pair symbol to query.
        :return: A list of open orders.
        """
        timestamp = int(time.time() * 1000)
        if not self._has_keys():
            logging.warning("Cannot query orders without API keys.")
            return []

        params = {
            "symbol": symbol,
            "orderId": order_id,
            "timestamp": timestamp
        }
        url = sign_url(self._api_secret, '/fapi/v1/openOrders', params)

        session = requests.Session()
        session.headers.update({"X-MBX-APIKEY": self._api_key})
        response = session.get(url=url)
        return response.json() if response.status_code == 200 else []
