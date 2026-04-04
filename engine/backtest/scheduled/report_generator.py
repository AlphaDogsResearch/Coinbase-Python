"""Generate reports from backtest results."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from engine.backtest.models import (
    BacktestEquityPoint,
    BacktestResult,
    BacktestTradeRecord,
    HistoricalDataset,
)

from .models import (
    BacktestReport,
    PositionState,
    SchedulePeriod,
    StrategyReport,
)

logger = logging.getLogger(__name__)


def _compute_max_drawdown_pct(equity_curve: List[BacktestEquityPoint]) -> float:
    """Compute maximum drawdown percentage from equity curve."""
    if not equity_curve:
        return 0.0

    peak = equity_curve[0].equity
    max_dd = 0.0

    for point in equity_curve:
        if point.equity > peak:
            peak = point.equity
        if peak > 0:
            drawdown = (peak - point.equity) / peak
            if drawdown > max_dd:
                max_dd = drawdown

    return max_dd * 100


class ReportGenerator:
    """Generate reports from backtest results."""

    def __init__(self, period: SchedulePeriod):
        self.period = period

    def generate_strategy_report(
        self,
        strategy_id: str,
        result: BacktestResult,
        open_position: Optional[PositionState],
        last_price: float = 0.0,
    ) -> StrategyReport:
        """Generate report for a single strategy."""
        trades = result.trades
        total_trades = len(trades)

        gross_pnl = sum(t.pnl_gross for t in trades)
        net_pnl = sum(t.pnl_net for t in trades)
        total_commission = sum(t.commission_total for t in trades)

        wins = sum(1 for t in trades if t.pnl_net > 0)
        win_rate_pct = (wins / total_trades * 100.0) if total_trades > 0 else 0.0

        max_drawdown_pct = _compute_max_drawdown_pct(result.equity_curve)

        has_open_position = (
            open_position is not None and open_position.side != "FLAT"
        )

        # Calculate unrealized P&L for open position
        unrealized_pnl = 0.0
        if has_open_position and open_position and last_price > 0:
            if open_position.side == "LONG":
                unrealized_pnl = (last_price - open_position.entry_price) * open_position.quantity
            elif open_position.side == "SHORT":
                unrealized_pnl = (open_position.entry_price - last_price) * open_position.quantity

        return StrategyReport(
            strategy_id=strategy_id,
            trades=trades,
            total_trades=total_trades,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            total_commission=total_commission,
            win_rate_pct=win_rate_pct,
            max_drawdown_pct=max_drawdown_pct,
            has_open_position=has_open_position,
            open_position=open_position,
            last_price=last_price,
            unrealized_pnl=unrealized_pnl,
        )

    def generate_aggregate_report(
        self,
        strategy_reports: List[StrategyReport],
        dataset: HistoricalDataset,
        period_start: datetime,
        period_end: datetime,
    ) -> BacktestReport:
        """Generate aggregate report from all strategy reports."""
        total_trades = sum(r.total_trades for r in strategy_reports)
        total_net_pnl = sum(r.net_pnl for r in strategy_reports)
        total_gross_pnl = sum(r.gross_pnl for r in strategy_reports)
        total_commission = sum(r.total_commission for r in strategy_reports)

        # Aggregate win rate: total wins / total trades
        total_wins = sum(
            sum(1 for t in r.trades if t.pnl_net > 0)
            for r in strategy_reports
        )
        aggregate_win_rate_pct = (
            (total_wins / total_trades * 100.0) if total_trades > 0 else 0.0
        )

        return BacktestReport(
            period=self.period,
            period_start=period_start,
            period_end=period_end,
            symbol=dataset.symbol,
            interval=dataset.interval,
            data_source=dataset.source,
            bars_processed=len(dataset.candles),
            strategy_reports=strategy_reports,
            total_trades=total_trades,
            total_net_pnl=total_net_pnl,
            total_gross_pnl=total_gross_pnl,
            total_commission=total_commission,
            aggregate_win_rate_pct=aggregate_win_rate_pct,
            generated_at=datetime.now(timezone.utc),
        )

    def compute_period_bounds(
        self, dataset: HistoricalDataset, warmup_bars: int
    ) -> Tuple[datetime, datetime]:
        """Compute the actual backtest period start/end from dataset."""
        if not dataset.candles:
            now = datetime.now(timezone.utc)
            return now, now

        # Period starts after warmup
        if warmup_bars < len(dataset.candles):
            period_start = dataset.candles[warmup_bars].start_time
        else:
            period_start = dataset.candles[0].start_time

        period_end = dataset.candles[-1].start_time

        return period_start, period_end
