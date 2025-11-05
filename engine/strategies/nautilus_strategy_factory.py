"""
Nautilus Strategy Factory

Factory functions for creating Nautilus Trader strategies adapted for your trading system.
Provides easy-to-use constructors for ROC Mean Reversion, CCI Momentum, and other strategies.

Used in production by main.py to instantiate and configure Nautilus strategies.
"""

import logging
import os
from engine.strategies.nautilus_strategies.roc_mean_reversion_strategy import (
    ROCMeanReversionStrategy,
    ROCMeanReversionStrategyConfig,
)
from engine.strategies.nautilus_strategies.cci_momentum_strategy import (
    CCIMomentumStrategy,
    CCIMomentumStrategyConfig,
)
from engine.strategies.nautilus_strategies.simple_order_test_strategy import (
    SimpleOrderTestStrategy,
    SimpleOrderTestStrategyConfig,
)
from engine.strategies.nautilus_strategies.apo_mean_reversion_strategy import (
    APOMeanReversionStrategy,
    APOMeanReversionStrategyConfig,
)
from engine.strategies.nautilus_strategies.ppo_momentum_strategy import (
    PPOMomentumStrategy,
    PPOMomentumStrategyConfig,
)
from engine.strategies.nautilus_strategies.adx_mean_reversion_strategy import (
    ADXMeanReversionStrategy,
    ADXMeanReversionStrategyConfig,
)
from engine.strategies.nautilus_adapter import NautilusStrategyAdapter
from engine.market_data.candle import CandleAggregator


def create_roc_mean_reversion_strategy(
    symbol: str,
    position_manager,
    interval_seconds: int = 3600,  # 1 hour
):
    """
    Create a ROC Mean Reversion strategy adapted for your system.

    Args:
        symbol: Trading symbol (e.g., "ETHUSDT")
        position_manager: Your PositionManager instance
        interval_seconds: Candle interval in seconds

    Returns:
        NautilusStrategyAdapter instance ready to add to StrategyManager
    """
    # Construct Nautilus instrument ID
    instrument_id = f"{symbol}.BINANCE"

    # Determine bar spec from interval
    if interval_seconds == 1:
        bar_spec = "1-SECOND-LAST"
    else:
        bar_spec = "1-HOUR-LAST"

    bar_type = f"{instrument_id}-{bar_spec}-EXTERNAL"

    # Configure Nautilus strategy
    nautilus_config = ROCMeanReversionStrategyConfig(
        instrument_id=instrument_id,
        bar_type=bar_type,
        roc_period=22,
        roc_upper=3.4,
        roc_lower=-3.6,
        roc_mid=-2.1,
        quantity="1.000",
        stop_loss_percent=2.1,
        max_holding_bars=100,
    )

    # Create Nautilus strategy instance
    nautilus_strategy = ROCMeanReversionStrategy(config=nautilus_config)

    # Create candle aggregator
    candle_agg = CandleAggregator(interval_seconds=interval_seconds)

    # Wrap with adapter
    adapted_strategy = NautilusStrategyAdapter(
        nautilus_strategy_instance=nautilus_strategy,
        symbol=symbol,
        candle_aggregator=candle_agg,
        position_manager=position_manager,
        instrument_id=instrument_id,
        bar_type_spec=bar_spec,
    )

    logging.info("Created ROC Mean Reversion strategy for %s", symbol)
    return adapted_strategy


def create_cci_momentum_strategy(
    symbol: str,
    position_manager,
    interval_seconds: int = 3600,  # 1 hour
):
    """
    Create a CCI Momentum strategy adapted for your system.

    Args:
        symbol: Trading symbol (e.g., "ETHUSDT")
        position_manager: Your PositionManager instance
        interval_seconds: Candle interval in seconds

    Returns:
        NautilusStrategyAdapter instance ready to add to StrategyManager
    """
    # Construct Nautilus instrument ID
    instrument_id = f"{symbol}.BINANCE"

    # Determine bar spec from interval
    if interval_seconds == 1:
        bar_spec = "1-SECOND-LAST"
    else:
        bar_spec = "1-HOUR-LAST"

    bar_type = f"{instrument_id}-{bar_spec}-EXTERNAL"

    # Configure Nautilus strategy
    nautilus_config = CCIMomentumStrategyConfig(
        instrument_id=instrument_id,
        bar_type=bar_type,
        cci_period=14,
        cci_upper=205.0,
        cci_lower=-101.0,
        cci_mid=12.0,
        quantity="1.000",
        stop_loss_percent=7.4,
        max_holding_bars=25,
    )

    # Create Nautilus strategy instance
    nautilus_strategy = CCIMomentumStrategy(config=nautilus_config)

    # Create candle aggregator
    candle_agg = CandleAggregator(interval_seconds=interval_seconds)

    # Wrap with adapter
    adapted_strategy = NautilusStrategyAdapter(
        nautilus_strategy_instance=nautilus_strategy,
        symbol=symbol,
        candle_aggregator=candle_agg,
        position_manager=position_manager,
        instrument_id=instrument_id,
        bar_type_spec=bar_spec,
    )

    logging.info("Created CCI Momentum strategy for %s", symbol)
    return adapted_strategy


def create_simple_order_test_strategy(
    symbol: str,
    position_manager,
    interval_seconds: int = 1,  # 1 second for fast testing
    bars_per_trade: int = 5,  # Trade every 5 bars
):
    """
    Create a Simple Order Test strategy for testing order execution flow.

    This strategy alternates between long and short positions every N bars,
    making it perfect for testing order creation, submission, and tracking
    without complex indicator logic.

    Args:
        symbol: Trading symbol (e.g., "ETHUSDT")
        position_manager: Your PositionManager instance
        interval_seconds: Candle interval in seconds (default: 1 for fast testing)
        bars_per_trade: Execute trade every N bars (default: 5)

    Returns:
        NautilusStrategyAdapter instance ready to add to StrategyManager
    """
    # Construct Nautilus instrument ID
    instrument_id = f"{symbol}.BINANCE"

    # Determine bar spec from interval
    if interval_seconds == 1:
        bar_spec = "1-SECOND-LAST"
    else:
        bar_spec = "1-HOUR-LAST"

    bar_type = f"{instrument_id}-{bar_spec}-EXTERNAL"

    # Configure test strategy
    nautilus_config = SimpleOrderTestStrategyConfig(
        instrument_id=instrument_id,
        bar_type=bar_type,
        bars_per_trade=bars_per_trade,
        quantity="1.000",
    )

    # Create Nautilus strategy instance
    nautilus_strategy = SimpleOrderTestStrategy(config=nautilus_config)

    # Create candle aggregator
    candle_agg = CandleAggregator(interval_seconds=interval_seconds)

    # Wrap with adapter
    adapted_strategy = NautilusStrategyAdapter(
        nautilus_strategy_instance=nautilus_strategy,
        symbol=symbol,
        candle_aggregator=candle_agg,
        position_manager=position_manager,
        instrument_id=instrument_id,
        bar_type_spec=bar_spec,
    )

    logging.info(
        "🧪 Created Simple Order Test strategy for %s (trades every %d bars)",
        symbol,
        bars_per_trade,
    )
    return adapted_strategy


def create_apo_mean_reversion_strategy(
    symbol: str,
    position_manager,
    interval_seconds: int = 3600,  # 1 hour
):
    """
    Create an APO Mean Reversion strategy adapted for your system.

    Args:
        symbol: Trading symbol (e.g., "ETHUSDT")
        position_manager: Your PositionManager instance
        interval_seconds: Candle interval in seconds

    Returns:
        NautilusStrategyAdapter instance ready to add to StrategyManager
    """
    instrument_id = f"{symbol}.BINANCE"

    if interval_seconds == 1:
        bar_spec = "1-SECOND-LAST"
    elif interval_seconds == 60:
        bar_spec = "1-MINUTE-LAST"
    elif interval_seconds == 300:
        bar_spec = "5-MINUTE-LAST"
    elif interval_seconds == 3600:
        bar_spec = "1-HOUR-LAST"
    else:
        bar_spec = "1-HOUR-LAST"

    bar_type = f"{instrument_id}-{bar_spec}-EXTERNAL"

    nautilus_config = APOMeanReversionStrategyConfig(
        instrument_id=instrument_id,
        bar_type=bar_type,
        apo_fast_period=10,
        apo_slow_period=122,
        matype=1,
        apo_upper=38.0,
        apo_lower=-31.0,
        apo_mid=-2.0,
        quantity="1.000",
        stop_loss_percent=7.0,
        max_holding_bars=175,
    )

    nautilus_strategy = APOMeanReversionStrategy(config=nautilus_config)
    candle_agg = CandleAggregator(interval_seconds=interval_seconds)

    adapted_strategy = NautilusStrategyAdapter(
        nautilus_strategy_instance=nautilus_strategy,
        symbol=symbol,
        candle_aggregator=candle_agg,
        position_manager=position_manager,
        instrument_id=instrument_id,
        bar_type_spec=bar_spec,
    )

    logging.info("Created APO Mean Reversion strategy for %s", symbol)
    return adapted_strategy


def create_ppo_momentum_strategy(
    symbol: str,
    position_manager,
    interval_seconds: int = 3600,  # 1 hour
):
    """
    Create a PPO Momentum strategy adapted for your system.

    Args:
        symbol: Trading symbol (e.g., "ETHUSDT")
        position_manager: Your PositionManager instance
        interval_seconds: Candle interval in seconds

    Returns:
        NautilusStrategyAdapter instance ready to add to StrategyManager
    """
    instrument_id = f"{symbol}.BINANCE"

    if interval_seconds == 1:
        bar_spec = "1-SECOND-LAST"
    elif interval_seconds == 60:
        bar_spec = "1-MINUTE-LAST"
    elif interval_seconds == 300:
        bar_spec = "5-MINUTE-LAST"
    elif interval_seconds == 3600:
        bar_spec = "1-HOUR-LAST"
    else:
        bar_spec = "1-HOUR-LAST"

    bar_type = f"{instrument_id}-{bar_spec}-EXTERNAL"

    nautilus_config = PPOMomentumStrategyConfig(
        instrument_id=instrument_id,
        bar_type=bar_type,
        ppo_fast_period=38,
        ppo_slow_period=205,
        matype=3,
        ppo_upper=1.4,
        ppo_lower=-0.8,
        ppo_mid=0.0,
        quantity="1.000",
        stop_loss_percent=10.4,
        max_holding_bars=93,
        use_stop_loss=True,
    )

    nautilus_strategy = PPOMomentumStrategy(config=nautilus_config)
    candle_agg = CandleAggregator(interval_seconds=interval_seconds)

    adapted_strategy = NautilusStrategyAdapter(
        nautilus_strategy_instance=nautilus_strategy,
        symbol=symbol,
        candle_aggregator=candle_agg,
        position_manager=position_manager,
        instrument_id=instrument_id,
        bar_type_spec=bar_spec,
    )

    logging.info("Created PPO Momentum strategy for %s", symbol)
    return adapted_strategy


def create_adx_mean_reversion_strategy(
    symbol: str,
    position_manager,
    interval_seconds: int = 3600,  # 1 hour
):
    """
    Create an ADX Mean Reversion strategy adapted for your system.

    Args:
        symbol: Trading symbol (e.g., "ETHUSDT")
        position_manager: Your PositionManager instance
        interval_seconds: Candle interval in seconds

    Returns:
        NautilusStrategyAdapter instance ready to add to StrategyManager
    """
    instrument_id = f"{symbol}.BINANCE"

    if interval_seconds == 1:
        bar_spec = "1-SECOND-LAST"
    elif interval_seconds == 60:
        bar_spec = "1-MINUTE-LAST"
    elif interval_seconds == 300:
        bar_spec = "5-MINUTE-LAST"
    elif interval_seconds == 3600:
        bar_spec = "1-HOUR-LAST"
    else:
        bar_spec = "1-HOUR-LAST"

    bar_type = f"{instrument_id}-{bar_spec}-EXTERNAL"

    nautilus_config = ADXMeanReversionStrategyConfig(
        instrument_id=instrument_id,
        bar_type=bar_type,
        adx_period=22,
        adx_smoothing=22,
        quantity="1.000",
        stop_loss_percent=3.0,
        adx_low=23.0,
        adx_mid=38.0,
        adx_high=65.0,
        di_spread_extreme=8.625853,
    )

    nautilus_strategy = ADXMeanReversionStrategy(config=nautilus_config)
    candle_agg = CandleAggregator(interval_seconds=interval_seconds)

    adapted_strategy = NautilusStrategyAdapter(
        nautilus_strategy_instance=nautilus_strategy,
        symbol=symbol,
        candle_aggregator=candle_agg,
        position_manager=position_manager,
        instrument_id=instrument_id,
        bar_type_spec=bar_spec,
    )

    logging.info("Created ADX Mean Reversion strategy for %s", symbol)
    return adapted_strategy


def example_integration_with_strategy_manager():
    """
    Example showing how to integrate Nautilus strategies into your main.py.

    This is pseudo-code showing the pattern - adapt to your actual main.py.
    """
    print(
        """
    # In your main.py, after creating StrategyManager and PositionManager:
    
    from engine.strategies.nautilus_strategy_factory import (
        create_roc_mean_reversion_strategy,
        create_cci_momentum_strategy
    )
    
    # Create ROC Mean Reversion strategy for ETH
    roc_eth_strategy = create_roc_mean_reversion_strategy(
        symbol="ETHUSDT",
        position_manager=position_manager,
        trade_unit=1.0,
        interval_seconds=3600,  # 1 hour candles
        strategy_actions=StrategyAction.OPEN_CLOSE_POSITION
    )
    
    # Add to StrategyManager (works like any other strategy!)
    strategy_manager.add_strategy(roc_eth_strategy)
    
    # Create CCI Momentum strategy for BTC
    cci_btc_strategy = create_cci_momentum_strategy(
        symbol="BTCUSDT",
        position_manager=position_manager,
        trade_unit=1.0,
        interval_seconds=3600,
        strategy_actions=StrategyAction.POSITION_REVERSAL
    )
    
    # Add to StrategyManager
    strategy_manager.add_strategy(cci_btc_strategy)
    
    # That's it! The Nautilus strategies will now:
    # 1. Receive candles via add_order_book_listener → CandleAggregator → on_candle_created
    # 2. Use Nautilus indicators automatically
    # 3. Emit signals through your OrderManager
    # 4. Track positions via your PositionManager
    """
    )


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Show integration example
    example_integration_with_strategy_manager()

    print("\n" + "=" * 80)
    print("Nautilus Strategy Integration Example")
    print("=" * 80)
    print("\nAvailable Nautilus Strategies:")
    print("  1. ROC Mean Reversion Strategy")
    print("  2. CCI Momentum Strategy")
    print("  3. APO Mean Reversion Strategy")
    print("  4. PPO Momentum Strategy")
    print("  5. ADX Mean Reversion Strategy")
    print("\nAll strategies can be integrated using the same adapter pattern!")
    print("=" * 80)
