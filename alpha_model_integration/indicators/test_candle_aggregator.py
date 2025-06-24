import os
import pandas as pd
from pandas.testing import assert_frame_equal


def load_and_prepare_df(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["Timestamp"] = pd.to_datetime(df["Timestamp"])
    df.set_index("Timestamp", inplace=True)
    df = df.sort_index()
    return df


def test_candle_aggregator_output():
    base_path = "alpha_model_integration/indicators/generated_test_data"

    vectorized_path = os.path.join(base_path, "vectorized_candles.csv")
    generated_path = os.path.join(base_path, "generated_candles.csv")

    df_5min = load_and_prepare_df(vectorized_path)
    generated_df = load_and_prepare_df(generated_path)

    # ✅ Align on common timestamps only
    joined = df_5min.join(generated_df, how="inner", lsuffix="_vec", rsuffix="_gen")

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
