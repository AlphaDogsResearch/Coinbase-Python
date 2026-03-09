# Python vs Pine Implementation Comparison – ROC, RSI, PPO, ULTOSC

Direct comparison of bar counts, entry/exit semantics, and indicator logic for parity validation.

---

## 1. Bar Count Semantics

### Pine `entry_bar` and `bars_held`

```pine
// pine/ROC_Mean_Reversion.pine (and similar patterns in RSI, PPO, ULTOSC)
if is_long or is_short
    if na(entry_bar)
        entry_bar := bar_index
else
    entry_bar := na

bars_held = bar_index - entry_bar
```

- `entry_bar` = bar index when position was opened
- `bars_held` = 0 on entry bar, 1 on next bar, etc.
- Max hold exit: `bars_held >= max_holding_bars`

### Python `_entry_bar` / `_position_entry_bar` and `_bars_held`

| Strategy | Entry bar set | `_bars_held()` | Uses `_entry_bar_for_new_position()`? |
|----------|---------------|----------------|--------------------------------------|
| ROC | `_position_entry_bar = self._bars_processed` | `_bars_processed - _position_entry_bar` | No |
| RSI | `_entry_bar = self._bars_processed` | `_bars_processed - _entry_bar` | No |
| PPO | `_entry_bar = self._bars_processed` | `_bars_processed - _entry_bar` | No |
| ULTOSC | `_entry_bar = self._bars_processed` | `_bars_processed - _entry_bar` | No |
| BBAND, CCI, CMO, MOM | `_entry_bar = self._entry_bar_for_new_position()` | `_bars_processed - _entry_bar` | Yes |

### Execution timing: `next_bar_open`

Validation runs with `--execution-timing next_bar_open`:

- Order placed at bar N close
- Fill at bar N+1 open

So the effective entry bar is N+1, not N.

**`_entry_bar_for_new_position()`** (used by BBAND, CCI, CMO, MOM):

```python
if execution_timing == "next_bar_open":
    return self._bars_processed + 1
return self._bars_processed
```

ROC, RSI, PPO, ULTOSC use `_entry_bar = self._bars_processed` directly, so they treat the bar where the signal was emitted as the entry bar.

**Effect:** Python counts 1 extra bar held. Max-hold exits happen 1 bar earlier than in Pine. That matches the observed “exit times differ by 1 hour” (1 bar = 1 hour for 1h).

**Recommendation:** Add `_entry_bar_for_new_position()` (or equivalent) for ROC, RSI, PPO, ULTOSC and use it when the engine uses `next_bar_open`.

---

## 2. Strategy-Specific Differences

### ROC

| Aspect | Pine | Python |
|--------|------|--------|
| ROC formula | `ta.roc(close, roc_period)` → `(close - close[n]) / close[n] * 100` | `(close - prev) / prev`; strategy multiplies by 100 |
| Signal | `roc[1]` vs `roc` (cross threshold) | `_previous_roc` vs `current_roc` |
| Entry bar | `entry_bar := bar_index` | `_position_entry_bar = _bars_processed` (no `next_bar_open` adjustment) |
| Stop loss | `low <= long_stop` (intrabar) | `close_price <= _stop_loss_price` (close only) |
| Max hold | `bars_held >= max_holding_bars` | `_bars_processed - _position_entry_bar >= max_holding_bars` |

**Stop loss:** Pine uses `low`/`high`; Python uses `close`. Python can exit later when low touches stop but close is above.

**Parity:** 390/391 with 60 min tolerance; 1 exit-time mismatch.

---

### RSI

| Aspect | Pine | Python |
|--------|------|--------|
| RSI | `ta.rsi(close, rsi_period)` | Wilder’s smoothing in `RelativeStrengthIndex` |
| Signal | `rsi[1]` vs `rsi` | `_previous_rsi` vs `current_rsi` |
| Entry bar | `entry_bar := bar_index` | `_entry_bar = self._bars_processed` | 
| Stop loss | `low <= long_stop` | `low_price <= long_stop` (intrabar) |
| Max hold | `bars_held >= max_holding_bars` | `_bars_held() >= max_holding_bars` | 
| Flip | `allow_flip and short_entry_signal` → close then entry | Same pattern |

**Indicator warmup:** Both need `period + 1` bars. First RSI value at bar `period` (0-indexed).

**Parity:** 214/218 matched (226 generated vs 218 reference). Python has 8 more trades. Possible causes: floating-point differences or subtle differences in when RSI is considered “initialized” and used for signals.

---

### PPO

| Aspect | Pine | Python |
|--------|------|--------|
| MA type | `matype=3` → DEMA (2×EMA − EMA(EMA)) | `DoubleExponentialMovingAverage` |
| PPO | `(ma_fast - ma_slow) / ma_slow * 100` | Same formula |
| Signal | `ppo[1]` vs `ppo` | `_previous_ppo` vs `current_ppo` |
| Entry bar | `entry_bar := bar_index` | `_entry_bar = self._bars_processed` |
| Stop loss | `low <= long_stop` | `low_price <= long_stop` |
| Max hold | `bars_held >= max_holding_bars` | `_bars_held() >= max_holding_bars` |
| Flip | `allow_flip and short_entry_signal and cooldown_left == 0` | Same |

**Indicator warmup:** Slow period = 205; first PPO value when both MAs are ready (≈ bar 205).

**Parity:** 59/87 matched (83 generated vs 87 reference). Python has 4 fewer trades. Possible causes: DEMA differences, warmup differences, or signal logic.

---

### ULTOSC

| Aspect | Pine | Python |
|--------|------|--------|
| BP | `close - min(low, prev_close)` | Same |
| TR | `max(high, prev_close) - min(low, prev_close)` | Same |
| Averages | `ta.sma(bp, n) * n` | `sum(bp_values[-n:])` |
| ULTOSC | `100 * (4*avg1 + 2*avg2 + avg3) / 7` | Same |
| First value | `bar_index >= timeperiod3` | `len(_bp_buffer) >= timeperiod3` |
| Entry bar | `entry_bar := bar_index` | `_entry_bar = self._bars_processed` |
| Stop loss | `low <= long_stop` | `low_price <= long_stop` |
| Max hold | `bars_held >= max_holding_bars` | `_bars_held() >= max_holding_bars` |

**Indicator warmup:** Both need `timeperiod3` bars (36). First value at bar 36 (0-indexed).

**Parity:** 255/290 matched (283 generated vs 290 reference). Python has 7 fewer trades in line with PPO.

---

## 3. Summary of Bar Count Differences

| Strategy | Issue | Cause | Effect |
|----------|-------|-------|--------|
| ROC | `_position_entry_bar` | No `next_bar_open` adjustment | Max hold exits 1 bar earlier |
| RSI | `_entry_bar` | No `next_bar_open` adjustment | Max hold exits 1 bar earlier |
| PPO | `_entry_bar` | No `next_bar_open` adjustment | Max hold exits 1 bar earlier |
| ULTOSC | `_entry_bar` | No `next_bar_open` adjustment | Max hold exits 1 bar earlier |
| ROC | Stop loss | Close vs low/high | Python exits later when low touches stop but close is above |

---

## 4. Recommended Fixes

1. **Entry bar / bars_held (ROC, RSI, PPO, ULTOSC)**  
   Add `_entry_bar_for_new_position()` (or equivalent) and use it when `execution_timing == "next_bar_open"` so `_entry_bar` matches the fill bar.

2. **ROC stop loss**  
   Use `candle.low` / `candle.high` for stop checks instead of `close_price` to match Pine’s intrabar logic.

3. **MOM max hold**  
   Pine uses `bars_held >= max_holding_bars`; MOM uses `_bars_held() > max_holding_bars`. Changing to `>=` worsened parity (13 vs 180 matched); reverted. MOM’s `>` may compensate for other bar-count differences.

---

## 5. Indicator Warmup Summary

| Indicator | Pine first value | Python first value |
|-----------|------------------|---------------------|
| ROC | `period` bars | `period + 1` closes (buffer length) |
| RSI | `period + 1` bars | `period + 1` bars |
| PPO | When slow MA ready (≈205 bars) | When both MAs ready |
| ULTOSC | `bar_index >= timeperiod3` | `len(_bp_buffer) >= timeperiod3` |

---

## 6. Reference vs Generated Counts (Current)

| Strategy | Reference | Generated | Matched | Mismatched |
|----------|-----------|-----------|---------|-------------|
| ROC | 391 | 391 | 390 | 1 |
| RSI | 218 | 226 | 214 | 13 |
| PPO | 87 | 83 | 59 | 36 |
| ULTOSC | 290 | 283 | 255 | 43 |
