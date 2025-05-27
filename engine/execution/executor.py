"""
Executor class for executing orders using various strategies.
"""
from dotenv import load_dotenv
import logging
import os
import time
from urllib.parse import urlencode
import hmac
import hashlib
import requests

from engine.core.trade_execution import TradeExecution
from gateways.binance.binance_gateway import BinanceGateway


# logging.basicConfig(format='%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s', level=logging.INFO)
# BASE_URL = 'https://testnet.binancefuture.com'
#
# def get_credentials():
#     dotenv_path = '../../gateways/binance2/vault/binance_keys'
#     load_dotenv(dotenv_path=dotenv_path)
#     # return api key and secret as tuple
#     return os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET')
#
# def sign_url(secret: str, api_url, params: {}):
#     # create query string
#     query_string = urlencode(params)
#     # signature
#     signature = hmac.new(secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()
#
#     # url
#     return BASE_URL + api_url + "?" + query_string + "&signature=" + signature

class Executor(TradeExecution):
    def __init__(self, gateway: BinanceGateway):
        """
        Initialize the executor with API key and secret.

        :param api_key: API key for authentication.
        :param api_secret: API secret for authentication.
        """
        # self.api_key = api_key
        # self.api_secret = api_secret
        # self.signature = None
        self._gateway = gateway

    def place_orders(self, symbol: str, quantity: float, side: bool):
        """
        Place orders using the specified execution strategy.

        :param order: A dictionary of orders to be executed.
        """
        # order parameters
        timestamp = int(time.time() * 1000)
        side_str = "BUY" if side else "SELL"
        order_params = {
            "symbol": symbol,
            "side": side_str,
            "type": "MARKET",
            "quantity": quantity,
            'timestamp': timestamp
        }
        order_params_response = self._gateway.place_orders(order_params)
        return order_params_response

    def query_order(self, symbol: str, order_id: str):
        """
        Query the status of an order.

        :param order_id: The ID of the order to query.
        :return: The status of the order.
        """
        return self._gateway.query_order(symbol, order_id)

    def place_and_query_order(self, symbol: str, quantity: float, side: bool):
        """
        Place an order and query its status.

        :param symbol: The trading pair symbol.
        :param quantity: The quantity of the asset to trade.
        :param side: True for buy, False for sell.
        :return: The status of the order.
        """
        order_response = self.place_orders(symbol, quantity, side)
        order_id = order_response['orderId']
        if order_id:
            return self.query_order(symbol, order_id)
        else:
            logging.error("Order placement failed.")
            return None