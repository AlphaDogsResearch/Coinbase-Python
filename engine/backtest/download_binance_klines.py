#!/usr/bin/env python3
"""
Download ETHUSDT.P (Binance USD-M perpetual) OHLCV data from Binance.

Fetches historical klines as far back as the API allows (~2019-11-17) and
saves to CSV in a format compatible with load_csv_dataset.

Usage:
  python -m engine.backtest.download_binance_klines \\
    --symbol ETHUSDT \\
    --interval 1h \\
    --start 2019-11-17 \\
    --end 2026-03-09 \\
    --output data/ETHUSDT_1h.csv

Defaults:
  --start: 2019-11-17 (earliest Binance ETHUSDT perpetual data)
  --end: yesterday 23:59:59 UTC
  --interval: 1h
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.backtest.data_sources import load_dataset
from engine.backtest.models import DataSourceSpec

EARLIEST_BINANCE_ETHUSDT = "2019-11-17T00:00:00+00:00"


def _parse_args() -> argparse.Namespace:
    now_utc = datetime.now(timezone.utc)
    yesterday = (now_utc - timedelta(days=1)).strftime("%Y-%m-%d")

    parser = argparse.ArgumentParser(
        description="Download Binance futures OHLCV klines to CSV"
    )
    parser.add_argument(
        "--symbol",
        default="ETHUSDT",
        help="Symbol (default: ETHUSDT for perpetual futures)",
    )
    parser.add_argument(
        "--interval",
        default="1h",
        help="Kline interval: 1m, 5m, 15m, 1h, 1d (default: 1h)",
    )
    parser.add_argument(
        "--start",
        default=EARLIEST_BINANCE_ETHUSDT,
        help="Start time ISO or YYYY-MM-DD (default: 2019-11-17)",
    )
    parser.add_argument(
        "--end",
        default=None,
        help=f"End time ISO or YYYY-MM-DD (default: {yesterday} 23:59:59 UTC)",
    )
    parser.add_argument(
        "--output",
        default="data/ETHUSDT_1h.csv",
        help="Output CSV path (default: data/ETHUSDT_1h.csv)",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=0.5,
        help="Seconds to wait between API batches (default: 0.5, use 1.0 for 1m full history)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    start_str = args.start
    if not start_str or start_str == EARLIEST_BINANCE_ETHUSDT:
        start_str = EARLIEST_BINANCE_ETHUSDT
    elif "T" not in start_str and " " not in start_str:
        start_str = start_str + "T00:00:00+00:00"

    now_utc = datetime.now(timezone.utc)
    yesterday_end = (now_utc.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(seconds=1))
    end_str = args.end
    if not end_str:
        end_str = yesterday_end.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    elif "T" not in end_str and " " not in end_str:
        end_str = end_str + "T23:59:59+00:00"
    elif "+" not in end_str and "Z" not in end_str:
        end_str = end_str + "+00:00"

    spec = DataSourceSpec(
        type="binance_futures",
        symbol=args.symbol,
        interval=args.interval,
        start_time=start_str,
        end_time=end_str,
        rate_limit_seconds=args.rate_limit,
    )

    print(f"Fetching {args.symbol} {args.interval} from {start_str} to {end_str}...", file=sys.stderr)
    dataset = load_dataset(spec)

    if not dataset.candles:
        print("No candles returned. Check symbol, interval, and date range.", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for i, candle in enumerate(dataset.candles):
        rows.append({
            "timestamp": candle.start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "open": f"{candle.open:.8f}",
            "high": f"{candle.high:.8f}",
            "low": f"{candle.low:.8f}",
            "close": f"{candle.close:.8f}",
            "volume": f"{dataset.volumes[i]:.8f}",
        })

    fieldnames = ["timestamp", "open", "high", "low", "close", "volume"]
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(",".join(fieldnames) + "\n")
        for r in rows:
            fh.write(",".join(r[f] for f in fieldnames) + "\n")

    print(f"Wrote {len(rows)} rows to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
