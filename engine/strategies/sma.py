import numpy as np

class sma:
    """
    Simple Moving Average (SMA) strategy.
    This strategy generates buy and sell signals based on the crossover of two moving averages.
    """

    def __init__(self, short_window=50, long_window=200):
        self.short_window = short_window
        self.long_window = long_window

    def generate_signals(self, data):
        """
        Generate buy and sell signals based on the SMA crossover strategy.

        :param data: DataFrame containing the stock price data with a 'Close' column.
        :return: DataFrame with buy/sell signals.
        """
        # Take the last x rows of data to calculate Long MA
        longMA = sum(data[-self.long_window:])/self.long_window

        # Take the last y rows of data to calculate Short MA
        shortMA = sum(data[self.short_window:])/self.short_window

        # Generate 1 for buy signals and -1 for sell signals
        return np.where(shortMA > longMA, 1, -1)