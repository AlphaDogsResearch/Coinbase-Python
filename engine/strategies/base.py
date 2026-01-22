
from typing import Dict, List, Optional, Any, TYPE_CHECKING
import logging
from engine.market_data.candle import MidPriceCandle
from .models import Position, Instrument
from .strategy_action import StrategyAction
from .strategy_order_mode import StrategyOrderMode

if TYPE_CHECKING:
    from engine.database.models import SignalContext


class Logger:
    def info(self, msg: str):
        logging.info(f"{msg}")

    def warning(self, msg: str):
        logging.warning(f"[WARN] {msg}")

    def error(self, msg: str):
        logging.error(f"[ERROR] {msg}")

    def debug(self, msg: str):
        # print(f"[DEBUG] {msg}")
        pass


class StrategyPositionCache:
    """
    Combined cache for strategy positions and instruments.

    This class combines the functionality of Portfolio and Cache:
    - Stores and manages positions by instrument_id
    - Stores and manages instrument metadata
    - Provides convenient query methods for position state

    Position Sync Mechanism:
    ------------------------
    Positions are synced from the system PositionManager when orders are filled:

    1. Order Fill Flow:
       - RemoteOrderClient receives OrderEvent from exchange
       - PositionManager.on_order_event() is called with OrderEvent
       - When OrderStatus.FILLED, PositionManager updates its Position via position.add_trade()
       - PositionManager emits position updates to position_amount_listener callbacks

    2. Strategy Sync:
       - StrategyManager._make_position_sync_callback() creates a callback
       - This callback is registered via position_manager.add_position_amount_listener()
       - When position changes, callback triggers StrategyManager._sync_portfolio()
       - _sync_portfolio() converts system Position to strategy Position model
       - StrategyPositionCache.update_position() is called with the converted position

    3. Usage in Strategy:
       - Strategy can query position via cache.position(instrument_id)
       - Strategy can check position state via cache.is_flat(), cache.is_net_long(), etc.
       - Position is automatically kept in sync with system PositionManager
    """

    def __init__(self):
        self._positions: Dict[str, Position] = {}
        self._instruments: Dict[str, Instrument] = {}

    # ===== Position Methods =====

    def position(self, instrument_id: str) -> Optional[Position]:
        """Get position for an instrument."""
        return self._positions.get(instrument_id)

    def is_flat(self, instrument_id: str) -> bool:
        """Check if position is flat (no position or zero quantity)."""
        pos = self.position(instrument_id)
        return pos is None or pos.is_flat

    def is_net_long(self, instrument_id: str) -> bool:
        """Check if position is net long."""
        pos = self.position(instrument_id)
        return pos is not None and pos.is_long

    def is_net_short(self, instrument_id: str) -> bool:
        """Check if position is net short."""
        pos = self.position(instrument_id)
        return pos is not None and pos.is_short

    def update_position(self, position: Position):
        """
        Update position from system PositionManager.

        Called by StrategyManager when position changes are detected.
        Removes position entry if quantity becomes zero.
        """
        if position.quantity == 0:
            if position.instrument_id in self._positions:
                del self._positions[position.instrument_id]
        else:
            self._positions[position.instrument_id] = position

    def positions(self, instrument_id: str = None) -> List[Position]:
        """Get all positions or positions for a specific instrument."""
        if instrument_id:
            return [self._positions[instrument_id]] if instrument_id in self._positions else []
        return list(self._positions.values())

    # ===== Instrument Methods =====

    def instrument(self, instrument_id: str) -> Optional[Instrument]:
        """Get instrument metadata."""
        return self._instruments.get(instrument_id)

    def add_instrument(self, instrument: Instrument):
        """Add or update instrument metadata."""
        self._instruments[instrument.id] = instrument


class Strategy:
    def __init__(self, config: Any):
        self.config = config
        self.log = Logger()
        self.cache = StrategyPositionCache()  # Combined position and instrument cache
        self._order_manager = None  # Reference to order manager
        self._strategy_id = None  # Strategy ID set by main
        self._symbol = None  # Symbol set by main

    def set_order_manager(self, order_manager, strategy_id: str, symbol: str):
        """Set the order manager and strategy metadata."""
        self._order_manager = order_manager
        self._strategy_id = strategy_id
        self._symbol = symbol

    def on_start(self):
        """Called when strategy starts. Override in subclasses."""
        ...

    def on_stop(self):
        """Called when strategy stops. Override in subclasses."""
        ...

    def on_candle_created(self, candle: MidPriceCandle):
        """Handle incoming candle data. Override this method in subclasses."""
        ...

    def subscribe_bars(self, bar_type: str):
        """Subscribe to bar data (placeholder - handled by main wiring)."""
        ...

    def register_indicator_for_bars(self, bar_type: str, indicator):
        """Register indicator for automatic updates (placeholder)."""
        ...

    def on_signal(
        self,
        signal: int,
        price: float,
        strategy_actions: StrategyAction,
        strategy_order_mode: StrategyOrderMode,
        tags: List[str] = None,
        signal_context: "SignalContext" = None,
    ) -> bool:
        """
        Submit an order via the on_signal method on the order manager.

        Args:
            signal: Signal direction (1=BUY, -1=SELL, 0=HOLD)
            price: Current price at signal time
            strategy_actions: Action type (OPEN_CLOSE_POSITION, POSITION_REVERSAL, etc.)
            strategy_order_mode: Order sizing mode (NOTIONAL or QUANTITY)
            tags: Optional list of tags for the order
            signal_context: Optional SignalContext with indicator values and reason

        Returns:
            True if order was submitted successfully, False otherwise
        """
        if not self._order_manager:
            self.log.warning("Order manager not set, order not submitted")
            return False

        return self._order_manager.on_signal(
            strategy_id=self._strategy_id,
            signal=signal,
            price=price,
            symbol=self._symbol,
            strategy_actions=strategy_actions,
            strategy_order_mode=strategy_order_mode,
            tags=tags,
            signal_context=signal_context,
        )

    def cancel_all_orders(self, instrument_id: str):
        """Cancel all orders for instrument (placeholder - may need implementation)."""
        self.log.warning("cancel_all_orders not yet implemented")

    def close_all_positions(self, instrument_id: str):
        """Close all positions for instrument."""
        if instrument_id == self._symbol and self._order_manager:
            # Get current price from cache or use a default
            pos = self.cache.position(instrument_id)
            if pos:
                # Use entry price as fallback, but ideally should get mark price
                price = pos.entry_price if hasattr(pos, "entry_price") else 0.0
                return self._order_manager.submit_market_close(
                    strategy_id=self._strategy_id,
                    symbol=self._symbol,
                    price=price,
                    tags=["action=CLOSE"],
                )
        return True
