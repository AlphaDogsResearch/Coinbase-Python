from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from .data_sources import load_binance_futures_dataset, load_csv_dataset
from .engine import GenericBacktestEngine
from .models import (
    BacktestEngineConfig,
    BacktestResult,
    DataSourceSpec,
    HistoricalDataset,
    OutputSpec,
)
from .reporting import export_backtest_result


@dataclass
class HistoricalBacktester:
    """Reusable historical backtester wrapper around the generic engine."""

    dataset: HistoricalDataset
    engine_config: BacktestEngineConfig = field(default_factory=BacktestEngineConfig)

    @classmethod
    def for_binance(
        cls,
        symbol: str = "ETHUSDT",
        interval: str = "1h",
        days: int = 8,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        engine_config: Optional[BacktestEngineConfig] = None,
    ) -> "HistoricalBacktester":
        dataset = load_binance_futures_dataset(
            DataSourceSpec(
                type="binance_futures",
                symbol=symbol,
                interval=interval,
                days=days,
                start_time=start_time,
                end_time=end_time,
            )
        )
        return cls(
            dataset=dataset, engine_config=engine_config or BacktestEngineConfig()
        )

    @classmethod
    def for_csv(
        cls,
        csv_path: str,
        symbol: str = "ETHUSDT",
        interval: str = "1h",
        timestamp_column: str = "timestamp",
        open_column: str = "open",
        high_column: str = "high",
        low_column: str = "low",
        close_column: str = "close",
        price_column: str = "price",
        volume_column: str = "volume",
        engine_config: Optional[BacktestEngineConfig] = None,
    ) -> "HistoricalBacktester":
        dataset = load_csv_dataset(
            DataSourceSpec(
                type="csv",
                csv_path=csv_path,
                symbol=symbol,
                interval=interval,
                timestamp_column=timestamp_column,
                open_column=open_column,
                high_column=high_column,
                low_column=low_column,
                close_column=close_column,
                price_column=price_column,
                volume_column=volume_column,
            )
        )
        return cls(
            dataset=dataset, engine_config=engine_config or BacktestEngineConfig()
        )

    def run_strategy(
        self,
        strategy,
        strategy_id: str = "historical_backtest",
        symbol: Optional[str] = None,
    ) -> BacktestResult:
        engine = GenericBacktestEngine(dataset=self.dataset, config=self.engine_config)
        return engine.run(strategy=strategy, strategy_id=strategy_id, symbol=symbol)

    def export(
        self,
        result: BacktestResult,
        output_dir: str = "reports",
        prefix: str = "historical_backtest",
    ):
        return export_backtest_result(
            result=result,
            output=OutputSpec(dir=output_dir, prefix=prefix),
        )


def main() -> None:
    """
    Default historical run example.

    Uses ROC strategy to keep parity with the previous script behavior.
    """
    from engine.strategies.roc_mean_reversion_strategy import (
        ROCMeanReversionStrategy,
        ROCMeanReversionStrategyConfig,
    )

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    backtester = HistoricalBacktester.for_binance(
        symbol="ETHUSDT",
        interval="1h",
        days=8,
        engine_config=BacktestEngineConfig(
            initial_capital=100_000.0,
            commission_rate=0.0005,
            close_open_position_at_end=True,
        ),
    )

    strategy = ROCMeanReversionStrategy(
        ROCMeanReversionStrategyConfig(
            instrument_id="ETHUSDT",
            bar_type="ETHUSDT-1h",
        )
    )

    result = backtester.run_strategy(
        strategy=strategy,
        strategy_id="roc_historical",
        symbol="ETHUSDT",
    )
    paths = backtester.export(
        result=result, output_dir="reports", prefix="roc_historical"
    )

    print("=" * 60)
    print("Historical Backtest Summary")
    print("=" * 60)
    print(f"Strategy: {result.summary.strategy_id}")
    print(f"Symbol: {result.summary.symbol}")
    print(f"Source: {result.summary.source}")
    print(f"Bars: {result.summary.bars_processed}")
    print(f"Signals: {result.summary.total_signals}")
    print(f"Trades: {result.summary.total_trades}")
    print(f"Final equity: {result.summary.final_equity:.2f}")
    print(f"Return: {result.summary.total_return_pct:.4f}%")
    print(f"Max drawdown: {result.summary.max_drawdown_pct:.4f}%")
    print(f"Output files: {paths}")


if __name__ == "__main__":
    main()
