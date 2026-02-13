from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
from typing import Tuple

from .data_sources import load_dataset
from .engine import GenericBacktestEngine
from .models import BacktestResult, BacktestRunnerConfig
from .reporting import export_backtest_result


def _load_class(module_name: str, class_name: str):
    module = importlib.import_module(module_name)
    if not hasattr(module, class_name):
        raise AttributeError(f"{module_name} has no class {class_name}")
    return getattr(module, class_name)


def _build_strategy(config: BacktestRunnerConfig):
    strategy_cfg_spec = config.strategy.config
    config_cls = _load_class(strategy_cfg_spec.module, strategy_cfg_spec.class_name)
    strategy_config = config_cls(**strategy_cfg_spec.params)

    strategy_cls = _load_class(config.strategy.module, config.strategy.class_name)
    strategy = strategy_cls(strategy_config)

    symbol = config.strategy.symbol or getattr(strategy_config, "instrument_id", None)
    if not symbol:
        raise ValueError(
            "Unable to resolve strategy symbol. "
            "Provide strategy.symbol in runner config or instrument_id in strategy config."
        )

    return strategy, symbol


def load_runner_config(path: str | Path) -> BacktestRunnerConfig:
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return BacktestRunnerConfig.from_dict(payload)


def run_backtest(config: BacktestRunnerConfig) -> Tuple[BacktestResult, dict]:
    dataset = load_dataset(config.data_source)
    strategy, symbol = _build_strategy(config)

    engine = GenericBacktestEngine(dataset=dataset, config=config.engine)
    result = engine.run(
        strategy=strategy,
        strategy_id=config.strategy.strategy_id,
        symbol=symbol,
    )
    output_paths = export_backtest_result(result=result, output=config.output)
    return result, output_paths


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Configurable modular strategy backtest runner"
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to JSON config (see engine/backtest/configs/*.json)",
    )
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    config = load_runner_config(args.config)
    result, output_paths = run_backtest(config)

    print("=" * 60)
    print("Backtest Complete")
    print("=" * 60)
    print(f"Strategy: {result.summary.strategy_id}")
    print(f"Symbol: {result.summary.symbol}")
    print(f"Source: {result.summary.source}")
    print(f"Interval: {result.summary.interval}")
    print(f"Bars: {result.summary.bars_processed}")
    print(f"Signals: {result.summary.total_signals}")
    print(f"Trades: {result.summary.total_trades}")
    print(f"Final equity: {result.summary.final_equity:.2f}")
    print(f"Return: {result.summary.total_return_pct:.4f}%")
    print(f"Net PnL: {result.summary.net_pnl:.2f}")
    print(f"Gross PnL: {result.summary.gross_pnl:.2f}")
    print(f"Commission: {result.summary.total_commission:.2f}")
    print(f"Win rate: {result.summary.win_rate_pct:.2f}%")
    print(f"Max drawdown: {result.summary.max_drawdown_pct:.4f}%")
    print("Output files:")
    for key, value in output_paths.items():
        print(f"  - {key}: {value}")


if __name__ == "__main__":
    main()
