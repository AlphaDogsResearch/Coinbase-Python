import asyncio
import json
import logging
import threading
import uuid
from threading import Thread

from coinbase.rest import RESTClient
from coinbase.websocket import WSClient, WSClientConnectionClosedException, WSClientException, WebsocketResponse

from common.callback_utils import assert_param_counts
from common.interface_book import VenueOrderBook
from gateways.coinbase.aggregated_book.aggregated_order_book_manager import AggregatedOrderBookManager
from gateways.gateway_interface import GatewayInterface, ReadyCheck


class CoinbaseAdvancedGateway(GatewayInterface):
    def __init__(self, symbols, channels=None, name="CoinBase", api_key=None, api_secret=None,key_file=None, base_url=None, is_sand_box=True):
        # If keys are not provided, the SDK will read from environment variables
        # todo change key and secret to file
        if channels is None:
            channels = ["level2"]
        self.api_key = api_key
        self.api_secret = api_secret
        self.symbols = symbols
        self.is_sand_box = is_sand_box
        self.base_url = base_url
        self.channels = channels
        self.key_file = key_file
        self._depth_callbacks = []

        self.loop = asyncio.new_event_loop()
        self.order_book_manager = AggregatedOrderBookManager()

        logging.info("Initializing Coinbase Advanced Gateway, Symbols: {}".format(self.symbols) )

        if self.is_sand_box:
            if self.base_url is None:
                # use sandbox url for uat
                self.base_url = "api-sandbox.coinbase.com"
                logging.info("No base_url given, using default sandbox uat url {} for REST".format(self.base_url))
            self.rest_client = RESTClient(api_key=api_key, api_secret=api_secret,key_file=key_file, base_url=self.base_url)
        else:
            if self.base_url is None:
                self.rest_client = RESTClient(api_key=api_key, api_secret=api_secret,key_file=key_file)
            else:
                self.rest_client = RESTClient(api_key=api_key, api_secret=api_secret,key_file=key_file, base_url=base_url)


        self.ws_client = None
        self.ws_thread = None
        self._exchange_name = name
        self._ready_check = ReadyCheck()
        self._loop = asyncio.new_event_loop()

    def get_name(self):
        return self._exchange_name

    # ---- REST methods ----
    def list_products(self):
        if (self.is_sand_box):
            logging.info("Sandbox mode does not have list_products ")
            return None
        return self.rest_client.get_products()

    def get_product(self,product_id):
        if(self.is_sand_box):
            logging.info("Sandbox mode does not have get_product ")
            return None

        return self.rest_client.get_product(product_id=product_id)

    def get_accounts(self):
        return self.rest_client.get_accounts()

    def get_account(self, account_id):
        return self.rest_client.get_account(account_id)

    def generate_unique_id(self):
        return str(uuid.uuid4())

    def place_order(self, product_id, side, size, order_type="MARKET", price=None, stop_price=None,
                    stop_limit_price=None, time_in_force=None, post_only=None, cancel_after=None, stp=None):
        """
        Create a new order with Advanced Trade API

        Args:
            product_id (str): The product to trade (e.g., 'BTC-USD')
            side (str): 'BUY' or 'SELL'
            size (str): The base size for market orders or base quantity for limit orders
            order_type (str): 'MARKET', 'LIMIT', 'STOP', 'STOP_LIMIT'
            price (str, optional): Limit price for LIMIT and STOP_LIMIT orders
            stop_price (str, optional): Stop price for STOP and STOP_LIMIT orders
            stop_limit_price (str, optional): Limit price for STOP_LIMIT orders (alternative to price)
            time_in_force (str, optional): 'UNKNOWN_TIME_IN_FORCE', 'GOOD_UNTIL_DATE_TIME', 'GOOD_UNTIL_CANCELLED', 'IMMEDIATE_OR_CANCEL', 'FILL_OR_KILL'
            post_only (bool, optional): Whether the order should be post only
            cancel_after (str, optional): 'UNKNOWN_CANCEL_AFTER', 'MIN', 'HOUR', 'DAY'
            stp (str, optional): Self-trade prevention flag: 'UNKNOWN_STP', 'DECREMENT_AND_CANCEL', 'CANCEL_OLDEST', 'CANCEL_NEWEST', 'CANCEL_BOTH'
        """
        uuid = self.generate_unique_id()

        # Print all input parameters
        print("\n=== PLACE ORDER PARAMETERS ===")
        print(f"client_order_id: {uuid}")
        print(f"product_id: {product_id}")
        print(f"side: {side}")
        print(f"size: {size}")
        print(f"order_type: {order_type}")
        print(f"price: {price}")
        print(f"stop_price: {stop_price}")
        print(f"stop_limit_price: {stop_limit_price}")
        print(f"time_in_force: {time_in_force}")
        print(f"post_only: {post_only}")
        print(f"cancel_after: {cancel_after}")
        print(f"stp: {stp}")
        print("==============================\n")

        # Build order configuration
        order_config = {
            "client_order_id": uuid,
            "product_id": product_id,
            "side": side.upper(),  # Ensure uppercase
            "order_configuration": {}
        }

        # Handle different order types
        if order_type.upper() == "MARKET":
            print("Configuring MARKET order...")
            order_config["order_configuration"] = {
                "market_market_ioc": {
                    "base_size": str(size)
                }
            }
        elif order_type.upper() == "LIMIT":
            print("Configuring LIMIT order...")
            if not price:
                raise ValueError("Limit orders require a price parameter")
            limit_config = {
                "base_size": str(size),
                "limit_price": str(price)
            }
            if time_in_force:
                limit_config["time_in_force"] = time_in_force
                print(f"time_in_force set to: {time_in_force}")
            if post_only is not None:
                limit_config["post_only"] = post_only
                print(f"post_only set to: {post_only}")
            if cancel_after:
                limit_config["cancel_after"] = cancel_after
                print(f"cancel_after set to: {cancel_after}")
            order_config["order_configuration"] = {
                "limit_limit_gtc": limit_config
            }
        elif order_type.upper() == "STOP":
            print("Configuring STOP order...")
            if not stop_price:
                raise ValueError("Stop orders require a stop_price parameter")
            order_config["order_configuration"] = {
                "stop_limit_stop_limit_gtc": {
                    "base_size": str(size),
                    "limit_price": str(price) if price else str(stop_price),
                    "stop_price": str(stop_price)
                }
            }
        elif order_type.upper() == "STOP_LIMIT":
            print("Configuring STOP_LIMIT order...")
            if not stop_price or not (price or stop_limit_price):
                raise ValueError("STOP_LIMIT orders require stop_price and either price or stop_limit_price")
            order_config["order_configuration"] = {
                "stop_limit_stop_limit_gtc": {
                    "base_size": str(size),
                    "limit_price": str(price) if price else str(stop_limit_price),
                    "stop_price": str(stop_price)
                }
            }
        else:
            raise ValueError(f"Unsupported order type: {order_type}")

        # Add optional parameters
        if stp:
            order_config["stp"] = stp
            print(f"stp set to: {stp}")

        # Print final order configuration
        print("Final order configuration:")
        print(order_config)
        print("\n")

        return self.rest_client.create_order(**order_config)

    def cancel_order(self, order_id):
        return self.rest_client.cancel_order(order_id)

    def rest_client(self):
        return self.rest_client


    # ---- WebSocket ----

    def connect(self):
        logging.info('Initializing connection')
        self._loop.create_task(self._reconnect_ws())
        self._loop.run_forever()


    async def _reconnect_ws(self):
        logging.info("reconnecting")
        self._ready_check = ReadyCheck()
        self._init_cache()
        self.start_ws()

    def run_reconnect_in_thread(self):
        threading.Thread(
            target=lambda: asyncio.run_coroutine_threadsafe(
                self._reconnect_ws(), self.loop
            )
        ).start()

    def _has_keys(self) -> bool:
        return self.api_key and self.api_secret

    def _init_cache(self):
        logging.info("initializing cache")
        if self._has_keys():
            self._get_positions()
            self._get_wallet_balances()
        self._ready_check.snapshot_ready = True

    def start_ws(self):
        self.ws_client = WSClient(self.api_key, self.api_secret, on_message=self.on_message)
        try:
            self.ws_client.open()
            self.subscribe_all()
            self.ws_client.run_forever_with_exception_check()
        except WSClientConnectionClosedException as e:
            print("Connection closed! Retry attempts exhausted.")
        except WSClientException as e:
            print("Error encountered!")

    def subscribe_all(self):
        logging.info("Subscribing all symbols...")
        self.ws_client.subscribe(product_ids=self.symbols, channels=self.channels)

    def unsubscribe_all(self):
        self.ws_client.unsubscribe(product_ids=self.symbols,channels=self.channels)

    def register_depth_callback(self, callback):
        assert_param_counts(callback, 2)
        logging.info("Registering depth callback...")
        self._depth_callbacks.append(callback)

    def register_mark_price_callback(self, callback):
        assert_param_counts(callback, 2)

    def on_message(self,msg):
        try:
            logging.debug("Message \n %s", msg)
            json_message = json.loads(msg)
            if "type" in json_message:
                if json_message["type"] == "error":
                    print("Error Message", json_message["message"])
                    return

            ws_object = WebsocketResponse(json_message)
            if ws_object.channel == "l2_data":
                symbol = ""
                for event in ws_object.events:
                    if event["type"] == "snapshot":

                        product_id = event["product_id"]
                        symbol = product_id
                        event_updates = event["updates"]

                        # print("--------------")
                        # print("Snapshot : Product ID",product_id)
                        # print("Snapshot : No of Updates",len(event_updates))
                        # print("--------------")
                        for update in event_updates:
                            quantity = update['new_quantity']
                            side = update['side']
                            price = update['price_level']
                            event_time = update['event_time']
                            if side == "bid":
                                self.order_book_manager.add_bid(product_id, price, quantity,event_time)
                            elif side == "offer":
                                self.order_book_manager.add_ask(product_id, price, quantity,event_time)
                    elif event["type"] == "update":
                        product_id = event["product_id"]
                        symbol = product_id
                        event_updates = event["updates"]

                        # print("--------------")
                        # print("Incremental Update : Product ID",product_id)
                        # print("Incremental Update : No of Updates",len(event_updates))
                        # print("--------------")
                        for update in event_updates:
                            quantity = update['new_quantity']
                            side = update['side']
                            price = update['price_level']
                            event_time = update['event_time']
                            if side == "bid":
                                self.order_book_manager.update_bid(product_id, price, quantity,event_time)
                            elif side == "offer":
                                self.order_book_manager.update_ask(product_id, price, quantity,event_time)

                order_book = self.order_book_manager.get_order_book(symbol)
                if self._depth_callbacks:
                    for _cb in self._depth_callbacks:
                        _cb(self._exchange_name, VenueOrderBook(self._exchange_name, order_book))
                logging.debug(order_book)
                # logging.info("[%s] Best Bid %s Best Ask %s",symbol, self.order_book_manager.best_bid(symbol) , self.order_book_manager.best_ask(symbol))

        except:
            logging.error("Coinbase Gateway error Occurred ")

    def stop_ws(self):
        if self.ws_client:
            self.ws_client.stop()
            self.ws_thread.join()