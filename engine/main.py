import logging
import os
import sys
import signal

from dotenv import load_dotenv

from common import config_risk
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
from engine.strategies.nautilus_strategy_factory import (
    create_roc_mean_reversion_strategy,
    create_cci_momentum_strategy,
    create_apo_mean_reversion_strategy,
    create_ppo_momentum_strategy,
    create_adx_mean_reversion_strategy,
    create_simple_order_test_strategy,
)
from engine.strategies.strategy_manager import StrategyManager
from engine.tracking.telegram_notifier import TelegramNotifier
from engine.trades.trades_manager import TradesManager
from engine.trading_cost.trading_cost_manager import TradingCostManager
from graph.ohlc_plot import RealTimePlotWithCandlestick


def main():
    # Load environment variables from .env file
    load_dotenv()

    # Configure logging with optional LOG_LEVEL env
    # Configure logging to both console and daily rotating file (rotates at midnight UTC)
    to_stdout_and_daily_file(log_dir="logs", log_prefix="trading")
    logging.info("Running Engine...")

    # Get configuration from environment variables
    environment = os.getenv("ENVIRONMENT", "development")
    notional_amount = 500.0  # Notional amount per trade

    # Use TEST_INTERVAL only in development, otherwise default to 3600 (1-hour)
    if environment == "development":
        interval_seconds = int(os.getenv("TEST_INTERVAL", "1"))  # Default: 1 second for dev
    else:
        interval_seconds = 3600  # Always 1-hour for testnet/production

    logging.info("Environment: %s", environment)
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
    selected_symbol = input_symbol

    # Initialize Position and RiskManager
    position = Position(symbol=selected_symbol)
    risk_manager = RiskManager(position=position)
    # Ensure symbol is registered for per-symbol risk tracking
    try:
        risk_manager.add_symbol(selected_symbol, position=position)
    except Exception:
        logging.debug(
            "RiskManager.add_symbol at startup failed (symbol may already be registered)",
            exc_info=True,
        )

    margin_manager = MarginInfoManager()
    trading_cost_manager = TradingCostManager()
    sharpe_calculator = BinanceFuturesSharpeCalculator()

    trade_manager = TradesManager(sharpe_calculator)

    # initialise reference price manager
    reference_price_manager = ReferencePriceManager()

    position_manager = PositionManager(
        margin_manager, trading_cost_manager, reference_price_manager
    )
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
    account = Account(0.8)
    account.add_wallet_balance_listener(sharpe_calculator.init_capital)
    # Forward wallet balance updates into RiskManager (updates AUM internally)
    account.add_wallet_balance_listener(risk_manager.on_wallet_balance_update)

    position_manager.add_maint_margin_listener(account.on_maint_margin_update)
    position_manager.add_unrealized_pnl_listener(account.on_unrealised_pnl_update)
    # Also forward risk-relevant state to RiskManager
    position_manager.add_maint_margin_listener(risk_manager.on_maint_margin_update)
    position_manager.add_unrealized_pnl_listener(risk_manager.on_unrealised_pnl_update)
    position_manager.add_realized_pnl_listener(account.update_wallet_with_realized_pnl)
    # Also treat realized PnL as part of daily loss tracking (aggregate)
    position_manager.add_realized_pnl_listener(lambda pnl: risk_manager.update_daily_loss(pnl))

    # initialise remote client
    remote_market_data_client = RemoteMarketDataClient()

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

    remote_order_client = RemoteOrderClient(
        margin_manager,
        position_manager,
        account,
        trading_cost_manager,
        trade_manager,
        reference_data_manager,
    )

    # create executor
    order_type = OrderType.Market
    executor = Executor(order_type, remote_order_client)
    # create order manager
    order_manager = FCFSOrderManager(executor, risk_manager, reference_data_manager)
    order_manager.start()

    remote_order_client.add_order_event_listener(order_manager.on_order_event)
    # Allow PositionManager to resolve strategy_id from order_id/client_id
    try:
        position_manager.set_order_lookup(lambda cid: order_manager.orders.get(cid))
    except Exception:
        logging.debug("Failed to set order lookup on PositionManager", exc_info=True)

    # Initialize telegram notifier and wire as listener (non-blocking)
    telegram_notifier = None
    try:
        telegram_notifier = TelegramNotifier(
            api_key=telegram_api_key,
            user_id=telegram_user_id,
            exchange_env=telegram_exchange_env,
            account=account,
            position_manager=position_manager,
        )

        # Register telegram notifier as listener for all events
        remote_order_client.add_order_event_listener(telegram_notifier.on_order_event)
        account.add_margin_warning_listener(telegram_notifier.on_margin_warning)

        # Register PnL listeners for profit/loss notifications
        position_manager.add_unrealized_pnl_listener(telegram_notifier.on_unrealized_pnl_update)
        position_manager.add_realized_pnl_listener(telegram_notifier.on_realized_pnl_update)

        # Start telegram bot command listener (starts message sender + bot threads)
        telegram_notifier.start_bot_listener()

        if telegram_notifier.is_enabled():
            logging.info("✅ Telegram notifier initialized and listeners registered")
        else:
            logging.warning(
                "⚠️ Telegram notifier created but disabled - trading will continue normally"
            )
    except Exception as e:
        logging.error(f"❌ Failed to initialize Telegram notifier: {e}", exc_info=True)
        logging.warning("⚠️ Trading will continue without Telegram notifications")
        telegram_notifier = None

    # setup strategy manager
    strategy_manager = StrategyManager(remote_market_data_client, order_manager)

    if telegram_notifier:
        strategy_manager.add_on_strategy_order_submitted_listener(
            telegram_notifier.on_strategy_order_submitted
        )

    # Connect strategy manager to order manager for signal tags
    order_manager.strategy_manager = strategy_manager

    # ===== STRATEGIES =====
    # 1. ROC Mean Reversion Strategy (1-hour candles)
    logging.info("Initializing ROC Mean Reversion Strategy...")
    roc_strategy = create_roc_mean_reversion_strategy(
        symbol=selected_symbol,
        position_manager=position_manager,
        interval_seconds=interval_seconds,
    )
    strategy_manager.add_strategy(roc_strategy)
    roc_strategy.start()
    logging.info("✅ ROC Mean Reversion strategy added")

    # 2. CCI Momentum Strategy (1-hour candles)
    logging.info("Initializing CCI Momentum Strategy...")
    cci_strategy = create_cci_momentum_strategy(
        symbol=selected_symbol,
        position_manager=position_manager,
        interval_seconds=interval_seconds,
    )
    # strategy_manager.add_strategy(cci_strategy)
    cci_strategy.start()
    logging.info("✅ CCI Momentum strategy added")

    # 3. APO Mean Reversion Strategy (1-hour candles)
    logging.info("Initializing APO Mean Reversion Strategy...")
    apo_strategy = create_apo_mean_reversion_strategy(
        symbol=selected_symbol,
        position_manager=position_manager,
        interval_seconds=interval_seconds,
    )
    strategy_manager.add_strategy(apo_strategy)
    apo_strategy.start()
    logging.info("✅ APO Mean Reversion strategy added")

    # 4. PPO Momentum Strategy (1-hour candles)
    logging.info("Initializing PPO Momentum Strategy...")
    ppo_strategy = create_ppo_momentum_strategy(
        symbol=selected_symbol,
        position_manager=position_manager,
        interval_seconds=interval_seconds,
    )
    strategy_manager.add_strategy(ppo_strategy)
    ppo_strategy.start()
    logging.info("✅ PPO Momentum strategy added")

    # 5. ADX Mean Reversion Strategy (1-hour candles)
    logging.info("Initializing ADX Mean Reversion Strategy...")
    adx_strategy = create_adx_mean_reversion_strategy(
        symbol=selected_symbol,
        position_manager=position_manager,
        interval_seconds=interval_seconds,
    )
    strategy_manager.add_strategy(adx_strategy)
    adx_strategy.start()
    logging.info("✅ ADX Mean Reversion strategy added")

    # 6. Simple Order Test Strategy (for testing)
    logging.info("Initializing Simple Order Test Strategy...")
    test_strategy = create_simple_order_test_strategy(
        symbol=selected_symbol,
        position_manager=position_manager,
        interval_seconds=interval_seconds,
        bars_per_trade=20,  # Trade every 20 bars
    )
    strategy_manager.add_strategy(test_strategy)
    test_strategy.start()
    logging.info("✅ Simple Order Test strategy added")

    logging.info(f"🎉 All 6 Nautilus strategies initialized for {selected_symbol}")

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
        if telegram_notifier:
            telegram_notifier.stop_bot_listener()
        logging.info("✅ Application stopped gracefully")
        sys.exit(0)


if __name__ == "__main__":
    main()
