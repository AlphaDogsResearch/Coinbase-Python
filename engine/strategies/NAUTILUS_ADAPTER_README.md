# Nautilus Strategy Adapter

A comprehensive adapter system that enables Nautilus Trader strategies to work seamlessly with your existing StrategyManager, OrderManager, and PositionManager infrastructure.

## Overview

The adapter bridges the gap between:
- **Nautilus Trader**: A powerful trading framework with advanced indicators and strategies
- **Your System**: Your existing candle-based market data flow and signal-based order execution

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      StrategyManager                        │
│  (Your existing system - no changes required)              │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   │ add_strategy()
                   ▼
          ┌────────────────────┐
          │ NautilusStrategy   │  ◄── Wrapper
          │     Adapter        │
          └────────┬───────────┘
                   │
         ┌─────────┼─────────┐
         │         │         │
         ▼         ▼         ▼
    Portfolio  Cache    OrderFactory
     Adapter   Adapter    Adapter
         │         │         │
         └────┬────┴────┬────┘
              │         │
              ▼         ▼
      PositionManager  Signal
      (Your system)    Emission
```

## Components

### 1. NautilusStrategyAdapter
**File**: `engine/strategies/nautilus_adapter.py`

Main adapter class that:
- Wraps Nautilus strategy instances
- Converts `MidPriceCandle` → Nautilus `Bar`
- Intercepts order submissions → converts to signals
- Inherits from your `Strategy` base class

### 2. NautilusPortfolioAdapter
**File**: `engine/strategies/nautilus_adapters.py`

Adapts Nautilus Portfolio API to your `PositionManager`:
- `is_flat(instrument_id)` - Check if no position
- `is_net_long(instrument_id)` - Check if long position
- `is_net_short(instrument_id)` - Check if short position
- `positions(instrument_id)` - Get position objects

### 3. NautilusCacheAdapter
**File**: `engine/strategies/nautilus_adapters.py`

Provides instrument metadata:
- `instrument(instrument_id)` - Get instrument details
- Caches instrument information

### 4. NautilusOrderFactoryAdapter
**File**: `engine/strategies/nautilus_adapters.py`

Captures order intents from Nautilus strategies:
- `market()` - Market orders
- `stop_market()` - Stop market orders
- `limit()` - Limit orders

Converts to signals for your `OrderManager`.

### 5. Data Converters
**File**: `engine/strategies/nautilus_converters.py`

Utilities for data conversion:
- `convert_candle_to_bar()` - MidPriceCandle → Nautilus Bar
- `parse_bar_type()` - Create Nautilus BarType
- `extract_symbol_from_instrument_id()` - Symbol extraction
- `normalize_symbol()` - Symbol normalization

## Available Nautilus Strategies

Located in `engine/strategies/nautilus_strategies/`:

1. **ROC Mean Reversion Strategy** - Rate of Change based mean reversion
2. **CCI Momentum Strategy** - Commodity Channel Index momentum
3. **APO Mean Reversion Strategy** - Absolute Price Oscillator
4. **PPO Momentum Strategy** - Percentage Price Oscillator
5. **ADX Mean Reversion Strategy** - Average Directional Index

All strategies can be used via the adapter!

## Usage

### Basic Example

```python
from engine.strategies.nautilus_strategies.roc_mean_reversion_strategy import (
    ROCMeanReversionStrategy,
    ROCMeanReversionStrategyConfig
)
from engine.strategies.nautilus_adapter import NautilusStrategyAdapter
from engine.market_data.candle import CandleAggregator
from engine.strategies.strategy_action import StrategyAction

# 1. Configure Nautilus strategy
nautilus_config = ROCMeanReversionStrategyConfig(
    instrument_id="BTCUSDC.BINANCE",
    bar_type="BTCUSDC.BINANCE-1-HOUR-LAST-EXTERNAL",
    roc_period=22,
    roc_upper=3.4,
    roc_lower=-3.6,
    roc_mid=-2.1,
    quantity="1.000",
    stop_loss_percent=2.1,
    max_holding_bars=100
)

# 2. Create Nautilus strategy instance
nautilus_strat = ROCMeanReversionStrategy(config=nautilus_config)

# 3. Create candle aggregator
candle_agg = CandleAggregator(interval_seconds=3600)  # 1 hour

# 4. Wrap with adapter
adapted_strategy = NautilusStrategyAdapter(
    nautilus_strategy_instance=nautilus_strat,
    symbol="BTCUSDC",
    trade_unit=1.0,
    strategy_actions=StrategyAction.OPEN_CLOSE_POSITION,
    candle_aggregator=candle_agg,
    position_manager=position_manager,
    instrument_id="BTCUSDC.BINANCE",
    bar_type_spec="1-HOUR-LAST"
)

# 5. Add to StrategyManager (works like any other strategy!)
strategy_manager.add_strategy(adapted_strategy)
```

### Using Helper Functions

```python
from engine.strategies.nautilus_strategy_example import (
    create_roc_mean_reversion_strategy,
    create_cci_momentum_strategy
)

# Create ROC strategy for BTC
roc_btc = create_roc_mean_reversion_strategy(
    symbol="BTCUSDC",
    position_manager=position_manager,
    trade_unit=1.0,
    interval_seconds=3600
)
strategy_manager.add_strategy(roc_btc)

# Create CCI strategy for ETH
cci_eth = create_cci_momentum_strategy(
    symbol="ETHUSDC",
    position_manager=position_manager,
    trade_unit=1.0,
    interval_seconds=3600
)
strategy_manager.add_strategy(cci_eth)
```

## Integration with Your System

### Data Flow

1. **Market Data** → `RemoteMarketDataClient`
2. **Order Book Updates** → `add_order_book_listener()`
3. **Candle Aggregation** → `CandleAggregator.on_order_book()`
4. **Candle Created** → `NautilusStrategyAdapter.on_candle_created()`
5. **Convert to Bar** → `convert_candle_to_bar()`
6. **Feed to Nautilus** → `nautilus_strategy.on_bar()`
7. **Nautilus Logic** → Indicators update, signals generate
8. **Order Created** → `NautilusOrderFactoryAdapter.market()`
9. **Convert to Signal** → `NautilusStrategyAdapter._on_order_created()`
10. **Emit Signal** → `on_signal()` callback
11. **Your OrderManager** → Processes signal as usual!

### No Changes Required To:

✅ StrategyManager  
✅ OrderManager  
✅ PositionManager  
✅ Nautilus strategies  
✅ Your existing strategies

## Configuration

### Candle Intervals

Map your candle aggregator intervals to Nautilus bar specs:

| Interval (seconds) | Bar Spec |
|-------------------|----------|
| 60 | "1-MINUTE-LAST" |
| 300 | "5-MINUTE-LAST" |
| 900 | "15-MINUTE-LAST" |
| 3600 | "1-HOUR-LAST" |
| 14400 | "4-HOUR-LAST" |
| 86400 | "1-DAY-LAST" |

### Instrument IDs

Format: `{SYMBOL}.{VENUE}`

Examples:
- `BTCUSDC.BINANCE`
- `ETHUSDC.BINANCE`
- `XRPUSDC.BINANCE`

### Strategy Actions

- `StrategyAction.OPEN_CLOSE_POSITION` - Normal open/close
- `StrategyAction.POSITION_REVERSAL` - Close and reverse

## Testing

Run the basic tests:

```bash
cd /Users/johannfong/Development/Coinbase-Python
python -m engine.strategies.test_nautilus_adapter
```

Tests cover:
- Data conversion (Candle → Bar)
- Portfolio adapter (position queries)
- Instrument adapter (metadata)
- Cache adapter (instrument lookup)

## Benefits

✅ **Zero Code Changes** - No modifications to Nautilus strategies  
✅ **Nautilus Indicators** - Reuse entire Nautilus indicators library  
✅ **Seamless Integration** - Works with your existing StrategyManager  
✅ **Unified Order Flow** - All orders through your OrderManager  
✅ **Position Tracking** - Uses your existing PositionManager  
✅ **Multiple Strategies** - Deploy any number of Nautilus strategies  
✅ **Clean Architecture** - Adapter pattern for maintainability

## Troubleshooting

### Issue: Nautilus imports fail

**Solution**: Install nautilus_trader:
```bash
pip install nautilus_trader
```

### Issue: Candle conversion fails

**Check**:
- Candle has `open`, `close` values
- `high`/`low` are not inf/-inf
- Timestamps are valid datetime objects

### Issue: Position queries return wrong values

**Check**:
- Symbol mapping between Nautilus ID and your symbol
- PositionManager has correct position data
- Instrument ID format: "SYMBOL.VENUE"

### Issue: Signals not emitting

**Check**:
- Nautilus strategy is calling `submit_order()`
- Order factory adapter callback is registered
- Signal listeners are properly connected

## Future Enhancements

Potential improvements:

1. **Stop Order Tracking** - Track pending stops, trigger on price
2. **Limit Order Management** - Queue limit orders, execute when hit
3. **Multiple Venues** - Support different exchanges
4. **Live Instrument Data** - Fetch real instrument metadata
5. **Performance Metrics** - Track Nautilus strategy performance
6. **Risk Integration** - Pass through your RiskManager

## Support

For questions or issues:
1. Check this README
2. Review example: `nautilus_strategy_factory.py`
3. Run tests: `test_nautilus_adapter.py`
4. Check logs for detailed error messages

## License

Same as your project.

