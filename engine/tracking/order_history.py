"""
Order and Signal History Storage.

Thread-safe in-memory storage for order and signal history with bounded size.
"""

import threading
from collections import deque
from typing import List, Dict, Any
from datetime import datetime


class OrderHistory:
    """Thread-safe storage for order and signal history."""

    def __init__(self, max_orders: int = 50, max_signals: int = 100):
        """
        Initialize order history storage.

        Args:
            max_orders: Maximum number of orders to store
            max_signals: Maximum number of signals to store
        """
        self.orders = deque(maxlen=max_orders)
        self.signals = deque(maxlen=max_signals)
        self.lock = threading.RLock()

    def add_order(self, order_data: Dict[str, Any]) -> None:
        """
        Add order to history.

        Args:
            order_data: Dictionary containing order information
        """
        with self.lock:
            order_data["timestamp"] = datetime.now()
            self.orders.append(order_data)

    def add_signal(self, signal_data: Dict[str, Any]) -> None:
        """
        Add signal to history.

        Args:
            signal_data: Dictionary containing signal information
        """
        with self.lock:
            signal_data["timestamp"] = datetime.now()
            self.signals.append(signal_data)

    def get_recent_orders(self, count: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent orders.

        Args:
            count: Number of recent orders to retrieve

        Returns:
            List of order dictionaries (most recent first)
        """
        with self.lock:
            # Return most recent first
            return list(reversed(list(self.orders)))[:count]

    def get_recent_signals(self, count: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent signals.

        Args:
            count: Number of recent signals to retrieve

        Returns:
            List of signal dictionaries (most recent first)
        """
        with self.lock:
            # Return most recent first
            return list(reversed(list(self.signals)))[:count]

    def get_order_count(self) -> int:
        """Get total number of orders stored."""
        with self.lock:
            return len(self.orders)

    def get_signal_count(self) -> int:
        """Get total number of signals stored."""
        with self.lock:
            return len(self.signals)
