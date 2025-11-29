import logging
from typing import Optional, Callable, List
from common import config_risk

from common.interface_order import Order, Side
from engine.position.position import Position
import threading


class RiskManager:
    """
    Institutional-grade risk manager for algorithmic trading systems.
    Performs multiple risk checks before allowing order execution.
    """
    def __init__(
        self,
        max_order_value: Optional[float] = None,
        max_position_value: Optional[float] = None,
        max_leverage: Optional[float] = None,
        max_open_orders: Optional[int] = None,
        max_loss_per_day: Optional[float] = 0.10,  # 15% of AUM
        max_var_ratio: Optional[float] = None,     # 15% of AUM
        allowed_symbols: Optional[list] = None,
        min_order_size: Optional[float] = None,
        position: Optional[Position] = None,
        liquidation_loss_threshold: Optional[float] = None,  # 25% loss threshold
        max_drawdown: Optional[float] = 0.10,  # 10% drawdown cap until reset
    ):
        # Global limits (applied per symbol unless overridden)
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
        self.max_loss_per_day = (
            config_risk.MAX_LOSS_PER_DAY_DEFAULT if max_loss_per_day is None else max_loss_per_day
        )
        self.max_var_ratio = (
            config_risk.MAX_VAR_RATIO_DEFAULT if max_var_ratio is None else max_var_ratio
        )
        self.min_order_size = (
            config_risk.MIN_ORDER_SIZE_DEFAULT if min_order_size is None else min_order_size
        )

        # Dynamic symbol management
        symbols_list = allowed_symbols if allowed_symbols is not None else config_risk.ALLOWED_SYMBOLS_DEFAULT
        self.allowed_symbols = set(symbols_list) if symbols_list else None
        self.positions = {}
        self.symbol_daily_loss = {}
        self.symbol_var_value = {}
        self.symbol_portfolio_value = {}

        # Backward-compat single-position path
        self.position = position

        # Inbound state caches (for independent operation via listeners)
        self.account_wallet_balance = 0.0
        self.account_margin_balance = 0.0
        self.account_maint_margin = 0.0
        self.account_unrealised_pnl = 0.0
        self.account_margin_ratio = None  # type: Optional[float]
        self._position_amounts = {}
        self._open_orders_count = {}
        self._latest_prices = {}

        # Global portfolio/AUM
        self.aum = 1.0  # Should be set by account/wallet manager

        self.liquidation_loss_threshold = (
            config_risk.LIQUIDATION_LOSS_THRESHOLD_DEFAULT if liquidation_loss_threshold is None else liquidation_loss_threshold
        )
        # Lifetime drawdown tracking
        self.max_drawdown = max_drawdown if max_drawdown is not None else 0.10
        self._peak_aum = None  # highest observed AUM since last reset
        self._current_drawdown_ratio = 0.0
    # Daily loss reset is orchestrated by higher-level scheduler (e.g., Account/main)

        # If an initial position is provided, register its symbol
        if self.position and getattr(self.position, 'symbol', None):
            self.add_symbol(self.position.symbol, self.position)

        # Reporting and price provider
        self._price_provider = None
        self._report_thread = None
        self._report_stop = threading.Event()
        self._report_logger = None
        self._report_interval_seconds = 600
        self._report_symbols = None

    # Removed internal daily loss reset thread; handled by orchestrator

    def set_aum(self, aum: float):
        logging.info(f"Updating AUM to {aum}")
        self.aum = aum
        # Update peak and drawdown
        if self._peak_aum is None or aum > self._peak_aum:
            self._peak_aum = aum
            self._current_drawdown_ratio = 0.0
        elif self._peak_aum > aum and self._peak_aum > 0:
            dd = (self._peak_aum - aum) / self._peak_aum
            self._current_drawdown_ratio = max(self._current_drawdown_ratio, dd)

    # ------------------------
    # Internal helpers (deduplicate logic)
    # ------------------------
    def _get_position_and_open_orders(self, symbol: str):
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
        try:
            self.account_wallet_balance = float(wallet_balance)
        except Exception:
            self.account_wallet_balance = wallet_balance
        self.set_aum(self.account_wallet_balance)

    def on_margin_ratio_update(self, margin_ratio: float):
        """Listener to receive margin ratio from Account."""
        self.account_margin_ratio = margin_ratio

    def on_unrealised_pnl_update(self, unrealised_pnl: float):
        """Listener to receive unrealised PnL from Position/Account."""
        try:
            self.account_unrealised_pnl = float(unrealised_pnl)
        except Exception:
            self.account_unrealised_pnl = unrealised_pnl

        # Optionally incorporate into daily loss tracking if desired
        # self.update_daily_loss(self.account_unrealised_pnl, symbol=None)

    def on_maint_margin_update(self, maint_margin: float):
        """Listener to receive maintenance margin updates."""
        try:
            self.account_maint_margin = float(maint_margin)
        except Exception:
            self.account_maint_margin = maint_margin

    def on_position_amount_update(self, symbol: str, position_amount: float):
        """Listener to receive per-symbol position amount updates when Position objects aren't provided."""
        try:
            self._position_amounts[symbol] = float(position_amount)
        except Exception:
            self._position_amounts[symbol] = position_amount

    def on_open_orders_update(self, symbol: str, count: int):
        """Listener to receive per-symbol open orders count when not deriving from Position."""
        try:
            self._open_orders_count[symbol] = int(count)
        except Exception:
            self._open_orders_count[symbol] = count

    def on_mark_price_update(self, symbol: str, price: float):
        """Listener to receive mark price updates; used as fallback price source if no provider is set."""
        try:
            self._latest_prices[symbol] = float(price)
        except Exception:
            # best effort
            self._latest_prices[symbol] = price

    # ------------------------
    # Price provider
    # ------------------------
    def set_price_provider(self, provider: Callable[[str], Optional[float]]):
        """Register a callable that returns the latest mark price for a symbol."""
        self._price_provider = provider
        logging.info("RiskManager: price provider set")

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
                self._symbol_min_order_size = {}
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
        # Determine signed delta quantity based on side
        qty = float(abs(order.leaves_qty)) if order.leaves_qty is not None else 0.0
        if getattr(order, 'side', None) == Side.SELL:
            delta_qty = -qty
        else:
            # Treat missing side as BUY (positive) by default
            delta_qty = qty

        # Resolve current position and open orders
        position_amt, open_orders = self._get_position_and_open_orders(symbol)

        # 0. Directional gating: If a position is open, only allow trades in the opposite direction
        # - Long position (>0): only SELL orders are allowed (delta < 0)
        # - Short position (<0): only BUY orders are allowed (delta > 0)
        # - Flat (==0): both BUY and SELL are allowed
        if position_amt > 0 and delta_qty > 0:
            logging.warning(
                f"Order rejected: long position open ({position_amt}); adding to same direction (BUY) is disabled."
            )
            return False
        if position_amt < 0 and delta_qty < 0:
            logging.warning(
                f"Order rejected: short position open ({position_amt}); adding to same direction (SELL) is disabled."
            )
            return False

        # max drawdown gating: block all new orders (including potential hedge adds) once drawdown exceeded
        if self._peak_aum > 0 and self._current_drawdown_ratio > self.max_drawdown:
            logging.warning(
                f"Order rejected: drawdown {self._current_drawdown_ratio*100:.2f}% exceeds max lifetime drawdown {self.max_drawdown*100:.2f}% (peak AUM={self._peak_aum}, current AUM={self.aum})."
            )
            return False

        # Resolve price to use (explicit price or latest mark)
        exec_price = order.price if getattr(order, 'price', None) not in (None, 0) else self._get_mark_price(symbol)

        # 1. Compliance: symbol whitelist
        if self.allowed_symbols and symbol not in self.allowed_symbols:
            logging.warning(f"Order rejected: {symbol} not in allowed symbols.")
            return False

        # 2. Minimum order size
        # Per-symbol min order size if provided
        min_size = self.min_order_size
        if getattr(self, '_symbol_min_order_size', None) is not None:
            min_size = getattr(self, '_symbol_min_order_size').get(symbol, self.min_order_size)
        if abs(qty) < min_size:
            logging.warning(f"Order rejected: quantity {qty} below minimum {min_size}.")
            return False

        # Price-dependent checks require a price
        if exec_price is None:
            logging.warning("Order rejected: no price available to evaluate notional/leverage (missing order.price and mark price)")
            return False

        # 3. Max order notional
        notional = abs(qty) * float(exec_price)
        if notional > self.max_order_value:
            logging.warning(f"Order rejected: notional {notional} exceeds max order value {self.max_order_value}.")
            return False

        # 4. Max position notional
        future_position_notional = abs(position_amt + delta_qty) * float(exec_price)
        if future_position_notional > self.max_position_value:
            logging.warning(f"Order rejected: position size would exceed max position value {self.max_position_value}.")
            return False

        # 5. Max open orders per symbol
        if open_orders >= self.max_open_orders:
            logging.warning(f"Order rejected: open orders {open_orders} exceeds max {self.max_open_orders}.")
            return False

        # 6. Leverage check (if applicable)
        if self.aum > 0:
            leverage = future_position_notional / self.aum
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

    # ------------------------
    # Risk reporting
    # ------------------------
    def _ensure_report_logger(self, report_file: str) -> logging.Logger:
        if self._report_logger:
            return self._report_logger
        logger = logging.getLogger("RiskReport")
        logger.setLevel(logging.INFO)
        # Avoid duplicate handlers if reconfigured
        logger.handlers = []
        # Create directory if needed
        try:
            import os
            directory = os.path.dirname(report_file)
            if directory:
                os.makedirs(directory, exist_ok=True)
        except Exception:
            logging.debug("Failed to ensure report directory", exc_info=True)
        fh = logging.FileHandler(report_file)
        fh.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        self._report_logger = logger
        return logger

    def _get_mark_price(self, symbol: str) -> Optional[float]:
        if self._price_provider:
            try:
                price = self._price_provider(symbol)
                return float(price) if price is not None else None
            except Exception:
                logging.debug("RiskManager price provider failed", exc_info=True)
        # Fallback to internal cache if available
        if symbol in self._latest_prices:
            return self._latest_prices.get(symbol)
        return None

    def generate_risk_report_text(self, symbols: Optional[List[str]] = None) -> str:
        """Create a human-readable risk report for the provided symbols (or all known)."""
        syms = symbols or list(self.positions.keys() or ([] if not self.position else [self.position.symbol]))
        lines: List[str] = []
        lines.append(f"AUM={self.aum}")
        if self._peak_aum is not None:
            lines.append(
                f"peak_AUM={self._peak_aum} drawdown={self._current_drawdown_ratio*100:.2f}% limit={self.max_drawdown*100:.2f}%"
            )
        # Global VaR (if set)
        g_pv = self.symbol_portfolio_value.get('__GLOBAL__', 0.0)
        g_var = self.symbol_var_value.get('__GLOBAL__', 0.0)
        if g_pv > 0:
            lines.append(f"Global VaR={g_var}, PV={g_pv}, Ratio={g_var/g_pv:.4f}")
        lines.append(f"liquidation_threshold={self.liquidation_loss_threshold*100:.1f}% AUM (loss reset handled externally)")
        for sym in syms:
            qty, open_orders = self._get_position_and_open_orders(sym)
            price = self._get_mark_price(sym)
            notional = abs(qty) * price if (price is not None) else None
            leverage = (notional / self.aum) if (notional is not None and self.aum > 0) else None
            dloss = self.symbol_daily_loss.get(sym, 0.0)
            svar = self.symbol_var_value.get(sym, 0.0)
            spv = self.symbol_portfolio_value.get(sym, 0.0)
            var_ratio = (svar / spv) if spv > 0 else None
            # Assemble line
            line = (
                f"[{sym}] qty={qty} open_orders={open_orders} daily_loss={dloss} "
                f"price={price if price is not None else 'NA'} "
                f"notional={notional if notional is not None else 'NA'} "
                f"leverage={f'{leverage:.4f}' if leverage is not None else 'NA'} "
                f"VaR={svar} PV={spv} ratio={f'{var_ratio:.4f}' if var_ratio is not None else 'NA'}"
            )
            lines.append(line)
        return "\n".join(lines)

    def start_periodic_risk_reports(self, report_file: str, interval_seconds: int = 600, symbols: Optional[List[str]] = None):
        """Start a background thread that logs and writes a risk report every interval."""
        self._report_interval_seconds = max(10, int(interval_seconds))
        self._report_symbols = symbols
        self._report_stop.clear()
        self._ensure_report_logger(report_file)

        def loop():
            threading.current_thread().name = "risk_reporter"
            while not self._report_stop.is_set():
                try:
                    text = self.generate_risk_report_text(self._report_symbols)
                    # Log to standard logger and report logger
                    logging.info("Risk report generated")
                    if self._report_logger:
                        self._report_logger.info("\n" + text)
                except Exception:
                    logging.error("Failed generating risk report", exc_info=True)
                finally:
                    self._report_stop.wait(self._report_interval_seconds)

        if self._report_thread and self._report_thread.is_alive():
            logging.info("Risk report thread already running")
            return
        self._report_thread = threading.Thread(target=loop, daemon=True)
        self._report_thread.start()
        logging.info(f"Started periodic risk reports every {self._report_interval_seconds}s -> {report_file}")

    def stop_periodic_risk_reports(self):
        self._report_stop.set()
        if self._report_thread and self._report_thread.is_alive():
            self._report_thread.join(timeout=3)
        logging.info("Stopped periodic risk reports")

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

    # ------------------------
    # Drawdown reset
    # ------------------------
    def reset_drawdown(self):
        """Reset peak AUM to current AUM, clearing drawdown lockout."""
        self._peak_aum = self.aum
        self._current_drawdown_ratio = 0.0
        logging.info("RiskManager: drawdown reset; peak AUM set to current AUM")

    def get_drawdown_info(self):
        """Return current drawdown stats dict."""
        return {
            'aum': self.aum,
            'peak_aum': self._peak_aum,
            'drawdown_ratio': self._current_drawdown_ratio,
            'limit': self.max_drawdown,
            'exceeded': self._current_drawdown_ratio > self.max_drawdown if self._peak_aum else False,
        }