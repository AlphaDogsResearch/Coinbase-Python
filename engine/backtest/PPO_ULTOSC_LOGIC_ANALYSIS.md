# PPO and ULTOSC Logic Analysis

## Mismatch Summary

| Strategy | Ref | Gen | Matched | Mismatched |
|----------|-----|-----|---------|------------|
| PPO | 87 | 83 | 58 | 37 |
| ULTOSC | 290 | 282 | 256 | 41 |

## Observed Pattern

### PPO (from pairs CSV)

1. **Same entry, Python exits much later**
   - Example: Both enter LONG at 2025-02-10 11:00. Pine exits 2025-02-11 22:00 (Flip). Python exits 2025-02-14 09:00 (~59h later).
   - `exit_time_diff_minutes` often 1200–4500 (20–75 hours).
   - Python holds until **max_hold (93 bars)** instead of flipping on opposite signal.

2. **MISSING_GENERATED**: Pine has trades Python doesn’t
   - Pine flips earlier; Python never opens that trade.

3. **MISSING_REFERENCE**: Python has trades Pine doesn’t
   - Python holds until max hold; Pine already flipped and opened a new trade.

### ULTOSC

- Same pattern: Python exits 20–28 hours later in many MISMATCH cases.
- `exit_time_diff_minutes`: 120, 1200, 1440, 1560, 1680.

---

## Exit Logic Deep Dive

### Exit Priority (Pine vs Python)

Both use the same order:

| # | Condition | Pine | Python |
|---|-----------|------|--------|
| 1 | Stop loss | `low <= long_stop` / `high >= short_stop` | `_candle_low() <= long_stop` / `_candle_high() >= short_stop` |
| 2 | Take profit | `high >= long_tp` / `low <= short_tp` | Same |
| 3 | Midpoint exit | `long_exit_signal` / `short_exit_signal` | Same (exit_mode=breakout → always False) |
| 4 | **Flip** | `allow_flip and short_entry_signal` | Same |
| 5 | Max hold | `bars_held >= max_holding_bars` | `_bars_held() >= max_holding_bars` |

### Verified: Exit Logic Structure Matches

- Exit order, conditions, and early returns are aligned.
- `_reverse_position` sets `_entry_bar` correctly for the new position.
- `_close_position` clears `_entry_bar` and `_position_side`.
- `_sync_position_state` updates `_position_side` and `_entry_price` (not `_entry_bar`; that is set only on entry/reversal).

### bars_held Semantics

| | Pine | Python |
|-|------|--------|
| Entry bar | `entry_bar := bar_index` when position opens | `_entry_bar = _entry_bar_for_new_position()` = `_bars_processed + 1` (next_bar_open) |
| bars_held | `bar_index - entry_bar` | `_bars_processed - _entry_bar` |
| Max hold | `bars_held >= 93` | `_bars_held() >= 93` |

With `next_bar_open`, both treat the fill bar as the first held bar; max-hold timing matches for initial entry.

### entry_bar on Flip (Potential Mismatch)

| | Pine | Python |
|-|------|--------|
| On flip | `entry_bar` is **not** reset. `entry_bar` stays from original entry. | `_entry_bar = _entry_bar_for_new_position()` — **reset** to new position bar |
| bars_held after flip | Continues from original entry (e.g. 35 bars held long, flip to short → bars_held = 36, 37…) | Resets to 0 (new position) |

**Impact**: After a flip, Pine would hit max_hold sooner (e.g. 58 more bars if we held 35 before flip). Python would hold 93 full bars from the flip. If both ever flip, Python could exit ~35 bars later than Pine. To match Pine, Python should **not** reset `_entry_bar` on flip — keep counting from the original entry. This only matters once flip parity is achieved.

### Root Cause: Flip Signal Not Firing

Because exit structure and bars_held match, the remaining cause is that **`short_entry_signal` (or `long_entry_signal`) is False in Python when it is True in Pine**.

Flip condition (long → short):

- **Pine**: `short_entry_signal` = `ultosc[1] > ultosc_lower and ultosc <= ultosc_lower` (momentum)
- **Python**: `short_entry_signal` = `_previous_ultosc > ultosc_lower and current_ultosc <= ultosc_lower`

Logic is equivalent. The difference is in **indicator values** (`current_ppo` / `current_ultosc` vs Pine’s `ppo` / `ultosc`).

---

## Why Indicator Values Differ

### PPO

- Python vs TA-Lib sample delta ~0.026 (Python lower).
- EMA init: Python uses first close; TA-Lib uses SMA of first `period` values.
- If PPO is shifted or scaled, the crossover happens on different bars, so the flip signal fires on different bars.

### ULTOSC

- Python skips bar 0 for bp/tr; Pine uses `nz(close[1], close)` on bar 0.
- That can shift the ULTOSC series by one bar.

---

## Potential Exit Logic Edge Cases

### 1. _candle_low / _candle_high fallback

```python
def _candle_low(self, candle: MidPriceCandle) -> float:
    if candle.low == float("inf"):
        return self._candle_close(candle)
    return candle.low
```

If `candle.low` is ever `float("inf")`, stop loss uses close instead of low. **Backtest candles** (CSV/Binance) always have valid high/low from the data source, so this fallback does not apply to Pine parity validation. It only matters for live tick data (MidPriceCandle) with incomplete candles.

### 2. Position state vs cache

If `cache.is_flat()` is True when we actually have a position (e.g. sync delay), we would skip `_handle_long_position` and never evaluate the flip. In the backtest, the cache is updated synchronously in `on_signal`, so this should not occur.

### 3. last bar / next_candle

When `next_candle` is None (last bar), `_resolve_execution` uses current close instead of next open. Exits on the last bar could differ slightly, but this does not explain the large exit time differences seen.

---

## Summary: Exit Logic Findings

| Finding | Status |
|---------|--------|
| Exit order (SL → TP → midpoint → flip → max hold) | Matches |
| Stop/TP use intrabar low/high | Matches (backtest candles have valid OHLC) |
| Flip condition logic | Matches |
| bars_held for initial entry | Matches |
| **entry_bar on flip** | **Mismatch**: Python resets, Pine does not |
| **Flip signal firing** | **Root cause**: Python misses flip because PPO/ULTOSC values differ from Pine |

## Recommended Fixes (in order)

1. **Indicator parity** (primary)
   - **PPO**: Align EMA init with Pine (e.g. SMA seed). Scope to PPO/DEMA if needed.
   - **ULTOSC**: Align first-bar handling with Pine (`prev_close = close` on bar 0, compute bp/tr).

2. **entry_bar on flip** (secondary, after flip parity)
   - Consider not resetting `_entry_bar` on flip so bars_held continues from original entry, matching Pine. Verify Pine behavior with a test flip first.

3. **Diagnostic**
   - Add logging when flip condition is almost met (e.g. `current_ppo` near `ppo_lower`) to confirm whether the flip is missed due to value vs logic.

4. **Re-validate**
   - After each change, run strict validation and compare match counts.

---

## Commands

```bash
# Dump PPO around a mismatch window
python -m engine.backtest.dump_ppo_values \
  --start 2025-02-08 --end 2025-02-15 \
  --output ppo_mismatch_window.csv

# Dump ULTOSC
python -m engine.backtest.dump_ultosc_values \
  --start 2023-06-05 --end 2023-06-25 \
  --output ultosc_mismatch_window.csv

# Validate
python -m engine.backtest.validate_runner \
  --reference-dir engine/backtest/pine_reference_list_of_trades \
  --execution-timing next_bar_open \
  --strategy-config engine/backtest/configs/validate_pine_parity.json
```
