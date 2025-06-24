import os
import logging
import pandas as pd
from common.config_logging import to_stdout
from common.interface_book import OrderBook, PriceLevel
from engine.market_data.candle import CandleAggregator

OUTPUT_DIR = "alpha_model_integration/indicators/generated_test_data"
INPUT_FILE = "alpha_model_integration/test_data/btcusd_1-min_data.csv"


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


def main():
    to_stdout()
    logging.info("📊 Starting Candle Data Generation...")

    # Ensure output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load raw 1-min data
    df = pd.read_csv(INPUT_FILE)
    df = df[1200000:]  # Optional: truncate for speed
    df["Timestamp_ms"] = df["Timestamp"] * 1000

    # Generate both candle types
    logging.info("🔁 Generating vectorized candles...")
    df_5min = generate_vectorized_candles(df)

    logging.info("⚙️ Generating event-driven candles via CandleAggregator...")
    generated_df = generate_event_driven_candles(df)

    # Align lengths
    if len(generated_df) > len(df_5min):
        logging.warning("Trimming trailing incomplete candle from generated_df.")
        generated_df = generated_df.iloc[:-1]

    # Save results
    vectorized_path = os.path.join(OUTPUT_DIR, "vectorized_candles.csv")
    generated_path = os.path.join(OUTPUT_DIR, "generated_candles.csv")

    df_5min.to_csv(vectorized_path, index=False)
    generated_df.to_csv(generated_path)

    logging.info(f"✅ Saved vectorized candles to {vectorized_path}")
    logging.info(f"✅ Saved generated candles to {generated_path}")


if __name__ == "__main__":
    main()
