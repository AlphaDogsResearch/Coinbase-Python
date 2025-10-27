import logging
import os
import sys

from dotenv import load_dotenv

from common.config_logging import to_stdout
from common.interface_order import OrderType, OrderSizeMode
from common.metrics.sharpe_calculator import BinanceFuturesSharpeCalculator
from engine.account.account import Account
from engine.database.database_connection import DatabaseConnectionPool
from engine.execution.executor import Executor
from engine.management.order_management_system import FCFSOrderManager
from engine.margin.margin_info_manager import MarginInfoManager
from engine.position.position import Position
from engine.position.position_manager import PositionManager
from engine.reference_data.reference_data_manager import ReferenceDataManager
from engine.reference_data.reference_price_manager import ReferencePriceManager
from engine.remote.remote_market_data_client import RemoteMarketDataClient
from engine.remote.remote_order_service_client import RemoteOrderClient
from engine.risk.risk_manager import RiskManager
from engine.strategies.sma import SMAStrategy
from engine.strategies.sma_crossover_inflection_strategy import (
    SMACrossoverInflectionStrategy,
)
from engine.strategies.strategy_action import StrategyAction
from engine.strategies.strategy_manager import StrategyManager
from engine.strategies.strategy_order_mode import StrategyOrderMode
from engine.tracking.in_memory_tracker import InMemoryTracker
from engine.tracking.telegram_alert import telegramAlert
from engine.market_data.candle import CandleAggregator
from engine.trades.trades_manager import TradesManager
from engine.trading_cost.trading_cost_manager import TradingCostManager


from graph.ohlc_plot import  RealTimePlotWithCandlestick
from graph.plot import RealTimePlot



from engine.core.order import Order
from common.config_symbols import TRADING_SYMBOLS
from common import config_risk


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
    # Ensure symbol is registered for per-symbol risk tracking
    try:
        risk_manager.add_symbol(selected_symbol, position=position)
    except Exception:
        logging.debug("RiskManager.add_symbol at startup failed (symbol may already be registered)", exc_info=True)

    margin_manager = MarginInfoManager()
    trading_cost_manager = TradingCostManager()
    sharpe_calculator = BinanceFuturesSharpeCalculator()

    trade_manager = TradesManager(sharpe_calculator)

    # initialise reference price manager
    reference_price_manager = ReferencePriceManager()

    position_manager = PositionManager(margin_manager, trading_cost_manager,reference_price_manager)
    reference_price_manager.attach_mark_price_listener(position_manager.on_mark_price_event)

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


    # initialise remote client
    remote_market_data_client = RemoteMarketDataClient()



    # attach position manager listener to remote client
    remote_market_data_client.add_mark_price_listener(
        reference_price_manager.on_reference_data_event
    )

    # Maintain latest mark prices per symbol for risk reporting
    latest_prices = {}

    def _on_mark_price(mp):
        try:
            latest_prices[mp.symbol] = float(mp.price)
        except Exception:
            logging.debug("Failed to cache mark price", exc_info=True)

    remote_market_data_client.add_mark_price_listener(_on_mark_price)

    # Provide price provider to RiskManager for per-symbol reporting
    risk_manager.set_price_provider(lambda s: latest_prices.get(s))

    # Start periodic risk reports using config file defaults (env can override in config)
    if config_risk.RISK_REPORT_ENABLED_DEFAULT:
        risk_manager.start_periodic_risk_reports(
            report_file=config_risk.RISK_REPORT_FILE_DEFAULT,
            interval_seconds=config_risk.RISK_REPORT_INTERVAL_SECONDS_DEFAULT,
            symbols=config_risk.RISK_REPORT_SYMBOLS_DEFAULT,
        )
        logging.info(
            f"Risk reporting enabled -> {config_risk.RISK_REPORT_FILE_DEFAULT} every {config_risk.RISK_REPORT_INTERVAL_SECONDS_DEFAULT}s"
        )

    reference_data_manager = ReferenceDataManager(reference_price_manager)

    remote_order_client = RemoteOrderClient(margin_manager, position_manager, account,trading_cost_manager,trade_manager,reference_data_manager)



    # create executor
    order_type = OrderType.Market
    executor = Executor(order_type, remote_order_client)
    # create order manager
    order_manager = FCFSOrderManager(executor, risk_manager,reference_data_manager)
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

    # smaCrossoverInflectionStrategy = SMACrossoverInflectionStrategy(symbol="BTCUSDC",trade_unit=1,strategy_actions=StrategyAction.POSITION_REVERSAL,candle_aggregator=inflectionSMACrossoverCandleAggregatorBTCUSDC,short_window=5,long_window=10)  # need
    # smaCrossoverInflectionStrategyETHUSDC = SMACrossoverInflectionStrategy(symbol="ETHUSDC",trade_unit=1,strategy_actions=StrategyAction.POSITION_REVERSAL,candle_aggregator=inflectionSMACrossoverCandleAggregatorETHUSDC,short_window=5,long_window=10)  # need

    # TODO figure out lot size,e.g. ETHUSDC minimum size is 20 USDC , meaning min size  =  roundup(current value / 20)
    # TODO https://www.binance.com/en/futures/trading-rules
    # use trade size to determine min qty

    BTCUSDC_notional = StrategyOrderMode(order_size_mode=OrderSizeMode.NOTIONAL, notional_value=100)
    ETHUSDC_notional = StrategyOrderMode(order_size_mode=OrderSizeMode.NOTIONAL,notional_value=25)
    ETHUSDC_quantity = StrategyOrderMode(order_size_mode=OrderSizeMode.QUANTITY,quantity=0.000655)
    XRPUSDC_notional = StrategyOrderMode(order_size_mode=OrderSizeMode.NOTIONAL,notional_value=5)


    sma = SMAStrategy(symbol="BTCUSDC",strategy_order_mode=BTCUSDC_notional,strategy_actions=StrategyAction.POSITION_REVERSAL,short_window=10, long_window=20)
    smaETHUSDC_10_20 = SMAStrategy(symbol="ETHUSDC",strategy_order_mode=ETHUSDC_notional,strategy_actions=StrategyAction.OPEN_CLOSE_POSITION,short_window=10, long_window=20)
    smaETHUSDC_10_30 = SMAStrategy(symbol="ETHUSDC",strategy_order_mode=ETHUSDC_quantity,strategy_actions=StrategyAction.OPEN_CLOSE_POSITION,short_window=10, long_window=30)
    smaXPUSDC = SMAStrategy(symbol="XRPUSDC",strategy_order_mode=XRPUSDC_notional,strategy_actions=StrategyAction.POSITION_REVERSAL,short_window=10, long_window=20)

    # strategy_manager.add_strategy(smaCrossoverInflectionStrategy)
    # strategy_manager.add_strategy(smaCrossoverInflectionStrategyETHUSDC)
    # strategy_manager.add_strategy(sma)
    strategy_manager.add_strategy(smaETHUSDC_10_20)
    strategy_manager.add_strategy(smaETHUSDC_10_30)
    # strategy_manager.add_strategy(smaXPUSDC)

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
