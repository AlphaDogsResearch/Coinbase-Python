import logging
import os
import sys

from dotenv import load_dotenv

from common.config_logging import to_stdout
from common.interface_order import OrderType
from common.metrics.sharpe_calculator import BinanceFuturesSharpeCalculator
from engine.account.account import Account
from engine.database.database_connection import DatabaseConnectionPool
from engine.execution.executor import Executor
from engine.management.order_management_system import FCFSOrderManager
from engine.margin.margin_info_manager import MarginInfoManager
from engine.position.position import Position
from engine.position.position_manager import PositionManager
from engine.remote.remote_market_data_client import RemoteMarketDataClient
from engine.remote.remote_order_service_client import RemoteOrderClient
from engine.risk.risk_manager import RiskManager
from engine.strategies.sma import SMAStrategy
from engine.strategies.sma_crossover_inflection_strategy import (
    SMACrossoverInflectionStrategy,
)
from engine.strategies.strategy_manager import StrategyManager
from engine.tracking.in_memory_tracker import InMemoryTracker
from engine.tracking.telegram_alert import telegramAlert
from engine.market_data.candle import CandleAggregator
from engine.trades.trades_manager import TradesManager
from engine.trading_cost.trading_cost_manager import TradingCostManager
from engine.core.sizing import SizingPolicy

from graph.ohlc_plot import  RealTimePlotWithCandlestick
from graph.plot import RealTimePlot



from engine.core.order import Order
from common.config_symbols import TRADING_SYMBOLS


def main():
    # Configure logging with optional LOG_LEVEL env
    to_stdout()
    logging.info("Running Engine...")
    start = True

    # Get symbol from CLI argument
    if len(sys.argv) < 2:
        logging.error(f"Usage: python {os.path.basename(__file__)} SYMBOL")
        logging.error(f"Available symbols: {', '.join(TRADING_SYMBOLS)}")
        sys.exit(1)
    input_symbol = sys.argv[1].upper()
    if input_symbol not in TRADING_SYMBOLS:
        logging.error(f"'{input_symbol}' not in allowed trading symbols: {', '.join(TRADING_SYMBOLS)}")
        sys.exit(1)
    selected_symbol = input_symbol

    # Initialize Position and RiskManager
    position = Position(symbol=selected_symbol)
    risk_manager = RiskManager(position=position)

    margin_manager = MarginInfoManager()
    trading_cost_manager = TradingCostManager()
    sharpe_calculator = BinanceFuturesSharpeCalculator()

    trade_manager = TradesManager(sharpe_calculator)
    position_manager = PositionManager(margin_manager, trading_cost_manager)

    # --- BinanceGateway for selected instrument ---
    # from gateways.binance.binance_gateway import BinanceGateway
    # # You should load your API keys from env or config
    # api_key = os.getenv('BINANCE_API_KEY')
    # api_secret = os.getenv('BINANCE_API_SECRET')
    # binance_gateway = BinanceGateway([selected_symbol], api_key=api_key, api_secret=api_secret, product_type=None)
    # binance_gateway.connect()

    # Setup telegram Alert
    base_dir = os.path.dirname(os.path.abspath(__file__))  # directory where this script is located
    dotenv_path = os.path.join(base_dir, 'vault', 'telegram_keys')  # adjust '..' if needed
    load_dotenv(dotenv_path=dotenv_path)

    telegram_api_key = os.getenv("API_KEY")
    telegram_user_id = os.getenv("USER_ID")
    telegram_alert = telegramAlert(telegram_api_key, telegram_user_id)


    # init account
    account = Account(telegram_alert, 0.8)
    account.add_wallet_balance_listener(sharpe_calculator.init_capital)
    account.add_wallet_balance_listener(risk_manager.set_aum)


    position_manager.add_maint_margin_listener(account.on_maint_margin_update)
    position_manager.add_unrealized_pnl_listener(account.on_unrealised_pnl_update)
    position_manager.add_realized_pnl_listener(account.update_wallet_with_realized_pnl)


    # initalise remote client
    remote_market_data_client = RemoteMarketDataClient()
    # attach position manager listener to remote client
    remote_market_data_client.add_mark_price_listener(
        position_manager.on_mark_price_event
    )

    remote_order_client = RemoteOrderClient(margin_manager, position_manager, account,trading_cost_manager,trade_manager)



    # create executor
    order_type = OrderType.Market
    executor = Executor(order_type, remote_order_client)
    # create order manager
    order_manager = FCFSOrderManager(executor, risk_manager)
    order_manager.start()

    remote_order_client.add_order_event_listener(order_manager.on_order_event)

    # setup strategy manager
    strategy_manager = StrategyManager(remote_market_data_client,order_manager)

    # actual
    # init CandleAggregator and Strategy


    inflectionSMACrossoverCandleAggregatorBTCUSDC = CandleAggregator(
        interval_seconds=2
    )  # should change to 5 min (300) price aggregator

    inflectionSMACrossoverCandleAggregatorETHUSDC = CandleAggregator(
        interval_seconds=2
    )

    # smaCrossoverInflectionStrategy = SMACrossoverInflectionStrategy(symbol="BTCUSDC",quantity_per_order=0.001,candle_aggregator=inflectionSMACrossoverCandleAggregatorBTCUSDC,short_window=5,long_window=10)  # need
    # smaCrossoverInflectionStrategyETHUSDC = SMACrossoverInflectionStrategy(symbol="ETHUSDC",quantity_per_order=0.005,candle_aggregator=inflectionSMACrossoverCandleAggregatorETHUSDC,short_window=5,long_window=10)  # need

    # TODO figure out lot size,e.g. ETHUSDC minimum size is 20 USDC , meaning min size  =  roundup(current value / 20)
    # TODO https://www.binance.com/en/futures/trading-rules
    aum = getattr(risk_manager, 'aum', 0.0)
    trade_quantity = SizingPolicy().get_size(aum)

    logging.info(f"[Sizing] Trade qty={trade_quantity} from AUM={aum}")

    sma = SMAStrategy(symbol="BTCUSDC",quantity_per_order=trade_quantity,short_window=10, long_window=20)
    smaETHUSDC = SMAStrategy(symbol="ETHUSDC",quantity_per_order=trade_quantity,short_window=10, long_window=20)

    # strategy_manager.add_strategy(smaCrossoverInflectionStrategy)
    # strategy_manager.add_strategy(smaCrossoverInflectionStrategyETHUSDC)
    strategy_manager.add_strategy(sma)
    strategy_manager.add_strategy(smaETHUSDC)

    plotter = RealTimePlotWithCandlestick(ticker_name=selected_symbol, max_minutes=60, max_ticks=300, update_interval_ms=100,
                           is_simulation=False)


    account.add_margin_ratio_listener(plotter.add_margin_ratio)
    plotter.add_capital(account.wallet_balance)
    account.add_wallet_balance_listener(plotter.add_capital)
    plotter.add_daily_sharpe(sharpe_calculator.sharpe)
    sharpe_calculator.add_sharpe_listener(plotter.add_daily_sharpe)
    # add for plot
    position_manager.add_unrealized_pnl_listener(plotter.add_unrealized_pnl)
    position_manager.add_realized_pnl_listener(plotter.add_realized_pnl)

    # #tick
    # smaCrossoverInflectionStrategy.candle_aggregator.add_tick_candle_listener(plotter.add_ohlc_candle)
    # #signal
    # smaCrossoverInflectionStrategy.add_plot_signal_listener(plotter.add_signal)
    # #sma
    # smaCrossoverInflectionStrategy.add_plot_sma_listener(plotter.add_sma_point)
    # smaCrossoverInflectionStrategy.add_plot_sma2_listener(plotter.add_sma2_point)





    # #### for testing only ####
    # sma = SMAStrategy(10,20)
    #
    # remote_market_data_client.add_order_book_listener(
    #     sma.on_update
    # )
    #
    # plotter = RealTimePlot(ticker_name=contract, max_minutes=60, max_ticks=500, update_interval_ms=100,
    #                        is_simulation=False)
    #
    # #add for plot
    # account.add_margin_ratio_listener(plotter.add_margin_ratio)
    # account.add_wallet_balance_listener(plotter.add_capital)
    # sharpe_calculator.add_sharpe_listener(plotter.add_daily_sharpe)
    # # add for plot
    # position_manager.add_unrealized_pnl_listener(plotter.add_unrealized_pnl)
    # position_manager.add_realized_pnl_listener(plotter.add_realized_pnl)
    #
    # sma.add_tick_signal_listener(plotter.add_signal)
    # sma.add_tick_sma_listener(plotter.add_sma_point)
    # sma.add_tick_sma2_listener(plotter.add_sma2_point)
    #
    # remote_market_data_client.add_tick_price(plotter.add_tick)
    #
    # strategy_manager.add_strategy(sma)
    #
    # ##testing####

    tracker = InMemoryTracker(telegram_alert)

    while start:
        plotter.start()
        continue


if __name__ == "__main__":
    main()
