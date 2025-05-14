from abc import ABC, abstractmethod

class MarketDataHandler(ABC):
    @abstractmethod
    def get_latest_data(self) -> dict:
        """
        Fetch and standardize market data.
        Returns: dict like {"BTCUSDT": {"price": 58000, "volume": 1000, ...}, ...}
        """
        pass
