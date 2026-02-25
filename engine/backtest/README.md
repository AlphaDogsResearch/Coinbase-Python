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

Strict parity gate (recommended):

```bash
python -m engine.backtest.validate_runner \
  --reference-file engine/backtest/pine_reference_list_of_trades/TRIX_Signal_Strategy_BINANCE_ETHUSDT.P_2026-02-26.csv \
  --execution-timing next_bar_open \
  --strategy-config engine/backtest/configs/validate_pine_parity.json \
  --output-dir reports/validation
```

Optional diagnostic only (do not treat as parity pass):

```bash
python -m engine.backtest.validate_runner \
  --reference-file engine/backtest/pine_reference_list_of_trades/TRIX_Signal_Strategy_BINANCE_ETHUSDT.P_2026-02-26.csv \
  --execution-timing next_bar_open \
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
- `engine/backtest/configs/validate_pine_parity.json` contains TRIX overrides aligned to research/Pine defaults.
- Validation writes per-strategy summaries, pair-diff CSVs, and a combined summary into `reports/validation` (or `--output-dir`).
- This runner fetches historical market data from Binance for the validation window.

## Config Shape

See `engine/backtest/configs/*.json` for complete examples.
