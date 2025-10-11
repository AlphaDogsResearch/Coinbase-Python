import logging
from typing import Optional

from common.interface_order import Order
from engine.position.position import Position
import threading
import time
import datetime
import pytz


class RiskManager:
    """
    Institutional-grade risk manager for algorithmic trading systems.
    Performs multiple risk checks before allowing order execution.
    """
    def __init__(
        self,
        max_order_value: float = 5000.0,
        max_position_value: float = 20000.0,
        max_leverage: float = 5.0,
        max_open_orders: int = 20,
        max_loss_per_day: float = 0.15,  # 10% of AUM
        max_var_ratio: float = 0.15,     # 15% of AUM
        allowed_symbols: Optional[list] = None,
        min_order_size: float = 0.001,
        position: Optional[Position] = None,
        liquidation_loss_threshold: float = 0.25,  # 25% loss threshold
    ):
        self.max_order_value = max_order_value
        self.max_position_value = max_position_value
        self.max_leverage = max_leverage
        self.max_open_orders = max_open_orders
        self.max_loss_per_day = max_loss_per_day
        self.max_var_ratio = max_var_ratio
        self.allowed_symbols = allowed_symbols
        self.min_order_size = min_order_size
        self.daily_loss = 0.0
        self.aum = 1.0  # Should be set by account/wallet manager
        self.var_value = 0.0
        self.portfolio_value = 0.0
        self.position = position
        self.liquidation_loss_threshold = liquidation_loss_threshold
        self._start_daily_loss_reset_thread()

    def _start_daily_loss_reset_thread(self):
        def reset_loop():
            eastern = pytz.timezone('US/Eastern')
            while True:
                now = datetime.datetime.now(tz=eastern)
                next_reset = now.replace(hour=8, minute=0, second=0, microsecond=0)
                if now >= next_reset:
                    next_reset += datetime.timedelta(days=1)
                sleep_seconds = (next_reset - now).total_seconds()
                time.sleep(sleep_seconds)
                self.reset_daily_loss()
                logging.info("Daily loss reset at 8am EST.")
        t = threading.Thread(target=reset_loop, daemon=True)
        t.start()

    def set_aum(self, aum: float):
        logging.info(f"Updating AUM to {aum}")
        self.aum = aum

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
        notional = order.leaves_qty * (order.price if order.price else 1.0)
        position_amt = 0.0
        open_orders = 0
        if self.position and self.position.symbol == symbol:
            position_amt = self.position.position_amount
            open_orders = self.position.get_open_orders()

        # 1. Compliance: symbol whitelist
        if self.allowed_symbols and symbol not in self.allowed_symbols:
            logging.warning(f"Order rejected: {symbol} not in allowed symbols.")
            return False

        # 2. Minimum order size
        if order.leaves_qty < self.min_order_size:
            logging.warning(f"Order rejected: quantity {order.leaves_qty} below minimum {self.min_order_size}.")
            return False

        # 3. Max order notional
        if notional > self.max_order_value:
            logging.warning(f"Order rejected: notional {notional} exceeds max order value {self.max_order_value}.")
            return False

        # 4. Max position notional
        if abs(position_amt + order.leaves_qty) * (order.price if order.price else 1.0) > self.max_position_value:
            logging.warning(f"Order rejected: position size would exceed max position value {self.max_position_value}.")
            return False

        # 5. Max open orders per symbol
        if open_orders >= self.max_open_orders:
            logging.warning(f"Order rejected: open orders {open_orders} exceeds max {self.max_open_orders}.")
            return False

        # 6. Leverage check (if applicable)
        if self.aum > 0:
            leverage = abs((position_amt + order.leaves_qty) * (order.price if order.price else 1.0)) / self.aum
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

    def check_and_liquidate_on_loss(self):
        """
        If cumulative PnL of all open positions is below -liquidation_loss_threshold * AUM, close all positions and orders.
        """
        if not self.position:
            return
        cumulative_pnl = self.position.get_position_pnl()
        threshold = -self.liquidation_loss_threshold * self.aum
        if cumulative_pnl <= threshold:
            logging.warning(f"Cumulative PnL {cumulative_pnl} <= {threshold}: Closing all positions and orders!")
            # Implement your close logic here, e.g. self.position.reset() or similar