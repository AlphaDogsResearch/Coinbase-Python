#!/usr/bin/env python3
"""
Dump PPO indicator values for bar-by-bar comparison with TradingView.

Use this to validate Python PPO calculations against Pine Script or TradingView.
Load the same symbol/interval in TradingView, add the PPO indicator with matching
params (fast=38, slow=205, DEMA), and compare values at specific timestamps.

Usage:
  python -m engine.backtest.dump_ppo_values \\
    --symbol ETHUSDT \\
    --interval 1h \\
    --start 2025-01-01 \\
    --end 2025-02-01 \\
    --output ppo_values.csv

Optional: Install talib (pip install TA-Lib) for TA-Lib PPO comparison column.
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
from engine.market_data.candle import MidPriceCandle
from engine.strategies.indicators import PPO


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dump PPO values for validation against TradingView"
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
        default="ppo_values.csv",
        help="Output CSV path (default: ppo_values.csv)",
    )
    parser.add_argument(
        "--fast",
        type=int,
        default=38,
        help="PPO fast period (default: 38)",
    )
    parser.add_argument(
        "--slow",
        type=int,
        default=205,
        help="PPO slow period (default: 205)",
    )
    parser.add_argument(
        "--matype",
        type=int,
        default=3,
        help="MA type 0=SMA 1=EMA 2=WMA 3=DEMA (default: 3)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    start_dt = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)

    # Load extra warmup bars before start for PPO initialization (slow_period)
    interval_sec = parse_interval_to_seconds(args.interval)
    warmup_seconds = args.slow * int(interval_sec)
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

    # Filter to requested range for output (but run PPO on full data for warmup)
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

    # Run our PPO indicator on full dataset
    ppo = PPO(
        fast_period=args.fast,
        slow_period=args.slow,
        ma_type=args.matype,
    )

    ppo_values: list[float | None] = []
    for candle in candles:
        ppo.handle_bar(candle)
        ppo_values.append(ppo.value if ppo.initialized else None)

    rows: list[dict] = []
    for out_i, i in enumerate(in_range_indices):
        candle = candles[i]
        close = candle.close or 0.0
        ts = candle.start_time.strftime("%Y-%m-%d %H:%M:%S")
        ppo_val = ppo_values[i]
        rows.append({
            "bar_index": out_i,
            "bar_index_global": i,
            "timestamp": ts,
            "close": f"{close:.2f}",
            "ppo_python": f"{ppo_val:.6f}" if ppo_val is not None else "",
        })

    # Optional: TA-Lib comparison (uses full candle series)
    try:
        import numpy as np
        import talib
        closes = np.array([c.close or 0.0 for c in candles], dtype=np.float64)
        # matype: 0=SMA 1=EMA 2=WMA 3=DEMA
        tppo = talib.PPO(
            closes,
            fastperiod=args.fast,
            slowperiod=args.slow,
            matype=args.matype,
        )
        for j, row in enumerate(rows):
            i = in_range_indices[j]
            if i < len(tppo) and not (tppo[i] != tppo[i]):  # not nan
                row["ppo_talib"] = f"{tppo[i]:.6f}"
            else:
                row["ppo_talib"] = ""
    except ImportError:
        for row in rows:
            row["ppo_talib"] = ""
        print("TA-Lib not installed. Install with: pip install TA-Lib", file=sys.stderr)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["bar_index", "bar_index_global", "timestamp", "close", "ppo_python", "ppo_talib"]
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {out_path}", file=sys.stderr)
    with_ppo = [r for r in rows if r.get("ppo_python")]
    if with_ppo:
        print(f"Sample (first 3 with PPO):", file=sys.stderr)
        for r in with_ppo[:3]:
            print(f"  {r}", file=sys.stderr)


if __name__ == "__main__":
    main()
