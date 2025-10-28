"""
Data conversion utilities for Nautilus Trader integration.

Converts between your system's data structures and Nautilus Trader's expected formats.
"""

import logging
from typing import Optional

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.core.datetime import dt_to_unix_nanos

from engine.market_data.candle import MidPriceCandle


def convert_candle_to_bar(candle: MidPriceCandle, bar_type: BarType) -> Optional[Bar]:
    """
    Convert a MidPriceCandle to a Nautilus Bar.

    Args:
        candle: Your system's MidPriceCandle
        bar_type: Nautilus BarType for this bar

    Returns:
        Nautilus Bar object, or None if candle is invalid
    """
    try:
        # Validate candle has required data
        if candle.open is None or candle.close is None:
            logging.warning("Candle missing OHLC data: %s", candle)
            return None

        # Handle inf values for high/low
        high = candle.high if candle.high != float("inf") else candle.close
        low = candle.low if candle.low != float("-inf") else candle.close

        # Ensure high >= low
        if high < low:
            high, low = low, high

        # Create Nautilus Bar
        bar = Bar(
            bar_type=bar_type,
            open=Price(candle.open, precision=2),
            high=Price(high, precision=2),
            low=Price(low, precision=2),
            close=Price(candle.close, precision=2),
            volume=Quantity(0, precision=0),  # No volume data in MidPriceCandle
            ts_event=dt_to_unix_nanos(candle.start_time),
            ts_init=dt_to_unix_nanos(candle.start_time),
        )

        return bar

    except Exception as e:  # noqa: broad-except
        logging.error("Error converting candle to bar: %s", e, exc_info=True)
        return None


def parse_bar_type(instrument_id_str: str, bar_spec: str = "1-HOUR-LAST") -> BarType:
    """
    Parse a BarType from instrument ID string and bar specification.

    Args:
        instrument_id_str: e.g., "ETHUSDT.BINANCE"
        bar_spec: e.g., "1-HOUR-LAST" or "5-MINUTE-MID"

    Returns:
        Nautilus BarType

    Example:
        >>> bar_type = parse_bar_type("ETHUSDT.BINANCE", "1-HOUR-LAST")
        >>> str(bar_type)
        'ETHUSDT.BINANCE-1-HOUR-LAST-EXTERNAL'
    """
    bar_type_str = f"{instrument_id_str}-{bar_spec}-EXTERNAL"
    return BarType.from_str(bar_type_str)


def extract_symbol_from_instrument_id(instrument_id_str: str) -> str:
    """
    Extract the symbol part from a Nautilus instrument ID.

    Args:
        instrument_id_str: e.g., "ETHUSDT.BINANCE"

    Returns:
        Symbol without venue, e.g., "ETHUSDT"
    """
    return instrument_id_str.split(".")[0] if "." in instrument_id_str else instrument_id_str


def normalize_symbol(symbol: str, add_venue: bool = True, venue: str = "BINANCE") -> str:
    """
    Normalize symbol format between your system and Nautilus.

    Args:
        symbol: Your system's symbol (e.g., "ETHUSDT")
        add_venue: Whether to add venue suffix
        venue: Venue name to add

    Returns:
        Normalized symbol, e.g., "ETHUSDT.BINANCE"
    """
    if add_venue and "." not in symbol:
        return f"{symbol}.{venue}"
    return symbol
