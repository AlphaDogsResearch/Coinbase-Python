from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict
from datetime import datetime
from typing import Dict

from .models import BacktestResult, OutputSpec


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _serialize_json(value) -> str:
    if value is None:
        return ""
    return json.dumps(value, sort_keys=True)


def export_backtest_result(
    result: BacktestResult, output: OutputSpec
) -> Dict[str, str]:
    """Export backtest artifacts to disk and return generated file paths."""
    _ensure_dir(output.dir)
    token = _stamp()
    prefix = output.prefix or "backtest"
    base = f"{prefix}_{token}"

    paths: Dict[str, str] = {}

    if output.export_signals:
        path = os.path.join(output.dir, f"{base}_signals.csv")
        with open(path, "w", newline="", encoding="utf-8") as fh:
            fieldnames = [
                "timestamp",
                "bar_index",
                "strategy_id",
                "symbol",
                "signal",
                "action",
                "reason",
                "side_before",
                "side_after",
                "price",
                "quantity",
                "notional",
                "tags",
                "indicators",
                "config",
                "candle_open",
                "candle_high",
                "candle_low",
                "candle_close",
                "volume",
            ]
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for item in result.signals:
                writer.writerow(
                    {
                        "timestamp": item.timestamp.isoformat(),
                        "bar_index": item.bar_index,
                        "strategy_id": item.strategy_id,
                        "symbol": item.symbol,
                        "signal": item.signal,
                        "action": item.action,
                        "reason": item.reason,
                        "side_before": item.side_before,
                        "side_after": item.side_after,
                        "price": item.price,
                        "quantity": item.quantity,
                        "notional": item.notional,
                        "tags": _serialize_json(item.tags),
                        "indicators": _serialize_json(item.indicators),
                        "config": _serialize_json(item.config),
                        "candle_open": item.candle_open,
                        "candle_high": item.candle_high,
                        "candle_low": item.candle_low,
                        "candle_close": item.candle_close,
                        "volume": item.volume,
                    }
                )
        paths["signals"] = path

    if output.export_trades:
        path = os.path.join(output.dir, f"{base}_trades.csv")
        with open(path, "w", newline="", encoding="utf-8") as fh:
            fieldnames = [
                "strategy_id",
                "symbol",
                "side",
                "quantity",
                "entry_time",
                "exit_time",
                "entry_price",
                "exit_price",
                "bars_held",
                "entry_reason",
                "exit_reason",
                "pnl_gross",
                "commission_total",
                "pnl_net",
            ]
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for item in result.trades:
                writer.writerow(
                    {
                        "strategy_id": item.strategy_id,
                        "symbol": item.symbol,
                        "side": item.side,
                        "quantity": item.quantity,
                        "entry_time": item.entry_time.isoformat(),
                        "exit_time": item.exit_time.isoformat(),
                        "entry_price": item.entry_price,
                        "exit_price": item.exit_price,
                        "bars_held": item.bars_held,
                        "entry_reason": item.entry_reason,
                        "exit_reason": item.exit_reason,
                        "pnl_gross": item.pnl_gross,
                        "commission_total": item.commission_total,
                        "pnl_net": item.pnl_net,
                    }
                )
        paths["trades"] = path

    if output.export_equity:
        path = os.path.join(output.dir, f"{base}_equity.csv")
        with open(path, "w", newline="", encoding="utf-8") as fh:
            fieldnames = [
                "timestamp",
                "bar_index",
                "cash",
                "unrealized_pnl",
                "equity",
                "position_side",
                "position_qty",
                "mark_price",
            ]
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for item in result.equity_curve:
                writer.writerow(
                    {
                        "timestamp": item.timestamp.isoformat(),
                        "bar_index": item.bar_index,
                        "cash": item.cash,
                        "unrealized_pnl": item.unrealized_pnl,
                        "equity": item.equity,
                        "position_side": item.position_side,
                        "position_qty": item.position_qty,
                        "mark_price": item.mark_price,
                    }
                )
        paths["equity"] = path

    if output.export_summary:
        path = os.path.join(output.dir, f"{base}_summary.json")
        payload = asdict(result.summary)
        payload["generated_at"] = datetime.now().isoformat()
        payload["dataset"] = {
            "source": result.dataset.source,
            "symbol": result.dataset.symbol,
            "interval": result.dataset.interval,
            "bars": len(result.dataset.candles),
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        paths["summary"] = path

    return paths
