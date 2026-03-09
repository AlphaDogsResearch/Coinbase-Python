# PPO and ULTOSC Parity Implementation Plan

**Current status**: PPO 58/87 matched, ULTOSC 256/290 matched. Target: 100% trade match.

## Implementation Status (2026-02-26)

| Task | Status | Notes |
|------|--------|------|
| PPO research notebook | Done | `research/PPO_Signal.ipynb` |
| ULTOSC research notebook | Done | `research/ULTOSC_Signal.ipynb` |
| dump_ultosc_values.py | Done | `engine/backtest/dump_ultosc_values.py` |
| EMA SMA-seed fix | **Reverted** | Broke PPO/RSI validation (0 matched) |
| ULTOSC first-bar fix | **Reverted** | Broke ULTOSC validation (0 matched) |

EMA and ULTOSC fixes need further investigation (Pine ta.ema may use first-close seed; first-bar alignment may require different approach).

---

## 1. Research Notebooks

### 1.1 PPO Research Notebook

**File**: `research/PPO_Signal.ipynb` (new)

**Contents**:
- **Indicator math**:
  - DEMA formula: `2 * EMA(close, period) - EMA(EMA(close, period), period)`
  - PPO formula: `(ma_fast - ma_slow) / ma_slow * 100`
  - MA types: 0=SMA, 1=EMA, 2=WMA, 3=DEMA
- **EMA initialization**: Document TA-Lib behavior (SMA of first `period` values as seed) and Pine `ta.ema` behavior
- **Signal logic**: momentum vs mean_reversion, breakout vs midpoint exit
- **Validation**: Compare TA-Lib PPO vs hand-rolled PPO on sample data; document expected values at known timestamps

**Dependencies**: Reuse `research/BTCSignal.ipynb` pattern (yfinance, talib, pandas). Add cells for PPO calculation and comparison.

### 1.2 ULTOSC Research Notebook

**File**: `research/ULTOSC_Signal.ipynb` (new)

**Contents**:
- **Indicator math**:
  - BP = `close - min(low, prev_close)`
  - TR = `max(high, prev_close) - min(low, prev_close)`
  - prev_close: bar 0 uses `close` (Pine: `nz(close[1], close)`)
  - UO = `100 * (4*avg1 + 2*avg2 + avg3) / 7` where avgN = sum(BP, N) / sum(TR, N)
  - First value: bar_index >= timeperiod3 (Pine)
- **First-bar handling**: Document that bar 0 must produce bp/tr with prev_close=close
- **Signal logic**: Same as PPO (momentum/mean_reversion, breakout/midpoint)
- **Validation**: Compare TA-Lib ULTOSC vs hand-rolled on sample data

**Dependencies**: Same as PPO notebook.

---

## 2. Indicator Diagnostic Scripts

### 2.1 PPO Dump (Done)

**File**: `engine/backtest/dump_ppo_values.py`

**Status**: Exists. Outputs `bar_index`, `timestamp`, `close`, `ppo_python`, `ppo_talib`.

**Action**: None. Optionally extend to support `--strategy` to dump from a specific strategy config.

### 2.2 ULTOSC Dump (To Do)

**File**: `engine/backtest/dump_ultosc_values.py` (new)

**Scope**:
- Mirror `dump_ppo_values.py` structure
- Load Binance data with warmup (timeperiod3 bars)
- Run `UltimateOscillator` on candles
- Output: `bar_index`, `timestamp`, `close`, `ultosc_python`, `ultosc_talib` (if TA-Lib installed)
- Params from config: timeperiod1=14, timeperiod2=28, timeperiod3=36

**Usage**:
```bash
python -m engine.backtest.dump_ultosc_values \
  --symbol ETHUSDT --interval 1h \
  --start 2025-01-15 --end 2025-02-15 \
  --output ultosc_values.csv
```

---

## 3. EMA Initialization (PPO)

### 3.1 Verify Pine ta.ema

**Action**: Research Pine Script docs / source to confirm:
- Does `ta.ema(source, length)` use first source value as seed, or SMA of first `length` values?
- Document finding in PPO research notebook.

### 3.2 Align Python EMA

**File**: `engine/strategies/indicators.py` — `ExponentialMovingAverage`

**Current behavior** (lines 65–84):
- Bar 1: `value = close` (first close as seed)
- Bar 2..period: recursive EMA formula
- Initialized when `_count >= period`

**Target behavior** (TA-Lib / common convention):
- Bars 1..period: accumulate closes, compute SMA when `_count == period`
- Use SMA as initial EMA value
- Bar period+1 onward: recursive EMA formula

**Implementation**:
```python
# In handle_bar, when not initialized:
if self._count < self.period:
    self._buffer.append(close_price)
    self._count += 1
    if self._count == self.period:
        self.value = sum(self._buffer) / self.period
        self._initialized = True
else:
    self.value = (close_price - self.value) * self.alpha + self.value
```

**Impact**: PPO, DEMA, and any strategy using EMA (RSI, etc.). Run full validation after change.

---

## 4. ULTOSC First-Bar Handling

### 4.1 Problem

| Bar | Pine | Python |
|-----|------|--------|
| 0 | prev_close=close, bp/tr computed | Skip (return early) |
| 1 | prev_close=close[0], bp/tr | First bp/tr added |

Python skips bar 0, so the ULTOSC series is shifted by one bar vs Pine.

### 4.2 Fix

**File**: `engine/strategies/indicators.py` — `UltimateOscillator.handle_bar`

**Current** (lines 889–894):
```python
if self._prev_close is None:
    self._prev_close = close
    self.value = 0.0
    self._initialized = False
    return
```

**Target**: On first bar, use `prev_close = close` (same as Pine `nz(close[1], close)`), compute bp/tr, append to buffers, then update `_prev_close`.

**Implementation**:
```python
if self._prev_close is None:
    prev = close  # Pine: nz(close[1], close) -> bar 0 uses close
else:
    prev = self._prev_close

bp = close - min(low, prev)
tr = max(high, prev) - min(low, prev)

self._bp_buffer.append(bp)
self._tr_buffer.append(tr)
self._prev_close = close

# Rest unchanged: check len(buffer) >= timeperiod3, compute value
```

**Buffer sizing**: Buffers are `maxlen=timeperiod3`. Bar 0 adds one element. No size change needed.

**Caveat**: A prior attempt to align first-bar handling broke validation (0 trades). Root cause may have been buffer/alignment. Revisit with:
1. Dump ULTOSC values before/after fix
2. Compare with TradingView at specific timestamps
3. Run validation; if regression, bisect (e.g. first-bar only vs full alignment)

---

## 5. Execution Order

| Step | Task | Dependency |
|------|------|------------|
| 1 | Create `research/PPO_Signal.ipynb` | None |
| 2 | Create `research/ULTOSC_Signal.ipynb` | None |
| 3 | Add `dump_ultosc_values.py` | None |
| 4 | Verify Pine ta.ema initialization | Step 1 |
| 5 | Implement EMA SMA-seed fix in `indicators.py` | Step 1, 4 |
| 6 | Implement ULTOSC first-bar fix in `indicators.py` | Step 2 |
| 7 | Run PPO dump, compare with TradingView | Step 5 |
| 8 | Run ULTOSC dump, compare with TradingView | Step 6 |
| 9 | Run strict validation on PPO and ULTOSC | Steps 7, 8 |
| 10 | Update `PPO_ULTOSC_VERIFICATION.md` with results | Step 9 |

---

## 6. Validation Commands

```bash
# PPO
python -m engine.backtest.validate_runner \
  --reference-file engine/backtest/pine_reference_list_of_trades/PPO_Signal_Strategy_BINANCE_ETHUSDT.P_*.csv \
  --execution-timing next_bar_open \
  --strategy-config engine/backtest/configs/validate_pine_parity.json

# ULTOSC
python -m engine.backtest.validate_runner \
  --reference-file engine/backtest/pine_reference_list_of_trades/ULTOSC_Signal_Strategy_BINANCE_ETHUSDT.P_*.csv \
  --execution-timing next_bar_open \
  --strategy-config engine/backtest/configs/validate_pine_parity.json
```

---

## 7. Success Criteria

- PPO: 87/87 matched (or 100% of reference)
- ULTOSC: 290/290 matched (or 100% of reference)
- Research notebooks define indicator math and match engine behavior
- Diagnostic scripts produce values that match TradingView at sample timestamps
