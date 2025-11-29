import logging
import os
import sys
import signal
from pathlib import Path

# Add project root to Python path
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv, find_dotenv

from common import config_risk
from common.config_loader import basic_config_loader
from common.config_logging import to_stdout_and_daily_file
from common.config_symbols import TRADING_SYMBOLS
from common.interface_order import OrderType
from common.metrics.sharpe_calculator import BinanceFuturesSharpeCalculator
from engine.account.account import Account
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
from engine.strategies.strategy_manager import StrategyManager
from engine.tracking.telegram_notifier import TelegramNotifier
from engine.trades.trades_manager import TradesManager
from engine.trading_cost.trading_cost_manager import TradingCostManager
# from engine.market_data.mock_market_data_generator import MockMarketDataGenerator
from graph.ohlc_plot import RealTimePlotWithCandlestick


def main():
    # Load environment variables from .env file
    load_dotenv()

    # Configure logging with optional LOG_LEVEL env
    # Configure logging to both console and daily rotating file (rotates at midnight UTC)
    to_stdout_and_daily_file(log_dir="logs", log_prefix="trading")
    env_path = find_dotenv()
    logging.info(f"Loading environment from {env_path}")

    logging.info("Running Engine...")

    # Get configuration from environment variables
    environment = os.getenv("ENVIRONMENT", "development")
    logging.info("Environment: %s", environment)

    config = basic_config_loader.load_config(environment)
    logging.info(f"Config loaded. {config}")
    components = basic_config_loader.create_objects(config)
    logging.info(f"Components Created. {components}")

    default_settings_parameters = components["default_settings"]
    notional_amount = default_settings_parameters["notional_amount"]

    interval_seconds = default_settings_parameters["interval_seconds"]

    logging.info(
        "Candle interval: %d seconds (%s)",
        interval_seconds,
        "1-second" if interval_seconds == 1 else "1-hour",
    )
    logging.info("Notional Amount: %s", notional_amount)

    start = True

    # Get symbol from CLI argument
    if len(sys.argv) < 2:
        logging.error(f"Usage: python {os.path.basename(__file__)} SYMBOL")
        logging.error(f"Available symbols: {', '.join(TRADING_SYMBOLS)}")
        sys.exit(1)
    input_symbol = sys.argv[1].upper()
    if input_symbol not in TRADING_SYMBOLS:
        logging.error(
            f"'{input_symbol}' not in allowed trading symbols: {', '.join(TRADING_SYMBOLS)}"
        )
        sys.exit(1)

    selected_symbol = default_settings_parameters["selected_symbol"]

    # Initialize Position and RiskManager
    position = components["position"]
    risk_manager = components["risk_manager"]
    # Ensure symbol is registered for per-symbol risk tracking
    try:
        risk_manager.add_symbol(selected_symbol, position=position)
    except Exception:
        logging.debug(
            "RiskManager.add_symbol at startup failed (symbol may already be registered)",
            exc_info=True,
        )

    margin_manager = components["margin_manager"]
    trading_cost_manager = components["trading_cost_manager"]
    sharpe_calculator = components["sharpe_calculator"]

    trade_manager = components["trade_manager"]

    # initialise reference price manager
    reference_price_manager = components["reference_price_manager"]

    position_manager = components["position_manager"]

    reference_price_manager.attach_mark_price_listener(position_manager.on_mark_price_event)
    # Wire per-symbol position and open-orders listeners to RiskManager
    position_manager.add_position_amount_listener(
        lambda sym, qty: risk_manager.on_position_amount_update(sym, qty)
    )
    position_manager.add_open_orders_listener(
        lambda sym, cnt: risk_manager.on_open_orders_update(sym, cnt)
    )

    # --- BinanceGateway for selected instrument ---
    # from gateways.binance.binance_gateway import BinanceGateway
    # # You should load your API keys from env or config
    # api_key = os.getenv('BINANCE_API_KEY')
    # api_secret = os.getenv('BINANCE_API_SECRET')
    # binance_gateway = BinanceGateway([selected_symbol], api_key=api_key, api_secret=api_secret, product_type=None)
    # binance_gateway.connect()

    # Setup telegram notifier
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dotenv_path = os.path.join(base_dir, "vault", "telegram_keys")
    load_dotenv(dotenv_path=dotenv_path)

    telegram_api_key = os.getenv("API_KEY")
    telegram_user_id = os.getenv("USER_ID")
    telegram_exchange_env = os.getenv("EXCHANGE_ENV", "testnet")

    # Note: Account and position_manager will be passed to notifier after they're created
    # We'll initialize the notifier fully after account is created

    # init account
    account = components["account"]
    account.add_wallet_balance_listener(sharpe_calculator.init_capital)
    # Forward wallet balance updates into RiskManager (updates AUM internally)
    account.add_wallet_balance_listener(risk_manager.on_wallet_balance_update)
    logging.info("Attaching balance listener")

    position_manager.add_maint_margin_listener(account.on_maint_margin_update)
    position_manager.add_unrealized_pnl_listener(account.on_unrealised_pnl_update)
    # Also forward risk-relevant state to RiskManager
    position_manager.add_maint_margin_listener(risk_manager.on_maint_margin_update)
    position_manager.add_unrealized_pnl_listener(risk_manager.on_unrealised_pnl_update)
    position_manager.add_realized_pnl_listener(account.update_wallet_with_realized_pnl)
    # Also treat realized PnL as part of daily loss tracking (aggregate)
    position_manager.add_realized_pnl_listener(lambda pnl: risk_manager.update_daily_loss(pnl))

    # initialise remote client
    remote_market_data_client = components["remote_market_data_client"]

    # attach position manager listener to remote client
    remote_market_data_client.add_mark_price_listener(
        reference_price_manager.on_reference_data_event
    )

    # Stream mark prices directly into RiskManager via listener
    def _risk_on_mark_price(mp):
        try:
            risk_manager.on_mark_price_update(mp.symbol, mp.price)
        except Exception:
            logging.debug("Failed to forward mark price to RiskManager", exc_info=True)

    remote_market_data_client.add_mark_price_listener(_risk_on_mark_price)

    # Start periodic risk reports using config_loader file defaults (env can override in config_loader)
    if config_risk.RISK_REPORT_ENABLED_DEFAULT:
        risk_manager.start_periodic_risk_reports(
            report_file=config_risk.RISK_REPORT_FILE_DEFAULT,
            interval_seconds=config_risk.RISK_REPORT_INTERVAL_SECONDS_DEFAULT,
            symbols=config_risk.RISK_REPORT_SYMBOLS_DEFAULT,
        )
        logging.info(
            f"Risk reporting enabled -> {config_risk.RISK_REPORT_FILE_DEFAULT} every {config_risk.RISK_REPORT_INTERVAL_SECONDS_DEFAULT}s"
        )

    reference_data_manager = components["reference_data_manager"]

    remote_order_client = components["remote_order_client"]
    remote_order_client.start()

    # create executor
    executor = components["executor"]
    # create order manager
    order_manager = components["order_manager"]
    # Set position_manager on order_manager for submit_market_close to work
    order_manager.position_manager = position_manager
    order_manager.start()

    remote_order_client.add_order_event_listener(order_manager.on_order_event)
    # Allow PositionManager to resolve strategy_id from order_id/client_id
    try:
        position_manager.set_order_lookup(lambda cid: order_manager.orders.get(cid))
    except Exception:
        logging.debug("Failed to set order lookup on PositionManager", exc_info=True)

    # Initialize telegram notifier and wire as listener (non-blocking)
    # DISABLED: Telegram causing connection issues
    telegram_notifier = None
    # try:
    #     telegram_notifier = TelegramNotifier(
    #         api_key=telegram_api_key,
    #         user_id=telegram_user_id,
    #         exchange_env=telegram_exchange_env,
    #         account=account,
    #         position_manager=position_manager,
    #     )
    #
    #     # Register telegram notifier as listener for all events
    #     remote_order_client.add_order_event_listener(telegram_notifier.on_order_event)
    #     account.add_margin_warning_listener(telegram_notifier.on_margin_warning)
    #
    #     # Register PnL listeners for profit/loss notifications
    #     position_manager.add_unrealized_pnl_listener(telegram_notifier.on_unrealized_pnl_update)
    #     position_manager.add_realized_pnl_listener(telegram_notifier.on_realized_pnl_update)
    #
    #     # Start telegram bot command listener (starts message sender + bot threads)
    #     telegram_notifier.start_bot_listener()
    #
    #     if telegram_notifier.is_enabled():
    #         logging.info("✅ Telegram notifier initialized and listeners registered")
    #     else:
    #         logging.warning(
    #             "⚠️ Telegram notifier created but disabled - trading will continue normally"
    #         )
    # except Exception as e:
    #     logging.error(f"❌ Failed to initialize Telegram notifier: {e}", exc_info=True)
    #     logging.warning("⚠️ Trading will continue without Telegram notifications")
    #     telegram_notifier = None
    logging.info("📱 Telegram notifier disabled (skipped initialization)")

    # ===== Strategy Manager Setup =====

    # Initialize strategy manager
    strategy_manager = StrategyManager(
        order_manager=order_manager,
        position_manager=position_manager,
        remote_market_data_client=remote_market_data_client,
    )

    # Add strategies from config
    strategies = components.get("strategy_map", {})
    if strategies:
        logging.info("========================== Adding strategies ==========================")

        for key, strategy in strategies.items():
            # Set strategy name if not already set
            if not hasattr(strategy, "name") or not strategy.name:
                strategy.name = key
            strategy_id = strategy.name

            # Get strategy symbol/instrument_id
            symbol = (
                getattr(strategy, "symbol", None)
                or getattr(strategy, "instrument_id", None)
                or selected_symbol
            )

            # Add strategy to manager (handles all wiring)
            if strategy_manager.add_strategy(strategy, strategy_id, symbol):
                logging.info(f"[Strategy] Added {strategy_id} for symbol {symbol}")
            else:
                logging.error(f"[Strategy] Failed to add {strategy_id}")

        # Start all strategies
        strategy_manager.start_all()

        logging.info("========================== Done adding strategies ==========================")
    else:
        logging.info("No strategies configured in config file")

    # ===== Mock Market Data Generator (for testing without gateway) =====
    mock_market_data_generator = None
    use_mock_data = os.getenv("USE_MOCK_MARKET_DATA", "false").lower() == "true"
    if use_mock_data:
        logging.info("🧪 [MockMarketData] Enabled - Using simulated market data")
        # Get base price from config or use default
        base_price = float(os.getenv("MOCK_BASE_PRICE", "3000.0"))
        update_interval_ms = int(os.getenv("MOCK_UPDATE_INTERVAL_MS", "100"))
        price_volatility = float(os.getenv("MOCK_PRICE_VOLATILITY", "0.001"))

        # mock_market_data_generator = MockMarketDataGenerator(
        #     remote_market_data_client=remote_market_data_client,
        #     symbol=selected_symbol,
        #     base_price=base_price,
        #     update_interval_ms=update_interval_ms,
        #     price_volatility=price_volatility,
        # )
        # Small delay to ensure all listeners are registered
        import time

        time.sleep(0.5)

        # Log registered listeners before starting
        listeners = remote_market_data_client.order_book_listeners.get(selected_symbol, [])
        logging.info(
            f"🧪 [MockMarketData] Found {len(listeners)} listener(s) registered for {selected_symbol} "
            f"before starting generator"
        )

        mock_market_data_generator.start()
        logging.info(
            f"🧪 [MockMarketData] Started generating data for {selected_symbol} "
            f"at base_price={base_price}, interval={update_interval_ms}ms"
        )
    else:
        logging.info("📡 [MarketData] Using real market data from gateway")

    # plotter = RealTimePlotWithCandlestick(
    #     ticker_name=selected_symbol,
    #     max_minutes=60,
    #     max_ticks=300,
    #     update_interval_ms=100,
    #     is_simulation=False,
    # )

    # account.add_margin_ratio_listener(plotter.add_margin_ratio)
    # account.add_margin_ratio_listener(risk_manager.on_margin_ratio_update)
    # plotter.add_capital(account.wallet_balance)
    # account.add_wallet_balance_listener(plotter.add_capital)
    # plotter.add_daily_sharpe(sharpe_calculator.sharpe)
    # sharpe_calculator.add_sharpe_listener(plotter.add_daily_sharpe)
    # # add for plot
    # position_manager.add_unrealized_pnl_listener(plotter.add_unrealized_pnl)
    # position_manager.add_realized_pnl_listener(plotter.add_realized_pnl)

    # ===== WIRE STRATEGIES TO PLOTTER =====
    # Wire test strategy for candlestick visualization
    # ppo_strategy.candle_aggregator.add_tick_candle_listener(plotter.add_ohlc_candle)

    # logging.info("📊 Simple Order Test strategy wired to real-time plotter")

    # Setup signal handler for graceful shutdown
    shutdown_in_progress = False

    def signal_handler(_sig, _frame):
        nonlocal start, shutdown_in_progress
        if shutdown_in_progress:
            logging.warning("⚠️ Shutdown already in progress, ignoring signal")
            return
        shutdown_in_progress = True
        logging.info("🛑 Shutdown signal received (Ctrl+C), stopping...")
        start = False

        # Stop all strategies gracefully
        if strategies:
            strategy_manager.stop_all()

        # Stop mock market data generator
        if mock_market_data_generator:
            mock_market_data_generator.stop()

        if telegram_notifier:
            telegram_notifier.stop_bot_listener()
        # Force exit after a short delay if graceful shutdown fails
        import threading

        def force_exit():
            import time

            time.sleep(3)  # Wait 3 seconds for graceful shutdown
            logging.warning("⚠️ Forcing exit after timeout")
            import os

            os._exit(0)

        force_thread = threading.Thread(target=force_exit, daemon=True)
        force_thread.start()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logging.info("✅ System ready. Press Ctrl+C to stop.")

    try:
        while start:
            # plotter.start()
            continue
    except KeyboardInterrupt:
        logging.info("🛑 Keyboard interrupt received, stopping...")

        # Stop all strategies gracefully
        if strategies:
            strategy_manager.stop_all()

        # Stop mock market data generator
        if mock_market_data_generator:
            mock_market_data_generator.stop()

        if telegram_notifier:
            telegram_notifier.stop_bot_listener()
        logging.info("✅ Application stopped gracefully")
        sys.exit(0)


if __name__ == "__main__":
    main()
