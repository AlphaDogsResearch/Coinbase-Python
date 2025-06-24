import numpy as np


def VectorizedSMAInflectionCrossoverSignal(SignalDF):
    TradingStrategy = SignalDF
    TradingStrategy["Action"] = 0
    # TradingStrategy["Open"] = SignalDF["Open"]
    # TradingStrategy["High"] = SignalDF["High"]
    # TradingStrategy["Low"] = SignalDF["Low"]
    TradingStrategy["Close"] = SignalDF["Close"]
    TradingStrategy["SMAShortWindow"] = SignalDF["SMAShortWindow"]
    TradingStrategy["SMALongWindow"] = SignalDF["SMALongWindow"]
    TradingStrategy["SMADiff"] = (
        TradingStrategy["SMAShortWindow"] - TradingStrategy["SMALongWindow"]
    )

    # Calculate SMA first differences
    long_diff = TradingStrategy["SMALongWindow"].diff()
    TradingStrategy["LongDiff"] = long_diff.bfill()
    TradingStrategy["LongDiffSMA"] = (
        TradingStrategy["LongDiff"].rolling(window=10).mean().bfill()
    )

    # Detect inflections: sign of diff changes
    long_inflection_up = (TradingStrategy["LongDiffSMA"].shift(1) < 0) & (
        TradingStrategy["LongDiffSMA"] > 0
    )  # long SMA local minimum
    short_inflection_down = (TradingStrategy["LongDiffSMA"].shift(1) > 0) & (
        TradingStrategy["LongDiffSMA"] < 0
    )  # short SMA local maximum

    # Entry signals
    TradingStrategy["Positions"] = np.where(
        long_inflection_up, 1, np.nan
    )  # long signal
    TradingStrategy["Positions"] = np.where(
        short_inflection_down, -1, TradingStrategy["Positions"]
    )  # short signal

    # Position exit
    TradingStrategy["Positions"] = TradingStrategy["Positions"].ffill()
    TradingStrategy["Positions"] = TradingStrategy["Positions"].fillna(0)
    TradingStrategy["Action"] = TradingStrategy["Positions"].diff()
    TradingStrategy["Action"][0] = 0
    TradingStrategy["Returns"] = np.log(
        TradingStrategy["Close"] / TradingStrategy["Close"].shift(1)
    )
    TradingStrategy["Strategy"] = TradingStrategy["Returns"] * TradingStrategy[
        "Positions"
    ].shift(1)
    TradingStrategy["Returns"][0] = 0
    TradingStrategy["Strategy"][0] = 0
    log_cost = np.log(1 - 0.0001)
    TradingStrategy["Strategy_w_cost"] = TradingStrategy["Strategy"] + np.where(
        TradingStrategy["Action"] != 0, log_cost * abs(TradingStrategy["Action"]), 0
    )
    return TradingStrategy
