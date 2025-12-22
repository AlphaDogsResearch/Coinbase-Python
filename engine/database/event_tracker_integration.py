"""
Event Tracker Integration Wrapper.

Provides easy integration of event tracking into existing order and position managers.
"""

import logging
from typing import Optional
from datetime import datetime

from common.interface_order import OrderEvent, OrderStatus, Side
from engine.database.event_tracker import EventTracker


class EventTrackerIntegration:
    """
    Integration wrapper for adding event tracking to order and position managers.
    
    This class can be optionally added to managers to enable event tracking without
    modifying core logic.
    """
    
    def __init__(self, database_path: str = "data/trading_events.db", enabled: bool = True):
        """
        Initialize event tracker integration.
        
        Args:
            database_path: Path to SQLite database
            enabled: Whether tracking is enabled
        """
        self.enabled = enabled
        self.tracker = None
        self.logger = logging.getLogger(__name__)
        
        if self.enabled:
            try:
                self.tracker = EventTracker(database_path)
                self.logger.info(f"Event tracking enabled: {database_path}")
            except Exception as e:
                self.logger.error(f"Failed to initialize event tracker: {e}", exc_info=True)
                self.enabled = False
    
    def track_signal(
        self,
        strategy_id: str,
        symbol: str,
        signal: int,
        price: float,
        action: Optional[str] = None,
        order_mode: Optional[str] = None,
        tags: Optional[list] = None
    ):
        """Track a trading signal."""
        if not self.enabled or not self.tracker:
            return
        
        try:
            self.tracker.log_signal(
                strategy_id=strategy_id,
                symbol=symbol,
                signal_type=signal,
                price=price,
                action=action,
                order_mode=order_mode,
                tags=tags
            )
        except Exception as e:
            self.logger.error(f"Failed to track signal: {e}")
    
    def track_order_created(
        self,
        order_id: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        client_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
        tags: Optional[list] = None
    ):
        """Track order creation."""
        if not self.enabled or not self.tracker:
            return
        
        try:
            self.tracker.create_order(
                order_id=order_id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                client_id=client_id,
                strategy_id=strategy_id,
                status="PENDING_NEW",
                tags=tags
            )
        except Exception as e:
            self.logger.error(f"Failed to track order creation: {e}")
    
    def track_order_event(self, order_event: OrderEvent, strategy_id: Optional[str] = None):
        """
        Track an order event from the exchange.
        
        Args:
            order_event: OrderEvent from exchange
            strategy_id: Optional strategy ID if not in event
        """
        if not self.enabled or not self.tracker:
            return
        
        try:
            # Update order status
            self.tracker.update_order_status(
                order_id=order_event.order_id,
                status=order_event.status.name if hasattr(order_event.status, 'name') else str(order_event.status)
            )
            
            # Record fill if this is a fill event
            if order_event.status == OrderStatus.FILLED and order_event.last_filled_quantity:
                side_str = order_event.side.name if hasattr(order_event.side, 'name') else str(order_event.side)
                
                self.tracker.record_fill(
                    order_id=order_event.order_id,
                    symbol=order_event.contract_name,
                    side=side_str,
                    price=float(order_event.last_filled_price),
                    quantity=float(order_event.last_filled_quantity),
                    timestamp=datetime.utcnow(),
                    is_maker=(order_event.order_type.name != "Market" if hasattr(order_event, 'order_type') else None)
                )
        except Exception as e:
            self.logger.error(f"Failed to track order event: {e}")
    
    def track_position_update(
        self,
        symbol: str,
        position_amount: float,
        entry_price: Optional[float] = None,
        strategy_id: Optional[str] = None,
        unrealized_pnl: float = 0,
        realized_pnl: float = 0,
        total_trading_cost: float = 0
    ):
        """Track a position update."""
        if not self.enabled or not self.tracker:
            return
        
        try:
            self.tracker.snapshot_position(
                symbol=symbol,
                position_amount=position_amount,
                entry_price=entry_price,
                strategy_id=strategy_id,
                unrealized_pnl=unrealized_pnl,
                realized_pnl=realized_pnl,
                total_trading_cost=total_trading_cost
            )
        except Exception as e:
            self.logger.error(f"Failed to track position update: {e}")
    
    def close(self):
        """Close event tracker."""
        if self.tracker:
            try:
                self.tracker.close()
            except Exception as e:
                self.logger.error(f"Failed to close event tracker: {e}")
