import logging
import threading
from typing import Optional, Callable, List, Tuple

from common import config_risk
from common.interface_order import Order, Side
from engine.position.position import Position


class RiskManager:
	"""
	Risk engine with:
	- Pre-order sanity checks
	- Portfolio-level drawdown gate (lifetime until reset)
	- Portfolio-level daily/max loss gate
	- Instrument-level VaR gate
	Prices and AUM are fed via gateway listeners (price provider + wallet balance updates).
	"""

	def __init__(
		self,
		max_order_value: Optional[float] = None,
		max_position_value: Optional[float] = None,
		max_leverage: Optional[float] = None,
		max_open_orders: Optional[int] = None,
		max_loss_per_day: Optional[float] = 0.10,  # portfolio daily loss cap (fraction of AUM)
		max_var_ratio: Optional[float] = None,     # instrument-level VaR cap ratio of instrument PV
		allowed_symbols: Optional[list] = None,
		min_order_size: Optional[float] = None,
		position: Optional[Position] = None,
		liquidation_loss_threshold: Optional[float] = None,
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
		# Instrument-level tracking
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
		self.account_margin_ratio: Optional[float] = None
		self._position_amounts = {}
		self._open_orders_count = {}
		self._latest_prices = {}

		# Global portfolio/AUM and daily loss
		self.aum = 0.0  # Should be set via wallet balance listener
		self.initial_aum = 0.0  # first AUM observed from gateway
		self.portfolio_daily_loss = 0.0
		self.portfolio_max_loss_ratio = self.max_loss_per_day
		# Trading block state and publisher hook
		self.trading_blocked = False
		self.block_reason: Optional[str] = None
		self._block_publisher: Optional[Callable[[dict], None]] = None

		self.liquidation_loss_threshold = (
			config_risk.LIQUIDATION_LOSS_THRESHOLD_DEFAULT if liquidation_loss_threshold is None else liquidation_loss_threshold
		)
		# Lifetime drawdown tracking
		self.max_drawdown = max_drawdown if max_drawdown is not None else 0.10
		self._peak_aum = None  # type: Optional[float]
		self._current_drawdown_ratio = 0.0

		# Price provider (reporting removed)
		self._price_provider = None  # type: Optional[Callable[[str], Optional[float]]]

		# If an initial position is provided, register its symbol
		if self.position and getattr(self.position, 'symbol', None):
			self.add_symbol(self.position.symbol, self.position)

	# ------------------------
	# Lifecycle and inputs
	# ------------------------
	def set_aum(self, aum: float):
		logging.info(f"Updating AUM to {aum}")
		# Record the first observed AUM as initial_aum
		if self.initial_aum is None:
			self.initial_aum = aum
		self.aum = aum
		# Update peak and drawdown
		if self._peak_aum is None or aum > self._peak_aum:
			self._peak_aum = aum
			self._current_drawdown_ratio = 0.0
		elif self._peak_aum > aum and self._peak_aum > 0:
			dd = (self._peak_aum - aum) / self._peak_aum
			self._current_drawdown_ratio = max(self._current_drawdown_ratio, dd)
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
		try:
			self.account_wallet_balance = float(wallet_balance)
		except Exception:
			self.account_wallet_balance = wallet_balance
		self.set_aum(self.account_wallet_balance)

	def on_margin_ratio_update(self, margin_ratio: float):
		self.account_margin_ratio = margin_ratio

	def on_unrealised_pnl_update(self, unrealised_pnl: float):
		try:
			self.account_unrealised_pnl = float(unrealised_pnl)
		except Exception:
			self.account_unrealised_pnl = unrealised_pnl
		# Update portfolio daily loss (assumes delta input)
		try:
			self.portfolio_daily_loss += float(unrealised_pnl)
		except Exception:
			pass

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
	# Price provider
	# ------------------------
	def set_price_provider(self, provider: Callable[[str], Optional[float]]):
		self._price_provider = provider
		logging.info("RiskManager: price provider set")

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
				"drawdown_ratio": self._current_drawdown_ratio,
				"daily_loss": self.portfolio_daily_loss,
			}
			try:
				self._block_publisher(payload)
			except Exception:
				logging.debug("Failed to publish trading block event", exc_info=True)

	def _get_mark_price(self, symbol: str) -> Optional[float]:
		if self._price_provider:
			try:
				price = self._price_provider(symbol)
				return float(price) if price is not None else None
			except Exception:
				logging.debug("RiskManager price provider failed", exc_info=True)
		if symbol in self._latest_prices:
			return self._latest_prices.get(symbol)
		return None

	# ------------------------
	# Daily loss and VaR
	# ------------------------
	def update_daily_loss(self, pnl: float, symbol: Optional[str] = None):
		try:
			self.portfolio_daily_loss += float(pnl)
		except Exception:
			pass
		if symbol:
			self.symbol_daily_loss[symbol] = self.symbol_daily_loss.get(symbol, 0.0) + pnl

	def reset_daily_loss(self):
		self.portfolio_daily_loss = 0.0
		for k in list(self.symbol_daily_loss.keys()):
			self.symbol_daily_loss[k] = 0.0

	def set_symbol_var(self, symbol: str, var_value: float, portfolio_value: float):
		self.symbol_var_value[symbol] = var_value
		self.symbol_portfolio_value[symbol] = portfolio_value

	# ------------------------
	# Dynamic symbol management
	# ------------------------
	def add_symbol(self, symbol: str, position: Optional[Position] = None, min_order_size: Optional[float] = None):
		if self.allowed_symbols is not None:
			self.allowed_symbols.add(symbol)
		if position:
			self.positions[symbol] = position
		self.symbol_daily_loss.setdefault(symbol, 0.0)
		if min_order_size is not None:
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
		if self.allowed_symbols and symbol not in self.allowed_symbols:
			logging.warning(f"Preorder rejected: {symbol} not in allowed symbols")
			return False
		# Per-symbol min order size
		min_size = self.min_order_size
		if getattr(self, '_symbol_min_order_size', None) is not None:
			min_size = getattr(self, '_symbol_min_order_size').get(symbol, self.min_order_size)
		if abs(qty) < min_size:
			logging.warning(f"Preorder rejected: quantity {qty} below minimum {min_size}")
			return False
		# Price must be available (either on order or via provider/cache)
		exec_price = order.price if getattr(order, 'price', None) not in (None, 0) else self._get_mark_price(symbol)
		if exec_price is None:
			logging.warning("Preorder rejected: price not available (order.price missing and mark price unavailable)")
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

		symbol = order.symbol
		qty = float(abs(order.leaves_qty)) if order.leaves_qty is not None else 0.0
		if getattr(order, 'side', None) == Side.SELL:
			delta_qty = -qty
		else:
			delta_qty = qty

		# Resolve current position and open orders
		position_amt, open_orders = self._get_position_and_open_orders(symbol)

		# Directional gating: prevent adding to same direction
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

		# Portfolio-level drawdown gate
		if self._peak_aum and self._peak_aum > 0 and self._current_drawdown_ratio > self.max_drawdown:
			self.trading_blocked = True
			self.block_reason = (
				f"drawdown {self._current_drawdown_ratio*100:.2f}% exceeds max {self.max_drawdown*100:.2f}%"
			)
			logging.warning(
				f"Order rejected: {self.block_reason} (peak={self._peak_aum}, aum={self.aum})."
			)
			self._publish_block_event()
			return False

		# Resolve price
		exec_price = order.price if getattr(order, 'price', None) not in (None, 0) else self._get_mark_price(symbol)
		if exec_price is None:
			logging.warning("Order rejected: missing price for notional/leverage checks")
			return False

		# Max order notional
		notional = abs(qty) * float(exec_price)
		if notional > self.max_order_value:
			logging.warning(f"Order rejected: notional {notional} exceeds max order value {self.max_order_value}.")
			return False

		# Max position notional
		future_position_notional = abs(position_amt + delta_qty) * float(exec_price)
		if future_position_notional > self.max_position_value:
			logging.warning(f"Order rejected: position size would exceed max position value {self.max_position_value}.")
			return False

		# Max open orders per symbol
		if open_orders >= self.max_open_orders:
			logging.warning(f"Order rejected: open orders {open_orders} exceeds max {self.max_open_orders}.")
			return False

		# Leverage
		if self.aum > 0:
			leverage = future_position_notional / self.aum
			if leverage > self.max_leverage:
				logging.warning(f"Order rejected: leverage {leverage:.2f}x exceeds max {self.max_leverage}x.")
				return False

		# Portfolio daily loss gate
		if self.portfolio_daily_loss < 0 and abs(self.portfolio_daily_loss) > self.max_loss_per_day * self.aum:
			self.trading_blocked = True
			self.block_reason = (
				f"portfolio daily loss {self.portfolio_daily_loss} exceeds cap {self.max_loss_per_day * self.aum}"
			)
			logging.warning(
				f"Order rejected: {self.block_reason}."
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
