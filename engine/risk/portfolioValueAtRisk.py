import numpy as np
import pandas as pd
from scipy.stats import norm


class PortfolioValueAtRisk:
    """
    Class to calculate the Value at Risk (VaR) for a portfolio.

    Attributes:
        portfolio (DataFrame): A DataFrame containing portfolio data, including returns.
        portfolioValue (float): The total value of the portfolio.
        confidenceLevel (float): The confidence level for VaR calculation (default is 0.95).
    """

    def __init__(self, portfolio, portfolio_value, confidence_level=0.95):
        """
        Initialize the PortfolioValueAtRisk class.

        Args:
            portfolio (DataFrame): A DataFrame containing 5 minutes portfolio data.
            portfolio_value (float): The total value of the portfolio.
            confidence_level (float, optional): The confidence level for VaR calculation. Defaults to 0.95.
        """
        self.portfolio = portfolio
        self.portfolioValue = portfolio_value
        self.confidenceLevel = confidence_level

    def calculate_var(self):
        """
        Calculate the Value at Risk (VaR) for the portfolio.

        Returns:
            float: The calculated VaR value for the portfolio.
        """
        returns = self.portfolio[-144:].pct_change().dropna()
        # Calculate hourly returns variance scaled by 12 (assuming 5 minutes returns) for past 1 day.
        hourly_variance = returns.var() * 12
        # Calculate the standard deviation (sigma) of hourly returns
        hourly_sigma = np.sqrt(hourly_variance)
        # Calculate the z-score for the given confidence level
        z = norm.ppf(self.confidenceLevel)

        # Calculate the hourly portfolio VaR
        hourly_portfolio_var = hourly_sigma * z * self.portfolioValue

        return hourly_portfolio_var