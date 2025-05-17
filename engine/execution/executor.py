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


logging.basicConfig(format='%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s', level=logging.INFO)
BASE_URL = 'https://testnet.binancefuture.com'

def get_credentials():
    dotenv_path = '../../gateways/binance2/vault/binance_keys'
    load_dotenv(dotenv_path=dotenv_path)
    # return api key and secret as tuple
    return os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET')

def sign_url(secret: str, api_url, params: {}):
    # create query string
    query_string = urlencode(params)
    # signature
    signature = hmac.new(secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()

    # url
    return BASE_URL + api_url + "?" + query_string + "&signature=" + signature

class Executor(TradeExecution):
    def __init__(self, api_key: str, api_secret: str):
        """
        Initialize the executor with API key and secret.

        :param api_key: API key for authentication.
        :param api_secret: API secret for authentication.
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.signature = None

    def place_orders(self, key: str, secret: str, sym: str, quantity: float, side: bool):
        """
        Place orders using the specified execution strategy.

        :param orders: A dictionary of orders to be executed.
        """
        # order parameters
        timestamp = int(time.time() * 1000)
        side_str = "BUY" if side else "SELL"
        order_params = {
            "symbol": sym,
            "side": side_str,
            "type": "MARKET",
            "quantity": quantity,
            'timestamp': timestamp
        }
        self.signature = hmac.new(self.api_secret.encode("utf-8"), urlencode(order_params).encode("utf-8"), hashlib.sha256).hexdigest()

        logging.info(
            'Sending market order: Symbol: {}, Side: {}, Quantity: {}'.
            format(sym, side_str, quantity)
        )

        # new order url
        url = sign_url(secret, '/fapi/v1/order', order_params)

        # POST order request
        session = requests.Session()
        session.headers.update(
            {"Content-Type": "application/json;charset=utf-8", "X-MBX-APIKEY": key}
        )
        post_response = session.post(url=url, params={})
        post_response_data = post_response.json()
        logging.info(post_response_data)
        # GET filled price
        timestamp = int(time.time() * 1000)
        query_params = {
            "symbol": sym,
            "orderId": post_response_data['orderId'],
            "timestamp": timestamp
        }
        url = sign_url(secret, '/fapi/v1/order', query_params)
        get_response = session.get(url=url, params={})
        get_response_data = get_response.json()
        print(get_response_data)
        return get_response_data['avgPrice']
