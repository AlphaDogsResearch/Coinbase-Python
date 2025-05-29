"""
Open a paper trading account at Binance Futures Testnet: https://testnet.binancefuture.com/en/futures/BTCUSDT

After login in, there is an "API Key" tab at the bottom section where you will find API Key and API Secret.
Using Notepad or Notepad++, create a file with the following key-value pairs
and saved under directory /vault as "binance_keys"

    BINANCE_API_KEY=<API Key>
    BINANCE_API_SECRET=<API Secret>

Remember to keep these secret and do not share with anyone.

For further information:
https://www.binance.com/en/support/faq/how-to-test-my-functions-on-binance-testnet-ab78f9a1b8824cf0a106b4229c76496d

"""
import logging
import os
import time

from dotenv import load_dotenv

from common.config_logging import to_stdout
from gateways.binance.binance_gateway import BinanceGateway, ProductType
from gateways.binance.market_connection import MarketDataConnection
from gateways.binance.order_connection import OrderConnection

if __name__ == '__main__':
    logging.info("Running Binance Gateway...")
    to_stdout()

    # read key and secret from environment variable file
    dotenv_path = 'vault/binance_keys'
    load_dotenv(dotenv_path=dotenv_path)
    API_KEY = os.getenv('BINANCE_API_KEY')
    API_SECRET = os.getenv('BINANCE_API_SECRET')

    contract = 'BTCUSDT'
    binance = BinanceGateway(symbol=contract, api_key=API_KEY, api_secret=API_SECRET, product_type=ProductType.FUTURE)
    binance.connect()
    market_data_port = 8080
    order_port = 8081

    market_data_connection = MarketDataConnection(market_data_port, binance)

    order_connection = OrderConnection(order_port, binance)

    while True:
        time.sleep(2)

        if binance.not_ready():
            logging.info("Not ready to trade")
        else:
            pass
            # orderBook = binance.get_order_book(contract)
            # logging.info('Depth: %s' % orderBook)
