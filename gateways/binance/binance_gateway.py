"""
Binance gateway implementation using library https://github.com/sammchardy/python-binance
"""
import asyncio
import hashlib
import hmac
import json
import logging
import sys
import threading
import time
from enum import Enum
from threading import Thread
from urllib.parse import urlencode

import pandas as pd
import numpy as np
import csv

import requests
import websocket
from binance import AsyncClient, BinanceSocketManager, DepthCacheManager
from binance import FuturesDepthCacheManager
from binance.client import Client
from binance.enums import FuturesType
from binance.ws.depthcache import DepthCache

from common.callback_utils import assert_param_counts
from common.file.file_utils import save_dict_to_file
from common.interface_book import VenueOrderBook, PriceLevel, OrderBook
from common.interface_order import Trade, Side, NewOrderSingle, OrderType, OrderEvent, ExecutionType
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
    def __init__(self, symbols, api_key=None, api_secret=None, product_type=ProductType.SPOT, name='Binance'):
        """
        symbols: list of trading pairs (e.g. ["BTCUSDT", "ETHUSDT"])
        """
        self._api_key = api_key
        self._api_secret = api_secret
        self._exchange_name = name
        self._symbols = symbols if isinstance(symbols, list) else [symbols]
        self._product_type = product_type
        self.BASE_URL = 'https://testnet.binancefuture.com'

        self.api_client = Client(self._api_key, self._api_secret)
        self.api_client.FUTURES_URL = 'https://testnet.binancefuture.com/fapi'

        self._client = None
        self._bm = None
        self._dcm = {}  # symbol -> DepthCacheManager
        self._dws = {}  # symbol -> depth ws
        self._ts = {}   # symbol -> trade socket
        self._tws = {}  # symbol -> trade ws
        self._depth_cache = {}  # symbol -> cache

        self._loop = asyncio.new_event_loop()
        self._loop_thread = Thread(target=self._run_async_tasks, daemon=True, name=name)

        self._ready_check = ReadyCheck()
        self._signal_reconnect = False

        self._depth_callbacks = []
        self._mark_price_callbacks = []
        self._market_trades_callbacks = []

    def connect(self):
        logging.info('Initializing connection')

        # get instrument static data
        self._get_static()

        self._loop.run_until_complete(self._reconnect_ws())

        logging.info("starting event loop thread")
        self._loop_thread.start()

    def _run_async_tasks(self):
        for symbol in self._symbols:
            self._loop.create_task(self._listen_depth_forever(symbol))
            self._loop.create_task(self._listen_trade_forever(symbol))
        self._loop.create_task(self._listen_private_forever())
        self._loop.run_forever()

    def _has_keys(self) -> bool:
        return self._api_key and self._api_secret

    async def _reconnect_ws(self):
        logging.info("reconnecting")
        self._ready_check = ReadyCheck()
        self._init_cache()
        await self._connect_authenticate_ws()

    def _init_cache(self):
        logging.info("initializing cache")
        if self._has_keys():
            self._get_positions()
            self._get_wallet_balances()
            self._get_orders()
            self._get_account_info()
            self._get_margin_tier_info()
            self._start_websocket()
            self.get_reference_data()

            for symbol in self._symbols:
                self.get_user_trades(symbol)
                self.get_commission_rate(symbol)
                self._calculate_hourly_sharpe_ratio()
        self._ready_check.snapshot_ready = True

    async def _connect_authenticate_ws(self):
        logging.info("connecting to ws")
        self._client = await AsyncClient.create(self._api_key, self._api_secret)
        self._bm = BinanceSocketManager(self._client)
        self._ready_check.ws_connected = True

    async def _listen_depth_forever(self, symbol):
        logging.info(f"start subscribing and listen to depth events for {symbol}")
        while True:
            if symbol not in self._dws or not self._dws[symbol]:
                logging.info(f"depth socket not connected for {symbol}, reconnecting")
                if self._product_type == ProductType.SPOT:
                    self._dcm[symbol] = DepthCacheManager(self._client, symbol=symbol, bm=self._bm, ws_interval=100)
                elif self._product_type == ProductType.FUTURE:
                    self._dcm[symbol] = FuturesDepthCacheManager(self._client, symbol=symbol, bm=self._bm)
                else:
                    sys.exit('Unrecognized product type: '.format(self._product_type))

                self._dws[symbol] = await self._dcm[symbol].__aenter__()
                self._ready_check.depth_stream_ready = True

            try:
                self._depth_cache[symbol] = await self._dws[symbol].recv()
                if self._depth_callbacks:
                    for _cb in self._depth_callbacks:
                        order_book = self._get_order_book(symbol)
                        if order_book is None:
                            logging.info(f"Unable to get order book for {symbol}")
                            continue
                        _cb(self._exchange_name, VenueOrderBook(self._exchange_name, order_book))
            except Exception as e:
                await self._handle_exception(e, f'encountered issue in depth processing for {symbol}')

    async def _listen_trade_forever(self, symbol):
        logging.info(f"start subscribing and listen to trade events for {symbol}")
        while True:
            if symbol not in self._tws or not self._tws[symbol]:
                logging.info(f"trade socket not connected for {symbol}, reconnecting")
                if self._product_type == ProductType.SPOT:
                    self._ts[symbol] = self._bm.aggtrade_socket(symbol)
                elif self._product_type == ProductType.FUTURE:
                    self._ts[symbol] = self._bm.aggtrade_futures_socket(symbol=symbol, futures_type=FuturesType.USD_M)
                else:
                    sys.exit('Unrecognized product type: '.format(self._product_type))

                self._tws[symbol] = await self._ts[symbol].__aenter__()

            try:
                message = await self._tws[symbol].recv()
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
                await self._handle_exception(e, f'encountered issue in trade processing for {symbol}')

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

    # when disconnected _depth_cache will be empty
    def _get_order_book(self, symbol=None) -> OrderBook | None:
        try:
            cache = self._depth_cache[symbol]

            symbol = symbol or (self._symbols[0] if self._symbols else None)
            if symbol not in self._depth_cache or not cache:
                logging.warning(f'depth socket not found for {symbol}')
                return None


            if type(cache) is dict:
                if cache['e'] == 'error':
                    logging.error(f"Error while fetching depth for {symbol} probably due to disconnection")
                    return None

            # is DepthCache Object
            bids = [PriceLevel(price=p, size=s) for (p, s) in cache.get_bids()[:5]]
            asks = [PriceLevel(price=p, size=s) for (p, s) in cache.get_asks()[:5]]
            return OrderBook(timestamp=cache.update_time, contract_name=symbol, bids=bids,
                             asks=asks)
        except Exception as e:
            logging.error(f'Failed to get order book for {symbol} cache: {self._depth_cache} error: {e.with_traceback}')
            return None



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

    def _get_all_trades(self,symbol:str):
        try:
            trades = self.api_client.futures_account_trades(symbol=symbol)
            return trades
        except Exception as e:
            print("Error fetching trades:", e)
            return None

    def _calculate_hourly_sharpe_ratio(self):
        """
        Calculates the hourly and annualized Sharpe ratio based on realized PnL from futures trades.

        Returns:
        - sharpe (float): Hourly Sharpe ratio
        - annualized_sharpe (float): Annualized Sharpe ratio (hourly basis)
        """
        try:
            trades = self.api_client.futures_account_trades(symbol=self._symbols)
        except Exception as e:
            print("Error fetching trades:", e)
            return None, None

        pnl_data = []
        for trade in trades:
            pnl = float(trade['realizedPnl'])
            timestamp = pd.to_datetime(trade['time'], unit='ms')
            pnl_data.append({'timestamp': timestamp, 'realized_pnl': pnl})

        df = pd.DataFrame(pnl_data)

        if df.empty:
            print(f"No trades found for symbol: {self._symbols}")
            return 0.0, 0.0

        # Group by hourly bins
        df.set_index('timestamp', inplace=True)
        hourly = df.groupby(pd.Grouper(freq='H'))['realized_pnl'].sum().reset_index()

        # Calculate returns as pnl / account balance at calculation time
        hourly['return'] = hourly['realized_pnl'] / self.get_futures_usdt_balance()

        # Remove hours with no trades (optional, to avoid zero returns)
        # hourly = hourly[hourly['return'] != 0]

        if len(hourly) < 2:
            print("Not enough data points to calculate hourly Sharpe ratio.")
            return 0.0, 0.0

        mean_return = hourly['return'].mean()
        std_return = hourly['return'].std(ddof=1)
        sharpe = mean_return / std_return if std_return != 0 else 0

        # Annualize Sharpe ratio assuming ~8760 trading hours per year (crypto market doesn't close)
        # Total trading hours per year=24×365=8,760 hours/year
        annualized_sharpe = sharpe * np.sqrt(8760)

        print("Hourly Sharpe Ratio:", round(sharpe, 4))
        print("Annualized Hourly Sharpe Ratio:", round(annualized_sharpe, 4))

        return sharpe, annualized_sharpe

    def save_trades_to_csv(self,trades, filename='futures_trades.csv'):
        """
        Save futures trades data to CSV.

        trades: list of dicts returned by client.futures_account_trades()
        filename: str, name of the output CSV file
        """
        if not trades:
            print("No trades to save.")
            return

        # Extract CSV headers from keys of the first trade dict
        headers = trades[0].keys()

        with open(filename, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=headers)
            writer.writeheader()
            writer.writerows(trades)

        print(f"Saved {len(trades)} trades to {filename}")

    def _get_margin_tier_info(self):
        margin_data = self.api_client.futures_leverage_bracket()

        return margin_data

    def get_commission_rate(self,symbol:str):
        endpoint = "/fapi/v1/commissionRate"
        url = self.BASE_URL + endpoint

        timestamp = int(time.time() * 1000)
        params = {
            "symbol": symbol,
            "timestamp": timestamp
        }

        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        signature = hmac.new(
            self._api_secret.encode(),
            query_string.encode(),
            hashlib.sha256
        ).hexdigest()

        params['signature'] = signature

        headers = {
            "X-MBX-APIKEY": self._api_key
        }

        # TODO change to this
        # response = self.api_client.futures_commission_rate(symbol=symbol)
        response = requests.get(url, headers=headers, params=params)

        if response.status_code == 200:
            data = response.json()
            logging.info(f"Info {symbol}: {data}")
            logging.info(f"Commission info for {data['symbol']}:")
            #limit order
            logging.info(f"  Maker fee rate: {data['makerCommissionRate']}")
            #market order
            logging.info(f"  Taker fee rate: {data['takerCommissionRate']}")

            return data
        else:
            logging.error("Error:", response.status_code, response.text)

            return None

    def get_trades_by_order_id(self, order_id,symbol:str):
        endpoint = "/fapi/v1/userTrades"
        url = self.BASE_URL + endpoint

        timestamp = int(time.time() * 1000)
        params = {
            "symbol": symbol,
            "orderId": order_id,
            "timestamp": timestamp
        }

        query_string = '&'.join([f"{key}={params[key]}" for key in params])
        signature = hmac.new(
            self._api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        params['signature'] = signature
        headers = {
            "X-MBX-APIKEY": self._api_key
        }

        response = requests.get(url, headers=headers, params=params)

        if response.status_code == 200:
            trades = response.json()
            for t in trades:
                print(f"Trade ID: {t['id']}, Order ID: {t['orderId']}, Price: {t['price']}, Qty: {t['qty']}")
            return trades
        else:
            print("Error:", response.status_code, response.text)
            return None

    def get_user_trades(self,symbol, limit=10):
        logging.info(f"Getting All Trades limit: {limit}")
        endpoint = "/fapi/v1/userTrades"
        url = self.BASE_URL + endpoint

        timestamp = int(time.time() * 1000)
        params = {
            "symbol": symbol,
            "limit": limit,
            "timestamp": timestamp
        }

        query_string = '&'.join([f"{key}={params[key]}" for key in params])
        signature = hmac.new(
            self._api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        params['signature'] = signature

        headers = {
            "X-MBX-APIKEY": self._api_key
        }

        response = requests.get(url, headers=headers, params=params)

        if response.status_code == 200:
            trades = response.json()
            for t in trades:
                print(f"\nTrade ID: {t['id']}")
                print(f"  Symbol: {t['symbol']}")
                print(f"  Side: {t['side']}")
                print(f"  Price: {t['price']}")
                print(f"  Qty: {t['qty']}")
                print(f"  Realized PnL: {t['realizedPnl']}")
                print(f"  Commission: {t['commission']} {t['commissionAsset']}")
                net_pnl = float(t['realizedPnl']) - float(t['commission'])
                print(f"  Net PnL: {net_pnl:.4f} {t['commissionAsset']}")
        else:
            print("Error:", response.status_code, response.text)

    def _start_websocket(self):

        def on_message(ws, message):
            data = json.loads(message)

            # data information
            # {
            #     "p": "Mark Price – used for liquidation and PnL calculation",
            #     "i": "Index Price – weighted average spot price from multiple exchanges",
            #     "r": "Funding Rate – interest paid between longs/shorts at the next interval",
            #     "P": "Estimated Settle Price",
            #     "T": "Next Funding Time (UNIX ms)",
            #     "E": "Event timestamp",
            #     "e": "Event type",
            #     "s": "Symbol"
            # }

            symbol = data['s']
            mark_price = data['p']

            logging.debug(f"Mark Price: {data['p']}")

            if self._mark_price_callbacks:
                for _cb in self._mark_price_callbacks:
                    _cb(symbol, mark_price)

        def on_open(ws):
            print("Web socket connection opened")

        def on_close(ws, code, reason):
            print("Web socket connection closed")

        for symbol in self._symbols:
            logging.info(f"Starting Mark Price for Symbol: {symbol}")
            url = f"wss://fstream.binance.com/ws/{symbol.lower()}@markPrice"

            ws = websocket.WebSocketApp(url, on_message=on_message, on_open=on_open, on_close=on_close)
            thread = threading.Thread(target=ws.run_forever, daemon=True)
            thread.start()


    def _get_account_info(self):
        logging.info('REST - Getting account info')
        account_info = self.api_client.futures_account()
        print(f"Total Wallet Balance     : {account_info['totalWalletBalance']}")
        print(f"Total Margin Balance     : {account_info['totalMarginBalance']}")
        print(f"Total Unrealized PnL     : {account_info['totalUnrealizedProfit']}")
        print(f"Total Maintenance Margin : {account_info['totalMaintMargin']}")

        return account_info

    def get_reference_data(self):
        if self._product_type == ProductType.SPOT:
           return self._get_exchange_info()
        elif self._product_type == ProductType.FUTURE:
           return self._get_futures_exchange_info()
        return None

    def _get_futures_exchange_info(self):
        logging.info('REST - Getting Futures exchange info')
        futures_exchange_info = self.api_client.futures_exchange_info()

        # logging.info(f"Total Futures Exchange Info : {futures_exchange_info}")
        # save_dict_to_file(data=futures_exchange_info,filename="futures_exchange_info.json",method='json')
        return futures_exchange_info

    def _get_exchange_info(self):
        logging.info('REST - Getting exchange info')
        exchange_info = self.api_client.get_exchange_info()

        logging.info(f"Total Exchange Info : {exchange_info}")
        save_dict_to_file(data=exchange_info, filename="exchange_info.json", method='json')
        return exchange_info

    def get_futures_usdt_balance(self):
        """
        Fetch current USDT balance from Binance USDⓈ-M Futures account.
        """
        try:
            balances = self.api_client.futures_account_balance()
            usdt_balance = next((float(b['balance']) for b in balances if b['asset'] == 'USDT'), 0.0)
            return usdt_balance
        except Exception as e:
            print("Error fetching balance:", e)
            return 0.0

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
        return self._get_order_book(contract_name)

    def register_depth_callback(self, callback):
        """ a depth callback function takes two argument: (exchange_name:str, book: VenueOrderBook) """
        assert_param_counts(callback, 2)
        self._depth_callbacks.append(callback)

    def register_mark_price_callback(self,callback):
        """ a depth callback function takes two argument: (symbol:str, price: float) """
        assert_param_counts(callback, 2)
        self._mark_price_callbacks.append(callback)

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
        side = True
        if new_order.side == Side.SELL:
            side = False

        symbol = new_order.symbol
        quantity = new_order.quantity
        order_type = new_order.type
        price = new_order.price
        client_id = new_order.client_id
        return self.send_order(self._api_key, self._api_secret,client_id, symbol, quantity, side, order_type, price)

    def send_order(self, key: str, secret: str,client_id:str, symbol: str, quantity: float, side: bool, order_type: OrderType,
                   price: float):
        # order parameters
        timestamp = int(time.time() * 1000)

        params = {
            "newClientOrderId":client_id,
            "symbol": symbol,
            "side": "BUY" if side else "SELL",
            "type": "MARKET",
            "quantity": quantity,
            'timestamp': timestamp,
            "newOrderRespType": "RESULT"
        }

        if order_type == OrderType.Limit:
            params = {
                "newClientOrderId": client_id,
                "symbol": symbol,  # e.g. "BTCUSDT"
                "side": "BUY" if side else "SELL",  # BUY or SELL
                "type": "LIMIT",  # Order type
                "timeInForce": "FOK",  # Time in Force (required for LIMIT) IOC/FOK/GTC
                "quantity": quantity,  # Order quantity
                "price": price,  # Limit price (must be string or float)
                "timestamp": timestamp, # Current timestamp in ms
                "newOrderRespType":"RESULT"
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

        response_map = response.json()

        return response_map

    # external_order_id is binance order_id
    def get_filled_price(self, post_response_data:dict):
        # GET filled price
        timestamp = int(time.time() * 1000)
        symbol = post_response_data['symbol']
        order_id = post_response_data['orderId']

        session = requests.Session()
        session.headers.update(
            {"Content-Type": "application/json;charset=utf-8", "X-MBX-APIKEY": self._api_key}
        )

        query_params = {
            "symbol": symbol,
            "orderId": order_id,
            "timestamp": timestamp
        }
        url = sign_url(self._api_secret, '/fapi/v1/order', query_params)
        get_response = session.get(url=url, params={})
        get_response_data = get_response.json()

        return get_response_data

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
            logging.error("Cannot query orders without API keys.")
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
