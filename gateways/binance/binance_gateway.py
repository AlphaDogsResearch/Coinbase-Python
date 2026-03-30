"""
Binance gateway implementation using library https://github.com/sammchardy/python-binance
"""
import asyncio
import csv
import json
import logging
import sys
import threading
import time
from enum import Enum
from threading import Thread

import websocket
from binance import AsyncClient, BinanceSocketManager, DepthCacheManager
from binance import FuturesDepthCacheManager
from binance.client import Client
from binance.enums import FuturesType

from common.callback_utils import assert_param_counts
from common.file.file_utils import save_dict_to_file
from common.interface_book import VenueOrderBook, PriceLevel, OrderBook
from common.interface_order import Trade, Side, NewOrderSingle, OrderType
from gateways.gateway_interface import GatewayInterface, ReadyCheck


class ProductType(Enum):
    SPOT = 0
    FUTURE = 1  # USD_M, settle in USDT or BUSD


def log_session_header(url):
    # Detect Environment
    is_prod = "testnet" not in url.lower() and "uat" not in url.lower()

    # Theme Settings
    theme_color = '\033[91m' if is_prod else '\033[96m'  # Red for Prod, Cyan for UAT
    env_label = "PRODUCTION (LIVE)" if is_prod else "UAT (TESTNET)"
    status_msg = "LIVE EXECUTION ENABLED" if is_prod else "PAPER TRADING MODE"

    # ANSI Styles
    BOLD = '\033[1m'
    END = '\033[0m'

    # Header Construction
    border = f"{theme_color}--------------------------------------------------{END}"

    print(border)
    print(f"{theme_color}|{END}  {BOLD}ENVIRONMENT:{END}  {theme_color}{env_label}{END}".ljust(
        64) + f"{theme_color}|{END}")
    print(f"{theme_color}|{END}  {BOLD}ENDPOINT:{END}     {url}".ljust(58) + f"{theme_color}|{END}")
    print(
        f"{theme_color}|{END}  {BOLD}TIME:{END}         {time.strftime('%H:%M:%S')}".ljust(58) + f"{theme_color}|{END}")
    print(f"{theme_color}|{END}  {BOLD}STATUS:{END}       {status_msg}".ljust(58) + f"{theme_color}|{END}")
    print(border)
    print("")


class BinanceGateway(GatewayInterface):
    def __init__(self, symbols, api_key=None, api_secret=None, product_type=ProductType.SPOT, name='Binance',is_production=False):
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
        if not is_production:
            self.api_client.FUTURES_URL = 'https://testnet.binancefuture.com/fapi'

        log_session_header(self.api_client.FUTURES_URL)

        self._client = None
        self._bm = None
        self._dcm = {}  # symbol -> DepthCacheManager
        self._dws = {}  # symbol -> depth ws
        self._ts = {}  # symbol -> trade socket
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

    def _get_all_trades(self, symbol: str):
        try:
            trades = self.api_client.futures_account_trades(symbol=symbol)
            return trades
        except Exception as e:
            print("Error fetching trades:", e)
            return None

    def save_trades_to_csv(self, trades, filename='futures_trades.csv'):
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

    def get_commission_rate(self, symbol: str):
        try:
            if self._product_type == ProductType.FUTURE:
                data = self.api_client.futures_commission_rate(symbol=symbol)
            else:
                fees = self.api_client.get_trade_fee(symbol=symbol)
                # python-binance spot fee response can be dict or list depending on version
                if isinstance(fees, list):
                    data = fees[0] if fees else {}
                else:
                    trade_fee = fees.get("tradeFee", [])
                    data = trade_fee[0] if trade_fee else fees

            if not data:
                logging.warning(f"No commission data returned for {symbol}")
                return None

            logging.info(f"Info {symbol}: {data}")
            target_symbol = data.get('symbol', symbol)
            logging.info(f"Commission info for {target_symbol}:")
            logging.info(f"  Maker fee rate: {data.get('makerCommissionRate', data.get('makerCommission'))}")
            logging.info(f"  Taker fee rate: {data.get('takerCommissionRate', data.get('takerCommission'))}")
            return data
        except Exception as e:
            logging.exception(f"Error fetching commission rate for {symbol}: {e}")
            return None

    def get_trades_by_order_id(self, order_id, symbol: str):
        try:
            if self._product_type == ProductType.FUTURE:
                trades = self.api_client.futures_account_trades(symbol=symbol, orderId=order_id)
            else:
                # Spot does not accept orderId filter directly in get_my_trades
                all_trades = self.api_client.get_my_trades(symbol=symbol)
                trades = [t for t in all_trades if str(t.get("orderId")) == str(order_id)]

            for t in trades:
                qty = t.get('qty', t.get('origQty', t.get('quoteQty', '')))
                print(f"Trade ID: {t.get('id')}, Order ID: {t.get('orderId')}, Price: {t.get('price')}, Qty: {qty}")
            return trades
        except Exception as e:
            logging.exception(f"Error fetching trades by order id {order_id} for {symbol}: {e}")
            return None

    def get_user_trades(self, symbol, limit=10):
        logging.info(f"Getting All Trades limit: {limit}")
        try:
            if self._product_type == ProductType.FUTURE:
                trades = self.api_client.futures_account_trades(symbol=symbol, limit=limit)
            else:
                trades = self.api_client.get_my_trades(symbol=symbol, limit=limit)

            for t in trades:
                print(f"\nTrade ID: {t.get('id')}")
                print(f"  Symbol: {t.get('symbol')}")
                print(f"  Side: {t.get('side')}")
                print(f"  Price: {t.get('price')}")
                print(f"  Qty: {t.get('qty', t.get('origQty', t.get('quoteQty', '')))}")

                # Futures-specific fields
                if 'realizedPnl' in t and 'commission' in t:
                    print(f"  Realized PnL: {t['realizedPnl']}")
                    print(f"  Commission: {t['commission']} {t.get('commissionAsset', '')}")
                    net_pnl = float(t['realizedPnl']) - float(t['commission'])
                    print(f"  Net PnL: {net_pnl:.4f} {t.get('commissionAsset', '')}")
            return trades
        except Exception as e:
            logging.exception(f"Error fetching user trades for {symbol}: {e}")
            return None

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

    def register_mark_price_callback(self, callback):
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
        return self.send_order(self._api_key, self._api_secret, client_id, symbol, quantity, side, order_type, price)

    def send_order(self, key: str, secret: str, client_id: str, symbol: str, quantity: float, side: bool,
                   order_type: OrderType,
                   price: float):
        side_text = "BUY" if side else "SELL"
        order_params = {
            "newClientOrderId": client_id,
            "symbol": symbol,
            "side": side_text,
            "quantity": quantity,
            "newOrderRespType": "RESULT"
        }

        if order_type == OrderType.Limit:
            order_params["type"] = "LIMIT"
            order_params["timeInForce"] = "FOK"
            order_params["price"] = price
        else:
            order_params["type"] = "MARKET"

        logging.info(f"Submitting order with params: {order_params}")
        try:
            if self._product_type == ProductType.FUTURE:
                return self.api_client.futures_create_order(**order_params)
            return self.api_client.create_order(**order_params)
        except Exception as e:
            logging.exception(f"Failed to send order: {e}")
            return {"error": str(e), "symbol": symbol, "clientOrderId": client_id}

    ### not in use
    # external_order_id is binance order_id
    def get_filled_price(self, post_response_data: dict):
        symbol = post_response_data['symbol']
        order_id = post_response_data['orderId']

        logging.info(f"Fetching filled price for order {order_id} on {symbol} ")
        try:
            if self._product_type == ProductType.FUTURE:
                return self.api_client.futures_get_order(symbol=symbol, orderId=order_id)
            return self.api_client.get_order(symbol=symbol, orderId=order_id)
        except Exception as e:
            logging.exception(f"Failed to fetch filled price for order {order_id}: {e}")
            return {"error": str(e), "symbol": symbol, "orderId": order_id}

    def query_order(self, symbol: str, order_id: str):
        """
        Query open orders for a given symbol.

        :param symbol: The trading pair symbol to query.
        :return: A list of open orders.
        """
        if not self._has_keys():
            logging.error("Cannot query orders without API keys.")
            return []

        logging.info(f"Querying order {order_id} for {symbol} ")
        try:
            if self._product_type == ProductType.FUTURE:
                # Futures endpoint supports filtering open orders by orderId
                return self.api_client.futures_get_open_orders(symbol=symbol, orderId=order_id)

            # Spot: get all open orders for symbol and filter client-side if needed
            open_orders = self.api_client.get_open_orders(symbol=symbol)
            return [o for o in open_orders if str(o.get("orderId")) == str(order_id)]
        except Exception as e:
            logging.exception(f"Failed to query order {order_id} on {symbol}: {e}")
            return []
