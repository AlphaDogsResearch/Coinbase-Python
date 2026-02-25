# Strategy to Pine Script Converter

Convert Python strategy files from `engine/strategies/` into TradingView Pine Script v6 files in `pine/`.

## When to Use This Skill

Use when the user asks to:
- Convert a Python strategy to Pine Script
- Create a Pine Script from a strategy
- "Generate Pine for this strategy"
- "Make a TradingView version of this strategy"

Triggers: convert to pine, strategy to pine, create pine script, generate pine, tradingview version

## Source

Always convert from the **Python strategy file** (`engine/strategies/*_strategy.py`), NOT from the research notebook. The Python strategy is the canonical source of truth.

## Prerequisites

Before starting, read these files:
1. The source Python strategy file
2. At least two existing Pine scripts in `pine/` to confirm the conventions are still current
3. The Python strategy's config dataclass for default parameter values

## Pine Script Standard

All Pine scripts MUST follow this exact structure and conventions, derived from the existing scripts in `pine/`.

### Section 1: Strategy Declaration

```pine
//@version=6
strategy("<Strategy Name>",
         overlay=false,
         default_qty_type=strategy.cash,
         default_qty_value=100,
         initial_capital=100000,
         commission_type=strategy.commission.percent,
         commission_value=0.0005,
         pyramiding=0,
         calc_on_every_tick=false,
         process_orders_on_close=false)
```

Rules:
- Always `@version=6`
- `overlay=false` for oscillator/indicator strategies (RSI, CCI, MOM, ROC, etc.) — plotted in a separate pane
- `overlay=true` for price-overlay strategies (Bollinger Bands, moving average crossovers, etc.) — bands/lines must align with candles on the main chart. Do NOT also plot `close` when overlay=true, as the candles are already there.
- `default_qty_type=strategy.cash` with `default_qty_value=100`
- `initial_capital=100000`
- Commission is `0.0005` (0.05%) — matches `TradingCost` in research
- `pyramiding=0` — no stacking positions
- `calc_on_every_tick=false`
- `process_orders_on_close=false`

### Section 2: Configuration

```pine
// ============================================================================
// Configuration
// ============================================================================
```

Map the Python config dataclass fields to `input.*()` calls:

| Python Type | Pine Input |
|---|---|
| `int` | `input.int(default, "Label", minval=...)` |
| `float` (percent) | `input.float(default * 100, "Label %", minval=0, maxval=100)` |
| `float` (threshold) | `input.float(default, "Label")` |
| `bool` | `input.bool(default, "Label")` |
| `str` (enum) | `input.string(default, "Label", options=[...])` |

**IMPORTANT**: Stop loss and take profit percentages in Python are decimals (e.g., `0.105`). In Pine they are displayed as percentages (e.g., `10.5`). The conversion happens in the exit logic where Pine divides by 100.

Group inputs in this order:
1. **Indicator Settings** — period, windows, etc.
2. **Indicator Thresholds** — upper, lower, mid (if applicable)
3. **Signal Behavior** — signal_mode, exit_mode (if applicable)
4. **Position Management** — stop_loss_percent, take_profit_percent, max_holding_bars, cooldown_bars
5. **Risk Management** — use_stop_loss, use_take_profit, use_max_holding, allow_flip
6. **Display Options** — always include:
   ```pine
   show_signals = input.bool(true, "Show Signal Markers")
   show_background = input.bool(true, "Show Background Colors")
   ```

### Section 3: Indicator Calculation

```pine
// ============================================================================
// <Indicator Name> Calculation
// ============================================================================
```

Use Pine's built-in `ta.*` functions where possible:

| Python Indicator | Pine Equivalent |
|---|---|
| `RelativeStrengthIndex` | `ta.rsi(close, period)` |
| `RateOfChange` | `ta.roc(close, period)` |
| `Momentum` | `ta.mom(close, period)` |
| `ExponentialMovingAverage` | `ta.ema(close, period)` |
| `SimpleMovingAverage` | `ta.sma(close, period)` |
| `TripleExponentialMovingAverage` | Manual: `3*(ema1-ema2)+ema3` |
| `CommodityChannelIndex` | `ta.cci(close, period)` |
| `ADX` | `ta.adx(high, low, close, period)` |

### Section 4: Signal Detection

```pine
// ============================================================================
// Signal Detection (matches research notebook logic)
// ============================================================================
```

Translate `_compute_signals()` from the Python strategy. The `[1]` operator in Pine is equivalent to `self._previous_value` in Python.

**For band-crossover strategies** (RSI, MOM, ROC, CCI — strategies with upper/lower/mid thresholds):

```pine
// Mean reversion signals
mr_long_signal = (<indicator>[1] < <lower>) and (<indicator> >= <lower>)
mr_short_signal = (<indicator>[1] > <upper>) and (<indicator> <= <upper>)

// Momentum signals
mom_long_signal = (<indicator>[1] < <upper>) and (<indicator> >= <upper>)
mom_short_signal = (<indicator>[1] > <lower>) and (<indicator> <= <lower>)

// Select based on mode
long_entry_signal = signal_mode == "mean_reversion" ? mr_long_signal : mom_long_signal
short_entry_signal = signal_mode == "mean_reversion" ? mr_short_signal : mom_short_signal

// Exit signals
mr_long_mid_exit = (<indicator>[1] < <mid>) and (<indicator> >= <mid>)
mr_short_mid_exit = (<indicator>[1] > <mid>) and (<indicator> <= <mid>)
mom_long_mid_exit = (<indicator>[1] > <mid>) and (<indicator> <= <mid>)
mom_short_mid_exit = (<indicator>[1] < <mid>) and (<indicator> >= <mid>)

long_exit_signal = exit_mode == "midpoint" and (signal_mode == "mean_reversion" ? mr_long_mid_exit : mom_long_mid_exit)
short_exit_signal = exit_mode == "midpoint" and (signal_mode == "mean_reversion" ? mr_short_mid_exit : mom_short_mid_exit)
```

**For crossover strategies** (TEMA — strategies with two lines crossing):

```pine
long_entry_signal = (<diff>[1] < 0) and (<diff> > 0)
short_entry_signal = (<diff>[1] > 0) and (<diff> < 0)

long_exit_signal = short_entry_signal
short_exit_signal = long_entry_signal
```

### Section 5: Position State Tracking

```pine
// ============================================================================
// Position State Tracking
// ============================================================================
var int entry_bar = na
var int cooldown_left = 0
var int stopped_out_count = 0

is_flat = strategy.position_size == 0
is_long = strategy.position_size > 0
is_short = strategy.position_size < 0

entry_price = strategy.position_avg_price

if cooldown_left > 0 and is_flat
    cooldown_left := cooldown_left - 1

if is_long or is_short
    if na(entry_bar)
        entry_bar := bar_index
else
    entry_bar := na

bars_held = not na(entry_bar) ? bar_index - entry_bar : 0
```

This section is **identical across all strategies**. Copy it exactly. Only omit `cooldown_left` if the strategy has no cooldown feature.

### Section 6: Entry Logic

```pine
// ============================================================================
// Entry Logic
// ============================================================================
if is_flat and cooldown_left == 0
    if long_entry_signal
        strategy.entry("Long", strategy.long, comment="Long Entry")
    else if short_entry_signal
        strategy.entry("Short", strategy.short, comment="Short Entry")
```

This section is **identical across all strategies** that support cooldown. For strategies without cooldown:
```pine
if is_flat
    if long_entry_signal
        strategy.entry("Long", strategy.long, comment="Long Entry")
    else if short_entry_signal
        strategy.entry("Short", strategy.short, comment="Short Entry")
```

### Section 7: Exit Logic — Long Position

```pine
// ============================================================================
// Exit Logic - Long Position
// ============================================================================
if is_long and not na(entry_price)
    long_stop = entry_price * (1 - stop_loss_percent / 100)
    long_tp = entry_price * (1 + take_profit_percent / 100)

    if use_stop_loss and low <= long_stop
        strategy.close("Long", comment="SL")
        stopped_out_count := stopped_out_count + 1
        cooldown_left := cooldown_bars
    else if use_take_profit and high >= long_tp
        strategy.close("Long", comment="TP")
        stopped_out_count := 0
    else if long_exit_signal
        strategy.close("Long", comment="Mid Exit")
        stopped_out_count := 0
    else if allow_flip and short_entry_signal and cooldown_left == 0
        strategy.close("Long", comment="Flip")
        if cooldown_left == 0
            strategy.entry("Short", strategy.short, comment="Flip to Short")
        stopped_out_count := 0
    else if use_max_holding and bars_held >= max_holding_bars
        strategy.close("Long", comment="Max Hold")
```

Exit priority order (must match Python strategy):
1. Stop loss
2. Take profit
3. Signal exit (midpoint)
4. Flip on opposite signal
5. Max holding

**IMPORTANT**: The comment strings ("SL", "TP", "Mid Exit", "Flip", "Flip to Short", "Flip to Long", "Max Hold", "Long Entry", "Short Entry") are used by `validate_runner.py` for trade matching. Keep them consistent.

### Section 8: Exit Logic — Short Position

Mirror of Section 7 with inverted logic:
- `is_short` instead of `is_long`
- `short_stop = entry_price * (1 + stop_loss_percent / 100)` (inverted)
- `short_tp = entry_price * (1 - take_profit_percent / 100)` (inverted)
- `high >= short_stop` (inverted)
- `low <= short_tp` (inverted)
- Flip direction: close "Short", entry "Long"

### Section 9: Plot Indicator and Thresholds

```pine
// ============================================================================
// Plot <Indicator> and Thresholds
// ============================================================================
```

**For band-crossover strategies:**
```pine
plot(<indicator>, "<Name>", color=color.blue, linewidth=2)

hline(<upper>, "<Name> Upper", color=color.red, linestyle=hline.style_dashed)
hline(<lower>, "<Name> Lower", color=color.green, linestyle=hline.style_dashed)
hline(<mid>, "<Name> Midpoint", color=color.gray, linestyle=hline.style_dashed)
```

**For crossover strategies:**
```pine
plot(<diff>, "<Name> Diff", color=color.blue, linewidth=2)
hline(0, "Zero", color=color.gray, linestyle=hline.style_dashed)
```

**Signal markers** (always include):
```pine
plotshape(show_signals and long_entry_signal and is_flat ? <plot_level> : na,
          "Long Entry", shape.triangleup, location.absolute, color=color.lime, size=size.tiny)
plotshape(show_signals and short_entry_signal and is_flat ? <plot_level> : na,
          "Short Entry", shape.triangledown, location.absolute, color=color.red, size=size.tiny)
plotshape(show_signals and long_exit_signal and is_long ? <plot_level> : na,
          "Long Exit", shape.circle, location.absolute, color=color.aqua, size=size.tiny)
plotshape(show_signals and short_exit_signal and is_short ? <plot_level> : na,
          "Short Exit", shape.circle, location.absolute, color=color.yellow, size=size.tiny)
```

Where `<plot_level>`:
- For band strategies: use the threshold level (e.g., `rsi_lower` for long entry, `rsi_upper` for short entry, `rsi_mid` for exits)
- For crossover strategies: use `0`

**Background colors** (always include):
```pine
bgcolor(show_background and <bullish_condition> ? color.new(color.green, 94) : na, title="Bullish Regime")
bgcolor(show_background and <bearish_condition> ? color.new(color.red, 94) : na, title="Bearish Regime")
```

Where conditions depend on strategy type:
- Band strategies: `<indicator> < <lower>` (oversold green), `<indicator> > <upper>` (overbought red), alpha `95`
- Crossover strategies: `<diff> > 0` (bullish green), `<diff> < 0` (bearish red), alpha `94`

### Section 10: Info Table

```pine
// ============================================================================
// Info Table
// ============================================================================
var table info_table = table.new(position.top_right, 2, 8, bgcolor=color.new(color.gray, 80))
if barstate.islast
    pos_text = is_long ? "LONG" : is_short ? "SHORT" : "FLAT"
    pos_color = is_long ? color.green : is_short ? color.red : color.gray

    current_stop = is_long ? entry_price * (1 - stop_loss_percent / 100) :
                   is_short ? entry_price * (1 + stop_loss_percent / 100) : na

    table.cell(info_table, 0, 0, "Position", text_color=color.white)
    table.cell(info_table, 1, 0, pos_text, text_color=pos_color)
```

The info table always includes:
1. **Position** — LONG / SHORT / FLAT
2. **Indicator value** — current value of the primary indicator, formatted with `str.tostring(val, "#.##")`
3. **Strategy-specific row** — e.g., Mode for RSI, Short/Long windows for TEMA
4. **Entry Price** — with `-` when flat
5. **Stop Level** — orange colored, with `-` when flat
6. **Bars Held** — formatted as `current/max`, red when at limit
7. **Cooldown** — orange when active (omit if strategy has no cooldown)
8. **Stop Count** — total stop-loss triggers

Adjust the table row count (`2, N`) to match the number of rows.

## File Naming Convention

Output file: `pine/<Strategy_Name_With_Underscores>.pine`

Examples:
- `RSISignalStrategy` → `pine/RSI_Signal_Strategy.pine`
- `TEMACrossoverStrategy` → `pine/TEMA_Crossover_Strategy.pine`
- `MOMSignalStrategy` → `pine/MOM_Signal_Strategy.pine`
- `ROCMeanReversionStrategy` → `pine/ROC_Mean_Reversion.pine`

## Python-to-Pine Translation Reference

| Python | Pine |
|---|---|
| `self._previous_value` | `indicator[1]` |
| `current_value` | `indicator` (or `indicator[0]`) |
| `self.cache.is_flat(...)` | `strategy.position_size == 0` |
| `self.cache.is_net_long(...)` | `strategy.position_size > 0` |
| `self.cache.is_net_short(...)` | `strategy.position_size < 0` |
| `self._resolve_entry_price()` | `strategy.position_avg_price` |
| `self._bars_held()` | `bar_index - entry_bar` |
| `self._candle_low(candle)` | `low` |
| `self._candle_high(candle)` | `high` |
| `self._candle_close(candle)` | `close` |
| `self.on_signal(signal=1, ...)` | `strategy.entry("Long", strategy.long, ...)` |
| `self.on_signal(signal=-1, ...)` | `strategy.entry("Short", strategy.short, ...)` |
| `self._order_manager.submit_market_close(...)` | `strategy.close("Long"/"Short", ...)` |
| `config.stop_loss_percent` (decimal `0.10`) | `stop_loss_percent` (display `10.0`), used as `/ 100` in logic |

## Checklist Before Done

- [ ] `//@version=6` at top
- [ ] Strategy declaration matches standard (cash qty, 100000 capital, 0.0005 commission)
- [ ] All config parameters mapped to `input.*()` calls with correct types
- [ ] Stop loss percent correctly converted from decimal to percentage display
- [ ] Indicator calculation uses `ta.*` built-in where available
- [ ] Signal detection logic matches Python `_compute_signals()` exactly
- [ ] Position state tracking section present (var entry_bar, cooldown, etc.)
- [ ] Entry logic handles cooldown (if applicable)
- [ ] Exit priority order: SL → TP → Signal Exit → Flip → Max Hold
- [ ] Exit comments use standard strings: "SL", "TP", "Mid Exit", "Flip", "Max Hold"
- [ ] Flip logic present if `allow_flip` is in config
- [ ] Plot section includes indicator line, thresholds/zero line, signal markers, background colors
- [ ] Info table present with position, indicator value, entry price, stop level, bars held
- [ ] File saved to `pine/<Name>.pine`
