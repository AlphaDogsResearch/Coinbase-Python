import os
import pandas as pd
import numpy as np
from pandas.testing import assert_series_equal
from engine.strategies.sma_crossover_inflection_strategy import (
    SMACrossoverInflectionStrategy,
)
from engine.market_data.candle import MidPriceCandle
from model_integration.strategies.vectorized.sma_inflection_strategy import (
    VectorizedSMAInflectionCrossoverSignal,
)

# Paths
INPUT_FILE = "model_integration/tests/indicators/generated_test_data/test_candle_aggregator_vectorized.csv"
OUTPUT_DIR = "model_integration/tests/strategies/generated_test_data"
OUTPUT_FILE_PREFIX = "test_sma_inflection_strategy"

VECTORIZED_FILE = f"{OUTPUT_DIR}/{OUTPUT_FILE_PREFIX}_vectorized.csv"
EVENT_FILE = f"{OUTPUT_DIR}/{OUTPUT_FILE_PREFIX}_event_driven.csv"

# Ensure output dir exists
os.makedirs(OUTPUT_DIR, exist_ok=True)


def test_sma_inflection_strategy(regenerate):
    if regenerate:
        generate_test_signals()

    df_vec = pd.read_csv(VECTORIZED_FILE)
    df_evt = pd.read_csv(EVENT_FILE)

    df_vec["Timestamp"] = pd.to_datetime(df_vec["Timestamp"])
    df_evt["Timestamp"] = pd.to_datetime(df_evt["Timestamp"])
    df_vec.set_index("Timestamp", inplace=True)
    df_evt.set_index("Timestamp", inplace=True)

    joined = df_vec.join(df_evt, how="inner", lsuffix="_vec", rsuffix="_evt")

    s_vec = joined["Signal_vec"]
    s_evt = joined["Signal_evt"]

    assert_series_equal(s_vec, s_evt, check_names=False, check_dtype=False)
    print("✅ SMA Inflection Strategy parity test passed.")


def generate_test_signals():
    df = pd.read_csv(INPUT_FILE)
    df["Timestamp"] = pd.to_datetime(df["Timestamp"])

    vectorized_df = generate_vectorized_signals(df)
    vectorized_df.to_csv(VECTORIZED_FILE, index=False)

    event_df = generate_event_driven_signals(df)
    event_df.to_csv(EVENT_FILE, index=False)

    print("✅ Test signal data regenerated.")


def generate_vectorized_signals(df: pd.DataFrame) -> pd.DataFrame:
    df["SMAShortWindow"] = df["Close"].rolling(window=5).mean().bfill()
    df["SMALongWindow"] = df["Close"].rolling(window=200).mean().bfill()
    signals = VectorizedSMAInflectionCrossoverSignal(df)

    df["Signal"] = np.where(
        signals["Action"] == 2, 1, np.where(signals["Action"] == -2, -1, np.nan)
    )
    return df[df["Signal"].notna()][["Timestamp", "Close", "Signal"]].copy()


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
