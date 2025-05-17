from abc import ABC, abstractmethod
from engine.strategies.sma import sma

import numpy as np
import zmq

class Strategy(ABC):
    def __init__(self):
        self.sma_strategy = sma(short_window=50, long_window=200)
        self.signals = []
        # Initialize the publisher
        # self.context = zmq.Context()
        # self.socket = self.context.socket(zmq.PUB)
        # self.socket.bind("tcp://*:5555")
        # print("Publisher bound to port 5555")

    def process_data(self, market_data: dict):
        """
        Analyze data and generate trade signals.
        Returns: dict like {"BTCUSDT": "long", "ETHUSDT": "short"}
        """
        if len(market_data['price']) < self.sma_strategy.long_window:
            pass
        else:
            # Generate SMA signals
            self.signals.append(self.sma_strategy.generate_signals(market_data['price']))

            # Aggregate signals based on equal weighted average for each signals
            signal = np.mean(self.signals)
            # Publish the signals
            # self.socket.send_string(f"Signals: {signal}")
            return signal
