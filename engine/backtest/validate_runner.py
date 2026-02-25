from __future__ import annotations

import argparse
import csv
import importlib
import inspect
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
    execution_timing: str
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


@dataclass
class StrategyResolver:
    strategy_key: str
    strategy_module: str
    strategy_class: str
    config_module: str
    config_class: str


@dataclass(frozen=True)
class _PreparedGeneratedTrade:
    side: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float


@dataclass(frozen=True)
class _TradeDiff:
    side_match: bool
    entry_time_diff_minutes: float
    exit_time_diff_minutes: float
    entry_price_abs_diff: float
    exit_price_abs_diff: float


def _to_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_datetime(value: str) -> datetime:
    # Pine CSV format e.g. "2023-01-02 23:00"
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M")


def _normalize_reference_trades_to_utc(
    reference_trades: List[ReferenceTrade],
    reference_utc_offset_hours: float,
) -> List[ReferenceTrade]:
    """
    Normalize naive reference timestamps into UTC-naive times.

    `reference_utc_offset_hours` is the reference CSV timezone offset from UTC.
    Example: when CSV timestamps are UTC+8, pass 8 and subtract 8 hours so they
    can be compared against generated UTC timestamps.
    """
    if reference_utc_offset_hours == 0.0:
        return reference_trades

    shift = timedelta(hours=reference_utc_offset_hours)
    normalized: List[ReferenceTrade] = []
    for trade in reference_trades:
        normalized.append(
            ReferenceTrade(
                trade_id=trade.trade_id,
                side=trade.side,
                entry_time=trade.entry_time - shift,
                exit_time=trade.exit_time - shift,
                entry_signal=trade.entry_signal,
                exit_signal=trade.exit_signal,
                entry_price=trade.entry_price,
                exit_price=trade.exit_price,
                net_pnl=trade.net_pnl,
            )
        )
    return normalized


def _parse_float(value: str) -> float:
    text = str(value).strip().replace(",", "")
    if text == "":
        return 0.0
    return float(text)


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _pascal_to_snake(value: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _class_to_default_strategy_key(class_name: str) -> str:
    base = class_name[:-8] if class_name.endswith("Strategy") else class_name
    # Preserve legacy output keys used by the original validator.
    legacy = {
        "rocmeanreversion": "roc",
        "rsisignal": "rsi",
        "temacrossover": "tema",
    }
    token = _normalize_name(base)
    if token in legacy:
        return legacy[token]

    return f"{_pascal_to_snake(base)}_strategy"


def _extract_strategy_label_from_filename(path: Path) -> str:
    name = path.name
    if "_BINANCE_" in name:
        return name.split("_BINANCE_", 1)[0]
    # Fall back to filename stem if it does not follow BINANCE naming format.
    return path.stem


def _guess_symbol_from_filename(path: Path) -> str:
    match = re.search(r"BINANCE_([A-Z0-9]+)\.P", path.name)
    if match:
        return match.group(1)
    return "ETHUSDT"


def _discover_strategy_catalog() -> Dict[str, StrategyResolver]:
    strategy_dir = Path(__file__).resolve().parents[1] / "strategies"
    catalog: Dict[str, StrategyResolver] = {}

    for file_path in sorted(strategy_dir.glob("*_strategy.py")):
        module_name = f"engine.strategies.{file_path.stem}"
        module = importlib.import_module(module_name)

        classes = [
            cls
            for _, cls in inspect.getmembers(module, inspect.isclass)
            if cls.__module__ == module_name
        ]

        strategy_classes = [
            cls
            for cls in classes
            if cls.__name__.endswith("Strategy") and cls.__name__ != "Strategy"
        ]

        config_classes = {
            cls.__name__: cls
            for cls in classes
            if cls.__name__.endswith("StrategyConfig")
        }

        for strategy_cls in strategy_classes:
            expected_cfg_name = f"{strategy_cls.__name__}Config"
            config_cls = config_classes.get(expected_cfg_name)
            if config_cls is None and len(config_classes) == 1:
                config_cls = next(iter(config_classes.values()))
            if config_cls is None:
                continue

            resolver = StrategyResolver(
                strategy_key=_class_to_default_strategy_key(strategy_cls.__name__),
                strategy_module=module_name,
                strategy_class=strategy_cls.__name__,
                config_module=module_name,
                config_class=config_cls.__name__,
            )

            aliases = {
                _normalize_name(strategy_cls.__name__),
                _normalize_name(resolver.strategy_key),
                _normalize_name(file_path.stem),
                _normalize_name(strategy_cls.__name__.replace("Strategy", "_Strategy")),
            }

            # Also match Pine filename style, e.g. TRIX_Signal_Strategy.
            if strategy_cls.__name__.endswith("Strategy"):
                pine_style = _pascal_to_snake(strategy_cls.__name__)
                aliases.add(_normalize_name(pine_style))

            for alias in aliases:
                catalog[alias] = resolver

    if not catalog:
        raise ValueError("No strategy classes discovered under engine/strategies")

    return catalog


def _resolve_refs(value: Any, root: Dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("@"):
        node: Any = root
        for part in value[1:].split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return value
        return _resolve_refs(node, root)
    if isinstance(value, dict):
        return {k: _resolve_refs(v, root) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_refs(v, root) for v in value]
    return value


def _load_strategy_param_overrides(
    config_path: Optional[str],
) -> Dict[str, Dict[str, Any]]:
    if not config_path:
        return {}

    path = Path(config_path)
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    strategy_map = payload.get("strategy_map")
    if not isinstance(strategy_map, dict):
        return {}

    overrides: Dict[str, Dict[str, Any]] = {}
    for strategy_id, strategy_entry in strategy_map.items():
        if not isinstance(strategy_entry, dict):
            continue

        strategy_class = strategy_entry.get("class") or strategy_entry.get("class_name")
        if not strategy_class:
            continue

        config_ref = strategy_entry.get("params", {}).get("config")
        config_entry: Optional[Dict[str, Any]] = None
        if isinstance(config_ref, str) and config_ref.startswith("@"):
            config_key = config_ref[1:]
            candidate = payload.get(config_key)
            if isinstance(candidate, dict):
                config_entry = candidate
        elif isinstance(config_ref, dict):
            config_entry = config_ref

        params: Dict[str, Any] = {}
        if config_entry is not None:
            raw_params = config_entry.get("params", {})
            if isinstance(raw_params, dict):
                params = _resolve_refs(raw_params, payload)

        overrides[_normalize_name(strategy_id)] = {
            "strategy_id": strategy_id,
            "params": params,
        }
        overrides[_normalize_name(strategy_class)] = {
            "strategy_id": strategy_id,
            "params": params,
        }

    return overrides


def _resolve_strategy_for_reference(
    reference_file: Path,
    catalog: Dict[str, StrategyResolver],
) -> StrategyResolver:
    label = _extract_strategy_label_from_filename(reference_file)
    key = _normalize_name(label)

    resolver = catalog.get(key)
    if resolver:
        return resolver

    # Fallback: try adding/removing "strategy" suffix noise.
    if key.endswith("strategy"):
        resolver = catalog.get(key[:-8])
        if resolver:
            return resolver

    candidates = sorted({r.strategy_class for r in catalog.values()})
    raise ValueError(
        "Unable to infer strategy for reference file "
        f"'{reference_file}'. Parsed label='{label}'. "
        f"Known strategy classes: {candidates}"
    )


def _build_strategy_payload(
    strategy: StrategyResolver,
    symbol: str,
    interval: str,
    overrides: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    bar_type = f"{symbol}-{interval}"

    override = overrides.get(_normalize_name(strategy.strategy_class))
    if not override:
        override = overrides.get(_normalize_name(strategy.strategy_key))

    strategy_id = f"validate_{strategy.strategy_key}"
    params: Dict[str, Any] = {}
    if override:
        strategy_id = str(override.get("strategy_id") or strategy_id)
        params = dict(override.get("params") or {})

    # Always align instrument/bar type with reference file being validated.
    params["instrument_id"] = symbol
    params["bar_type"] = bar_type

    return {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "module": strategy.strategy_module,
        "class": strategy.strategy_class,
        "config": {
            "module": strategy.config_module,
            "class": strategy.config_class,
            "params": params,
        },
    }


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


def _prepare_generated_trades(
    generated_trades: List[Any],
) -> List[_PreparedGeneratedTrade]:
    prepared: List[_PreparedGeneratedTrade] = []
    for trade in generated_trades:
        prepared.append(
            _PreparedGeneratedTrade(
                side=str(getattr(trade, "side", "")).upper(),
                entry_time=_to_naive_utc(trade.entry_time),
                exit_time=_to_naive_utc(trade.exit_time),
                entry_price=float(trade.entry_price),
                exit_price=float(trade.exit_price),
            )
        )
    return prepared


def _diff_trades(
    reference_trade: ReferenceTrade,
    generated_trade: _PreparedGeneratedTrade,
) -> _TradeDiff:
    return _TradeDiff(
        side_match=generated_trade.side == reference_trade.side,
        entry_time_diff_minutes=abs(
            (generated_trade.entry_time - reference_trade.entry_time).total_seconds()
        )
        / 60.0,
        exit_time_diff_minutes=abs(
            (generated_trade.exit_time - reference_trade.exit_time).total_seconds()
        )
        / 60.0,
        entry_price_abs_diff=abs(
            generated_trade.entry_price - reference_trade.entry_price
        ),
        exit_price_abs_diff=abs(
            generated_trade.exit_price - reference_trade.exit_price
        ),
    )


def _alignment_match_cost(
    diff: _TradeDiff,
    time_scale_minutes: float,
    price_scale: float,
    side_penalty: float,
) -> float:
    cost = (
        diff.entry_time_diff_minutes + diff.exit_time_diff_minutes
    ) / time_scale_minutes
    cost += (diff.entry_price_abs_diff + diff.exit_price_abs_diff) / price_scale
    if not diff.side_match:
        cost += side_penalty
    return cost


def _align_trade_indices(
    reference_trades: List[ReferenceTrade],
    generated_trades: List[_PreparedGeneratedTrade],
    time_tolerance_minutes: float,
    price_tolerance: float,
) -> List[Tuple[Optional[int], Optional[int]]]:
    # Monotonic sequence alignment (Needleman-Wunsch style):
    # diagonal = pair reference/generated trades, up/left = unmatched gap.
    n = len(reference_trades)
    m = len(generated_trades)
    cols = m + 1

    if n == 0 and m == 0:
        return []

    DIR_DIAG = 0
    DIR_UP = 1
    DIR_LEFT = 2

    # Keep costs stable even when strict tolerances are requested.
    # A relatively high gap penalty reduces "double-gap" fragmentation and keeps
    # comparisons mostly in one-to-one chronological order.
    time_scale_minutes = max(time_tolerance_minutes, 120.0)
    price_scale = max(price_tolerance, 10.0)
    side_penalty = 2.0
    gap_penalty = 20.0

    backtrack = bytearray((n + 1) * cols)
    prev = [0.0] * cols
    curr = [0.0] * cols

    for j in range(1, cols):
        prev[j] = prev[j - 1] + gap_penalty
        backtrack[j] = DIR_LEFT

    for i in range(1, n + 1):
        row_offset = i * cols
        curr[0] = prev[0] + gap_penalty
        backtrack[row_offset] = DIR_UP
        ref = reference_trades[i - 1]

        for j in range(1, cols):
            gen = generated_trades[j - 1]
            diff = _diff_trades(ref, gen)
            diag = prev[j - 1] + _alignment_match_cost(
                diff=diff,
                time_scale_minutes=time_scale_minutes,
                price_scale=price_scale,
                side_penalty=side_penalty,
            )
            up = prev[j] + gap_penalty
            left = curr[j - 1] + gap_penalty

            direction = DIR_DIAG
            best = diag
            if up < best:
                best = up
                direction = DIR_UP
            if left < best:
                best = left
                direction = DIR_LEFT

            curr[j] = best
            backtrack[row_offset + j] = direction

        prev, curr = curr, prev

    alignment: List[Tuple[Optional[int], Optional[int]]] = []
    i = n
    j = m
    while i > 0 or j > 0:
        direction = backtrack[i * cols + j]

        if i > 0 and j > 0 and direction == DIR_DIAG:
            alignment.append((i - 1, j - 1))
            i -= 1
            j -= 1
            continue

        if i > 0 and (j == 0 or direction == DIR_UP):
            alignment.append((i - 1, None))
            i -= 1
            continue

        alignment.append((None, j - 1))
        j -= 1

    alignment.reverse()
    return alignment


def _compare_trades(
    strategy_key: str,
    reference_trades: List[ReferenceTrade],
    generated_trades: List[Any],
    time_tolerance_minutes: float,
    price_tolerance: float,
    require_price_match: bool,
) -> List[TradeComparison]:
    prepared_generated = _prepare_generated_trades(generated_trades)
    aligned_indices = _align_trade_indices(
        reference_trades=reference_trades,
        generated_trades=prepared_generated,
        time_tolerance_minutes=time_tolerance_minutes,
        price_tolerance=price_tolerance,
    )

    pairs: List[TradeComparison] = []
    for idx, (ref_idx, gen_idx) in enumerate(aligned_indices):
        ref = reference_trades[ref_idx] if ref_idx is not None else None
        prepared = prepared_generated[gen_idx] if gen_idx is not None else None

        if ref is None and prepared is not None:
            pairs.append(
                TradeComparison(
                    strategy_key=strategy_key,
                    index=idx,
                    status="MISSING_REFERENCE",
                    side_reference="",
                    side_generated=prepared.side,
                    entry_time_reference="",
                    entry_time_generated=str(prepared.entry_time),
                    exit_time_reference="",
                    exit_time_generated=str(prepared.exit_time),
                    entry_time_diff_minutes=None,
                    exit_time_diff_minutes=None,
                    entry_price_reference=None,
                    entry_price_generated=prepared.entry_price,
                    exit_price_reference=None,
                    exit_price_generated=prepared.exit_price,
                    entry_price_abs_diff=None,
                    exit_price_abs_diff=None,
                    notes="Generated trade has no matching reference trade index",
                )
            )
            continue

        if prepared is None and ref is not None:
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

        if ref is None or prepared is None:
            continue

        diff = _diff_trades(ref, prepared)

        time_match = (
            diff.entry_time_diff_minutes <= time_tolerance_minutes
            and diff.exit_time_diff_minutes <= time_tolerance_minutes
        )
        price_match = (
            diff.entry_price_abs_diff <= price_tolerance
            and diff.exit_price_abs_diff <= price_tolerance
        )

        status = (
            "MATCH"
            if (
                diff.side_match
                and time_match
                and (price_match or not require_price_match)
            )
            else "MISMATCH"
        )
        notes = []
        if not diff.side_match:
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
                side_generated=prepared.side,
                entry_time_reference=str(ref.entry_time),
                entry_time_generated=str(prepared.entry_time),
                exit_time_reference=str(ref.exit_time),
                exit_time_generated=str(prepared.exit_time),
                entry_time_diff_minutes=diff.entry_time_diff_minutes,
                exit_time_diff_minutes=diff.exit_time_diff_minutes,
                entry_price_reference=ref.entry_price,
                entry_price_generated=prepared.entry_price,
                exit_price_reference=ref.exit_price,
                exit_price_generated=prepared.exit_price,
                entry_price_abs_diff=diff.entry_price_abs_diff,
                exit_price_abs_diff=diff.exit_price_abs_diff,
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
    execution_timing: str,
    reference_utc_offset_hours: float,
    time_tolerance_minutes: float,
    price_tolerance: float,
    require_price_match: bool,
    output_dir: Path,
    strategy_catalog: Dict[str, StrategyResolver],
    strategy_overrides: Dict[str, Dict[str, Any]],
) -> ValidationSummary:
    strategy = _resolve_strategy_for_reference(reference_file, strategy_catalog)
    strategy_key = strategy.strategy_key
    symbol = _guess_symbol_from_filename(reference_file)
    reference_trades, raw_ref_start, raw_ref_end = _load_reference_trades(
        reference_file
    )
    reference_trades = _normalize_reference_trades_to_utc(
        reference_trades=reference_trades,
        reference_utc_offset_hours=reference_utc_offset_hours,
    )
    ref_start = min(t.entry_time for t in reference_trades)
    ref_end = max(t.exit_time for t in reference_trades)

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
        "strategy": _build_strategy_payload(
            strategy=strategy,
            symbol=symbol,
            interval=interval,
            overrides=strategy_overrides,
        ),
        "engine": {
            "initial_capital": 100000.0,
            "commission_rate": 0.0005,
            "close_open_position_at_end": False,
            "execution_timing": execution_timing,
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
        "strategy_class": strategy.strategy_class,
        "reference_file": str(reference_file),
        "symbol": symbol,
        "interval": interval,
        "reference_start": ref_start.isoformat(sep=" "),
        "reference_end": ref_end.isoformat(sep=" "),
        "reference_start_raw": raw_ref_start.isoformat(sep=" "),
        "reference_end_raw": raw_ref_end.isoformat(sep=" "),
        "reference_utc_offset_hours": reference_utc_offset_hours,
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
        "execution_timing": execution_timing,
    }
    with summary_path.open("w", encoding="utf-8") as fh:
        json.dump(summary_payload, fh, indent=2)

    return ValidationSummary(
        strategy_key=strategy_key,
        reference_file=str(reference_file),
        symbol=symbol,
        interval=interval,
        execution_timing=execution_timing,
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
        "--execution-timing",
        default="bar_close",
        choices=["bar_close", "next_bar_open"],
        help="Order fill timing for backtest simulation.",
    )
    parser.add_argument(
        "--reference-utc-offset-hours",
        type=float,
        default=0.0,
        help="Reference CSV timezone offset from UTC (e.g. 8 for UTC+8). "
        "The validator converts reference timestamps to UTC by subtracting this offset.",
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
        "--strategy-config",
        default="engine/config/config_development.json",
        help="Optional config file used to load per-strategy parameter overrides dynamically.",
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

    strategy_catalog = _discover_strategy_catalog()
    strategy_overrides = _load_strategy_param_overrides(args.strategy_config)

    summaries: List[ValidationSummary] = []
    for reference_path in reference_paths:
        summary = _validate_one_file(
            reference_file=reference_path,
            interval=args.interval,
            warmup_bars=args.warmup_bars,
            execution_timing=args.execution_timing,
            reference_utc_offset_hours=args.reference_utc_offset_hours,
            time_tolerance_minutes=args.time_tolerance_minutes,
            price_tolerance=args.price_tolerance,
            require_price_match=args.require_price_match,
            output_dir=Path(args.output_dir),
            strategy_catalog=strategy_catalog,
            strategy_overrides=strategy_overrides,
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
        print(f"  Reference UTC offset hours: {args.reference_utc_offset_hours}")
        print(f"  Fetch window: {summary.fetch_start} -> {summary.fetch_end}")
        print(f"  Execution timing: {args.execution_timing}")
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
