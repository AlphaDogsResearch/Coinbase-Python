"""Public interface for RiskManager to be used by other modules.

This facade exposes a stable set of methods to interact with the risk engine
without relying on internal/private helpers. Other modules (gateway, strategy,
portfolio) should depend on this interface rather than RiskManager directly.
"""

from typing import Callable, Optional, List, Dict, Any
import logging

from engine.risk.risk_manager import RiskManager
from common.interface_order import Order
from engine.position.position import Position


class RiskEngineInterface:
    """Facade wrapping RiskManager with a stable public API."""

    def __init__(self, risk_manager: Optional[RiskManager] = None):
        self._rm = risk_manager or RiskManager()

    # -----------------
    # Inbound updates (listeners)
    # -----------------
    def update_wallet_balance(self, wallet_balance: float) -> None:
        self._rm.on_wallet_balance_update(wallet_balance)

    def update_margin_ratio(self, margin_ratio: float) -> None:
        self._rm.on_margin_ratio_update(margin_ratio)

    def update_unrealised_pnl(self, unrealised_pnl: float) -> None:
        self._rm.on_unrealised_pnl_update(unrealised_pnl)

    def update_maint_margin(self, maint_margin: float) -> None:
        self._rm.on_maint_margin_update(maint_margin)

    def update_position_amount(self, symbol: str, position_amount: float) -> None:
        self._rm.on_position_amount_update(symbol, position_amount)

    def update_open_orders(self, symbol: str, count: int) -> None:
        self._rm.on_open_orders_update(symbol, count)

    def update_mark_price(self, symbol: str, price: float) -> None:
        self._rm.on_mark_price_update(symbol, price)

    # -----------------
    # Queries and actions
    # -----------------
    def validate_order(self, order: Order) -> bool:
        return self._rm.validate_order(order)

    def reset_drawdown(self) -> None:
        self._rm.reset_drawdown()

    def get_drawdown_info(self) -> Dict[str, Any]:
        return self._rm.get_drawdown_info()

    def set_aum(self, aum: float) -> None:
        self._rm.set_aum(aum)

    # -----------------
    # Access underlying RM if needed (read-only preferred)
    # -----------------
    @property
    def risk_manager(self) -> RiskManager:
        return self._rm
