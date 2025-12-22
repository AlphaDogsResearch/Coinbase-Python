"""
Event Tracker Service - Main interface for tracking trading events.

Provides methods to log events, track orders, record fills, snapshot positions,
and query historical data for audit and analysis.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from contextlib import contextmanager
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, or_, func

from engine.database.event_tracker_models import (
    TradingEvent, Order, Fill, Position, Signal,
    get_session_maker, Base
)


class EventTracker:
    """
    Main event tracking service for trading system.
    
    Captures all trading events from order intent to fill with full audit trail.
    """
    
    def __init__(self, database_path: str = "data/trading_events.db"):
        """
        Initialize event tracker.
        
        Args:
            database_path: Path to SQLite database file
        """
        self.database_path = database_path
        database_url = f"sqlite:///{database_path}"
        self.SessionMaker, self.engine = get_session_maker(database_url)
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"EventTracker initialized with database: {database_path}")
    
    @contextmanager
    def session_scope(self):
        """Provide a transactional scope for database operations."""
        session = self.SessionMaker()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            self.logger.error(f"Database error: {e}", exc_info=True)
            raise
        finally:
            session.close()
    
    # ==================== Event Logging ====================
    
    def log_event(
        self,
        event_type: str,
        symbol: str,
        timestamp: Optional[datetime] = None,
        strategy_id: Optional[str] = None,
        order_id: Optional[str] = None,
        client_id: Optional[str] = None,
        event_data: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Log a trading event to the master event log.
        
        Args:
            event_type: Type of event (ORDER_INTENT, ORDER_SUBMITTED, etc.)
            symbol: Trading symbol
            timestamp: Event timestamp (defaults to now)
            strategy_id: Strategy identifier
            order_id: Exchange order ID
            client_id: Client order ID
            event_data: Additional event data as dictionary
        
        Returns:
            Event ID
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        with self.session_scope() as session:
            event = TradingEvent(
                event_type=event_type,
                timestamp=timestamp,
                symbol=symbol,
                strategy_id=strategy_id,
                order_id=order_id,
                client_id=client_id,
                event_data=event_data
            )
            session.add(event)
            session.flush()
            event_id = event.id
            self.logger.debug(f"Logged event: {event_type} for {symbol}")
            return event_id
    
    # ==================== Order Tracking ====================
    
    def create_order(
        self,
        order_id: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        client_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
        status: str = "PENDING_NEW",
        tags: Optional[List[str]] = None
    ) -> int:
        """
        Create a new order record.
        
        Args:
            order_id: Exchange order ID
            symbol: Trading symbol
            side: BUY or SELL
            order_type: MARKET, LIMIT, etc.
            quantity: Order quantity
            price: Order price (optional for market orders)
            client_id: Client order ID
            strategy_id: Strategy identifier
            status: Initial order status
            tags: Order tags
        
        Returns:
            Order database ID
        """
        with self.session_scope() as session:
            order = Order(
                order_id=order_id,
                client_id=client_id,
                symbol=symbol,
                strategy_id=strategy_id,
                side=side,
                order_type=order_type,
                price=price,
                quantity=quantity,
                filled_quantity=0,
                remaining_quantity=quantity,
                status=status,
                tags=tags
            )
            session.add(order)
            session.flush()
            db_id = order.id
            
            # Log event
            self.log_event(
                event_type="ORDER_CREATED",
                symbol=symbol,
                strategy_id=strategy_id,
                order_id=order_id,
                client_id=client_id,
                event_data={
                    "side": side,
                    "type": order_type,
                    "quantity": quantity,
                    "price": price,
                    "tags": tags
                }
            )
            
            return db_id
    
    def update_order_status(
        self,
        order_id: str,
        status: str,
        filled_quantity: Optional[float] = None,
        avg_fill_price: Optional[float] = None
    ):
        """
        Update order status and fill information.
        
        Args:
            order_id: Exchange order ID
            status: New order status
            filled_quantity: Total filled quantity
            avg_fill_price: Average fill price
        """
        with self.session_scope() as session:
            order = session.query(Order).filter_by(order_id=order_id).first()
            if order:
                order.status = status
                if filled_quantity is not None:
                    order.filled_quantity = filled_quantity
                    order.remaining_quantity = order.quantity - filled_quantity
                if avg_fill_price is not None:
                    order.avg_fill_price = avg_fill_price
                order.updated_at = datetime.utcnow()
                
                # Log event
                self.log_event(
                    event_type=f"ORDER_{status}",
                    symbol=order.symbol,
                    strategy_id=order.strategy_id,
                    order_id=order_id,
                    event_data={
                        "status": status,
                        "filled_quantity": filled_quantity,
                        "avg_fill_price": avg_fill_price
                    }
                )
            else:
                self.logger.warning(f"Order not found: {order_id}")
    
    # ==================== Fill Recording ====================
    
    def record_fill(
        self,
        order_id: str,
        symbol: str,
        side: str,
        price: float,
        quantity: float,
        timestamp: Optional[datetime] = None,
        commission: float = 0,
        realized_pnl: float = 0,
        is_maker: Optional[bool] = None
    ) -> int:
        """
        Record a trade fill/execution.
        
        Args:
            order_id: Exchange order ID
            symbol: Trading symbol
            side: BUY or SELL
            price: Fill price
            quantity: Fill quantity
            timestamp: Fill timestamp
            commission: Trading fee
            realized_pnl: Realized P&L from this fill
            is_maker: True if maker, False if taker
        
        Returns:
            Fill database ID
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        with self.session_scope() as session:
            fill = Fill(
                order_id=order_id,
                symbol=symbol,
                side=side,
                price=price,
                quantity=quantity,
                commission=commission,
                realized_pnl=realized_pnl,
                timestamp=timestamp,
                is_maker=is_maker
            )
            session.add(fill)
            session.flush()
            fill_id = fill.id
            
            # Log event
            self.log_event(
                event_type="FILL",
                symbol=symbol,
                order_id=order_id,
                timestamp=timestamp,
                event_data={
                    "side": side,
                    "price": price,
                    "quantity": quantity,
                    "commission": commission,
                    "realized_pnl": realized_pnl,
                    "is_maker": is_maker
                }
            )
            
            return fill_id
    
    # ==================== Position Snapshots ====================
    
    def snapshot_position(
        self,
        symbol: str,
        position_amount: float,
        entry_price: Optional[float] = None,
        strategy_id: Optional[str] = None,
        unrealized_pnl: float = 0,
        realized_pnl: float = 0,
        total_trading_cost: float = 0,
        timestamp: Optional[datetime] = None
    ) -> int:
        """
        Create a position snapshot.
        
        Args:
            symbol: Trading symbol
            position_amount: Current position size
            entry_price: Average entry price
            strategy_id: Strategy identifier
            unrealized_pnl: Unrealized P&L
            realized_pnl: Realized P&L
            total_trading_cost: Cumulative trading fees
            timestamp: Snapshot timestamp
        
        Returns:
            Position snapshot ID
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        with self.session_scope() as session:
            position = Position(
                symbol=symbol,
                strategy_id=strategy_id,
                position_amount=position_amount,
                entry_price=entry_price,
                unrealized_pnl=unrealized_pnl,
                realized_pnl=realized_pnl,
                total_trading_cost=total_trading_cost,
                timestamp=timestamp
            )
            session.add(position)
            session.flush()
            return position.id
    
    # ==================== Signal Logging ====================
    
    def log_signal(
        self,
        strategy_id: str,
        symbol: str,
        signal_type: int,
        price: Optional[float] = None,
        action: Optional[str] = None,
        order_mode: Optional[str] = None,
        tags: Optional[List[str]] = None,
        timestamp: Optional[datetime] = None
    ) -> int:
        """
        Log a trading signal.
        
        Args:
            strategy_id: Strategy identifier
            symbol: Trading symbol
            signal_type: Signal value (-1, 0, 1)
            price: Signal price
            action: Strategy action
            order_mode: Order mode
            tags: Signal tags
            timestamp: Signal timestamp
        
        Returns:
            Signal database ID
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        with self.session_scope() as session:
            signal = Signal(
                strategy_id=strategy_id,
                symbol=symbol,
                signal_type=signal_type,
                price=price,
                action=action,
                order_mode=order_mode,
                tags=tags,
                timestamp=timestamp
            )
            session.add(signal)
            session.flush()
            signal_id = signal.id
            
            # Log event
            self.log_event(
                event_type="SIGNAL",
                symbol=symbol,
                strategy_id=strategy_id,
                timestamp=timestamp,
                event_data={
                    "signal_type": signal_type,
                    "price": price,
                    "action": action,
                    "order_mode": order_mode,
                    "tags": tags
                }
            )
            
            return signal_id
    
    # ==================== Query Methods ====================
    
    def get_recent_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent trading events."""
        with self.session_scope() as session:
            events = session.query(TradingEvent).order_by(
                desc(TradingEvent.timestamp)
            ).limit(limit).all()
            
            return [{
                "id": e.id,
                "event_type": e.event_type,
                "timestamp": e.timestamp.isoformat(),
                "symbol": e.symbol,
                "strategy_id": e.strategy_id,
                "order_id": e.order_id,
                "client_id": e.client_id,
                "event_data": e.event_data
            } for e in events]
    
    def get_order_events(self, order_id: str) -> List[Dict[str, Any]]:
        """Get all events for a specific order."""
        with self.session_scope() as session:
            events = session.query(TradingEvent).filter_by(
                order_id=order_id
            ).order_by(TradingEvent.timestamp).all()
            
            return [{
                "id": e.id,
                "event_type": e.event_type,
                "timestamp": e.timestamp.isoformat(),
                "event_data": e.event_data
            } for e in events]
    
    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get order details."""
        with self.session_scope() as session:
            order = session.query(Order).filter_by(order_id=order_id).first()
            if order:
                return {
                    "order_id": order.order_id,
                    "client_id": order.client_id,
                    "symbol": order.symbol,
                    "strategy_id": order.strategy_id,
                    "side": order.side,
                    "order_type": order.order_type,
                    "price": float(order.price) if order.price else None,
                    "quantity": float(order.quantity),
                    "filled_quantity": float(order.filled_quantity),
                    "remaining_quantity": float(order.remaining_quantity),
                    "avg_fill_price": float(order.avg_fill_price) if order.avg_fill_price else None,
                    "status": order.status,
                    "created_at": order.created_at.isoformat(),
                    "updated_at": order.updated_at.isoformat(),
                    "tags": order.tags
                }
            return None
    
    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all open orders, optionally filtered by symbol."""
        with self.session_scope() as session:
            query = session.query(Order).filter(
                Order.status.in_(['PENDING_NEW', 'NEW', 'OPEN', 'PARTIALLY_FILLED'])
            )
            if symbol:
                query = query.filter_by(symbol=symbol)
            
            orders = query.order_by(desc(Order.created_at)).all()
            return [self._order_to_dict(o) for o in orders]
    
    def get_fills_for_order(self, order_id: str) -> List[Dict[str, Any]]:
        """Get all fills for a specific order."""
        with self.session_scope() as session:
            fills = session.query(Fill).filter_by(
                order_id=order_id
            ).order_by(Fill.timestamp).all()
            
            return [{
                "id": f.id,
                "order_id": f.order_id,
                "symbol": f.symbol,
                "side": f.side,
                "price": float(f.price),
                "quantity": float(f.quantity),
                "commission": float(f.commission),
                "realized_pnl": float(f.realized_pnl),
                "timestamp": f.timestamp.isoformat(),
                "is_maker": f.is_maker
            } for f in fills]
    
    def get_current_positions(self) -> List[Dict[str, Any]]:
        """Get latest position snapshot for each symbol/strategy combination."""
        with self.session_scope() as session:
            # Subquery to get latest timestamp for each symbol/strategy
            subq = session.query(
                Position.symbol,
                Position.strategy_id,
                func.max(Position.timestamp).label('max_timestamp')
            ).group_by(Position.symbol, Position.strategy_id).subquery()
            
            # Join to get full position records
            positions = session.query(Position).join(
                subq,
                and_(
                    Position.symbol == subq.c.symbol,
                    Position.strategy_id == subq.c.strategy_id,
                    Position.timestamp == subq.c.max_timestamp
                )
            ).all()
            
            return [{
                "symbol": p.symbol,
                "strategy_id": p.strategy_id,
                "position_amount": float(p.position_amount),
                "entry_price": float(p.entry_price) if p.entry_price else None,
                "unrealized_pnl": float(p.unrealized_pnl),
                "realized_pnl": float(p.realized_pnl),
                "total_trading_cost": float(p.total_trading_cost),
                "timestamp": p.timestamp.isoformat()
            } for p in positions]
    
    def get_position_history(
        self,
        symbol: str,
        strategy_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get position history for a symbol."""
        with self.session_scope() as session:
            query = session.query(Position).filter_by(symbol=symbol)
            if strategy_id:
                query = query.filter_by(strategy_id=strategy_id)
            
            positions = query.order_by(desc(Position.timestamp)).limit(limit).all()
            
            return [{
                "position_amount": float(p.position_amount),
                "entry_price": float(p.entry_price) if p.entry_price else None,
                "unrealized_pnl": float(p.unrealized_pnl),
                "realized_pnl": float(p.realized_pnl),
                "timestamp": p.timestamp.isoformat()
            } for p in positions]
    
    def _order_to_dict(self, order: Order) -> Dict[str, Any]:
        """Convert Order model to dictionary."""
        return {
            "order_id": order.order_id,
            "symbol": order.symbol,
            "strategy_id": order.strategy_id,
            "side": order.side,
            "order_type": order.order_type,
            "price": float(order.price) if order.price else None,
            "quantity": float(order.quantity),
            "filled_quantity": float(order.filled_quantity),
            "status": order.status,
            "created_at": order.created_at.isoformat()
        }
    
    def close(self):
        """Close database connections."""
        self.engine.dispose()
        self.logger.info("EventTracker closed")
