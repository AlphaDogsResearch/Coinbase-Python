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

Validate against Pine reference trade exports:

```bash
python -m engine.backtest.validate_runner
```

Or validate specific files:

```bash
python -m engine.backtest.validate_runner \
  --reference-file engine/backtest/pine_reference_list_of_trades/ROC_Mean_Reversion_Strategy_BINANCE_ETHUSDT.P_2026-02-13.csv \
  --reference-file engine/backtest/pine_reference_list_of_trades/RSI_Signal_Strategy_BINANCE_ETHUSDT.P_2026-02-13.csv \
  --reference-file engine/backtest/pine_reference_list_of_trades/TEMA_Crossover_Strategy_BINANCE_ETHUSDT.P_2026-02-13.csv
```
```

## Config Shape

See `engine/backtest/configs/*.json` for complete examples.
