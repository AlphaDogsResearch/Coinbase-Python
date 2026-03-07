#!/usr/bin/env python3
"""
Dump ULTOSC (Ultimate Oscillator) indicator values for bar-by-bar comparison with TradingView.

Use this to validate Python ULTOSC calculations against Pine Script or TradingView.
Load the same symbol/interval in TradingView, add the Ultimate Oscillator with matching
params (t1=14, t2=28, t3=36), and compare values at specific timestamps.

Usage:
  python -m engine.backtest.dump_ultosc_values \\
    --symbol ETHUSDT \\
    --interval 1h \\
    --start 2025-01-01 \\
    --end 2025-02-01 \\
    --output ultosc_values.csv

Optional: Install talib (pip install TA-Lib) for TA-Lib ULTOSC comparison column.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.backtest.data_sources import load_dataset, parse_interval_to_seconds
from engine.backtest.models import DataSourceSpec
from engine.strategies.indicators import UltimateOscillator


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dump ULTOSC values for validation against TradingView"
    )
    parser.add_argument("--symbol", default="ETHUSDT", help="Symbol (default: ETHUSDT)")
    parser.add_argument("--interval", default="1h", help="Interval (default: 1h)")
    parser.add_argument(
        "--start",
        default="2025-01-01T00:00:00",
        help="Start time ISO (default: 2025-01-01T00:00:00)",
    )
    parser.add_argument(
        "--end",
        default="2025-02-15T00:00:00",
        help="End time ISO (default: 2025-02-15T00:00:00)",
    )
    parser.add_argument(
        "--output",
        default="ultosc_values.csv",
        help="Output CSV path (default: ultosc_values.csv)",
    )
    parser.add_argument(
        "--t1",
        type=int,
        default=14,
        help="ULTOSC timeperiod1 (default: 14)",
    )
    parser.add_argument(
        "--t2",
        type=int,
        default=28,
        help="ULTOSC timeperiod2 (default: 28)",
    )
    parser.add_argument(
        "--t3",
        type=int,
        default=36,
        help="ULTOSC timeperiod3 (default: 36)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    start_dt = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)

    # Load extra warmup bars before start for ULTOSC initialization (timeperiod3)
    interval_sec = parse_interval_to_seconds(args.interval)
    warmup_seconds = args.t3 * int(interval_sec)
    fetch_start = start_dt.timestamp() - warmup_seconds
    fetch_start_dt = datetime.fromtimestamp(fetch_start, tz=timezone.utc)

    spec = DataSourceSpec(
        type="binance_futures",
        symbol=args.symbol,
        interval=args.interval,
        start_time=fetch_start_dt.isoformat(),
        end_time=end_dt.isoformat(),
    )
    dataset = load_dataset(spec)
    candles = dataset.candles

    if not candles:
        print("No candles loaded. Check symbol/interval/date range.", file=sys.stderr)
        sys.exit(1)

    # Filter to requested range for output (but run ULTOSC on full data for warmup)
    start_ts = start_dt.timestamp()
    end_ts = end_dt.timestamp()
    in_range_indices: list[int] = []
    for i, c in enumerate(candles):
        if start_ts <= c.start_time.timestamp() <= end_ts:
            in_range_indices.append(i)

    print(
        f"Loaded {len(candles)} candles (warmup + range). Output range: {len(in_range_indices)} bars",
        file=sys.stderr,
    )

    # Run our ULTOSC indicator on full dataset
    ultosc = UltimateOscillator(
        timeperiod1=args.t1,
        timeperiod2=args.t2,
        timeperiod3=args.t3,
    )

    ultosc_values: list[float | None] = []
    for candle in candles:
        ultosc.handle_bar(candle)
        ultosc_values.append(ultosc.value if ultosc.initialized else None)

    rows: list[dict] = []
    for out_i, i in enumerate(in_range_indices):
        candle = candles[i]
        close = candle.close or 0.0
        ts = candle.start_time.strftime("%Y-%m-%d %H:%M:%S")
        ultosc_val = ultosc_values[i]
        rows.append({
            "bar_index": out_i,
            "bar_index_global": i,
            "timestamp": ts,
            "close": f"{close:.2f}",
            "ultosc_python": f"{ultosc_val:.6f}" if ultosc_val is not None else "",
        })

    # Optional: TA-Lib comparison (uses full candle series)
    try:
        import numpy as np
        import talib
        highs = np.array([c.high or 0.0 for c in candles], dtype=np.float64)
        lows = np.array([c.low or 0.0 for c in candles], dtype=np.float64)
        closes = np.array([c.close or 0.0 for c in candles], dtype=np.float64)
        tult = talib.ULTOSC(highs, lows, closes, args.t1, args.t2, args.t3)
        for j, row in enumerate(rows):
            i = in_range_indices[j]
            if i < len(tult) and not (tult[i] != tult[i]):  # not nan
                row["ultosc_talib"] = f"{tult[i]:.6f}"
            else:
                row["ultosc_talib"] = ""
    except ImportError:
        for row in rows:
            row["ultosc_talib"] = ""
        print("TA-Lib not installed. Install with: pip install TA-Lib", file=sys.stderr)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["bar_index", "bar_index_global", "timestamp", "close", "ultosc_python", "ultosc_talib"]
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {out_path}", file=sys.stderr)
    with_ultosc = [r for r in rows if r.get("ultosc_python")]
    if with_ultosc:
        print("Sample (first 3 with ULTOSC):", file=sys.stderr)
        for r in with_ultosc[:3]:
            print(f"  {r}", file=sys.stderr)


if __name__ == "__main__":
    main()
