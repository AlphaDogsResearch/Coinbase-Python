import asyncio
import json
import logging
import threading
import uuid
import time
from decimal import Decimal, ROUND_DOWN
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
        # Callback registries (lists of callables)
        self._depth_callbacks = []
        self._mark_price_callbacks = []  # new mark price callbacks
        self._wallet_balance_callbacks = []
        self._position_callbacks = []
        self._open_orders_callbacks = []
        self._fills_callbacks = []
        # Unified generic event callback registry
        self._event_callbacks = {
            'depth': [], 'mark_price': [], 'wallet': [], 'position': [], 'open_orders': [], 'fills': []
        }
        # Caches & tracking
        self._client_to_server_order_id = {}
        self._product_cache = {}
        self._last_mid = {}  # symbol -> (mid_price, timestamp)
        self._last_ws_msg_ts = None

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
        client_id = self.generate_unique_id()

        logging.info(
            "PLACE_ORDER client_order_id=%s product_id=%s side=%s size=%s order_type=%s price=%s stop_price=%s stop_limit_price=%s time_in_force=%s post_only=%s cancel_after=%s stp=%s",
            client_id, product_id, side, size, order_type, price, stop_price, stop_limit_price, time_in_force, post_only, cancel_after, stp
        )

        # Build order configuration
        order_config = {
            "client_order_id": client_id,
            "product_id": product_id,
            "side": side.upper(),  # Ensure uppercase
            "order_configuration": {}
        }

        # Handle different order types
        if order_type.upper() == "MARKET":
            logging.debug("Configuring MARKET order for %s", product_id)
            order_config["order_configuration"] = {
                "market_market_ioc": {
                    "base_size": str(size)
                }
            }
        elif order_type.upper() == "LIMIT":
            logging.debug("Configuring LIMIT order for %s", product_id)
            if not price:
                raise ValueError("Limit orders require a price parameter")
            limit_config = {
                "base_size": str(size),
                "limit_price": str(price)
            }
            if time_in_force:
                limit_config["time_in_force"] = time_in_force
                logging.debug("time_in_force=%s", time_in_force)
            if post_only is not None:
                limit_config["post_only"] = post_only
                logging.debug("post_only=%s", post_only)
            if cancel_after:
                limit_config["cancel_after"] = cancel_after
                logging.debug("cancel_after=%s", cancel_after)
            order_config["order_configuration"] = {
                "limit_limit_gtc": limit_config
            }
        elif order_type.upper() == "STOP":
            logging.debug("Configuring STOP order for %s", product_id)
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
            logging.debug("Configuring STOP_LIMIT order for %s", product_id)
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
            logging.debug("stp=%s", stp)
        # Final configuration log
        logging.info("Final order configuration: %s", order_config)

        try:
            response = self.rest_client.create_order(**order_config)
            logging.info("Order placed: client_order_id=%s response_status=%s", client_id, response.get('status') if isinstance(response, dict) else 'UNKNOWN')
            # map client->server id
            try:
                if isinstance(response, dict):
                    server_id = response.get('order_id') or response.get('id') or response.get('orderId')
                    if server_id:
                        self._client_to_server_order_id[client_id] = server_id
            except Exception:
                logging.debug("Could not map client id %s to server id", client_id)
            return response
        except Exception as e:
            logging.error("Failed placing order product_id=%s client_order_id=%s error=%s", product_id, client_id, e, exc_info=True)
            raise

    def cancel_order(self, order_id):
        try:
            resp = self.rest_client.cancel_order(order_id)
            logging.info("Cancel order submitted order_id=%s", order_id)
            return resp
        except Exception as e:
            logging.error("Failed cancelling order_id=%s error=%s", order_id, e, exc_info=True)
            return None

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
            wallet = self._get_wallet_balances()
            if wallet:
                self._emit_wallet_balance(wallet)
            open_orders = self._get_open_orders()
            if open_orders:
                self._emit_open_orders(open_orders)
        self._ready_check.snapshot_ready = True

    def start_ws(self):
        self.ws_client = WSClient(self.api_key, self.api_secret, on_message=self.on_message)
        try:
            self.ws_client.open()
            self.subscribe_all()
            self.ws_client.run_forever_with_exception_check()
        except WSClientConnectionClosedException as e:
            logging.error("Websocket connection closed retry attempts exhausted error=%s", e, exc_info=True)
        except WSClientException as e:
            logging.error("Websocket client exception encountered error=%s", e, exc_info=True)

    def subscribe_all(self):
        logging.info("Subscribing all symbols...")
        self.ws_client.subscribe(product_ids=self.symbols, channels=self.channels)

    def unsubscribe_all(self):
        self.ws_client.unsubscribe(product_ids=self.symbols,channels=self.channels)

    def register_depth_callback(self, callback):
        assert_param_counts(callback, 2)
        self._depth_callbacks.append(callback)
        logging.info("Registered depth callback total=%d", len(self._depth_callbacks))

    def register_mark_price_callback(self, callback):
        assert_param_counts(callback, 2)
        self._mark_price_callbacks.append(callback)
        logging.info("Registered mark price callback total=%d", len(self._mark_price_callbacks))

    # ---- New callback registration methods ----
    def register_wallet_balance_callback(self, callback):
        assert_param_counts(callback, 1)
        self._wallet_balance_callbacks.append(callback)
        logging.info("Registered wallet balance callback total=%d", len(self._wallet_balance_callbacks))

    def register_position_callback(self, callback):
        # (symbol, position_dict)
        assert_param_counts(callback, 2)
        self._position_callbacks.append(callback)
        logging.info("Registered position callback total=%d", len(self._position_callbacks))

    def register_open_orders_callback(self, callback):
        assert_param_counts(callback, 1)
        self._open_orders_callbacks.append(callback)
        logging.info("Registered open orders callback total=%d", len(self._open_orders_callbacks))

    def register_fills_callback(self, callback):
        assert_param_counts(callback, 1)
        self._fills_callbacks.append(callback)
        logging.info("Registered fills callback total=%d", len(self._fills_callbacks))

    # --- Unregister specialized callbacks ---
    def unregister_depth_callback(self, callback):
        if callback in self._depth_callbacks:
            self._depth_callbacks.remove(callback)
        if callback in self._event_callbacks['depth']:
            self._event_callbacks['depth'].remove(callback)
    def unregister_mark_price_callback(self, callback):
        if callback in self._mark_price_callbacks:
            self._mark_price_callbacks.remove(callback)
        if callback in self._event_callbacks['mark_price']:
            self._event_callbacks['mark_price'].remove(callback)
    def unregister_wallet_balance_callback(self, callback):
        if callback in self._wallet_balance_callbacks:
            self._wallet_balance_callbacks.remove(callback)
        if callback in self._event_callbacks['wallet']:
            self._event_callbacks['wallet'].remove(callback)
    def unregister_position_callback(self, callback):
        if callback in self._position_callbacks:
            self._position_callbacks.remove(callback)
        if callback in self._event_callbacks['position']:
            self._event_callbacks['position'].remove(callback)
    def unregister_open_orders_callback(self, callback):
        if callback in self._open_orders_callbacks:
            self._open_orders_callbacks.remove(callback)
        if callback in self._event_callbacks['open_orders']:
            self._event_callbacks['open_orders'].remove(callback)
    def unregister_fills_callback(self, callback):
        if callback in self._fills_callbacks:
            self._fills_callbacks.remove(callback)
        if callback in self._event_callbacks['fills']:
            self._event_callbacks['fills'].remove(callback)

    # --- Unified generic callback API ---
    _EVENT_PARAM_COUNTS = {
        'depth': 2,
        'mark_price': 2,
        'wallet': 1,
        'position': 2,
        'open_orders': 1,
        'fills': 1,
    }
    def register_callback(self, event_type: str, callback):
        if event_type not in self._event_callbacks:
            raise ValueError(f"Unsupported event_type {event_type}")
        assert_param_counts(callback, self._EVENT_PARAM_COUNTS[event_type])
        self._event_callbacks[event_type].append(callback)
        logging.info("Registered generic callback type=%s total=%d", event_type, len(self._event_callbacks[event_type]))
    def unregister_callback(self, event_type: str, callback):
        if event_type not in self._event_callbacks:
            return False
        if callback in self._event_callbacks[event_type]:
            self._event_callbacks[event_type].remove(callback)
            return True
        return False
    def _dispatch_event(self, event_type: str, *args):
        for cb in list(self._event_callbacks.get(event_type, [])):
            try:
                cb(*args)
            except Exception as e:
                logging.debug("Generic event callback error type=%s error=%s", event_type, e)

    def on_message(self,msg):
        try:
            logging.debug("Message \n %s", msg)
            json_message = json.loads(msg)
            if "type" in json_message and json_message["type"] == "error":
                logging.error("WebSocket error message=%s", json_message.get("message"))
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

                # Emit order book depth
                order_book = self.order_book_manager.get_order_book(symbol)
                if symbol and order_book:
                    if self._depth_callbacks:
                        for _cb in self._depth_callbacks:
                            try:
                                _cb(self._exchange_name, VenueOrderBook(self._exchange_name, order_book))
                            except Exception:
                                logging.debug("Depth callback failed symbol=%s", symbol, exc_info=True)
                    # Generic dispatch
                    self._dispatch_event('depth', self._exchange_name, VenueOrderBook(self._exchange_name, order_book))
                    # Mark / mid price emission
                    try:
                        best_bid = self.order_book_manager.best_bid(symbol)
                        best_ask = self.order_book_manager.best_ask(symbol)
                        if best_bid is not None and best_ask is not None:
                            mid = (float(best_bid) + float(best_ask)) / 2.0
                            if self._mark_price_callbacks:
                                for _cb in self._mark_price_callbacks:
                                    try:
                                        _cb(self._exchange_name, mid)
                                    except Exception:
                                        logging.debug("Mark price callback failed symbol=%s", symbol, exc_info=True)
                            self._last_mid[symbol] = (mid, time.time())
                            self._dispatch_event('mark_price', self._exchange_name, mid)
                    except Exception as e:
                        logging.debug("Mark price emission failed symbol=%s error=%s", symbol, e)
                    logging.debug(order_book)
                    # logging.info("[%s] Best Bid %s Best Ask %s",symbol, self.order_book_manager.best_bid(symbol) , self.order_book_manager.best_ask(symbol))

        except Exception:
            logging.exception("Coinbase Gateway error occurred during on_message handling")

    def stop_ws(self):
        if self.ws_client:
            self.ws_client.stop()
            self.ws_thread.join()

    # ------------------------------
    # Data retrieval methods
    # ------------------------------
    ### TODO Check if wallet balances is accurate
    def _get_wallet_balances(self):
        try:
            if hasattr(self.rest_client, 'get_accounts'):
                all_accounts = self.rest_client.get_accounts() or []
                accounts = all_accounts.accounts
                wallet = {}
                for acc in accounts:
                    currency = acc['currency'] or acc['asset']
                    balance = acc['available_balance'] or acc['balance']
                    try:
                        bal_float = float(balance)
                    except Exception:
                        continue
                    wallet[currency] = bal_float
                logging.info("Wallet balances=%s", wallet)
                return wallet
        except Exception as e:
            logging.error("_get_wallet_balances failed error=%s", e, exc_info=True)
        return None

    def _get_open_orders(self):
        try:
            if hasattr(self.rest_client, 'list_orders'):
                orders = self.rest_client.list_orders()
                logging.info(f"Open orders count=%s", len(orders['orders']) if orders else 0)
                return orders
        except Exception as e:
            logging.error("_get_open_orders failed error=%s", e, exc_info=True)
        return None

    # ------------------------------
    # Emission helpers
    # ------------------------------
    def _emit_wallet_balance(self, wallet_snapshot: dict):
        for cb in self._wallet_balance_callbacks:
            try:
                cb(wallet_snapshot)
            except Exception as e:
                logging.error("wallet_balance_callback error=%s", e, exc_info=True)
        self._dispatch_event('wallet', wallet_snapshot)

    def _emit_position(self, symbol: str, position: dict):
        for cb in self._position_callbacks:
            try:
                cb(symbol, position)
            except Exception as e:
                logging.error("position_callback error=%s", e, exc_info=True)
        self._dispatch_event('position', symbol, position)

    def _emit_open_orders(self, orders: list):
        for cb in self._open_orders_callbacks:
            try:
                cb(orders)
            except Exception as e:
                logging.error("open_orders_callback error=%s", e, exc_info=True)
        self._dispatch_event('open_orders', orders)

    def _emit_fills(self, fills: list):
        for cb in self._fills_callbacks:
            try:
                cb(fills)
            except Exception as e:
                logging.error("fills_callback error=%s", e, exc_info=True)
        self._dispatch_event('fills', fills)

    # ------------------------------
    # Query helpers
    # ------------------------------
    def query_order(self, order_id: str = None, client_order_id: str = None):
        try:
            if hasattr(self.rest_client, 'get_order') and order_id:
                return self.rest_client.get_order(order_id=order_id)
            if hasattr(self.rest_client, 'list_orders'):
                orders = self.rest_client.list_orders() or []
                for o in orders:
                    if order_id and str(o.get('order_id')) == str(order_id):
                        return o
                    if client_order_id and str(o.get('client_order_id')) == str(client_order_id):
                        return o
            logging.info("query_order no match order_id=%s client_order_id=%s", order_id, client_order_id)
        except Exception as e:
            logging.error("query_order failed order_id=%s client_order_id=%s error=%s", order_id, client_order_id, e, exc_info=True)
        return None

    def get_fills_for_product(self, product_id: str, limit: int = 50):
        try:
            if hasattr(self.rest_client, 'list_fills'):
                fills = self.rest_client.list_fills(product_id=product_id, limit=limit) or []
                logging.info("Fetched fills product_id=%s count=%s", product_id, len(fills))
                self._log_fee_summary(fills)
                self._emit_fills(fills)
                return fills
        except Exception as e:
            logging.error("get_fills_for_product failed product_id=%s error=%s", product_id, e, exc_info=True)
        return []

    def get_fills_by_order(self, order_id: str):
        try:
            if hasattr(self.rest_client, 'list_fills'):
                fills = self.rest_client.list_fills(order_id=order_id) or []
                logging.info("Fetched fills order_id=%s count=%s", order_id, len(fills))
                self._log_fee_summary(fills)
                self._emit_fills(fills)
                return fills
        except Exception as e:
            logging.error("get_fills_by_order failed order_id=%s error=%s", order_id, e, exc_info=True)
        return []

    # ------------------------------
    # Fee / commission extraction
    # ------------------------------
    def _log_fee_summary(self, fills: list):
        total_fee = 0.0
        currency = None
        for f in fills:
            fee_fields = [f.get('fee'), f.get('commission'), f.get('fee_amount')]
            fee_val = None
            for ff in fee_fields:
                if ff is not None:
                    try:
                        fee_val = float(ff)
                        break
                    except Exception:
                        continue
            if fee_val is not None:
                total_fee += fee_val
            if currency is None:
                currency = f.get('fee_currency') or f.get('commission_currency') or f.get('currency')
        if fills:
            logging.info("Fee summary fills_count=%s total_fee=%.8f currency=%s", len(fills), total_fee, currency)

    # ------------------------------
    # Tier 1 helper / accessor methods
    # ------------------------------
    def get_best_bid_ask(self, symbol: str):
        try:
            return self.order_book_manager.best_bid(symbol), self.order_book_manager.best_ask(symbol)
        except Exception:
            return None, None

    def get_mark_price(self, symbol: str):
        data = self._last_mid.get(symbol)
        if not data:
            return None
        return data[0]

    def get_gateway_status(self):
        return {
            'exchange': self._exchange_name,
            'ws_connected': bool(self.ws_client),
            'symbols': list(self.symbols),
            'last_mid': {s: self._last_mid.get(s) for s in self.symbols},
            'snapshot_ready': self._ready_check.snapshot_ready,
        }

    def list_open_orders(self, symbol: str = None):
        orders = self._get_open_orders() or []
        if symbol:
            return [o for o in orders if o.get('product_id') == symbol]
        return orders

    def cancel_all_orders(self, symbol: str = None):
        results = {}
        orders = self.list_open_orders(symbol)
        for o in orders:
            oid = o.get('order_id') or o.get('id')
            if oid:
                try:
                    resp = self.cancel_order(oid)
                    results[oid] = resp
                except Exception as e:
                    results[oid] = f"error:{e}"
        logging.info("cancel_all_orders symbol=%s count=%d", symbol, len(results))
        return results

    def map_client_to_server_id(self, client_id: str):
        return self._client_to_server_order_id.get(client_id)

    def _get_product_metadata(self, product_id: str):
        if product_id in self._product_cache:
            return self._product_cache[product_id]
        try:
            if hasattr(self.rest_client, 'get_product'):
                data = self.rest_client.get_product(product_id=product_id)
                self._product_cache[product_id] = data
                return data
        except Exception as e:
            logging.debug("_get_product_metadata failed product_id=%s error=%s", product_id, e)
        return None

    def quantize_price(self, product_id: str, price: float):
        meta = self._get_product_metadata(product_id) or {}
        inc = meta.get('quote_increment') or meta.get('price_increment')
        try:
            if inc:
                d_inc = Decimal(str(inc))
                return float((Decimal(str(price)) // d_inc) * d_inc)
        except Exception:
            pass
        return price

    def quantize_size(self, product_id: str, size: float):
        meta = self._get_product_metadata(product_id) or {}
        inc = meta.get('base_increment') or meta.get('size_increment')
        try:
            if inc:
                d_inc = Decimal(str(inc))
                return float((Decimal(str(size)) // d_inc) * d_inc)
        except Exception:
            pass
        return size

    def validate_order_constraints(self, product_id: str, price: float = None, size: float = None):
        meta = self._get_product_metadata(product_id) or {}
        errors = []
        if price is not None:
            inc = meta.get('quote_increment') or meta.get('price_increment')
            if inc:
                try:
                    d_inc = Decimal(str(inc))
                    mod = Decimal(str(price)) % d_inc
                    if mod != 0:
                        errors.append(f"price not multiple of increment {inc}")
                except Exception:
                    pass
        if size is not None:
            inc = meta.get('base_increment') or meta.get('size_increment')
            if inc:
                try:
                    d_inc = Decimal(str(inc))
                    mod = Decimal(str(size)) % d_inc
                    if mod != 0:
                        errors.append(f"size not multiple of increment {inc}")
                except Exception:
                    pass
        return errors