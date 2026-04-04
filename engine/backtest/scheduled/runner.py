"""Main orchestrator for scheduled backtests."""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from engine.backtest.data_sources import load_dataset, parse_interval_to_seconds
from engine.backtest.engine import GenericBacktestEngine, SimulatedOrderManager
from engine.backtest.models import (
    BacktestEngineConfig,
    BacktestResult,
    DataSourceSpec,
    HistoricalDataset,
)
from engine.strategies.base import Strategy
from engine.strategies.models import Position, PositionSide

from .config_parser import ConfigParser, ParsedStrategy
from .email_composer import EmailComposer
from .email_sender import EmailSender
from .models import (
    BacktestReport,
    PositionState,
    SchedulePeriod,
    ScheduledRunnerConfig,
    SMTPConfig,
    StrategyReport,
)
from .report_generator import ReportGenerator
from .state_manager import PositionStateManager

logger = logging.getLogger(__name__)


def _inject_position_state(
    order_manager: SimulatedOrderManager,
    state: PositionState,
) -> None:
    """
    Inject position state into order manager before running backtest.

    This allows continuing from previous day's open position.
    """
    if state.side == "FLAT":
        return

    from engine.backtest.engine import _OpenPosition

    order_manager._position = _OpenPosition(
        side=PositionSide[state.side],
        quantity=state.quantity,
        entry_price=state.entry_price,
        entry_time=state.entry_time,
        entry_bar_index=0,  # Reset to 0 for new backtest
        entry_reason=state.entry_reason,
        entry_commission=state.entry_commission,
    )

    # Deduct the entry commission from cash (it was already paid)
    order_manager._cash -= state.entry_commission
    order_manager._total_commission = state.entry_commission

    # Update strategy cache with position info
    order_manager.strategy.cache.update_position(
        Position(
            instrument_id=order_manager.symbol,
            side=PositionSide[state.side],
            quantity=state.quantity,
            entry_price=state.entry_price,
        )
    )

    logger.info(
        f"Injected position state: {state.side} {state.quantity} @ {state.entry_price}"
    )


def _extract_position_state(
    order_manager: SimulatedOrderManager,
    strategy_id: str,
    symbol: str,
) -> PositionState:
    """Extract current position state from order manager after backtest."""
    position = order_manager._position

    if position is None:
        return PositionState.flat(strategy_id, symbol)

    return PositionState(
        strategy_id=strategy_id,
        symbol=symbol,
        side=position.side.value,
        quantity=position.quantity,
        entry_price=position.entry_price,
        entry_time=position.entry_time,
        entry_bar_index=position.entry_bar_index,
        entry_reason=position.entry_reason,
        entry_commission=position.entry_commission,
        last_updated=datetime.now(timezone.utc),
    )


class ScheduledBacktestRunner:
    """
    Main orchestrator for scheduled backtests.

    Runs periodic backtests on all strategies, persists position state,
    and generates reports.
    """

    def __init__(self, config: ScheduledRunnerConfig):
        self.config = config
        self.config_parser = ConfigParser(config.config_path)
        self.state_manager = PositionStateManager(config.state_dir)
        self.report_generator = ReportGenerator(config.period)

    def fetch_data(self) -> HistoricalDataset:
        """Fetch historical data for the backtest period."""
        interval_seconds = parse_interval_to_seconds(self.config.interval)
        now_utc = datetime.now(timezone.utc)

        # Align to UTC midnight for daily backtests
        # For DAILY: backtest previous day 00:00-00:00 UTC + 24hr warmup before
        # For WEEKLY/MONTHLY: similar alignment to midnight
        if self.config.period == SchedulePeriod.DAILY:
            # End at today's midnight (00:00 UTC)
            end_time = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            # Backtest period: yesterday 00:00 to today 00:00 (24 hours)
            # Warmup: day before yesterday 00:00 to yesterday 00:00 (24 hours)
            start_time = end_time - timedelta(hours=self.config.total_hours)
        elif self.config.period == SchedulePeriod.WEEKLY:
            # End at today's midnight
            end_time = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            # Go back 7 days + 24hr warmup
            start_time = end_time - timedelta(hours=self.config.total_hours)
        else:  # MONTHLY
            # End at today's midnight
            end_time = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            # Go back 30 days + 24hr warmup
            start_time = end_time - timedelta(hours=self.config.total_hours)

        spec = DataSourceSpec(
            type=self.config.data_source_type,
            symbol=self.config.symbol,
            interval=self.config.interval,
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
        )

        logger.info(
            f"Fetching data: {self.config.symbol} {self.config.interval} "
            f"from {start_time} to {end_time} ({self.config.total_hours} hours)"
        )

        dataset = load_dataset(spec)
        logger.info(f"Fetched {len(dataset.candles)} candles")

        return dataset

    def parse_strategies(self) -> List[ParsedStrategy]:
        """Parse all strategies from config."""
        self.config_parser.load()
        strategies = self.config_parser.parse()
        logger.info(f"Parsed {len(strategies)} strategies from config")
        return strategies

    def _build_strategy(self, parsed: ParsedStrategy) -> Strategy:
        """Dynamically instantiate a strategy from parsed config."""
        # Import strategy module and class
        strategy_module = importlib.import_module(parsed.module)
        strategy_class = getattr(strategy_module, parsed.class_name)

        # Import config module and class
        config_module = importlib.import_module(parsed.config_module)
        config_class = getattr(config_module, parsed.config_class)

        # Instantiate config with params
        config_instance = config_class(**parsed.config_params)

        # Instantiate strategy with config
        strategy = strategy_class(config=config_instance)

        return strategy

    def run_single_strategy(
        self,
        parsed: ParsedStrategy,
        dataset: HistoricalDataset,
        initial_state: Optional[PositionState],
    ) -> Tuple[BacktestResult, PositionState]:
        """
        Run backtest for a single strategy.

        Returns:
            Tuple of (BacktestResult, final PositionState)
        """
        logger.info(f"Running backtest for {parsed.strategy_id}")

        # Build strategy instance
        strategy = self._build_strategy(parsed)

        # Configure engine - don't close position at end
        engine_config = BacktestEngineConfig(
            initial_capital=self.config.initial_capital,
            commission_rate=self.config.commission_rate,
            close_open_position_at_end=False,  # Preserve open positions
        )

        # Create engine
        engine = GenericBacktestEngine(dataset=dataset, config=engine_config)

        # Create order manager manually to inject position
        symbol = parsed.symbol or self.config.symbol
        order_manager = SimulatedOrderManager(
            strategy=strategy,
            strategy_id=parsed.strategy_id,
            symbol=symbol,
            config=engine_config,
        )

        # Inject initial position state if exists
        if initial_state and initial_state.side != "FLAT":
            _inject_position_state(order_manager, initial_state)

        # Set up strategy
        strategy.set_order_manager(order_manager, parsed.strategy_id, symbol)

        from engine.strategies.models import Instrument

        if strategy.cache.instrument(symbol) is None:
            strategy.cache.add_instrument(Instrument(id=symbol, symbol=symbol))

        # Run backtest
        strategy.on_start()

        for i, candle in enumerate(dataset.candles):
            volume = dataset.volumes[i] if i < len(dataset.volumes) else 0.0
            next_candle = (
                dataset.candles[i + 1] if i + 1 < len(dataset.candles) else None
            )

            order_manager.set_market_context(
                bar_index=i,
                candle=candle,
                next_candle=next_candle,
                volume=volume,
                interval_seconds=dataset.interval_seconds,
            )
            order_manager.fill_pending_orders(candle)
            strategy.on_candle_created(candle)
            order_manager.mark_to_market()

        strategy.on_stop()

        # Build result
        summary = order_manager.build_summary(dataset)
        result = BacktestResult(
            dataset=dataset,
            summary=summary,
            signals=order_manager.signals,
            trades=order_manager.trades,
            equity_curve=order_manager.equity_curve,
        )

        # Extract final position state
        final_state = _extract_position_state(order_manager, parsed.strategy_id, symbol)

        logger.info(
            f"Completed {parsed.strategy_id}: "
            f"{len(result.trades)} trades, "
            f"net P&L: ${summary.net_pnl:.2f}, "
            f"position: {final_state.side}"
        )

        return result, final_state

    def run_all(self) -> BacktestReport:
        """
        Run backtest for all strategies.

        Returns:
            Aggregate BacktestReport
        """
        # Fetch data once
        dataset = self.fetch_data()

        # Parse strategies
        strategies = self.parse_strategies()

        if not strategies:
            raise ValueError("No strategies found in config")

        # Calculate warmup bars
        interval_seconds = parse_interval_to_seconds(self.config.interval)
        warmup_bars = int(self.config.warmup_hours * 3600 / interval_seconds)

        # Get last price from dataset
        last_price = 0.0
        if dataset.candles:
            last_candle = dataset.candles[-1]
            last_price = last_candle.close if last_candle.close else 0.0

        # Run each strategy
        strategy_reports: List[StrategyReport] = []

        for parsed in strategies:
            try:
                # Load initial position state
                symbol = parsed.symbol or self.config.symbol
                initial_state = self.state_manager.load(parsed.strategy_id, symbol)

                # Run backtest
                result, final_state = self.run_single_strategy(
                    parsed, dataset, initial_state
                )

                # Save final position state
                self.state_manager.save(final_state)

                # Generate strategy report
                report = self.report_generator.generate_strategy_report(
                    strategy_id=parsed.strategy_id,
                    result=result,
                    open_position=final_state if final_state.side != "FLAT" else None,
                    last_price=last_price,
                )
                strategy_reports.append(report)

            except Exception as e:
                logger.error(f"Failed to run strategy {parsed.strategy_id}: {e}")
                raise

        # Compute period bounds
        period_start, period_end = self.report_generator.compute_period_bounds(
            dataset, warmup_bars
        )

        # Generate aggregate report
        report = self.report_generator.generate_aggregate_report(
            strategy_reports=strategy_reports,
            dataset=dataset,
            period_start=period_start,
            period_end=period_end,
        )

        logger.info(
            f"Backtest complete: {report.total_trades} trades, "
            f"net P&L: ${report.total_net_pnl:.2f}"
        )

        return report


def run_scheduled_backtest(
    config: ScheduledRunnerConfig,
    smtp_config: Optional[SMTPConfig] = None,
    recipients: Optional[List[str]] = None,
    dry_run: bool = False,
) -> BacktestReport:
    """
    Run scheduled backtest and optionally send email report.

    Args:
        config: Runner configuration
        smtp_config: SMTP configuration for email (optional)
        recipients: Email recipients (optional)
        dry_run: If True, skip email sending

    Returns:
        BacktestReport
    """
    runner = ScheduledBacktestRunner(config)
    report = runner.run_all()

    # Send email if configured
    if smtp_config and recipients and not dry_run:
        composer = EmailComposer()
        sender = EmailSender(smtp_config)

        html_body = composer.compose(report)
        subject = composer.compose_subject(report)

        sender.send(recipients, subject, html_body)

    return report


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Run scheduled strategy backtests"
    )
    parser.add_argument(
        "--config",
        default="engine/config/config_uat.json",
        help="Path to strategy config file",
    )
    parser.add_argument(
        "--period",
        choices=["daily", "weekly", "monthly"],
        default="daily",
        help="Backtest period",
    )
    parser.add_argument(
        "--symbol",
        default="ETHUSDT",
        help="Trading symbol",
    )
    parser.add_argument(
        "--interval",
        default="1h",
        help="Candle interval",
    )
    parser.add_argument(
        "--data-source",
        default="binance_futures",
        help="Data source type",
    )
    parser.add_argument(
        "--state-dir",
        default="state/positions",
        help="Directory for position state files",
    )
    parser.add_argument(
        "--initial-capital",
        type=float,
        default=100000.0,
        help="Initial capital for backtest",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip email sending",
    )
    parser.add_argument(
        "--output",
        help="Output file for JSON report",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Build config
    period = SchedulePeriod(args.period)
    config = ScheduledRunnerConfig(
        config_path=args.config,
        period=period,
        data_source_type=args.data_source,
        symbol=args.symbol,
        interval=args.interval,
        state_dir=args.state_dir,
        initial_capital=args.initial_capital,
    )

    # Run backtest
    report = run_scheduled_backtest(config, dry_run=args.dry_run)

    # Output report
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        report_dict = {
            "period": report.period.value,
            "period_start": report.period_start.isoformat(),
            "period_end": report.period_end.isoformat(),
            "symbol": report.symbol,
            "interval": report.interval,
            "data_source": report.data_source,
            "bars_processed": report.bars_processed,
            "total_trades": report.total_trades,
            "total_net_pnl": report.total_net_pnl,
            "total_gross_pnl": report.total_gross_pnl,
            "total_commission": report.total_commission,
            "aggregate_win_rate_pct": report.aggregate_win_rate_pct,
            "generated_at": report.generated_at.isoformat(),
            "strategies": [
                {
                    "strategy_id": sr.strategy_id,
                    "total_trades": sr.total_trades,
                    "net_pnl": sr.net_pnl,
                    "gross_pnl": sr.gross_pnl,
                    "total_commission": sr.total_commission,
                    "win_rate_pct": sr.win_rate_pct,
                    "max_drawdown_pct": sr.max_drawdown_pct,
                    "has_open_position": sr.has_open_position,
                }
                for sr in report.strategy_reports
            ],
        }

        with open(output_path, "w") as f:
            json.dump(report_dict, f, indent=2)

        logger.info(f"Report saved to {output_path}")

    # Print summary
    print(f"\n{'='*60}")
    print(f"SCHEDULED BACKTEST REPORT - {report.period.value.upper()}")
    print(f"{'='*60}")
    print(f"Period: {report.period_start} to {report.period_end}")
    print(f"Symbol: {report.symbol} | Interval: {report.interval}")
    print(f"Bars processed: {report.bars_processed}")
    print(f"\nTotal Trades: {report.total_trades}")
    print(f"Net P&L: ${report.total_net_pnl:,.2f}")
    print(f"Gross P&L: ${report.total_gross_pnl:,.2f}")
    print(f"Total Commission: ${report.total_commission:,.2f}")
    print(f"Win Rate: {report.aggregate_win_rate_pct:.1f}%")
    print(f"\nStrategy Breakdown:")
    print(f"{'-'*60}")

    for sr in report.strategy_reports:
        pos_label = f" [{sr.open_position.side}]" if sr.has_open_position else ""
        print(
            f"  {sr.strategy_id}: "
            f"${sr.net_pnl:+,.2f} | "
            f"{sr.total_trades} trades | "
            f"{sr.win_rate_pct:.1f}% win{pos_label}"
        )

    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
