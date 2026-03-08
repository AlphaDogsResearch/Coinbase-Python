# Backtest Module

`engine/backtest` contains a modular historical backtesting stack:

- `engine.py`: reusable backtest engine + simulated order manager
- `data_sources.py`: Binance Futures and CSV loaders
- `backtest_runner.py`: configurable runner (`--config <json>`)
- `backtest_historical.py`: convenience historical wrapper and default example
- `validate_runner.py`: compare Python backtest trades vs Pine CSV reference trades
- `reporting.py`: exports signals/trades/equity/summary files
- `configs/`: example runner configs

## Run Examples

Offline CSV run:

```bash
python -m engine.backtest.backtest_runner --config engine/backtest/configs/simple_order_csv.json
```

Binance Futures historical run:

```bash
python -m engine.backtest.backtest_runner --config engine/backtest/configs/roc_binance_1h.json
```

## Validate Runner

`validate_runner` compares generated Python backtest trades against Pine export CSVs in `engine/backtest/pine_reference_list_of_trades`.

Validate all reference files in the default directory:

```bash
python -m engine.backtest.validate_runner
```

Validate one specific file:

```bash
python -m engine.backtest.validate_runner \
  --reference-file engine/backtest/pine_reference_list_of_trades/TRIX_Signal_Strategy_BINANCE_ETHUSDT.P_2026-02-26.csv
```

Validate multiple specific files:

```bash
python -m engine.backtest.validate_runner \
  --reference-file engine/backtest/pine_reference_list_of_trades/ROC_Mean_Reversion_Strategy_BINANCE_ETHUSDT.P_2026-02-13.csv \
  --reference-file engine/backtest/pine_reference_list_of_trades/RSI_Signal_Strategy_BINANCE_ETHUSDT.P_2026-02-13.csv \
  --reference-file engine/backtest/pine_reference_list_of_trades/TEMA_Crossover_Strategy_BINANCE_ETHUSDT.P_2026-02-13.csv
```

Strict parity gate (recommended). The `validate_pine_parity.json` config includes per-strategy `reference_utc_offset_hours` (8 for most, 0 for TRIX) since TradingView exports in chart timezone (typically UTC+8):

```bash
python -m engine.backtest.validate_runner \
  --reference-dir engine/backtest/pine_reference_list_of_trades \
  --execution-timing next_bar_open \
  --strategy-config engine/backtest/configs/validate_pine_parity.json \
  --output-dir reports/validation
```

Strict parity gate (BBAND ETHUSDT reference exported in UTC):

```bash
python -m engine.backtest.validate_runner \
  --reference-file engine/backtest/pine_reference_list_of_trades/BBAND_Signal_Strategy_BINANCE_ETHUSDT.P_2026-03-07.csv \
  --execution-timing next_bar_open \
  --strategy-config engine/backtest/configs/validate_pine_parity.json \
  --output-dir reports/validation
```

Strict parity gate (CMO ETHUSDT reference exported in UTC):

```bash
python -m engine.backtest.validate_runner \
  --reference-file engine/backtest/pine_reference_list_of_trades/CMO_Signal_Strategy_BINANCE_ETHUSDT.P_2026-03-08.csv \
  --execution-timing next_bar_open \
  --strategy-config engine/backtest/configs/validate_pine_parity.json \
  --output-dir reports/validation
```

**CMO re-export required:** Pine was updated to use TA-Lib-style CMO (Wilder smoothing) to align with research. If you changed the Pine script, export a fresh trade CSV from TradingView and replace the file in `engine/backtest/pine_reference_list_of_trades/` before validating.

Strict parity gate (CCI ETHUSDT reference exported in UTC+8):

```bash
python -m engine.backtest.validate_runner \
  --reference-file engine/backtest/pine_reference_list_of_trades/CCI_Signal_Strategy_BINANCE_ETHUSDT.P_2026-02-26.csv \
  --execution-timing next_bar_open \
  --reference-utc-offset-hours 8 \
  --strategy-config engine/backtest/configs/validate_pine_parity.json \
  --output-dir reports/validation
```

Strict parity gate (MOM ETHUSDT reference):

```bash
python -m engine.backtest.validate_runner \
  --reference-file engine/backtest/pine_reference_list_of_trades/MOM_Signal_Strategy_BINANCE_ETHUSDT.P_2026-02-26.csv \
  --execution-timing next_bar_open \
  --reference-utc-offset-hours 8 \
  --strategy-config engine/backtest/configs/validate_pine_parity.json \
  --output-dir reports/validation
```

Validate all 9 strategies (2026-02-26 exports):

Per-strategy UTC offset is read from `validate_pine_parity.json`. Single command:

```bash
python -m engine.backtest.validate_runner \
  --reference-dir engine/backtest/pine_reference_list_of_trades \
  --execution-timing next_bar_open \
  --reference-utc-offset-hours 8 \
  --strategy-config engine/backtest/configs/validate_pine_parity.json \
  --output-dir reports/validation
```

Per-strategy UTC offset (in `validate_pine_parity.json`):

| Strategy | Offset | Notes |
|----------|--------|-------|
| BBAND, CMO, TRIX | 0 (UTC) | 2026-03-07 exports in UTC |
| CCI, MOM, PPO, ROC, RSI, ULTOSC | 8 (UTC+8) | TradingView chart timezone |

Parity status (with `validate_pine_parity.json`):

| Strategy | Status | Notes |
|----------|--------|-------|
| BBAND | 100% match (498/498) | 2026-03-07 export, UTC+0, flip entry_bar fix |
| CMO | 100% match (652/652) | 2026-03-07 export, UTC+0 |
| CCI, TRIX | 100% match | Per-strategy UTC offset (TRIX=0) in config |
| ROC | 390/391 matched | 1 remaining |
| RSI | 214/218 matched | Trade count diff (226 gen vs 218 ref) |
| MOM | 180/183 matched | 3 exit-time mismatches (1h diff) |
| PPO | 59/87 matched | Trade count diff (83 gen vs 87 ref); signal/exit logic |
| ULTOSC | 255/290 matched | Trade count diff |

Config overrides: `reference_utc_offset_hours_by_strategy` (e.g. TRIX=0).

Optional diagnostic only (do not treat as parity pass):

```bash
python -m engine.backtest.validate_runner \
  --reference-file engine/backtest/pine_reference_list_of_trades/TRIX_Signal_Strategy_BINANCE_ETHUSDT.P_2026-02-26.csv \
  --execution-timing next_bar_open \
  --reference-utc-offset-hours 0 \
  --strategy-config engine/backtest/configs/validate_pine_parity.json \
  --time-tolerance-minutes 60 \
  --price-tolerance 2.0
```

Notes:

- `--reference-file` can be passed multiple times.
- If `--reference-file` is omitted, `--reference-dir` is used (default: `engine/backtest/pine_reference_list_of_trades`).
- `--execution-timing` supports `bar_close` (default) and `next_bar_open`.
- Run strict settings first; use relaxed tolerances only to diagnose root cause after strict fails.
- Use `--reference-utc-offset-hours` when Pine CSV timestamps are not UTC
  (example: `8` for UTC+8 exports).
- `engine/backtest/configs/validate_pine_parity.json` contains strategy overrides for all 9 strategies (BBAND, CCI, CMO, MOM, PPO, RSI, ROC, TRIX, ULTOSC) aligned to Pine defaults (`notional_amount=100`, risk toggles/thresholds).
- If you update CCI to research-aligned `hlc3` semantics (`ta.cci(hlc3, period)`), regenerate Pine CCI trade exports before using strict parity as an acceptance gate.
- Validation writes per-strategy summaries, pair-diff CSVs, and a combined summary into `reports/validation` (or `--output-dir`).
- This runner fetches historical market data from Binance for the validation window.

## Config Shape

See `engine/backtest/configs/*.json` for complete examples.
