from abc import ABC, abstractmethod

class Strategy(ABC):
    @abstractmethod
    def process_data(self, market_data: dict) -> dict:
        """
        Analyze data and generate trade signals.
        Returns: dict like {"BTCUSDT": "long", "ETHUSDT": "short"}
        """
        pass
