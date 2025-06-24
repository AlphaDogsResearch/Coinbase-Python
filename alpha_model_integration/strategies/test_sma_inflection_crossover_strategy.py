import pandas as pd
from pandas.testing import assert_series_equal


def test_vectorized_vs_event_signals():
    # Paths to the generated signal CSVs
    vec_path = "alpha_model_integration/strategies/generated_test_data/vectorized_sma_signals.csv"
    evt_path = (
        "alpha_model_integration/strategies/generated_test_data/event_sma_signals.csv"
    )

    # Load CSVs
    df_vec = pd.read_csv(vec_path)
    df_evt = pd.read_csv(evt_path)

    # Parse timestamps and set as index
    df_vec["Timestamp"] = pd.to_datetime(df_vec["Timestamp"])
    df_evt["Timestamp"] = pd.to_datetime(df_evt["Timestamp"])
    df_vec.set_index("Timestamp", inplace=True)
    df_evt.set_index("Timestamp", inplace=True)

    # Perform inner join on common timestamps
    joined = df_vec.join(df_evt, how="inner", lsuffix="_vec", rsuffix="_evt")

    # Get signal series
    s_vec = joined["Signal_vec"]
    s_evt = joined["Signal_evt"]

    # Assert signals are equal
    assert_series_equal(s_vec, s_evt, check_names=False, check_dtype=False)
