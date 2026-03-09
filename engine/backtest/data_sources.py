from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import pandas as pd
from binance.client import Client

from engine.market_data.candle import MidPriceCandle

from .models import DataSourceSpec, HistoricalDataset


def parse_interval_to_seconds(interval: str) -> float:
    """
    Parse interval string into seconds.

    Supported examples: 1s, 5m, 1h, 1d, ETHUSDT-1h.
    """
    if not interval:
        raise ValueError("interval must be provided")

    interval_part = interval.split("-")[-1]
    match = re.match(r"^(\d+)([smhd])$", interval_part.lower())
    if not match:
        raise ValueError(f"Unsupported interval format: {interval}")

    value = int(match.group(1))
    unit = match.group(2)
    factors = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
    }
    return float(value * factors[unit])


def _resolve_binance_window(
    days: int,
    start_time: Optional[str],
    end_time: Optional[str],
) -> Tuple[datetime, datetime]:
    if start_time and end_time:
        start_dt = datetime.fromisoformat(start_time).astimezone(timezone.utc)
        end_dt = datetime.fromisoformat(end_time).astimezone(timezone.utc)
        return start_dt, end_dt

    now_utc = datetime.now(timezone.utc)
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = today_start - timedelta(seconds=1)  # yesterday 23:59:59 UTC
    start_dt = today_start - timedelta(days=days)
    return start_dt, end_dt


def load_binance_futures_dataset(spec: DataSourceSpec) -> HistoricalDataset:
    """Load futures candles from Binance."""
    if spec.type != "binance_futures":
        raise ValueError(
            f"Expected data source type 'binance_futures', got {spec.type}"
        )

    start_dt, end_dt = _resolve_binance_window(
        days=spec.days,
        start_time=spec.start_time,
        end_time=spec.end_time,
    )
    interval_seconds = parse_interval_to_seconds(spec.interval)

    client = Client()  # public market data
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    step_ms = int(interval_seconds * 1000)

    klines = []
    cursor = start_ms
    while cursor <= end_ms:
        batch = client.futures_klines(
            symbol=spec.symbol,
            interval=spec.interval,
            startTime=cursor,
            endTime=end_ms,
            limit=1500,
        )
        if not batch:
            break

        klines.extend(batch)
        last_open_ms = int(batch[-1][0])
        next_cursor = last_open_ms + step_ms
        if next_cursor <= cursor:
            break
        cursor = next_cursor

        # If Binance returned fewer than max rows, we've likely reached the end.
        if len(batch) < 1500:
            break

    candles = []
    volumes = []
    for kline in klines:
        # [open_time, open, high, low, close, volume, ...]
        open_time = datetime.fromtimestamp(kline[0] / 1000, tz=timezone.utc)
        candle = MidPriceCandle(start_time=open_time)
        candle.open = float(kline[1])
        candle.high = float(kline[2])
        candle.low = float(kline[3])
        candle.close = float(kline[4])
        candles.append(candle)
        volumes.append(float(kline[5]))

    return HistoricalDataset(
        symbol=spec.symbol,
        interval=spec.interval,
        interval_seconds=interval_seconds,
        candles=candles,
        volumes=volumes,
        source="binance_futures",
    )


def load_csv_dataset(spec: DataSourceSpec) -> HistoricalDataset:
    """Load historical candles from CSV."""
    if spec.type != "csv":
        raise ValueError(f"Expected data source type 'csv', got {spec.type}")
    if not spec.csv_path:
        raise ValueError("csv data source requires csv_path")

    interval_seconds = parse_interval_to_seconds(spec.interval)
    df = pd.read_csv(spec.csv_path)

    if spec.timestamp_column not in df.columns:
        raise ValueError(
            f"timestamp column '{spec.timestamp_column}' not found in {spec.csv_path}"
        )

    timestamps = pd.to_datetime(df[spec.timestamp_column], utc=True, errors="coerce")
    if timestamps.isna().any():
        raise ValueError(
            f"Found invalid timestamps in column '{spec.timestamp_column}' of {spec.csv_path}"
        )

    price_mode = (
        spec.price_column is not None
        and spec.price_column in df.columns
        and not all(
            c in df.columns
            for c in [
                spec.open_column,
                spec.high_column,
                spec.low_column,
                spec.close_column,
            ]
        )
    )

    if price_mode:
        price_series = df[spec.price_column].astype(float)
        open_series = price_series
        high_series = price_series
        low_series = price_series
        close_series = price_series
    else:
        missing = [
            name
            for name in [
                spec.open_column,
                spec.high_column,
                spec.low_column,
                spec.close_column,
            ]
            if name not in df.columns
        ]
        if missing:
            raise ValueError(
                "CSV must contain OHLC columns or fallback price column. "
                f"Missing columns: {missing}"
            )
        open_series = df[spec.open_column].astype(float)
        high_series = df[spec.high_column].astype(float)
        low_series = df[spec.low_column].astype(float)
        close_series = df[spec.close_column].astype(float)

    if spec.volume_column and spec.volume_column in df.columns:
        volume_series = df[spec.volume_column].astype(float)
    else:
        volume_series = pd.Series(0.0, index=df.index)

    candles = []
    volumes = []
    for idx in range(len(df)):
        candle = MidPriceCandle(start_time=timestamps.iloc[idx].to_pydatetime())
        candle.open = float(open_series.iloc[idx])
        candle.high = float(high_series.iloc[idx])
        candle.low = float(low_series.iloc[idx])
        candle.close = float(close_series.iloc[idx])
        candles.append(candle)
        volumes.append(float(volume_series.iloc[idx]))

    return HistoricalDataset(
        symbol=spec.symbol,
        interval=spec.interval,
        interval_seconds=interval_seconds,
        candles=candles,
        volumes=volumes,
        source="csv",
    )


def load_dataset(spec: DataSourceSpec) -> HistoricalDataset:
    """Dispatch dataset loading by source type."""
    source_type = spec.type.lower()
    if source_type == "binance_futures":
        return load_binance_futures_dataset(spec)
    if source_type == "csv":
        return load_csv_dataset(spec)
    raise ValueError(f"Unsupported data source type: {spec.type}")
