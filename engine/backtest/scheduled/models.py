"""Data models for scheduled backtest runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def _utcnow() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)

from engine.backtest.models import BacktestTradeRecord


class SchedulePeriod(Enum):
    """Backtest schedule period."""

    DAILY = "daily"  # 24hr backtest + 24hr warmup
    WEEKLY = "weekly"  # 7 day backtest + 24hr warmup
    MONTHLY = "monthly"  # 30 day backtest + 24hr warmup


@dataclass
class ScheduledRunnerConfig:
    """Configuration for scheduled backtest runner."""

    config_path: str = "engine/config/config_uat.json"
    period: SchedulePeriod = SchedulePeriod.DAILY
    data_source_type: str = "binance_futures"
    symbol: str = "ETHUSDT"
    interval: str = "1h"
    warmup_hours: int = 24  # Always 24hr warmup for indicators
    state_dir: str = "state/positions"
    initial_capital: float = 100_000.0
    commission_rate: float = 0.0005

    @property
    def backtest_hours(self) -> int:
        """Returns backtest window based on period."""
        return {
            SchedulePeriod.DAILY: 24,
            SchedulePeriod.WEEKLY: 24 * 7,
            SchedulePeriod.MONTHLY: 24 * 30,
        }[self.period]

    @property
    def total_hours(self) -> int:
        """Total hours needed: warmup + backtest."""
        return self.warmup_hours + self.backtest_hours


@dataclass
class PositionState:
    """Persisted position state for a strategy."""

    strategy_id: str
    symbol: str
    side: str  # "LONG", "SHORT", or "FLAT"
    quantity: float
    entry_price: float
    entry_time: datetime
    entry_bar_index: int
    entry_reason: str
    entry_commission: float
    last_updated: datetime

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for JSON."""
        return {
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "entry_time": self.entry_time.isoformat(),
            "entry_bar_index": self.entry_bar_index,
            "entry_reason": self.entry_reason,
            "entry_commission": self.entry_commission,
            "last_updated": self.last_updated.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PositionState:
        """Deserialize from dictionary."""
        return cls(
            strategy_id=data["strategy_id"],
            symbol=data["symbol"],
            side=data["side"],
            quantity=data["quantity"],
            entry_price=data["entry_price"],
            entry_time=datetime.fromisoformat(data["entry_time"]),
            entry_bar_index=data["entry_bar_index"],
            entry_reason=data["entry_reason"],
            entry_commission=data["entry_commission"],
            last_updated=datetime.fromisoformat(data["last_updated"]),
        )

    @classmethod
    def flat(cls, strategy_id: str, symbol: str) -> PositionState:
        """Create a flat (no position) state."""
        now = _utcnow()
        return cls(
            strategy_id=strategy_id,
            symbol=symbol,
            side="FLAT",
            quantity=0.0,
            entry_price=0.0,
            entry_time=now,
            entry_bar_index=0,
            entry_reason="",
            entry_commission=0.0,
            last_updated=now,
        )


@dataclass
class StrategyReport:
    """Report for a single strategy's backtest results."""

    strategy_id: str
    trades: List[BacktestTradeRecord]
    total_trades: int
    gross_pnl: float
    net_pnl: float
    total_commission: float
    win_rate_pct: float
    max_drawdown_pct: float
    has_open_position: bool
    open_position: Optional[PositionState]
    last_price: float = 0.0
    unrealized_pnl: float = 0.0


@dataclass
class BacktestReport:
    """Aggregate report for all strategies."""

    period: SchedulePeriod
    period_start: datetime
    period_end: datetime
    symbol: str
    interval: str
    data_source: str
    bars_processed: int
    strategy_reports: List[StrategyReport]
    total_trades: int
    total_net_pnl: float
    total_gross_pnl: float
    total_commission: float
    aggregate_win_rate_pct: float
    generated_at: datetime = field(default_factory=_utcnow)


@dataclass
class SMTPConfig:
    """SMTP configuration for email sending."""

    host: str
    port: int
    username: str
    password: str
    use_tls: bool = True
    from_address: str = ""
    from_name: str = "AlphaDogs Backtest"

    def __post_init__(self):
        if not self.from_address:
            self.from_address = self.username
