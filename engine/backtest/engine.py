from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from common.interface_order import OrderSizeMode
from engine.market_data.candle import MidPriceCandle
from engine.strategies.base import Strategy
from engine.strategies.models import Instrument, Position, PositionSide
from engine.strategies.strategy_action import StrategyAction
from engine.strategies.strategy_order_mode import StrategyOrderMode

from .models import (
    BacktestEngineConfig,
    BacktestEquityPoint,
    BacktestResult,
    BacktestSignalRecord,
    BacktestSummary,
    BacktestTradeRecord,
    HistoricalDataset,
)


@dataclass
class _OpenPosition:
    side: PositionSide
    quantity: float
    entry_price: float
    entry_time: datetime
    entry_bar_index: int
    entry_reason: str
    entry_commission: float


def _safe_candle_value(value: Optional[float], fallback: float = 0.0) -> float:
    if value is None:
        return fallback
    if value == float("inf") or value == float("-inf"):
        return fallback
    return float(value)


def _compute_max_drawdown_pct(equity_curve: List[BacktestEquityPoint]) -> float:
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


class SimulatedOrderManager:
    """
    Simulated order manager for backtests.

    It supports strategy APIs:
    - on_signal(...)
    - submit_market_close(...)
    """

    def __init__(
        self,
        strategy: Strategy,
        strategy_id: str,
        symbol: str,
        config: BacktestEngineConfig,
    ):
        self.strategy = strategy
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.config = config

        self.signals: List[BacktestSignalRecord] = []
        self.trades: List[BacktestTradeRecord] = []
        self.equity_curve: List[BacktestEquityPoint] = []

        self._position: Optional[_OpenPosition] = None
        self._cash = float(config.initial_capital)
        self._total_commission = 0.0

        self._current_candle: Optional[MidPriceCandle] = None
        self._current_volume: float = 0.0
        self._current_bar_index: int = -1
        self._current_close_time: datetime = datetime.now(timezone.utc)

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def total_commission(self) -> float:
        return self._total_commission

    def set_market_context(
        self,
        bar_index: int,
        candle: MidPriceCandle,
        volume: float,
        interval_seconds: float,
    ) -> None:
        self._current_bar_index = bar_index
        self._current_candle = candle
        self._current_volume = volume
        self._current_close_time = candle.start_time + timedelta(
            seconds=interval_seconds
        )

    def _current_price(self) -> float:
        if not self._current_candle:
            return 0.0
        return _safe_candle_value(self._current_candle.close, 0.0)

    def _position_side_text(self) -> str:
        if self._position is None:
            return PositionSide.FLAT.value
        return self._position.side.value

    def _extract_reason(
        self,
        tags: Optional[List[str]],
        signal_context: Any = None,
        fallback: str = "",
    ) -> str:
        if signal_context is not None and hasattr(signal_context, "reason"):
            reason = getattr(signal_context, "reason")
            if reason:
                return str(reason)
        if tags:
            for tag in tags:
                if tag.startswith("reason="):
                    return tag.replace("reason=", "", 1)
        return fallback

    def _extract_context_dict(
        self, signal_context: Any, field_name: str
    ) -> Optional[Dict[str, Any]]:
        if signal_context is None:
            return None
        if hasattr(signal_context, field_name):
            value = getattr(signal_context, field_name)
            if isinstance(value, dict):
                return value
        if isinstance(signal_context, dict) and isinstance(
            signal_context.get(field_name), dict
        ):
            return signal_context.get(field_name)
        return None

    def _calculate_order_quantity(
        self,
        strategy_order_mode: StrategyOrderMode,
        price: float,
    ) -> float:
        mode = strategy_order_mode.get_order_mode()
        if mode == OrderSizeMode.NOTIONAL:
            if price <= 0:
                return 0.0
            return float(strategy_order_mode.notional_value) / price
        if mode == OrderSizeMode.QUANTITY:
            return float(strategy_order_mode.quantity)
        return 0.0

    def _open_position(
        self,
        side: PositionSide,
        quantity: float,
        price: float,
        reason: str,
    ) -> None:
        notional = quantity * price
        entry_commission = notional * self.config.commission_rate
        self._cash -= entry_commission
        self._total_commission += entry_commission

        self._position = _OpenPosition(
            side=side,
            quantity=quantity,
            entry_price=price,
            entry_time=self._current_close_time,
            entry_bar_index=self._current_bar_index,
            entry_reason=reason,
            entry_commission=entry_commission,
        )

        self.strategy.cache.update_position(
            Position(
                instrument_id=self.symbol,
                side=side,
                quantity=quantity,
                entry_price=price,
            )
        )

    def _close_position(
        self,
        price: float,
        reason: str,
    ) -> float:
        if self._position is None:
            return 0.0

        position = self._position
        quantity = position.quantity
        notional = quantity * price
        exit_commission = notional * self.config.commission_rate
        self._total_commission += exit_commission

        if position.side == PositionSide.LONG:
            pnl_gross = (price - position.entry_price) * quantity
        else:
            pnl_gross = (position.entry_price - price) * quantity

        self._cash += pnl_gross - exit_commission

        trade = BacktestTradeRecord(
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            side=position.side.value,
            quantity=quantity,
            entry_time=position.entry_time,
            exit_time=self._current_close_time,
            entry_price=position.entry_price,
            exit_price=price,
            bars_held=max(0, self._current_bar_index - position.entry_bar_index),
            entry_reason=position.entry_reason,
            exit_reason=reason,
            pnl_gross=pnl_gross,
            commission_total=position.entry_commission + exit_commission,
            pnl_net=pnl_gross - position.entry_commission - exit_commission,
        )
        self.trades.append(trade)

        self._position = None
        self.strategy.cache.update_position(
            Position(
                instrument_id=self.symbol,
                side=PositionSide.FLAT,
                quantity=0.0,
                entry_price=0.0,
            )
        )
        return quantity

    def _record_signal(
        self,
        signal: int,
        action: str,
        reason: str,
        price: float,
        quantity: float,
        side_before: str,
        side_after: str,
        tags: Optional[List[str]],
        signal_context: Any,
    ) -> None:
        candle_open = 0.0
        candle_high = 0.0
        candle_low = 0.0
        candle_close = 0.0
        if self._current_candle is not None:
            candle_open = _safe_candle_value(self._current_candle.open, 0.0)
            candle_high = _safe_candle_value(self._current_candle.high, candle_open)
            candle_low = _safe_candle_value(self._current_candle.low, candle_open)
            candle_close = _safe_candle_value(self._current_candle.close, candle_open)

        self.signals.append(
            BacktestSignalRecord(
                timestamp=self._current_close_time,
                bar_index=self._current_bar_index,
                strategy_id=self.strategy_id,
                symbol=self.symbol,
                signal=signal,
                action=action,
                reason=reason,
                side_before=side_before,
                side_after=side_after,
                price=price,
                quantity=quantity,
                notional=quantity * price,
                tags=list(tags or []),
                indicators=self._extract_context_dict(signal_context, "indicators"),
                config=self._extract_context_dict(signal_context, "config"),
                candle_open=candle_open,
                candle_high=candle_high,
                candle_low=candle_low,
                candle_close=candle_close,
                volume=self._current_volume,
            )
        )

    def on_signal(
        self,
        strategy_id: str,
        signal: int,
        price: float,
        symbol: str,
        strategy_actions: StrategyAction,
        strategy_order_mode: StrategyOrderMode,
        tags: Optional[List[str]] = None,
        signal_context: Any = None,
    ) -> bool:
        if strategy_id != self.strategy_id or symbol != self.symbol:
            logging.warning(
                "Backtest order manager received mismatched strategy/symbol. "
                f"expected=({self.strategy_id},{self.symbol}) got=({strategy_id},{symbol})"
            )

        if signal not in (1, -1):
            return False

        if price <= 0:
            price = self._current_price()
        if price <= 0:
            logging.error("Cannot execute signal without valid price")
            return False

        quantity = self._calculate_order_quantity(strategy_order_mode, price)
        if quantity <= 0:
            logging.error("Calculated order quantity <= 0, signal ignored")
            return False

        target_side = PositionSide.LONG if signal == 1 else PositionSide.SHORT
        reason = self._extract_reason(
            tags=tags,
            signal_context=signal_context,
            fallback="ENTRY" if signal == 1 else "SHORT_ENTRY",
        )

        side_before = self._position_side_text()
        action_label = "ENTRY"
        executed_quantity = 0.0

        if self._position is None:
            self._open_position(target_side, quantity, price, reason)
            executed_quantity = quantity
            action_label = "ENTRY"
        elif self._position.side == target_side:
            action_label = "IGNORED_SAME_SIDE"
        else:
            if strategy_actions == StrategyAction.POSITION_REVERSAL:
                self._close_position(price, f"REVERSAL_CLOSE: {reason}")
                self._open_position(target_side, quantity, price, reason)
                action_label = "REVERSAL"
                executed_quantity = quantity
            else:
                self._close_position(price, f"OPPOSITE_SIGNAL_CLOSE: {reason}")
                self._open_position(target_side, quantity, price, reason)
                action_label = "OPPOSITE_REENTRY"
                executed_quantity = quantity

        side_after = self._position_side_text()
        self._record_signal(
            signal=signal,
            action=action_label,
            reason=reason,
            price=price,
            quantity=executed_quantity,
            side_before=side_before,
            side_after=side_after,
            tags=tags,
            signal_context=signal_context,
        )
        return True

    def submit_market_close(
        self,
        strategy_id: str,
        symbol: str,
        price: float,
        tags: Optional[List[str]] = None,
    ) -> bool:
        if strategy_id != self.strategy_id or symbol != self.symbol:
            logging.warning(
                "Backtest close request received mismatched strategy/symbol. "
                f"expected=({self.strategy_id},{self.symbol}) got=({strategy_id},{symbol})"
            )

        if price <= 0:
            price = self._current_price()
        if price <= 0:
            logging.error("Cannot close without valid price")
            return False

        reason = self._extract_reason(tags=tags, signal_context=None, fallback="CLOSE")
        side_before = self._position_side_text()
        quantity = 0.0
        action_label = "CLOSE_NO_POSITION"

        if self._position is not None:
            quantity = self._close_position(price, reason)
            action_label = "CLOSE"

        side_after = self._position_side_text()
        self._record_signal(
            signal=0,
            action=action_label,
            reason=reason,
            price=price,
            quantity=quantity,
            side_before=side_before,
            side_after=side_after,
            tags=tags,
            signal_context=None,
        )
        return True

    def force_close_open_position(self, reason: str = "END_OF_BACKTEST") -> bool:
        if self._position is None:
            return True
        return self.submit_market_close(
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            price=self._current_price(),
            tags=[f"reason={reason}"],
        )

    def mark_to_market(self) -> BacktestEquityPoint:
        mark_price = self._current_price()
        unrealized_pnl = 0.0
        position_side = PositionSide.FLAT.value
        position_qty = 0.0

        if self._position is not None and mark_price > 0:
            position_side = self._position.side.value
            position_qty = self._position.quantity
            if self._position.side == PositionSide.LONG:
                unrealized_pnl = (
                    mark_price - self._position.entry_price
                ) * self._position.quantity
            else:
                unrealized_pnl = (
                    self._position.entry_price - mark_price
                ) * self._position.quantity

        equity = self._cash + unrealized_pnl
        point = BacktestEquityPoint(
            timestamp=self._current_close_time,
            bar_index=self._current_bar_index,
            cash=self._cash,
            unrealized_pnl=unrealized_pnl,
            equity=equity,
            position_side=position_side,
            position_qty=position_qty,
            mark_price=mark_price,
        )
        self.equity_curve.append(point)
        return point

    def build_summary(self, dataset: HistoricalDataset) -> BacktestSummary:
        final_equity = (
            self.equity_curve[-1].equity
            if self.equity_curve
            else float(self.config.initial_capital)
        )
        net_pnl = final_equity - self.config.initial_capital
        gross_pnl = sum(trade.pnl_gross for trade in self.trades)
        total_trades = len(self.trades)
        wins = sum(1 for trade in self.trades if trade.pnl_net > 0)
        win_rate_pct = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
        total_return_pct = (
            (final_equity / self.config.initial_capital - 1.0) * 100.0
            if self.config.initial_capital > 0
            else 0.0
        )

        return BacktestSummary(
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            source=dataset.source,
            interval=dataset.interval,
            bars_processed=len(dataset.candles),
            initial_capital=float(self.config.initial_capital),
            final_equity=final_equity,
            total_return_pct=total_return_pct,
            net_pnl=net_pnl,
            gross_pnl=gross_pnl,
            total_commission=self._total_commission,
            total_signals=len(self.signals),
            total_trades=total_trades,
            win_rate_pct=win_rate_pct,
            max_drawdown_pct=_compute_max_drawdown_pct(self.equity_curve),
        )


class GenericBacktestEngine:
    """Reusable backtest engine for any strategy implementing on_candle_created()."""

    def __init__(
        self, dataset: HistoricalDataset, config: Optional[BacktestEngineConfig] = None
    ):
        self.dataset = dataset
        self.config = config or BacktestEngineConfig()

    def run(
        self,
        strategy: Strategy,
        strategy_id: str,
        symbol: Optional[str] = None,
    ) -> BacktestResult:
        if not self.dataset.candles:
            raise ValueError("Dataset has no candles")

        symbol_to_use = symbol or self.dataset.symbol
        order_manager = SimulatedOrderManager(
            strategy=strategy,
            strategy_id=strategy_id,
            symbol=symbol_to_use,
            config=self.config,
        )

        strategy.set_order_manager(order_manager, strategy_id, symbol_to_use)

        if strategy.cache.instrument(symbol_to_use) is None:
            strategy.cache.add_instrument(
                Instrument(id=symbol_to_use, symbol=symbol_to_use)
            )

        strategy.on_start()
        for i, candle in enumerate(self.dataset.candles):
            volume = self.dataset.volumes[i] if i < len(self.dataset.volumes) else 0.0
            order_manager.set_market_context(
                bar_index=i,
                candle=candle,
                volume=volume,
                interval_seconds=self.dataset.interval_seconds,
            )
            strategy.on_candle_created(candle)
            order_manager.mark_to_market()

        if self.config.close_open_position_at_end:
            order_manager.force_close_open_position(reason="END_OF_BACKTEST")
            order_manager.mark_to_market()

        strategy.on_stop()

        summary = order_manager.build_summary(self.dataset)
        return BacktestResult(
            dataset=self.dataset,
            summary=summary,
            signals=order_manager.signals,
            trades=order_manager.trades,
            equity_curve=order_manager.equity_curve,
        )
