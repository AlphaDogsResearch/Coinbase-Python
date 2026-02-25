from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from engine.market_data.candle import MidPriceCandle


@dataclass
class HistoricalDataset:
    """Historical candle dataset used by the backtest engine."""

    symbol: str
    interval: str
    interval_seconds: float
    candles: List[MidPriceCandle]
    volumes: List[float]
    source: str


@dataclass
class BacktestEngineConfig:
    """Core simulation settings."""

    initial_capital: float = 100_000.0
    commission_rate: float = 0.0005
    close_open_position_at_end: bool = True
    execution_timing: str = "bar_close"  # bar_close | next_bar_open


@dataclass
class BacktestSignalRecord:
    """One strategy signal event captured by the simulated order manager."""

    timestamp: datetime
    bar_index: int
    strategy_id: str
    symbol: str
    signal: int  # 1=BUY, -1=SELL, 0=CLOSE
    action: str
    reason: str
    side_before: str
    side_after: str
    price: float
    quantity: float
    notional: float
    tags: List[str] = field(default_factory=list)
    indicators: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None
    candle_open: float = 0.0
    candle_high: float = 0.0
    candle_low: float = 0.0
    candle_close: float = 0.0
    volume: float = 0.0


@dataclass
class BacktestTradeRecord:
    """Closed trade record."""

    strategy_id: str
    symbol: str
    side: str
    quantity: float
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    bars_held: int
    entry_reason: str
    exit_reason: str
    pnl_gross: float
    commission_total: float
    pnl_net: float


@dataclass
class BacktestEquityPoint:
    """Point-in-time equity snapshot."""

    timestamp: datetime
    bar_index: int
    cash: float
    unrealized_pnl: float
    equity: float
    position_side: str
    position_qty: float
    mark_price: float


@dataclass
class BacktestSummary:
    """Aggregated backtest summary."""

    strategy_id: str
    symbol: str
    source: str
    interval: str
    bars_processed: int
    initial_capital: float
    final_equity: float
    total_return_pct: float
    net_pnl: float
    gross_pnl: float
    total_commission: float
    total_signals: int
    total_trades: int
    win_rate_pct: float
    max_drawdown_pct: float


@dataclass
class BacktestResult:
    """Backtest output bundle."""

    dataset: HistoricalDataset
    summary: BacktestSummary
    signals: List[BacktestSignalRecord]
    trades: List[BacktestTradeRecord]
    equity_curve: List[BacktestEquityPoint]


@dataclass
class DataSourceSpec:
    """Data source configuration for the runner."""

    type: str = "binance_futures"  # binance_futures | csv
    symbol: str = "ETHUSDT"
    interval: str = "1h"
    days: int = 8
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    csv_path: Optional[str] = None
    timestamp_column: str = "timestamp"
    open_column: Optional[str] = "open"
    high_column: Optional[str] = "high"
    low_column: Optional[str] = "low"
    close_column: Optional[str] = "close"
    price_column: Optional[str] = "price"
    volume_column: Optional[str] = "volume"

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "DataSourceSpec":
        return cls(**payload)


@dataclass
class StrategyConfigSpec:
    """Strategy config class resolution settings."""

    module: str
    class_name: str
    params: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "StrategyConfigSpec":
        class_name = payload.get("class_name") or payload.get("class")
        if not class_name:
            raise ValueError("strategy.config must contain 'class' or 'class_name'")
        return cls(
            module=payload["module"],
            class_name=class_name,
            params=payload.get("params", {}),
        )


@dataclass
class StrategySpec:
    """Strategy class resolution settings."""

    module: str
    class_name: str
    config: StrategyConfigSpec
    strategy_id: str = "backtest_strategy"
    symbol: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "StrategySpec":
        class_name = payload.get("class_name") or payload.get("class")
        if not class_name:
            raise ValueError("strategy must contain 'class' or 'class_name'")
        return cls(
            module=payload["module"],
            class_name=class_name,
            config=StrategyConfigSpec.from_dict(payload["config"]),
            strategy_id=payload.get("strategy_id", "backtest_strategy"),
            symbol=payload.get("symbol"),
        )


@dataclass
class OutputSpec:
    """Output/report settings."""

    dir: str = "reports"
    prefix: str = "backtest"
    export_signals: bool = True
    export_trades: bool = True
    export_equity: bool = True
    export_summary: bool = True

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "OutputSpec":
        return cls(**payload)


@dataclass
class BacktestRunnerConfig:
    """Root config object for backtest_runner."""

    data_source: DataSourceSpec
    strategy: StrategySpec
    engine: BacktestEngineConfig = field(default_factory=BacktestEngineConfig)
    output: OutputSpec = field(default_factory=OutputSpec)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "BacktestRunnerConfig":
        engine_payload = payload.get("engine", {})
        output_payload = payload.get("output", {})
        return cls(
            data_source=DataSourceSpec.from_dict(payload["data_source"]),
            strategy=StrategySpec.from_dict(payload["strategy"]),
            engine=BacktestEngineConfig(**engine_payload),
            output=OutputSpec.from_dict(output_payload),
        )
