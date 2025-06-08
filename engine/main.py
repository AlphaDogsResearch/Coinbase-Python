import logging
import os
from dotenv import load_dotenv

from common.config_logging import to_stdout
from common.interface_order import OrderType
from engine.execution.executor import Executor
from engine.remote.remote_market_data_client import RemoteMarketDataClient
from engine.remote.remote_order_service_client import RemoteOrderClient
from engine.risk.risk_manager import RiskManager
from engine.strategies.sma import SMAStrategy
from engine.strategies.strategy_manager import StrategyManager
from engine.tracking.in_memory_tracker import InMemoryTracker
from engine.tracking.telegram_alert import telegramAlert


def main():
    to_stdout()
    logging.info("Running Engine...")
    start = True
    market_data = {"price": [], "ask": [], "bid": []}

    # initalise remote client
    remote_market_client = RemoteMarketDataClient()
    remote_order_client = RemoteOrderClient()

    # Setup telegram Alert
    dotenv_path = '../gateways/binance/vault/telegram_keys'
    load_dotenv(dotenv_path=dotenv_path)
    telegram_api_key = os.getenv('API_KEY')
    telegram_user_id = os.getenv('USER_ID')
    telegram_alert = telegramAlert(telegram_api_key, telegram_user_id)

    # setup risk manager
    risk_manager = RiskManager() #TODO: Calculate portfolio var

    # create executor
    order_type = OrderType.Limit
    executor = Executor(order_type,remote_order_client, risk_manager)

    # setup strategy manager
    strategy_manager = StrategyManager(executor)

    # add strategy
    short_sma = 50
    long_sma = 200
    amount = 0.001
    sma_strategy = SMAStrategy(short_sma, long_sma)
    strategy_manager.add_strategy(sma_strategy)

    # attach strategy manager listener to remote client
    remote_market_client.add_listener(strategy_manager.on_market_data_event)

    tracker = InMemoryTracker(telegram_alert)

    while start:
        continue

if __name__ == "__main__":
    main()
