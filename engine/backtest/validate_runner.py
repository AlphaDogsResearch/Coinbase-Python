from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .backtest_runner import run_backtest
from .data_sources import parse_interval_to_seconds
from .models import BacktestRunnerConfig


@dataclass
class ReferenceTrade:
    trade_id: int
    side: str  # LONG | SHORT
    entry_time: datetime
    exit_time: datetime
    entry_signal: str
    exit_signal: str
    entry_price: float
    exit_price: float
    net_pnl: float


@dataclass
class TradeComparison:
    strategy_key: str
    index: int
    status: str  # MATCH | MISMATCH | MISSING_REFERENCE | MISSING_GENERATED
    side_reference: str
    side_generated: str
    entry_time_reference: str
    entry_time_generated: str
    exit_time_reference: str
    exit_time_generated: str
    entry_time_diff_minutes: Optional[float]
    exit_time_diff_minutes: Optional[float]
    entry_price_reference: Optional[float]
    entry_price_generated: Optional[float]
    exit_price_reference: Optional[float]
    exit_price_generated: Optional[float]
    entry_price_abs_diff: Optional[float]
    exit_price_abs_diff: Optional[float]
    notes: str


@dataclass
class ValidationSummary:
    strategy_key: str
    reference_file: str
    symbol: str
    interval: str
    reference_start: str
    reference_end: str
    fetch_start: str
    fetch_end: str
    reference_trade_count: int
    generated_trade_count: int
    matched_count: int
    mismatched_count: int
    reference_net_pnl: float
    generated_net_pnl: float
    net_pnl_diff: float
    output_summary: str
    output_pairs: str


def _to_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_datetime(value: str) -> datetime:
    # Pine CSV format e.g. "2023-01-02 23:00"
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M")


def _parse_float(value: str) -> float:
    text = str(value).strip().replace(",", "")
    if text == "":
        return 0.0
    return float(text)


def _guess_symbol_from_filename(path: Path) -> str:
    match = re.search(r"BINANCE_([A-Z0-9]+)\.P", path.name)
    if match:
        return match.group(1)
    return "ETHUSDT"


def _strategy_key_for_file(path: Path) -> str:
    name = path.name
    if "ROC_Mean_Reversion_Strategy" in name:
        return "roc"
    if "RSI_Signal_Strategy" in name:
        return "rsi"
    if "TEMA_Crossover_Strategy" in name:
        return "tema"
    raise ValueError(f"Unable to infer strategy for reference file: {path}")


def _build_strategy_payload(
    strategy_key: str,
    symbol: str,
    interval: str,
) -> Dict[str, Any]:
    bar_type = f"{symbol}-{interval}"

    if strategy_key == "roc":
        return {
            "strategy_id": "validate_roc",
            "symbol": symbol,
            "module": "engine.strategies.roc_mean_reversion_strategy",
            "class": "ROCMeanReversionStrategy",
            "config": {
                "module": "engine.strategies.roc_mean_reversion_strategy",
                "class": "ROCMeanReversionStrategyConfig",
                "params": {
                    "instrument_id": symbol,
                    "bar_type": bar_type,
                    "roc_period": 10,
                    "roc_upper": 1.0,
                    "roc_lower": -1.0,
                    "roc_mid": 0.0,
                    "notional_amount": 100.0,
                    "stop_loss_percent": 0.5,
                    "max_holding_bars": 100,
                },
            },
        }

    if strategy_key == "rsi":
        return {
            "strategy_id": "validate_rsi",
            "symbol": symbol,
            "module": "engine.strategies.rsi_signal_strategy",
            "class": "RSISignalStrategy",
            "config": {
                "module": "engine.strategies.rsi_signal_strategy",
                "class": "RSISignalStrategyConfig",
                "params": {
                    "instrument_id": symbol,
                    "bar_type": bar_type,
                    "rsi_period": 30,
                    "rsi_upper": 65.0,
                    "rsi_lower": 33.0,
                    "rsi_mid": 45.0,
                    "signal_mode": "momentum",
                    "exit_mode": "breakout",
                    "notional_amount": 100.0,
                    "stop_loss_percent": 0.10584115511051861,
                    "take_profit_percent": 0.05,
                    "max_holding_bars": 15,
                    "cooldown_bars": 0,
                    "use_stop_loss": True,
                    "use_take_profit": False,
                    "use_max_holding": True,
                    "allow_flip": True,
                },
            },
        }

    if strategy_key == "tema":
        return {
            "strategy_id": "validate_tema",
            "symbol": symbol,
            "module": "engine.strategies.tema_crossover_strategy",
            "class": "TEMACrossoverStrategy",
            "config": {
                "module": "engine.strategies.tema_crossover_strategy",
                "class": "TEMACrossoverStrategyConfig",
                "params": {
                    "instrument_id": symbol,
                    "bar_type": bar_type,
                    "short_window": 14,
                    "long_window": 51,
                    "notional_amount": 100.0,
                    "stop_loss_percent": 0.09054410998184012,
                    "take_profit_percent": 0.05,
                    "max_holding_bars": 21,
                    "cooldown_bars": 0,
                    "use_stop_loss": True,
                    "use_take_profit": False,
                    "use_max_holding": True,
                    "allow_flip": True,
                },
            },
        }

    raise ValueError(f"Unsupported strategy key: {strategy_key}")


def _load_reference_trades(
    reference_file: Path,
) -> Tuple[List[ReferenceTrade], datetime, datetime]:
    grouped: Dict[int, Dict[str, Dict[str, str]]] = {}

    with reference_file.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            trade_id = int(row["Trade #"])
            row_type = str(row["Type"]).strip().lower()

            group = grouped.setdefault(trade_id, {})
            if row_type.startswith("entry"):
                group["entry"] = row
            elif row_type.startswith("exit"):
                group["exit"] = row

    trades: List[ReferenceTrade] = []
    for trade_id in sorted(grouped.keys()):
        group = grouped[trade_id]
        if "entry" not in group or "exit" not in group:
            continue

        entry = group["entry"]
        exit_ = group["exit"]

        # TradingView export includes the currently open position as "Exit ... / Signal=Open".
        if str(exit_.get("Signal", "")).strip().lower() == "open":
            continue

        entry_type = str(entry["Type"]).strip().lower()
        side = "LONG" if "long" in entry_type else "SHORT"

        trades.append(
            ReferenceTrade(
                trade_id=trade_id,
                side=side,
                entry_time=_parse_datetime(entry["Date and time"]),
                exit_time=_parse_datetime(exit_["Date and time"]),
                entry_signal=str(entry.get("Signal", "")).strip(),
                exit_signal=str(exit_.get("Signal", "")).strip(),
                entry_price=_parse_float(entry["Price USDT"]),
                exit_price=_parse_float(exit_["Price USDT"]),
                net_pnl=_parse_float(exit_.get("Net P&L USDT", "0")),
            )
        )

    if not trades:
        raise ValueError(f"No closed trades found in reference file: {reference_file}")

    start = min(t.entry_time for t in trades)
    end = max(t.exit_time for t in trades)
    return trades, start, end


def _compare_trades(
    strategy_key: str,
    reference_trades: List[ReferenceTrade],
    generated_trades: List[Any],
    time_tolerance_minutes: float,
    price_tolerance: float,
    require_price_match: bool,
) -> List[TradeComparison]:
    pairs: List[TradeComparison] = []
    max_len = max(len(reference_trades), len(generated_trades))

    for idx in range(max_len):
        ref = reference_trades[idx] if idx < len(reference_trades) else None
        gen = generated_trades[idx] if idx < len(generated_trades) else None

        if ref is None:
            pairs.append(
                TradeComparison(
                    strategy_key=strategy_key,
                    index=idx,
                    status="MISSING_REFERENCE",
                    side_reference="",
                    side_generated=getattr(gen, "side", ""),
                    entry_time_reference="",
                    entry_time_generated=str(_to_naive_utc(gen.entry_time)),
                    exit_time_reference="",
                    exit_time_generated=str(_to_naive_utc(gen.exit_time)),
                    entry_time_diff_minutes=None,
                    exit_time_diff_minutes=None,
                    entry_price_reference=None,
                    entry_price_generated=float(gen.entry_price),
                    exit_price_reference=None,
                    exit_price_generated=float(gen.exit_price),
                    entry_price_abs_diff=None,
                    exit_price_abs_diff=None,
                    notes="Generated trade has no matching reference trade index",
                )
            )
            continue

        if gen is None:
            pairs.append(
                TradeComparison(
                    strategy_key=strategy_key,
                    index=idx,
                    status="MISSING_GENERATED",
                    side_reference=ref.side,
                    side_generated="",
                    entry_time_reference=str(ref.entry_time),
                    entry_time_generated="",
                    exit_time_reference=str(ref.exit_time),
                    exit_time_generated="",
                    entry_time_diff_minutes=None,
                    exit_time_diff_minutes=None,
                    entry_price_reference=ref.entry_price,
                    entry_price_generated=None,
                    exit_price_reference=ref.exit_price,
                    exit_price_generated=None,
                    entry_price_abs_diff=None,
                    exit_price_abs_diff=None,
                    notes="Reference trade has no matching generated trade index",
                )
            )
            continue

        gen_entry = _to_naive_utc(gen.entry_time)
        gen_exit = _to_naive_utc(gen.exit_time)

        entry_time_diff = abs((gen_entry - ref.entry_time).total_seconds()) / 60.0
        exit_time_diff = abs((gen_exit - ref.exit_time).total_seconds()) / 60.0
        entry_price_diff = abs(float(gen.entry_price) - ref.entry_price)
        exit_price_diff = abs(float(gen.exit_price) - ref.exit_price)
        side_match = str(gen.side).upper() == ref.side
        time_match = (
            entry_time_diff <= time_tolerance_minutes
            and exit_time_diff <= time_tolerance_minutes
        )
        price_match = (
            entry_price_diff <= price_tolerance and exit_price_diff <= price_tolerance
        )

        status = (
            "MATCH"
            if (side_match and time_match and (price_match or not require_price_match))
            else "MISMATCH"
        )
        notes = []
        if not side_match:
            notes.append("side mismatch")
        if not time_match:
            notes.append("time mismatch")
        if not price_match:
            notes.append("price mismatch")

        pairs.append(
            TradeComparison(
                strategy_key=strategy_key,
                index=idx,
                status=status,
                side_reference=ref.side,
                side_generated=str(gen.side).upper(),
                entry_time_reference=str(ref.entry_time),
                entry_time_generated=str(gen_entry),
                exit_time_reference=str(ref.exit_time),
                exit_time_generated=str(gen_exit),
                entry_time_diff_minutes=entry_time_diff,
                exit_time_diff_minutes=exit_time_diff,
                entry_price_reference=ref.entry_price,
                entry_price_generated=float(gen.entry_price),
                exit_price_reference=ref.exit_price,
                exit_price_generated=float(gen.exit_price),
                entry_price_abs_diff=entry_price_diff,
                exit_price_abs_diff=exit_price_diff,
                notes=", ".join(notes),
            )
        )

    return pairs


def _write_pairs_csv(path: Path, pairs: List[TradeComparison]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = (
        list(asdict(pairs[0]).keys())
        if pairs
        else list(
            asdict(
                TradeComparison(
                    strategy_key="",
                    index=0,
                    status="",
                    side_reference="",
                    side_generated="",
                    entry_time_reference="",
                    entry_time_generated="",
                    exit_time_reference="",
                    exit_time_generated="",
                    entry_time_diff_minutes=None,
                    exit_time_diff_minutes=None,
                    entry_price_reference=None,
                    entry_price_generated=None,
                    exit_price_reference=None,
                    exit_price_generated=None,
                    entry_price_abs_diff=None,
                    exit_price_abs_diff=None,
                    notes="",
                )
            ).keys()
        )
    )

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for pair in pairs:
            writer.writerow(asdict(pair))


def _validate_one_file(
    reference_file: Path,
    interval: str,
    warmup_bars: int,
    time_tolerance_minutes: float,
    price_tolerance: float,
    require_price_match: bool,
    output_dir: Path,
) -> ValidationSummary:
    strategy_key = _strategy_key_for_file(reference_file)
    symbol = _guess_symbol_from_filename(reference_file)
    reference_trades, ref_start, ref_end = _load_reference_trades(reference_file)

    interval_seconds = parse_interval_to_seconds(interval)
    fetch_start = ref_start - timedelta(seconds=warmup_bars * interval_seconds)
    # Keep some headroom to ensure the end bar is included.
    fetch_end = ref_end + timedelta(seconds=2 * interval_seconds)

    fetch_start_aware = fetch_start.replace(tzinfo=timezone.utc)
    fetch_end_aware = fetch_end.replace(tzinfo=timezone.utc)

    payload: Dict[str, Any] = {
        "data_source": {
            "type": "binance_futures",
            "symbol": symbol,
            "interval": interval,
            "start_time": fetch_start_aware.isoformat(),
            "end_time": fetch_end_aware.isoformat(),
        },
        "strategy": _build_strategy_payload(strategy_key, symbol, interval),
        "engine": {
            "initial_capital": 100000.0,
            "commission_rate": 0.0005,
            "close_open_position_at_end": False,
        },
        "output": {
            "dir": str(output_dir),
            "prefix": f"validate_{strategy_key}",
            "export_signals": False,
            "export_trades": False,
            "export_equity": False,
            "export_summary": False,
        },
    }

    config = BacktestRunnerConfig.from_dict(payload)
    result, _ = run_backtest(config)

    generated_filtered = [
        trade
        for trade in result.trades
        if (
            ref_start <= _to_naive_utc(trade.entry_time) <= ref_end
            and ref_start <= _to_naive_utc(trade.exit_time) <= ref_end
        )
    ]
    generated_filtered.sort(
        key=lambda t: (_to_naive_utc(t.entry_time), _to_naive_utc(t.exit_time))
    )

    pairs = _compare_trades(
        strategy_key=strategy_key,
        reference_trades=reference_trades,
        generated_trades=generated_filtered,
        time_tolerance_minutes=time_tolerance_minutes,
        price_tolerance=price_tolerance,
        require_price_match=require_price_match,
    )

    matched_count = sum(1 for pair in pairs if pair.status == "MATCH")
    mismatched_count = len(pairs) - matched_count
    reference_net_pnl = sum(t.net_pnl for t in reference_trades)
    generated_net_pnl = sum(t.pnl_net for t in generated_filtered)

    output_dir.mkdir(parents=True, exist_ok=True)
    token = datetime.now().strftime("%Y%m%d_%H%M%S")
    pairs_path = output_dir / f"validation_{strategy_key}_{token}_pairs.csv"
    summary_path = output_dir / f"validation_{strategy_key}_{token}_summary.json"

    _write_pairs_csv(pairs_path, pairs)
    summary_payload = {
        "strategy_key": strategy_key,
        "reference_file": str(reference_file),
        "symbol": symbol,
        "interval": interval,
        "reference_start": ref_start.isoformat(sep=" "),
        "reference_end": ref_end.isoformat(sep=" "),
        "fetch_start": fetch_start_aware.isoformat(),
        "fetch_end": fetch_end_aware.isoformat(),
        "reference_trade_count": len(reference_trades),
        "generated_trade_count": len(generated_filtered),
        "matched_count": matched_count,
        "mismatched_count": mismatched_count,
        "reference_net_pnl": reference_net_pnl,
        "generated_net_pnl": generated_net_pnl,
        "net_pnl_diff": generated_net_pnl - reference_net_pnl,
        "time_tolerance_minutes": time_tolerance_minutes,
        "price_tolerance": price_tolerance,
        "require_price_match": require_price_match,
    }
    with summary_path.open("w", encoding="utf-8") as fh:
        json.dump(summary_payload, fh, indent=2)

    return ValidationSummary(
        strategy_key=strategy_key,
        reference_file=str(reference_file),
        symbol=symbol,
        interval=interval,
        reference_start=ref_start.isoformat(sep=" "),
        reference_end=ref_end.isoformat(sep=" "),
        fetch_start=fetch_start_aware.isoformat(),
        fetch_end=fetch_end_aware.isoformat(),
        reference_trade_count=len(reference_trades),
        generated_trade_count=len(generated_filtered),
        matched_count=matched_count,
        mismatched_count=mismatched_count,
        reference_net_pnl=reference_net_pnl,
        generated_net_pnl=generated_net_pnl,
        net_pnl_diff=generated_net_pnl - reference_net_pnl,
        output_summary=str(summary_path),
        output_pairs=str(pairs_path),
    )


def _collect_reference_files(
    reference_files: List[str], reference_dir: Optional[str]
) -> List[Path]:
    paths: List[Path] = []
    if reference_files:
        paths.extend(Path(p) for p in reference_files)
    elif reference_dir:
        paths.extend(sorted(Path(reference_dir).glob("*.csv")))
    else:
        default_dir = Path("engine/backtest/pine_reference_list_of_trades")
        paths.extend(sorted(default_dir.glob("*.csv")))

    if not paths:
        raise ValueError("No reference files found")
    return paths


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate Python backtest trades against Pine reference trade exports"
    )
    parser.add_argument(
        "--reference-file",
        action="append",
        default=[],
        help="Reference CSV file path. Can be passed multiple times.",
    )
    parser.add_argument(
        "--reference-dir",
        default="engine/backtest/pine_reference_list_of_trades",
        help="Directory containing reference CSV files (used when --reference-file is not provided).",
    )
    parser.add_argument("--interval", default="1h", help="Backtest interval, e.g. 1h")
    parser.add_argument(
        "--warmup-bars",
        type=int,
        default=300,
        help="Warmup bars fetched before first reference trade timestamp.",
    )
    parser.add_argument(
        "--time-tolerance-minutes",
        type=float,
        default=0.0,
        help="Allowed absolute entry/exit time diff for MATCH.",
    )
    parser.add_argument(
        "--price-tolerance",
        type=float,
        default=0.05,
        help="Allowed absolute entry/exit price diff for MATCH.",
    )
    parser.add_argument(
        "--require-price-match",
        action="store_true",
        help="When set, price mismatch also marks a trade as MISMATCH. "
        "Default behavior only requires side + time alignment.",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/validation",
        help="Directory for validation artifacts.",
    )
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    reference_paths = _collect_reference_files(
        reference_files=args.reference_file,
        reference_dir=args.reference_dir,
    )

    summaries: List[ValidationSummary] = []
    for reference_path in reference_paths:
        summary = _validate_one_file(
            reference_file=reference_path,
            interval=args.interval,
            warmup_bars=args.warmup_bars,
            time_tolerance_minutes=args.time_tolerance_minutes,
            price_tolerance=args.price_tolerance,
            require_price_match=args.require_price_match,
            output_dir=Path(args.output_dir),
        )
        summaries.append(summary)

    combined_path = Path(args.output_dir) / (
        f"validation_combined_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    combined_path.parent.mkdir(parents=True, exist_ok=True)
    with combined_path.open("w", encoding="utf-8") as fh:
        json.dump([asdict(summary) for summary in summaries], fh, indent=2)

    print("=" * 80)
    print("Validation Complete")
    print("=" * 80)
    for summary in summaries:
        print(f"Strategy: {summary.strategy_key}")
        print(f"  Reference: {summary.reference_file}")
        print(f"  Date window: {summary.reference_start} -> {summary.reference_end}")
        print(f"  Fetch window: {summary.fetch_start} -> {summary.fetch_end}")
        print(
            "  Trades: "
            f"reference={summary.reference_trade_count}, "
            f"generated={summary.generated_trade_count}, "
            f"matched={summary.matched_count}, "
            f"mismatched={summary.mismatched_count}"
        )
        print(
            f"  Net PnL: reference={summary.reference_net_pnl:.4f}, "
            f"generated={summary.generated_net_pnl:.4f}, diff={summary.net_pnl_diff:.4f}"
        )
        print(f"  Summary file: {summary.output_summary}")
        print(f"  Pair diff file: {summary.output_pairs}")
    print(f"Combined summary: {combined_path}")


if __name__ == "__main__":
    main()
