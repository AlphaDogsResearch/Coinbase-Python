import logging
import os

from dotenv import load_dotenv

from common.config_logging import to_stdout
from common.interface_order import OrderType
from engine.account.account import Account
from engine.execution.executor import Executor
from engine.margin.margin_info_manager import MarginInfoManager
from engine.position.position_manager import PositionManager
from engine.remote.remote_market_data_client import RemoteMarketDataClient
from engine.remote.remote_order_service_client import RemoteOrderClient
from engine.risk.risk_manager import RiskManager
from engine.strategies.inflection_sma_crossover_strategy import (
    InflectionSMACrossoverStrategy,
)
from engine.strategies.strategy_manager import StrategyManager
from engine.tracking.in_memory_tracker import InMemoryTracker
from engine.tracking.telegram_alert import telegramAlert
from engine.market_data.candle import CandleAggregator


def main():
    to_stdout()
    logging.info("Running Engine...")
    start = True
    market_data = {"price": [], "ask": [], "bid": []}

    margin_manager = MarginInfoManager()
    position_manager = PositionManager(margin_manager)

    # Setup telegram Alert
    dotenv_path = "../gateways/binance/vault/telegram_keys"
    load_dotenv(dotenv_path=dotenv_path)
    telegram_api_key = os.getenv("API_KEY")
    telegram_user_id = os.getenv("USER_ID")
    telegram_alert = telegramAlert(telegram_api_key, telegram_user_id)

    # init account
    account = Account(telegram_alert, 0.8)
    position_manager.add_maint_margin_listener(account.on_maint_margin_update)
    position_manager.add_pnl_listener(account.on_unrealised_pnl_update)

    # initalise remote client
    remote_market_data_client = RemoteMarketDataClient()
    remote_order_client = RemoteOrderClient(margin_manager, position_manager, account)

    # setup risk manager
    risk_manager = RiskManager()  # TODO: Calculate portfolio var

    # create executor
    order_type = OrderType.Market
    executor = Executor(order_type, remote_order_client, risk_manager)

    # setup strategy manager
    strategy_manager = StrategyManager(executor)

    # init CandleAggregator and Strategy
    aggregator = CandleAggregator(
        interval_seconds=1
    )  # should change to 5 min (300) price aggregator
    strategy = InflectionSMACrossoverStrategy()  # need
    aggregator.add_candle_created_listener(strategy.on_candle_created)
    strategy_manager.add_strategy(strategy)
    remote_market_data_client.add_order_book_listener(aggregator.on_order_book)

    # attach position manager listener to remote client
    remote_market_data_client.add_mark_price_listener(
        position_manager.on_mark_price_event
    )

    tracker = InMemoryTracker(telegram_alert)

    while start:
        continue


if __name__ == "__main__":
    main()
