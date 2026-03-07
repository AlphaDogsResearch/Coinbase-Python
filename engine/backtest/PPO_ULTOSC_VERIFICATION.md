# PPO and ULTOSC Parity Verification Report

## Current Status

| Strategy | Reference | Generated | Matched | Mismatched |
|----------|-----------|-----------|---------|------------|
| PPO | 87 | 83 | 58 | 37 |
| ULTOSC | 290 | 282 | 256 | 41 |

**Note**: Validation requires `reference_utc_offset_hours=8` for PPO and ULTOSC (TradingView exports in UTC+8). This is set in `validate_pine_parity.json`. Without it, all trades show 0 matched due to timezone mismatch.

## Research Validation (PPO)

### Research Notebook Status

- **`research/BTCSignal.ipynb`**: Uses **SMA crossover** (ShortWindow=5, LongWindow=200) only. **No PPO logic**.
- **Per validate-with-pine-trades skill**: A research notebook with PPO indicator math is required for authoritative validation. **PPO research notebook does not exist.**

### PPO Formula Verification

| Source | Formula | Notes |
|--------|---------|-------|
| **Pine** | `(ma_fast - ma_slow) / ma_slow * 100` | DEMA = `2*ta.ema - ta.ema(ta.ema)` |
| **Python** | Same | `engine/strategies/indicators.py` PPO class |
| **TA-Lib** | `PPO(close, fastperiod, slowperiod, matype)` | matype 3 = DEMA |

### Python vs TA-Lib PPO (Sample)

At 2025-01-31 05:00 UTC, ETHUSDT 1h:
- **Python PPO**: 2.229589
- **TA-Lib PPO** (matype=3): 2.255786
- **Delta**: ~0.026 (Python lower)

This suggests **EMA/DEMA initialization differs** between Python and TA-Lib (and likely Pine). TA-Lib typically uses SMA of first `period` values for EMA seed; our Python uses first close.

### EMA Initialization

| Implementation | First value |
|----------------|-------------|
| **Python** (`ExponentialMovingAverage`) | First close as seed; recursive from bar 1 |
| **Python** (PPO DEMA, `use_sma_seed=True`) | SMA of first `period` values (matches Pine) |
| **Pine** `ta.ema` | SMA of first `period` values (TradingView docs) |
| **TA-Lib** | SMA of first `period` values for EMA seed |

**Implemented**: PPO DEMA (matype=3) now uses `use_sma_seed=True` to align with Pine ta.ema.

## Mismatch Patterns

### PPO
- **Python holds longer**: In most MISMATCH cases, `exit_time_generated > exit_time_reference` (Python exits 1–4 days later).
- **MISSING_GENERATED**: Pine has trades Python doesn’t – Python exits earlier (flip/max hold) and never opens that trade.
- **MISSING_REFERENCE**: Python has trades Pine doesn’t – Python holds until max hold (93 bars) when Pine flipped earlier.
- **Root cause hypothesis**: Python’s PPO or flip signal differs from Pine, so Python misses flip exits and holds until max hold.

### ULTOSC
- Same pattern: Python often exits later; some MISSING_REFERENCE / MISSING_GENERATED.
- Exit time diffs range from 60 minutes to 4500+ minutes.

## Implementation Comparison

### PPO (matype=3 DEMA)
| Aspect | Pine | Python |
|--------|------|--------|
| DEMA | `2*EMA - EMA(EMA)` | `2*ema1 - ema2` (same) |
| EMA seed | ta.ema (SMA of first period) | SMA of first period (`use_sma_seed=True`) |
| Signal | `ppo[1]` vs `ppo` crossover | `_previous_ppo` vs `current_ppo` |

**Implemented**: PPO DEMA uses EMA with SMA seed to match Pine ta.ema.

### ULTOSC
| Aspect | Pine | Python |
|--------|------|--------|
| prev_close | `nz(close[1], close)` – bar 0 uses `close` | Bar 0: set `_prev_close = close`, compute bp/tr |
| First bp/tr | Bar 0: `bp = close - min(low, close)` | Bar 0: same (implemented) |
| First value | `bar_index >= timeperiod3` | `len(buffer) >= timeperiod3` |

**Implemented**: ULTOSC now computes bp/tr on bar 0 with `prev_close=close` to match Pine.

## Diagnostic Script

Run PPO value dump for manual comparison with TradingView:

```bash
python -m engine.backtest.dump_ppo_values \
  --symbol ETHUSDT \
  --interval 1h \
  --start 2025-01-15 \
  --end 2025-02-15 \
  --output ppo_values.csv
```

Output: `bar_index`, `timestamp`, `close`, `ppo_python`, `ppo_talib` (if TA-Lib installed). Compare `ppo_python` with TradingView PPO (fast=38, slow=205, DEMA) at matching timestamps.

## Implementation Plan

See **[PPO_ULTOSC_PARITY_PLAN.md](PPO_ULTOSC_PARITY_PLAN.md)** for a detailed execution plan.

**Implemented**: Research notebooks (PPO, ULTOSC), `dump_ultosc_values.py`, EMA SMA-seed for PPO DEMA, ULTOSC first-bar handling. Match counts unchanged (58 PPO, 256 ULTOSC); indicator alignment with Pine documented.

## Recommended Next Steps

1. **Create PPO research notebook**: Add PPO indicator (DEMA, formula) to `research/` with TA-Lib or explicit math. Required per validate-with-pine-trades skill. (BTCSignal.ipynb uses SMA crossover only; no PPO.)

2. **Diagnostic script**: Run `python -m engine.backtest.dump_ppo_values` to dump PPO values for comparison with TradingView (see Diagnostic Script section above).

3. **EMA initialization (PPO)**: Align Python EMA with Pine’s `ta.ema` initialization (e.g. SMA of first `period` values instead of first close). Pine uses the first source value as seed; verify exact behavior.

4. **ULTOSC first bar**: Align Python with Pine by computing bp/tr on the first bar using `prev_close = close` when `_prev_close is None`. Requires buffer size increase and careful alignment of first-output bar with `bar_index >= timeperiod3`.

5. **Re-validate**: After changes, run strict validation and report before/after metrics.
