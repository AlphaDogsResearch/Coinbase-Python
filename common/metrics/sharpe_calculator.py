import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List

import numpy as np
import pandas as pd

from common.interface_order import Trade


class BinanceFuturesSharpeCalculator:
    def __init__(self, risk_free_rate=0.0):
        self.starting_capital = 1000
        self.risk_free_rate = risk_free_rate
        self.sharpe = 0.0
        self.trades = {}
        self.initialized= False
        self.sharpe_listener: List[Callable[[float], None]] = []
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="SHARPE")
        self.sharpe = 0.0

    def add_sharpe_listener(self, callback: Callable[[float], None]):
        """Register a callback to receive OrderBook updates"""
        self.sharpe_listener.append(callback)

    def on_sharpe_update(self,sharpe:float):
        for listener in self.sharpe_listener:
            try:
                listener(sharpe)
            except Exception as e:
                logging.error(self.name + " Listener raised an exception: %s", e)

    def init_capital(self, starting_capital: float):
        self.starting_capital = starting_capital
        self.initialized = True

    def calculate_sharpe(self, trades: list, frequency: str = 'D'):
        """
        Calculates the Sharpe ratio and its annualized version based on realized PnL from futures trades.

        Parameters:
        - trades (list): List of trade objects with attributes 'realized_pnl' and 'received_time'
        - frequency (str): Resampling frequency (e.g., 'H' for hourly, '4H' for 4-hour, 'D' for daily)

        Returns:
        - sharpe (float): Sharpe ratio at the given frequency
        - annualized_sharpe (float): Annualized Sharpe ratio
        """
        if not self.initialized:
            logging.error("Initial Capital not loaded")
            return 0.0, 0.0

        # Parse trade data
        pnl_data = []
        for trade in trades:
            pnl = float(trade.realized_pnl)
            timestamp = pd.to_datetime(trade.received_time, unit='ms')
            pnl_data.append({'timestamp': timestamp, 'realized_pnl': pnl})

        df = pd.DataFrame(pnl_data)

        if df.empty:
            logging.error("No trades found")
            return 0.0, 0.0

        # Ensure timestamp is datetime and set as index
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)

        # Group by the selected frequency (e.g., hourly, daily)
        grouped = df.groupby(pd.Grouper(freq=frequency))['realized_pnl'].sum().reset_index()

        # Calculate return for each period
        grouped['return'] = grouped['realized_pnl'] / self.starting_capital

        # Optional: filter out periods with zero return
        # grouped = grouped[grouped['return'] != 0]

        if len(grouped) < 2:
            logging.error(f"Not enough data points to calculate Sharpe ratio for frequency '{frequency}'")
            return 0.0, 0.0

        mean_return = grouped['return'].mean()
        std_return = grouped['return'].std(ddof=1)
        sharpe = mean_return / std_return if std_return != 0 else 0

        # Determine annualization factor based on frequency
        freq_map = {
            'H': 8760,  # hourly: 24 hours * 365 days
            '4H': 2190,  # 4-hour: 6 periods/day * 365
            'D': 365  # daily: 365 calendar days
            # Add more mappings if needed (e.g., 'W': 52, etc.)
        }

        periods_per_year = freq_map.get(frequency.upper(), 365)  # default to daily
        annualized_sharpe = sharpe * np.sqrt(periods_per_year)

        print(f"{frequency}-Sharpe Ratio: {round(sharpe, 4)}")
        print(f"Annualized {frequency}-Sharpe Ratio: {round(annualized_sharpe, 4)}")
        self.on_sharpe_update(sharpe)
        self.sharpe = sharpe
        return sharpe, annualized_sharpe
