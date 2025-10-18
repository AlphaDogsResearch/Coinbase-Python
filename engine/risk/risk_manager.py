import logging
from typing import Optional, Dict, Set

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
        max_loss_per_day: float = 0.15,  # 15% of AUM
        max_var_ratio: float = 0.15,     # 15% of AUM
        allowed_symbols: Optional[list] = None,
        min_order_size: float = 0.001,
        position: Optional[Position] = None,
        liquidation_loss_threshold: float = 0.25,  # 25% loss threshold
    ):
        # Global limits (applied per symbol unless overridden)
        self.max_order_value = max_order_value
        self.max_position_value = max_position_value
        self.max_leverage = max_leverage
        self.max_open_orders = max_open_orders
        self.max_loss_per_day = max_loss_per_day
        self.max_var_ratio = max_var_ratio
        self.min_order_size = min_order_size

        # Dynamic symbol management
        self.allowed_symbols: Optional[Set[str]] = set(allowed_symbols) if allowed_symbols else None
        self.positions: Dict[str, Position] = {}
        self.symbol_daily_loss: Dict[str, float] = {}
        self.symbol_var_value: Dict[str, float] = {}
        self.symbol_portfolio_value: Dict[str, float] = {}

        # Backward-compat single-position path
        self.position = position

        # Global portfolio/AUM
        self.aum = 1.0  # Should be set by account/wallet manager

        self.liquidation_loss_threshold = liquidation_loss_threshold
        self._start_daily_loss_reset_thread()

        # If an initial position is provided, register its symbol
        if self.position and getattr(self.position, 'symbol', None):
            self.add_symbol(self.position.symbol, self.position)

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
        t = threading.Thread(target=reset_loop, daemon=True, name="daily_loss_reset_thread")
        t.start()

    def set_aum(self, aum: float):
        logging.info(f"Updating AUM to {aum}")
        self.aum = aum

    def set_var(self, var_value: float, portfolio_value: float):
        """Set portfolio-level VaR; kept for backward compatibility."""
        logging.debug("Setting global VaR (back-compat)")
        self.symbol_var_value['__GLOBAL__'] = var_value
        self.symbol_portfolio_value['__GLOBAL__'] = portfolio_value

    def update_daily_loss(self, pnl: float, symbol: Optional[str] = None):
        """Update daily loss; if symbol provided, track per-symbol as well."""
        if symbol:
            self.symbol_daily_loss[symbol] = self.symbol_daily_loss.get(symbol, 0.0) + pnl
        # Back-compat aggregate (not strictly used in per-symbol mode)
        self.symbol_daily_loss['__GLOBAL__'] = self.symbol_daily_loss.get('__GLOBAL__', 0.0) + pnl

    # ------------------------
    # Dynamic symbol management
    # ------------------------
    def add_symbol(self, symbol: str, position: Optional[Position] = None, min_order_size: Optional[float] = None):
        """Register a symbol for independent risk checks."""
        if self.allowed_symbols is not None:
            self.allowed_symbols.add(symbol)
        if position:
            self.positions[symbol] = position
        self.symbol_daily_loss.setdefault(symbol, 0.0)
        if min_order_size is not None:
            # Store per-symbol min size via a dedicated dict to extend later, for now simple attribute
            if not hasattr(self, '_symbol_min_order_size'):
                self._symbol_min_order_size: Dict[str, float] = {}
            self._symbol_min_order_size[symbol] = float(min_order_size)
        logging.info(f"RiskManager: added symbol {symbol}")

    def remove_symbol(self, symbol: str):
        self.positions.pop(symbol, None)
        self.symbol_daily_loss.pop(symbol, None)
        self.symbol_var_value.pop(symbol, None)
        self.symbol_portfolio_value.pop(symbol, None)
        if getattr(self, '_symbol_min_order_size', None) is not None:
            self._symbol_min_order_size.pop(symbol, None)
        if self.allowed_symbols is not None and symbol in self.allowed_symbols:
            self.allowed_symbols.remove(symbol)
        logging.info(f"RiskManager: removed symbol {symbol}")

    def set_symbol_position(self, symbol: str, position: Position):
        self.positions[symbol] = position

    def set_symbol_var(self, symbol: str, var_value: float, portfolio_value: float):
        self.symbol_var_value[symbol] = var_value
        self.symbol_portfolio_value[symbol] = portfolio_value

    def validate_order(self, order: Order) -> bool:
        """
        Run all risk checks. Return True if order is allowed, False otherwise.
        """
        symbol = order.symbol
        notional = order.leaves_qty * (order.price if order.price else 1.0)
        position_amt = 0.0
        open_orders = 0
        pos = self.positions.get(symbol)
        if not pos and self.position and getattr(self.position, 'symbol', None) == symbol:
            pos = self.position
        if pos:
            position_amt = getattr(pos, 'position_amount', 0.0)
            # Different implementations may provide open orders API with different names
            get_open = getattr(pos, 'get_open_orders', None)
            if callable(get_open):
                try:
                    open_orders = int(get_open())
                except Exception:
                    open_orders = 0

        # 1. Compliance: symbol whitelist
        if self.allowed_symbols and symbol not in self.allowed_symbols:
            logging.warning(f"Order rejected: {symbol} not in allowed symbols.")
            return False

        # 2. Minimum order size
        # Per-symbol min order size if provided
        min_size = self.min_order_size
        if getattr(self, '_symbol_min_order_size', None) is not None:
            min_size = getattr(self, '_symbol_min_order_size').get(symbol, self.min_order_size)
        if order.leaves_qty < min_size:
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
        sym_loss = self.symbol_daily_loss.get(symbol, 0.0)
        if sym_loss < 0 and abs(sym_loss) > self.max_loss_per_day * self.aum:
            logging.warning(f"Order rejected: daily loss {sym_loss} exceeds max allowed {self.max_loss_per_day * self.aum} for {symbol}.")
            return False

        # 8. Portfolio VaR check
        sym_var = self.symbol_var_value.get(symbol, self.symbol_var_value.get('__GLOBAL__', 0.0))
        sym_pv = self.symbol_portfolio_value.get(symbol, self.symbol_portfolio_value.get('__GLOBAL__', 0.0))
        if sym_pv > 0 and sym_var > self.max_var_ratio * sym_pv:
            logging.warning(f"Order rejected: VaR {sym_var} exceeds {self.max_var_ratio*100:.1f}% of portfolio value for {symbol}.")
            return False

        # 9. (Optional) Other custom checks can be added here

        return True

    def calculate_portfolio_var(self, portfolio_data, portfolio_value: float) -> float:
        # Placeholder: integrate with a real VaR model
        # Example: self.var_value = some_var_model(portfolio_data, portfolio_value)
        self.symbol_portfolio_value['__GLOBAL__'] = portfolio_value
        return self.symbol_var_value.get('__GLOBAL__', 0.0)

    def get_portfolio_var(self) -> float:
        return self.symbol_var_value.get('__GLOBAL__', 0.0)

    def get_portfolio_var_assessment(self, symbol: Optional[str] = None):
        pv = self.symbol_portfolio_value.get(symbol, self.symbol_portfolio_value.get('__GLOBAL__', 0.0))
        if pv == 0:
            return 1
        var = self.symbol_var_value.get(symbol, self.symbol_var_value.get('__GLOBAL__', 0.0))
        ratio = var / pv
        if ratio > 0.8:
            return 0
        elif ratio > 0.5:
            return 0.5
        else:
            return 1

    def reset_daily_loss(self):
        for k in list(self.symbol_daily_loss.keys()):
            self.symbol_daily_loss[k] = 0.0

    def check_and_liquidate_on_loss(self, symbol: Optional[str] = None):
        """
        If cumulative PnL of position(s) is below -threshold * AUM, close all positions and orders.
        If symbol is provided, check only that symbol; otherwise check all registered symbols.
        """
        symbols = [symbol] if symbol else list(self.positions.keys() or ([] if not self.position else [self.position.symbol]))
        for sym in symbols:
            pos = self.positions.get(sym)
            if not pos and self.position and getattr(self.position, 'symbol', None) == sym:
                pos = self.position
            if not pos:
                continue
            try:
                cumulative_pnl = pos.get_position_pnl()
            except Exception:
                cumulative_pnl = 0.0
            threshold = -self.liquidation_loss_threshold * self.aum
            if cumulative_pnl <= threshold:
                logging.warning(f"[{sym}] Cumulative PnL {cumulative_pnl} <= {threshold}: Closing all positions and orders!")
                # Implement your close logic here, e.g. pos.reset() or send close orders