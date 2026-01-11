import logging
import threading
from typing import Optional, Callable, List, Tuple
import numpy as np

from common import config_risk
from common.interface_order import Order, Side
from engine.position.position import Position


class RiskManager:
    """
    Risk engine with:
    - Pre-order sanity checks
    - Portfolio-level drawdown gate (lifetime until reset)
    AUM are fed via gateway listeners (wallet balance updates).
    """

    def __init__(
            self,
            max_order_value: Optional[float] = None,
            max_position_value: Optional[float] = None,
            max_leverage: Optional[float] = None,
            max_open_orders: Optional[int] = None,
            min_order_size: Optional[float] = None,
            position: Optional[Position] = None,
            max_drawdown: Optional[float] = 0.10,
    ):
        # Global limits
        self.max_order_value = (
            config_risk.MAX_ORDER_VALUE_DEFAULT if max_order_value is None else max_order_value
        )
        self.max_position_value = (
            config_risk.MAX_POSITION_VALUE_DEFAULT if max_position_value is None else max_position_value
        )
        self.max_leverage = (
            config_risk.MAX_LEVERAGE_DEFAULT if max_leverage is None else max_leverage
        )
        self.max_open_orders = (
            config_risk.MAX_OPEN_ORDERS_DEFAULT if max_open_orders is None else max_open_orders
        )
        self.min_order_size = (
            config_risk.MIN_ORDER_SIZE_DEFAULT if min_order_size is None else min_order_size
        )

        # Backward-compat single-position path
        self.position = position

        # Inbound state caches (for independent operation via listeners)
        self.account_wallet_balance = 0.0
        self.account_margin_balance = 0.0
        self.account_maint_margin = 0.0
        self.account_unrealised_pnl = 0.0
        self.account_margin_ratio: Optional[float] = None
        self._position_amounts = {}
        self._open_orders_count = {}
        self._latest_prices = {}

        # Global portfolio/AUM
        self.aum = 0.0  # Should be set via wallet balance listener
        self.initial_aum = 0.0  # first AUM observed from gateway

        # Trading block state and publisher hook
        self.trading_blocked = False
        self.block_reason: Optional[str] = None
        self._block_publisher: Optional[Callable[[dict], None]] = None

        # Lifetime drawdown tracking
        self.max_drawdown = max_drawdown if max_drawdown is not None else 0.10
        self._peak_aum = None  # type: Optional[float]
        self._current_drawdown_ratio = 0.0

    def set_aum(self, aum: float):
        logging.info(f"Updating AUM to {aum}")
        # Record the first observed AUM as initial_aum
        if not self.initial_aum:
            self.initial_aum = aum
        self.aum = aum
        self.update_drawdown(aum)

    # If previously blocked due to drawdown, keep blocked until reset
    def _get_position_and_open_orders(self, symbol: str) -> Tuple[float, int]:
        """Resolve position amount and open orders for a symbol using Position if present, otherwise cached listeners."""
        pos = self.positions.get(symbol)
        if not pos and self.position and getattr(self.position, 'symbol', None) == symbol:
            pos = self.position
        position_amt = 0.0
        open_orders = 0
        if pos:
            position_amt = getattr(pos, 'position_amount', 0.0)
            get_open = getattr(pos, 'get_open_orders', None)
            if callable(get_open):
                try:
                    open_orders = int(get_open())
                except Exception:
                    open_orders = 0
        else:
            position_amt = float(self._position_amounts.get(symbol, 0.0))
            open_orders = int(self._open_orders_count.get(symbol, 0))
        return position_amt, open_orders

    # ------------------------
    # Inbound listeners (account/position/price)
    # ------------------------
    def on_wallet_balance_update(self, wallet_balance: float):
        """Listener to receive wallet balance; updates AUM and cache."""
        logging.info(f"On Wallet Balance Update {wallet_balance}")
        try:
            self.account_wallet_balance = float(wallet_balance)
        except Exception:
            logging.error("Failed to get wallet balance", exc_info=True)
            self.account_wallet_balance = wallet_balance
        self.set_aum(self.account_wallet_balance)

    def on_margin_ratio_update(self, margin_ratio: float):
        self.account_margin_ratio = margin_ratio

    def on_unrealised_pnl_update(self, unrealised_pnl: float):
        try:
            self.account_unrealised_pnl = float(unrealised_pnl)
        except Exception:
            self.account_unrealised_pnl = unrealised_pnl

    def on_maint_margin_update(self, maint_margin: float):
        try:
            self.account_maint_margin = float(maint_margin)
        except Exception:
            self.account_maint_margin = maint_margin

    def on_position_amount_update(self, symbol: str, position_amount: float):
        try:
            self._position_amounts[symbol] = float(position_amount)
        except Exception:
            self._position_amounts[symbol] = position_amount

    def on_open_orders_update(self, symbol: str, count: int):
        try:
            self._open_orders_count[symbol] = int(count)
        except Exception:
            self._open_orders_count[symbol] = count

    def on_mark_price_update(self, symbol: str, price: float):
        try:
            self._latest_prices[symbol] = float(price)
        except Exception:
            self._latest_prices[symbol] = price

    # ------------------------
    # Block publication and queries
    # ------------------------
    def set_block_publisher(self, publisher: Callable[[dict], None]):
        """Register a callable to publish trading block events (e.g., via pub/sub)."""
        self._block_publisher = publisher

    def is_trading_blocked(self) -> bool:
        return self.trading_blocked

    def _publish_block_event(self):
        if self._block_publisher:
            payload = {
                "blocked": True,
                "reason": self.block_reason,
                "aum": self.aum,
                "peak_aum": self._peak_aum,
                "drawdown_ratio": self._current_drawdown_ratio
            }
            try:
                self._block_publisher(payload)
            except Exception:
                logging.debug("Failed to publish trading block event", exc_info=True)

    # ------------------------
    # Pre-order basic checks
    # ------------------------
    def validate_preorder(self, order: Order) -> bool:
        symbol = getattr(order, 'symbol', None)
        if not symbol:
            logging.warning("Preorder rejected: missing symbol")
            return False
        qty = float(abs(order.leaves_qty)) if getattr(order, 'leaves_qty', None) is not None else 0.0
        if qty <= 0:
            logging.warning("Preorder rejected: non-positive quantity")
            return False
        # Per-symbol min order size
        min_size = self.min_order_size
        if getattr(self, '_symbol_min_order_size', None) is not None:
            min_size = getattr(self, '_symbol_min_order_size').get(symbol, self.min_order_size)
        if abs(qty) < min_size:
            logging.warning(f"Preorder rejected: quantity {qty} below minimum {min_size}")
            return False
        return True

    # ------------------------
    # Full order validation
    # ------------------------
    def validate_order(self, order: Order) -> bool:
        # Pre-order checks
        if not self.validate_preorder(order):
            return False

        # If previously blocked, short-circuit reject and publish once
        if self.trading_blocked:
            logging.warning("Order rejected: trading is blocked by risk manager")
            self._publish_block_event()
            return False

        # Portfolio-level drawdown gate
        if self._peak_aum and self._peak_aum > 0 and self._current_drawdown_ratio > self.max_drawdown:
            self.trading_blocked = True
            self.block_reason = (
                f"drawdown {self._current_drawdown_ratio * 100:.2f}% exceeds max {self.max_drawdown * 100:.2f}%"
            )
            logging.warning(
                f"Order rejected: {self.block_reason} (peak={self._peak_aum}, aum={self.aum})."
            )
            self._publish_block_event()
            return False

        return True

    # ------------------------
    # Drawdown controls
    # ------------------------
    def reset_drawdown(self):
        self._peak_aum = self.aum
        self._current_drawdown_ratio = 0.0
        logging.info("RiskManager: drawdown reset; peak AUM set to current AUM")
        # Reset block state only if block was due to drawdown
        if self.trading_blocked and self.block_reason and "drawdown" in self.block_reason:
            self.trading_blocked = False
            self.block_reason = None

    def get_drawdown_info(self):
        return {
            'aum': self.aum,
            'peak_aum': self._peak_aum,
            'drawdown_ratio': self._current_drawdown_ratio,
            'limit': self.max_drawdown,
            'exceeded': self._current_drawdown_ratio > self.max_drawdown if self._peak_aum else False,
            'initial_aum': self.initial_aum,
            'blocked': self.trading_blocked,
            'reason': self.block_reason,
        }
    
    def update_drawdown(self, aum: float):    
        # Update peak and drawdown
        if self._peak_aum is None or aum > self._peak_aum:
            self._peak_aum = aum
            self._current_drawdown_ratio = 0.0
        elif self._peak_aum > aum and self._peak_aum > 0:
            dd = (self._peak_aum - aum) / self._peak_aum
            self._current_drawdown_ratio = max(self._current_drawdown_ratio, dd)
        logging.info(f"Current peak_aum:{self._peak_aum}, current_drawdown_ratio {self._current_drawdown_ratio}")

    # ------------------------
    # VaR matrices (historical and portfolio)
    # ------------------------
    def _historical_var_matrix(self):
        historical_var = [
            [-0.029, -0.048, 0.030, 0.045, -0.038, -0.058, 0.037, 0.053, -0.057, -0.058, 0.054, 0.053, -0.324, 0.305],
            [-0.052, -0.082, 0.053, 0.076, -0.065, -0.098, 0.064, 0.088, -0.096, -0.098, 0.089, 0.088, -0.473, 0.266],
            [-0.071, -0.114, 0.076, 0.106, -0.090, -0.137, 0.090, 0.122, -0.135, -0.137, 0.123, 0.122, -0.690, 0.362],
            [-0.094, -0.147, 0.100, 0.138, -0.118, -0.174, 0.120, 0.157, -0.175, -0.174, 0.157, 0.157, -0.741, 0.423],
            [-0.134, -0.210, 0.145, 0.196, -0.169, -0.250, 0.171, 0.222, -0.250, -0.250, 0.222, 0.222, -0.784, 0.455],
        ]
        return np.array(historical_var)

    def _portfolio_var_percent_matrix(self):
        historical_var = self._historical_var_matrix()
        max_var_matrix = np.full((historical_var.shape[0], historical_var.shape[1]), -0.1)
        return max_var_matrix

    def get_portfolio_var_matrices(self):
        max_var_matrix = self._max_var_matrix()
        historical_var = self._historical_var_matrix()
        iaum = self.initial_aum if self.initial_aum and self.initial_aum > 0 else 0
        max_var_amount = np.multiply(max_var_matrix, iaum)
        max_portfolio_trade_value = np.divide(max_var_amount, historical_var)
        return max_portfolio_trade_value