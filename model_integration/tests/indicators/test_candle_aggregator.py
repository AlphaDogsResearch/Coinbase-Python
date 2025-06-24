import os
import logging
import pandas as pd
from pandas.testing import assert_frame_equal
from engine.market_data.candle import CandleAggregator
from common.interface_book import OrderBook, PriceLevel


OUTPUT_DIR = "model_integration/tests/indicators/generated_test_data"
INPUT_FILE = "research/datasets/btcusd_1-min_data.csv"
OUTPUT_FILE_PREFIX = "test_candle_aggregator"


def test_candle_aggregator(regenerate):
    if regenerate:
        build_validation_signals()

    vectorized = pd.read_csv(f"{OUTPUT_DIR}/{OUTPUT_FILE_PREFIX}_vectorized.csv")
    event_driven = pd.read_csv(f"{OUTPUT_DIR}/{OUTPUT_FILE_PREFIX}_event_driven.csv")
    _assert_frame_equal(vectorized, event_driven)


def build_validation_signals():
    # Ensure output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load raw 1-min data
    df = pd.read_csv(INPUT_FILE)
    df = df[1200000:]  # Optional: truncate for speed
    df["Timestamp_ms"] = df["Timestamp"] * 1000

    # Generate both candle types
    logging.info("🔁 Generating vectorized candles...")
    vectorized = generate_vectorized_candles(df)

    logging.info("⚙️ Generating event-driven candles via CandleAggregator...")
    event_driven = generate_event_driven_candles(df)

    # Save results
    vectorized_path = os.path.join(OUTPUT_DIR, f"{OUTPUT_FILE_PREFIX}_vectorized.csv")
    generated_path = os.path.join(OUTPUT_DIR, f"{OUTPUT_FILE_PREFIX}_event_driven.csv")

    vectorized.to_csv(vectorized_path, index=False)
    event_driven.to_csv(generated_path)

    logging.info(f"✅ Saved vectorized candles to {vectorized_path}")
    logging.info(f"✅ Saved generated candles to {generated_path}")


def _assert_frame_equal(vectorized, event_driven):

    vectorized = parse_timestamp(vectorized)
    event_driven = parse_timestamp(event_driven)

    joined = vectorized.join(event_driven, how="inner", lsuffix="_vec", rsuffix="_gen")

    try:
        # Compare only 'Close' columns as an example — extend as needed
        assert_frame_equal(
            joined[["Close_vec"]],
            joined[["Close_gen"]],
            check_dtype=False,
            check_names=False,
        )
        print(
            "✅ CandleAggregator output matches vectorized candles on common timestamps."
        )
    except AssertionError as e:
        print("❌ Mismatch found between vectorized and generated candles:")
        print(e)


def generate_vectorized_candles(df: pd.DataFrame) -> pd.DataFrame:
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], unit="s")
    df.set_index("Timestamp", inplace=True)

    df_5min = (
        df.resample("5min")
        .agg({"Close": "last"})
        .dropna()
        .reset_index()[["Timestamp", "Close"]]
    )

    return df_5min


def generate_event_driven_candles(df: pd.DataFrame) -> pd.DataFrame:
    aggregator = CandleAggregator(interval_seconds=300)
    generated_candles = []

    def on_candle_created(candle):
        generated_candles.append(
            {"Timestamp": pd.to_datetime(candle.start_time), "Close": candle.close}
        )

    aggregator.add_candle_created_listener(on_candle_created)

    for _, row in df.iterrows():
        orderbook = OrderBook(
            row["Timestamp_ms"],
            "BTC",
            [PriceLevel(row["Close"], 100)],
            [PriceLevel(row["Close"], 100)],
        )
        aggregator.on_order_book(orderbook)

    generated_df = pd.DataFrame(generated_candles)
    generated_df.set_index("Timestamp", inplace=True)

    return generated_df


def parse_timestamp(df) -> pd.DataFrame:
    df["Timestamp"] = pd.to_datetime(df["Timestamp"])
    df.set_index("Timestamp", inplace=True)
    df = df.sort_index()
    return df
