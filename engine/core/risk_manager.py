from abc import ABC, abstractmethod
from engine.core.order import Order

class RiskManager(ABC):
    @abstractmethod
    def validate_order(self, order: Order, aum: float) -> bool:
        """
        Return True if order is within risk limits.
        """
        pass

    @abstractmethod
    def calculate_portfolio_var(self, portfolio_data, portfolio_value: float) -> float:
        """
        Calculate the portfolio Value at Risk (VaR).
        """
        pass

    @abstractmethod
    def get_portfolio_var(self) -> float:
        """
        Return the current portfolio Value at Risk (VaR).
        """
        pass