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
import sys
import time
from pathlib import Path

# Add project root to Python path
PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

from common.config_loader import basic_config_loader
from common.config_logging import to_stdout
from gateways.binance.binance_gateway import BinanceGateway, ProductType
from gateways.binance.market_connection import MarketDataConnection
from gateways.binance.order_connection import OrderConnection
from common.config_symbols import TRADING_SYMBOLS

if __name__ == '__main__':
    logging.info("Running Binance Gateway...")
    to_stdout()

    # read key and secret from environment variable file
    base_dir = os.path.dirname(os.path.abspath(__file__))  # directory where this script is located
    dotenv_path = os.path.join(base_dir, 'vault', 'binance_keys')  # adjust '..' if needed
    load_dotenv(dotenv_path=dotenv_path)
    print("Loading env from:", dotenv_path)
    API_KEY = os.getenv('BINANCE_API_KEY')
    API_SECRET = os.getenv('BINANCE_API_SECRET')

    # json config for gateway variables
    environment = os.getenv("ENVIRONMENT", "development")
    logging.info("Environment: %s", environment)

    config = basic_config_loader.load_config(environment)
    logging.info(f"Config loaded. {config}")
    components = basic_config_loader.create_objects(config)
    logging.info(f"Components Created. {components}")

    default_settings_parameters = components['default_settings']

    gateway_name= default_settings_parameters['gateway_name']
    trading_symbols= default_settings_parameters['trading_symbols']
    market_data_connection_port= default_settings_parameters['market_data_connection_port']
    order_connection_port= default_settings_parameters['order_connection_port']

    # Use global config for trading symbols
    binance = BinanceGateway(symbols=trading_symbols, api_key=API_KEY, api_secret=API_SECRET, product_type=ProductType.FUTURE)
    binance.connect()

    market_data_connection = MarketDataConnection(gateway_name,market_data_connection_port, binance)

    order_connection = OrderConnection(gateway_name,order_connection_port, binance)

    while True:
        time.sleep(2)

        if binance.not_ready():
            logging.info("Not ready to trade")
        else:
            pass
            # orderBook = binance.get_order_book(contract)
            # logging.info('Depth: %s' % orderBook)
