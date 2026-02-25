# Research to Strategy Converter

Convert Jupyter research notebooks from `research/` into production-ready strategy Python files in `engine/strategies/`.

## When to Use This Skill

Use when the user asks to:
- Convert a research notebook into a strategy
- Create a new strategy from research
- "Turn this notebook into a strategy"
- "Implement this research as a strategy"

Triggers: convert research, notebook to strategy, create strategy from research, implement research strategy

## Prerequisites

Before starting, read these files to understand the framework:
1. The source research notebook (in `research/`)
2. `engine/strategies/rsi_signal_strategy.py` — reference strategy implementation
3. `engine/strategies/base.py` — Strategy base class
4. `engine/strategies/indicators.py` — available indicators
5. `engine/strategies/models.py` — Instrument, PositionSide, Position
6. `engine/strategies/strategy_action.py` — StrategyAction enum
7. `engine/strategies/strategy_order_mode.py` — StrategyOrderMode
8. `engine/database/models.py` — SignalContext and context builder functions

## Step-by-Step Process

### Step 1: Analyze the Research Notebook

Read the entire research notebook and extract:
- **Indicator(s) used** (RSI, TEMA, MOM, ROC, etc.) and their parameters
- **Signal generation logic**: entry conditions (long/short), exit conditions
- **Signal modes**: mean_reversion vs momentum (crossover direction)
- **Exit modes**: midpoint vs breakout
- **Risk management**: stop_loss, take_profit, max_holding, cooldown, allow_flip
- **Optimized parameter values** (look for Optuna results or final parameter cells)

### Step 2: Check/Create Indicator

Check if the required indicator exists in `engine/strategies/indicators.py`.

If the indicator does NOT exist, create it following this pattern:

```python
class Momentum(Indicator):
    """Momentum indicator: close - close[period]"""
    def __init__(self, period: int = 10):
        super().__init__([period])
        self.period = period
        self.buffer = deque(maxlen=period + 1)
        self.value = 0.0

    def handle_bar(self, candle: MidPriceCandle) -> None:
        close_price = candle.close if candle.close is not None else 0.0
        self.buffer.append(close_price)
        if len(self.buffer) == self.period + 1:
            self.value = close_price - self.buffer[0]
            self._initialized = True
        else:
            self.value = 0.0
            self._initialized = False

    def reset(self) -> None:
        self.buffer.clear()
        self.value = 0.0
        self._initialized = False
```

Key rules for indicators:
- Inherit from `Indicator`
- Use `deque(maxlen=...)` for buffering
- Set `self._initialized = True` once enough bars are collected
- `handle_bar()` takes a `MidPriceCandle`
- Must implement `reset()`
- Use `candle.close` for the price input

### Step 3: Create Signal Context Builder

Add a `build_<indicator>_signal_context()` function to `engine/database/models.py` following the existing pattern. Example:

```python
def build_mom_signal_context(
    reason: str,
    mom: float,
    prev_mom: float,
    mom_upper: float,
    mom_lower: float,
    mom_mid: float,
    signal_mode: str,
    exit_mode: str,
    mom_period: int,
    stop_loss_percent: float,
    take_profit_percent: float,
    max_holding_bars: int,
    cooldown_bars: int,
    notional_amount: float,
    use_stop_loss: bool,
    use_take_profit: bool,
    use_max_holding: bool,
    allow_flip: bool,
    candle: Optional[Dict[str, float]] = None,
    action: str = None,
) -> SignalContext:
    """Build SignalContext for Momentum Signal strategy."""
    return SignalContext(
        reason=reason,
        indicators={
            "mom": mom,
            "prev_mom": prev_mom,
            "mom_upper": mom_upper,
            "mom_lower": mom_lower,
            "mom_mid": mom_mid,
            "signal_mode": signal_mode,
            "exit_mode": exit_mode,
        },
        config={
            "mom_period": mom_period,
            "stop_loss_percent": stop_loss_percent,
            "take_profit_percent": take_profit_percent,
            "max_holding_bars": max_holding_bars,
            "cooldown_bars": cooldown_bars,
            "notional_amount": notional_amount,
            "use_stop_loss": use_stop_loss,
            "use_take_profit": use_take_profit,
            "use_max_holding": use_max_holding,
            "allow_flip": allow_flip,
        },
        candle=candle,
        action=action,
    )
```

### Step 4: Create the Strategy File

Create `engine/strategies/<indicator>_signal_strategy.py` following the exact structure of `rsi_signal_strategy.py`. The file MUST contain:

#### A. Config Dataclass (frozen)

```python
@dataclass(frozen=True)
class <Name>SignalStrategyConfig:
    """<Name> Signal Strategy configuration."""
    instrument_id: str
    bar_type: str

    # Indicator Parameters (from research notebook)
    <indicator>_period: int = <default>
    <indicator>_upper: float = <default>
    <indicator>_lower: float = <default>
    <indicator>_mid: float = <default>

    # Signal Behavior
    signal_mode: str = "momentum"   # mean_reversion | momentum
    exit_mode: str = "breakout"     # midpoint | breakout

    # Position Management
    quantity: float = 1.0
    notional_amount: float = 500.0
    stop_loss_percent: float = <from_research>
    take_profit_percent: float = 0.05
    max_holding_bars: int = <from_research>
    cooldown_bars: int = 0

    # Risk Management
    use_stop_loss: bool = True
    use_take_profit: bool = False
    use_max_holding: bool = True
    allow_flip: bool = True
```

#### B. Strategy Class

Must inherit from `Strategy` and implement:

1. **`__init__(self, config)`** — Store config, initialize indicator(s), set up state tracking
2. **`on_start(self)`** — Look up instrument, subscribe to bars, log start
3. **`on_candle_created(self, candle)`** — Main loop: update indicator, compute signals, handle positions
4. **`_compute_signals(self, current_value)`** — Generate entry/exit signals based on indicator crossovers
5. **`_handle_long_position(...)`** — Stop loss, take profit, exit signal, flip, max holding
6. **`_handle_short_position(...)`** — Mirror of long position handling
7. **`_enter_long(...)`** — Submit long entry order with signal context
8. **`_enter_short(...)`** — Submit short entry order with signal context
9. **`_reverse_position(...)`** — Flip position direction
10. **`_close_position(...)`** — Close current position
11. **`_build_signal_context(...)`** — Build SignalContext using the context builder
12. **`_sync_position_state(self)`** — Sync with cache
13. **`_resolve_entry_price(self)`** — Get entry price from cache or state
14. **`_bars_held(self)`** — Calculate bars since entry
15. **`_candle_close/low/high(self, candle)`** — Safe candle accessors

### Step 5: Signal Logic Translation

This is the most critical step. Translate the notebook's signal generation into `_compute_signals()`.

**Standard crossover pattern** (works for RSI, MOM, ROC, CCI, etc.):

```python
def _compute_signals(self, current_value: float):
    # Mean reversion: enter ON the band (counter-trend)
    mr_long_signal = (
        self._previous_value < self.lower and current_value >= self.lower
    )
    mr_short_signal = (
        self._previous_value > self.upper and current_value <= self.upper
    )

    # Momentum: enter THROUGH the band (trend-following)
    mom_long_signal = (
        self._previous_value < self.upper and current_value >= self.upper
    )
    mom_short_signal = (
        self._previous_value > self.lower and current_value <= self.lower
    )

    if self.signal_mode == "mean_reversion":
        long_entry_signal = mr_long_signal
        short_entry_signal = mr_short_signal
    else:  # momentum
        long_entry_signal = mom_long_signal
        short_entry_signal = mom_short_signal

    # Exit signals (midpoint mode only)
    if self.exit_mode == "midpoint":
        if self.signal_mode == "mean_reversion":
            long_exit_signal = self._previous_value < self.mid and current_value >= self.mid
            short_exit_signal = self._previous_value > self.mid and current_value <= self.mid
        else:  # momentum
            long_exit_signal = self._previous_value > self.mid and current_value <= self.mid
            short_exit_signal = self._previous_value < self.mid and current_value >= self.mid
    else:  # breakout
        long_exit_signal = False
        short_exit_signal = False

    return long_entry_signal, short_entry_signal, long_exit_signal, short_exit_signal
```

### Step 6: Logging with [SIGNAL] Prefix

ALL entry and exit log messages MUST use the `[SIGNAL]` prefix for identification. Use this format:

```python
# Entries
self.log.info(f"[SIGNAL] LONG ENTRY | {reason} | Price: {close_price:.4f}")
self.log.info(f"[SIGNAL] SHORT ENTRY | {reason} | Price: {close_price:.4f}")

# Exits
self.log.info(f"[SIGNAL] LONG EXIT | {reason} | Price: {close_price:.4f}")
self.log.info(f"[SIGNAL] SHORT EXIT | {reason} | Price: {close_price:.4f}")

# Reversals
self.log.info(f"[SIGNAL] REVERSAL TO {side_label} | {reason} | Price: {close_price:.4f}")

# Strategy start
self.log.info(f"[SIGNAL] {StrategyName} started for {self.instrument_id} (mode={self.signal_mode}, exit={self.exit_mode})")
```

Do NOT use emoji in log messages. Use the `[SIGNAL]` prefix consistently.

### Step 7: Required Imports

Every strategy file needs these imports:

```python
import logging
from dataclasses import dataclass

from common.interface_order import OrderSizeMode
from engine.database.models import build_<indicator>_signal_context

from ..market_data.candle import MidPriceCandle
from .base import Strategy
from .indicators import <IndicatorClass>
from .models import Instrument, PositionSide
from .strategy_action import StrategyAction
from .strategy_order_mode import StrategyOrderMode
```

### Step 8: Order Submission Pattern

Use this exact pattern for submitting orders:

```python
# For entries (long or short)
strategy_order_mode = StrategyOrderMode(
    order_size_mode=OrderSizeMode.NOTIONAL,
    notional_value=self.notional_amount,
)

ok = self.on_signal(
    signal=1,  # 1 for long, -1 for short
    price=close_price,
    strategy_actions=StrategyAction.OPEN_CLOSE_POSITION,
    strategy_order_mode=strategy_order_mode,
    signal_context=signal_context,
)

# For reversals
ok = self.on_signal(
    signal=signal,  # 1 or -1
    price=close_price,
    strategy_actions=StrategyAction.POSITION_REVERSAL,
    strategy_order_mode=strategy_order_mode,
    signal_context=signal_context,
)

# For closing positions
tags = [f"reason={reason}"]
ok = self._order_manager.submit_market_close(
    strategy_id=self._strategy_id,
    symbol=self._symbol,
    price=close_price,
    tags=tags,
)
```

## Checklist Before Done

- [ ] Indicator exists in `engine/strategies/indicators.py` (create if missing)
- [ ] Context builder exists in `engine/database/models.py` (create if missing)
- [ ] Strategy file created at `engine/strategies/<name>_signal_strategy.py`
- [ ] Config dataclass has all parameters from research (with optimized defaults)
- [ ] Signal logic matches the research notebook's crossover conditions exactly
- [ ] ALL log messages use `[SIGNAL]` prefix (no emoji)
- [ ] Stop loss, take profit, max holding, cooldown, and flip logic implemented
- [ ] `_compute_signals()` supports both mean_reversion and momentum modes
- [ ] `_compute_signals()` supports both midpoint and breakout exit modes
- [ ] Signal context builder called with all indicator values and config

## Example: Converting "ETHSignal MOM v4.ipynb"

The notebook uses:
- **Indicator**: Momentum (MOM) = `close - close[period]` via `ta.MOM()`
- **Parameters**: `mom_period=40`, `mom_upper=130`, `mom_lower=-138`, `mom_mid=27`
- **Mode**: momentum (long when MOM crosses above upper, short when below lower)
- **Exit**: breakout (no midpoint exit, rely on stop loss / max holding)
- **Risk**: `stop_loss=0.067`, `max_holding_val=16`, `allow_flip=True`, `cooldown_bars=0`

This would produce:
1. A `Momentum` class in `indicators.py`
2. A `build_mom_signal_context()` in `database/models.py`
3. A `mom_signal_strategy.py` with `MOMSignalStrategyConfig` and `MOMSignalStrategy`
