# coinbase_gateway.py
import logging
import os
import time

from dotenv import load_dotenv

from common.config_logging import to_stdout
from gateways.coinbase.coinbase_gateway import CoinbaseAdvancedGateway
from gateways.coinbase.market_connection import MarketDataConnection
from gateways.coinbase.order_connection import OrderConnection

# ---- Example usage ----
if __name__ == "__main__":
    to_stdout()
    logging.info("Running CoinBase Gateway...")

    base_dir = os.path.dirname(os.path.abspath(__file__))  # directory where this script is located
    dotenv_path = os.path.join(base_dir, 'vault', 'coinbase_keys')  # adjust '..' if needed
    load_dotenv(dotenv_path=dotenv_path)
    api_key = os.getenv("COINBASE_TRADING_KEY_ID")
    api_secret = os.getenv("COINBASE_TRADING_SECRET")

    # api - public.sandbox.exchange.coinbase.com
    symbols = ["BTC-PERP-INTX", "ETH-PERP-INTX"]

    coinbase = CoinbaseAdvancedGateway(symbols=symbols, api_key=api_key, api_secret=api_secret, is_sand_box=True)


    market_data_port = 8090
    order_port = 8091
    gateway_name = "Coinbase"
    market_data_connection = MarketDataConnection(gateway_name,market_data_port, coinbase)

    order_connection = OrderConnection(gateway_name,order_port, coinbase)

    while True:
        time.sleep(2)

        if coinbase.not_ready():
            logging.info("Not ready to trade")
        else:
            coinbase.connect()
            pass
