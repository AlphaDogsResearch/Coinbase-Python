import logging
from typing import Optional, Dict
from engine.core.order import Order


class RiskManager:
   
    def __init__(
        self,
        max_order_value: float = 1000.0,
        max_position_value: float = 20000.0,
        max_leverage: float = 5.0,
        max_open_orders: int = 20,
        max_loss_per_day: float = 0.05,  # 5% of AUM
        max_var_ratio: float = 0.10,     # 10% of AUM
        allowed_symbols: Optional[list] = None,
        min_order_size: float = 0.001,
        compliance_blacklist: Optional[list] = None,
    ):
        self.max_order_value = max_order_value
        self.max_position_value = max_position_value
        self.max_leverage = max_leverage
        self.max_open_orders = max_open_orders
        self.max_loss_per_day = max_loss_per_day
        self.max_var_ratio = max_var_ratio
        self.allowed_symbols = allowed_symbols
        self.min_order_size = min_order_size
        self.compliance_blacklist = compliance_blacklist or []
        self.daily_loss = 0.0
        self.aum = 1.0  # Should be set by account/wallet manager
        self.positions: Dict[str, float] = {}  # symbol -> position size
        self.open_orders: Dict[str, int] = {}  # symbol -> open order count
        self.var_value = 0.0
        self.portfolio_value = 0.0

    def set_aum(self, aum: float):
        self.aum = aum

    def set_positions(self, positions: Dict[str, float]):
        self.positions = positions

    def set_open_orders(self, open_orders: Dict[str, int]):
        self.open_orders = open_orders

    def set_var(self, var_value: float, portfolio_value: float):
        self.var_value = var_value
        self.portfolio_value = portfolio_value

    def update_daily_loss(self, pnl: float):
        self.daily_loss += pnl

    def validate_order(self, order: Order) -> bool:
        """
        Run all risk checks. Return True if order is allowed, False otherwise.
        """
        symbol = order.symbol
        notional = order.quantity * (order.price if order.price else 1.0)
        position = self.positions.get(symbol, 0.0)
        open_orders = self.open_orders.get(symbol, 0)

        # 1. Compliance: symbol blacklist
        if self.allowed_symbols and symbol not in self.allowed_symbols:
            logging.warning(f"Order rejected: {symbol} not in allowed symbols.")
            return False
        if symbol in self.compliance_blacklist:
            logging.warning(f"Order rejected: {symbol} is blacklisted.")
            return False

        # 2. Minimum order size
        if order.quantity < self.min_order_size:
            logging.warning(f"Order rejected: quantity {order.quantity} below minimum {self.min_order_size}.")
            return False

        # 3. Max order notional
        if notional > self.max_order_value:
            logging.warning(f"Order rejected: notional {notional} exceeds max order value {self.max_order_value}.")
            return False

        # 4. Max position notional
        if abs(position + order.quantity) * (order.price if order.price else 1.0) > self.max_position_value:
            logging.warning(f"Order rejected: position size would exceed max position value {self.max_position_value}.")
            return False

        # 5. Max open orders per symbol
        if open_orders >= self.max_open_orders:
            logging.warning(f"Order rejected: open orders {open_orders} exceeds max {self.max_open_orders}.")
            return False

        # 6. Leverage check (if applicable)
        if self.aum > 0:
            leverage = abs((position + order.quantity) * (order.price if order.price else 1.0)) / self.aum
            if leverage > self.max_leverage:
                logging.warning(f"Order rejected: leverage {leverage:.2f}x exceeds max {self.max_leverage}x.")
                return False

        # 7. Daily loss limit
        if self.daily_loss < 0 and abs(self.daily_loss) > self.max_loss_per_day * self.aum:
            logging.warning(f"Order rejected: daily loss {self.daily_loss} exceeds max allowed {self.max_loss_per_day * self.aum}.")
            return False

        # 8. Portfolio VaR check
        if self.portfolio_value > 0 and self.var_value > self.max_var_ratio * self.portfolio_value:
            logging.warning(f"Order rejected: portfolio VaR {self.var_value} exceeds {self.max_var_ratio*100:.1f}% of portfolio value.")
            return False

        # 9. (Optional) Other custom checks can be added here

        return True

    def calculate_portfolio_var(self, portfolio_data, portfolio_value: float) -> float:
        # Placeholder: integrate with a real VaR model
        # Example: self.var_value = some_var_model(portfolio_data, portfolio_value)
        self.portfolio_value = portfolio_value
        return self.var_value

    def get_portfolio_var(self) -> float:
        return self.var_value

    def get_portfolio_var_assessment(self):
        if self.portfolio_value == 0:
            return 1
        ratio = self.var_value / self.portfolio_value
        if ratio > 0.8:
            return 0
        elif ratio > 0.5:
            return 0.5
        else:
            return 1

    def reset_daily_loss(self):
        self.daily_loss = 0.0