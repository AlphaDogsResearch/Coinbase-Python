from engine.core.risk_manager import RiskManager
from engine.core.order import Order
from engine.risk.portfolioValueAtRisk import PortfolioValueAtRisk


class RiskManager(RiskManager):
    def __init__(self, portfolio_var: PortfolioValueAtRisk=None, max_order_value=5000):
        self.max_order_value = max_order_value
        self.portfolio_var = portfolio_var
        self.var_value = 0.0
        self.portfolio_value = 0.0

    def validate_order(self, order: Order, aum: float) -> bool:
        estimated_value = order.quantity * 1000  # assume fixed price for logic
        return estimated_value <= self.max_order_value

    def calculate_portfolio_var(self, portfolio_data, portfolio_value: float) -> float:
        """
        Calculate the portfolio Value at Risk (VaR).
        """
        self.portfolio_value = portfolio_value
        return self.portfolio_var.calculate_var(portfolio_data, portfolio_value)

    def get_portfolio_var(self) -> float:
        return self.var_value

    def get_portfolio_var_assessment(self):
        """
        Assess the portfolio Value at Risk (VaR) and return a message.
        """
        if self.var_value > 0.8 * self.portfolio_value:
            return 0
        elif self.var_value > 0.5 * self.portfolio_value:
            return 0.5
        else:
            return 1