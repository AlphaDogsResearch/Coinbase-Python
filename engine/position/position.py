import logging
import json
from typing import Callable, Optional

from engine.trading_cost.trading_cost import TradingCost


class Position:
    """
    Manages a single trading position, open orders, PnL, and persistence for each symbol.
    Combines position logic and persistence for institutional trading systems.
    """

    def __init__(
        self,
        symbol: str,
        strategy_id: Optional[str] = None,
        position_amount: float = 0.0,
        entry_price: float = 0.0,
        unrealised_pnl: float = 0.0,
        maint_margin: float = 0.0,
        trading_cost: Optional[TradingCost] = None,
        realized_pnl_listener: Optional[Callable[[str, float], None]] = None,
        storage_path: str = "position_state.json",
    ):
        self.symbol = symbol
        # Optional strategy identifier for per-strategy isolation. None indicates aggregate.
        self.strategy_id = strategy_id
        self.position_amount = position_amount
        self.entry_price = entry_price
        self.unrealised_pnl = unrealised_pnl
        self.maint_margin = maint_margin
        self.unrealised_pnl_decimal_place = 4
        self.maint_margin_decimal_place = 4
        self.net_realized_pnl = 0.0
        self.realized_pnl_listener = realized_pnl_listener or (lambda symbol, pnl: None)
        logging.info("TYPE %s",type(trading_cost))
        self.taker_fee = float(trading_cost.taker_fee) if trading_cost else 0.0
        self.maker_fee = float(trading_cost.maker_fee) if trading_cost else 0.0
        self.total_trading_cost = 0.0
        self.open_orders: int = 0
        self.position_pnl: float = 0.0
        self.storage_path = storage_path
        # remove file loading for now
        # self._load_state()

    def _save_state(self):
        state = {
            "symbol": self.symbol,
            "strategy_id": self.strategy_id,
            "position_amount": self.position_amount,
            "entry_price": self.entry_price,
            "unrealised_pnl": self.unrealised_pnl,
            "maint_margin": self.maint_margin,
            "net_realized_pnl": self.net_realized_pnl,
            "taker_fee": self.taker_fee,
            "maker_fee": self.maker_fee,
            "total_trading_cost": self.total_trading_cost,
            "open_orders": self.open_orders,
            "position_pnl": self.position_pnl,
        }
        try:
            with open(self.storage_path, "w") as f:
                json.dump(state, f)
        except Exception as e:
            logging.error(f"Failed to save position state: {e}")

    def _load_state(self):
        try:
            with open(self.storage_path, "r") as f:
                state = json.load(f)
                self.symbol = state.get("symbol", self.symbol)
                self.strategy_id = state.get("strategy_id", None)
                self.position_amount = state.get("position_amount", 0.0)
                self.entry_price = state.get("entry_price", 0.0)
                self.unrealised_pnl = state.get("unrealised_pnl", 0.0)
                self.maint_margin = state.get("maint_margin", 0.0)
                self.net_realized_pnl = state.get("net_realized_pnl", 0.0)
                self.taker_fee = state.get("taker_fee", 0.0)
                self.maker_fee = state.get("maker_fee", 0.0)
                self.total_trading_cost = state.get("total_trading_cost", 0.0)
                self.open_orders = state.get("open_orders", 0)
                self.position_pnl = state.get("position_pnl", 0.0)
        except FileNotFoundError:
            pass
        except Exception as e:
            logging.error(f"Failed to load position state: {e}")

    def get_notional_amount(self, mark_price: float):
        return abs(self.position_amount) * mark_price

    def update_unrealised_pnl(self, mark_price: float):
        if self.position_amount > 0:
            self.unrealised_pnl = (mark_price - self.entry_price) * abs(self.position_amount)
        elif self.position_amount < 0:
            self.unrealised_pnl = (self.entry_price - mark_price) * abs(self.position_amount)
        else:
            self.unrealised_pnl = 0
        self.unrealised_pnl = round(self.unrealised_pnl, self.unrealised_pnl_decimal_place)
        self._save_state()
        logging.debug("Updated Unrealized Pnl for %s: %s", self.symbol, self)
        return self.unrealised_pnl

    def update_maintenance_margin(
        self, mark_price: float, maint_margin_rate: float, maint_amount: float
    ):
        notional_value = abs(self.position_amount) * mark_price
        self.maint_margin = (notional_value * maint_margin_rate) + maint_amount
        self.maint_margin = round(self.maint_margin, self.maint_margin_decimal_place)
        self._save_state()
        logging.debug("Updated Maint Margin for %s: %s", self.symbol, self)
        return self.maint_margin

    def add_trade(self, trade_qty: float, trade_price: float, is_taker):
        old_qty = self.position_amount
        new_qty = round(old_qty + trade_qty, 7)
        executed_notional = abs(trade_price * trade_qty)
        fee_rate = self.taker_fee if is_taker else self.maker_fee
        trading_cost = round(executed_notional * fee_rate, 9)
        self.total_trading_cost += trading_cost
        logging.info(
            "Trading Cost for %s, qty %s , price %s , fee %s -> %s",
            self.symbol,
            trade_qty,
            trade_price,
            fee_rate,
            trading_cost,
        )
        if old_qty * trade_qty < 0:  # Opposite direction: closing or flipping
            close_qty = min(abs(trade_qty), abs(old_qty))
            realized_pnl = close_qty * (trade_price - self.entry_price)
            if old_qty < 0:
                realized_pnl *= -1
            net_pnl = realized_pnl - trading_cost
            self.net_realized_pnl += net_pnl
            self.realized_pnl_listener(self.symbol, self.net_realized_pnl)
        if old_qty == 0 or (old_qty * trade_qty > 0):
            total_cost = self.entry_price * abs(old_qty) + trade_price * abs(trade_qty)
            self.entry_price = total_cost / abs(new_qty)
        elif old_qty * trade_qty < 0:
            if abs(trade_qty) > abs(old_qty):
                remaining_qty = trade_qty + old_qty
                self.entry_price = trade_price
                new_qty = remaining_qty
        self.position_amount = round(new_qty, 7)
        self._save_state()
        logging.info("Updated Position Amount: %s", self)

    def set_open_orders(self, count: int):
        self.open_orders = count
        self._save_state()

    def get_open_orders(self) -> int:
        return self.open_orders

    def set_position_pnl(self, pnl: float):
        self.position_pnl = pnl
        self._save_state()

    def get_position_pnl(self) -> float:
        return self.position_pnl

    def reset(self):
        self.position_amount = 0
        self.entry_price = 0
        self.unrealised_pnl = 0
        self.maint_margin = 0
        self.net_realized_pnl = 0
        self.total_trading_cost = 0
        self.open_orders = 0
        self.position_pnl = 0
        self._save_state()

    def __str__(self):
        return (
            f"Symbol={self.symbol}, "
            f"Strategy={self.strategy_id}, "
            f"Position Amount={self.position_amount}, "
            f"Entry Price={self.entry_price}, "
            f"Unrealized PNL={self.unrealised_pnl}, "
            f"Realized PNL={self.net_realized_pnl}, "
            f"Maint Margin={self.maint_margin}, "
            f"Open Orders={self.open_orders}"
        )

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "strategy_id": self.strategy_id,
            "position_amount": self.position_amount,
            "entry_price": self.entry_price,
            "unrealised_pnl": self.unrealised_pnl,
            "maint_margin": self.maint_margin,
            "net_realized_pnl": self.net_realized_pnl,
            "taker_fee": self.taker_fee,
            "maker_fee": self.maker_fee,
            "total_trading_cost": self.total_trading_cost,
            "open_orders": self.open_orders,
            "position_pnl": self.position_pnl,
        }

    @classmethod
    def from_dict(cls, d):
        dummy_listener = lambda symbol, pnl: None
        dummy_trading_cost = TradingCost(
            maker_fee=d.get("maker_fee", 0.0), taker_fee=d.get("taker_fee", 0.0)
        )
        pos = cls(
            symbol=d["symbol"],
            strategy_id=d.get("strategy_id", None),
            position_amount=d.get("position_amount", 0.0),
            entry_price=d.get("entry_price", 0.0),
            unrealised_pnl=d.get("unrealised_pnl", 0.0),
            maint_margin=d.get("maint_margin", 0.0),
            trading_cost=dummy_trading_cost,
            realized_pnl_listener=dummy_listener,
            storage_path="position_state.json",
        )
        pos.net_realized_pnl = d.get("net_realized_pnl", 0.0)
        pos.total_trading_cost = d.get("total_trading_cost", 0.0)
        pos.open_orders = d.get("open_orders", 0)
        pos.position_pnl = d.get("position_pnl", 0.0)
        return pos
