import os
import pandas as pd
import numpy as np
from engine.strategies.sma_crossover_inflection_strategy import (
    SMACrossoverInflectionStrategy,
)
from engine.market_data.candle import MidPriceCandle
from alpha_model_integration.strategies.vectorized.vectorized_sma_inflection_crossover_signal import (
    VectorizedSMAInflectionCrossoverSignal,
)  # adjust path

OUTPUT_DIR = "alpha_model_integration/strategies/generated_test_data"
INPUT_DIR = "alpha_model_integration/indicators/generated_test_data"
INPUT_FILE = f"{INPUT_DIR}/vectorized_candles.csv"


def generate_vectorized_signals(df: pd.DataFrame) -> pd.DataFrame:
    df["SMAShortWindow"] = df["Close"].rolling(window=5).mean().bfill()
    df["SMALongWindow"] = df["Close"].rolling(window=200).mean().bfill()
    signals = VectorizedSMAInflectionCrossoverSignal(df)

    df["Signal"] = np.where(
        signals["Action"] == 2, 1, np.where(signals["Action"] == -2, -1, np.nan)
    )
    # Filter and return only relevant columns where Signal is not NaN
    signal_df = df[df["Signal"].notna()][["Timestamp", "Close", "Signal"]].copy()
    return signal_df


def generate_event_driven_signals(df: pd.DataFrame) -> pd.DataFrame:
    strategy = SMACrossoverInflectionStrategy(
        short_window=5, long_window=200, smoothing_window=10
    )
    signals = []

    def listener(signal: int, price: float):
        if signal != 0:
            signals.append((current_time, price, signal))

    strategy.add_signal_listener(listener)

    for _, row in df.iterrows():
        current_time = row["Timestamp"]
        candle = MidPriceCandle(start_time=current_time)
        candle.add_tick(row["Close"])
        strategy.on_candle_created(candle)

    return pd.DataFrame(signals, columns=["Timestamp", "Close", "Signal"])


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df = pd.read_csv(INPUT_FILE)
    df["Timestamp"] = pd.to_datetime(df["Timestamp"])

    # vectorized_df = generate_vectorized_signals(df)
    # vectorized_df.to_csv(f"{OUTPUT_DIR}/vectorized_sma_signals.csv", index=False)

    event_df = generate_event_driven_signals(df)
    event_df.to_csv(f"{OUTPUT_DIR}/event_sma_signals.csv", index=False)

    print("✅ Signal data generated and saved.")


if __name__ == "__main__":
    main()
