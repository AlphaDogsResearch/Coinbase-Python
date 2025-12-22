"""
Pre-built queries for common event tracking use cases.

Provides convenient query methods for audit trails, performance analysis,
and position tracking.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy import and_, or_, func, desc
from sqlalchemy.orm import Session

from engine.database.event_tracker_models import (
    TradingEvent, Order, Fill, Position, Signal
)


class EventQueries:
    """Pre-built queries for event tracking database."""
    
    def __init__(self, session: Session):
        """
        Initialize with database session.
        
        Args:
            session: SQLAlchemy session
        """
        self.session = session
    
    # ==================== Audit Queries ====================
    
    def get_order_audit_trail(self, order_id: str) -> Dict[str, Any]:
        """
        Get complete audit trail for an order from intent to final state.
        
        Args:
            order_id: Exchange order ID
        
        Returns:
            Dictionary with order details, events, and fills
        """
        # Get order details
        order = self.session.query(Order).filter_by(order_id=order_id).first()
        if not order:
            return {"error": "Order not found"}
        
        # Get all events
        events = self.session.query(TradingEvent).filter_by(
            order_id=order_id
        ).order_by(TradingEvent.timestamp).all()
        
        # Get all fills
        fills = self.session.query(Fill).filter_by(
            order_id=order_id
        ).order_by(Fill.timestamp).all()
        
        return {
            "order": {
                "order_id": order.order_id,
                "symbol": order.symbol,
                "strategy_id": order.strategy_id,
                "side": order.side,
                "type": order.order_type,
                "quantity": float(order.quantity),
                "price": float(order.price) if order.price else None,
                "status": order.status,
                "filled_quantity": float(order.filled_quantity),
                "avg_fill_price": float(order.avg_fill_price) if order.avg_fill_price else None,
                "created_at": order.created_at.isoformat(),
                "updated_at": order.updated_at.isoformat()
            },
            "events": [{
                "timestamp": e.timestamp.isoformat(),
                "event_type": e.event_type,
                "event_data": e.event_data
            } for e in events],
            "fills": [{
                "timestamp": f.timestamp.isoformat(),
                "price": float(f.price),
                "quantity": float(f.quantity),
                "commission": float(f.commission),
                "realized_pnl": float(f.realized_pnl),
                "is_maker": f.is_maker
            } for f in fills]
        }
    
    def get_events_in_timerange(
        self,
        start_time: datetime,
        end_time: datetime,
        symbol: Optional[str] = None,
        event_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all events within a time range.
        
        Args:
            start_time: Start of time range
            end_time: End of time range
            symbol: Optional symbol filter
            event_type: Optional event type filter
        
        Returns:
            List of events
        """
        query = self.session.query(TradingEvent).filter(
            and_(
                TradingEvent.timestamp >= start_time,
                TradingEvent.timestamp <= end_time
            )
        )
        
        if symbol:
            query = query.filter_by(symbol=symbol)
        if event_type:
            query = query.filter_by(event_type=event_type)
        
        events = query.order_by(TradingEvent.timestamp).all()
        
        return [{
            "id": e.id,
            "timestamp": e.timestamp.isoformat(),
            "event_type": e.event_type,
            "symbol": e.symbol,
            "strategy_id": e.strategy_id,
            "order_id": e.order_id,
            "event_data": e.event_data
        } for e in events]
    
    # ==================== Performance Queries ====================
    
    def get_strategy_performance(
        self,
        strategy_id: str,
        start_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Get performance metrics for a strategy.
        
        Args:
            strategy_id: Strategy identifier
            start_time: Optional start time for analysis
        
        Returns:
            Performance metrics dictionary
        """
        query = self.session.query(Fill).join(
            Order, Fill.order_id == Order.order_id
        ).filter(Order.strategy_id == strategy_id)
        
        if start_time:
            query = query.filter(Fill.timestamp >= start_time)
        
        fills = query.all()
        
        if not fills:
            return {"error": "No fills found for strategy"}
        
        total_fills = len(fills)
        total_volume = sum(float(f.quantity) for f in fills)
        total_commission = sum(float(f.commission) for f in fills)
        total_realized_pnl = sum(float(f.realized_pnl) for f in fills)
        
        buy_fills = [f for f in fills if f.side == "BUY"]
        sell_fills = [f for f in fills if f.side == "SELL"]
        
        maker_fills = [f for f in fills if f.is_maker]
        taker_fills = [f for f in fills if not f.is_maker]
        
        return {
            "strategy_id": strategy_id,
            "total_fills": total_fills,
            "total_volume": total_volume,
            "total_commission": total_commission,
            "total_realized_pnl": total_realized_pnl,
            "buy_fills": len(buy_fills),
            "sell_fills": len(sell_fills),
            "maker_fills": len(maker_fills),
            "taker_fills": len(taker_fills),
            "avg_fill_size": total_volume / total_fills if total_fills > 0 else 0
        }
    
    def get_symbol_statistics(
        self,
        symbol: str,
        days: int = 7
    ) -> Dict[str, Any]:
        """
        Get trading statistics for a symbol.
        
        Args:
            symbol: Trading symbol
            days: Number of days to analyze
        
        Returns:
            Statistics dictionary
        """
        start_time = datetime.utcnow() - timedelta(days=days)
        
        # Get orders
        orders = self.session.query(Order).filter(
            and_(
                Order.symbol == symbol,
                Order.created_at >= start_time
            )
        ).all()
        
        # Get fills
        fills = self.session.query(Fill).filter(
            and_(
                Fill.symbol == symbol,
                Fill.timestamp >= start_time
            )
        ).all()
        
        total_orders = len(orders)
        filled_orders = len([o for o in orders if o.status == "FILLED"])
        canceled_orders = len([o for o in orders if o.status == "CANCELED"])
        
        return {
            "symbol": symbol,
            "period_days": days,
            "total_orders": total_orders,
            "filled_orders": filled_orders,
            "canceled_orders": canceled_orders,
            "fill_rate": filled_orders / total_orders if total_orders > 0 else 0,
            "total_fills": len(fills),
            "total_volume": sum(float(f.quantity) for f in fills),
            "total_commission": sum(float(f.commission) for f in fills),
            "total_realized_pnl": sum(float(f.realized_pnl) for f in fills)
        }
    
    # ==================== Position Queries ====================
    
    def get_position_timeline(
        self,
        symbol: str,
        strategy_id: Optional[str] = None,
        hours: int = 24
    ) -> List[Dict[str, Any]]:
        """
        Get position changes over time.
        
        Args:
            symbol: Trading symbol
            strategy_id: Optional strategy filter
            hours: Number of hours to look back
        
        Returns:
            List of position snapshots
        """
        start_time = datetime.utcnow() - timedelta(hours=hours)
        
        query = self.session.query(Position).filter(
            and_(
                Position.symbol == symbol,
                Position.timestamp >= start_time
            )
        )
        
        if strategy_id:
            query = query.filter_by(strategy_id=strategy_id)
        
        positions = query.order_by(Position.timestamp).all()
        
        return [{
            "timestamp": p.timestamp.isoformat(),
            "position_amount": float(p.position_amount),
            "entry_price": float(p.entry_price) if p.entry_price else None,
            "unrealized_pnl": float(p.unrealized_pnl),
            "realized_pnl": float(p.realized_pnl)
        } for p in positions]
    
    def get_all_current_positions(self) -> List[Dict[str, Any]]:
        """
        Get current position for all symbols.
        
        Returns:
            List of current positions
        """
        # Subquery to get latest timestamp for each symbol/strategy
        subq = self.session.query(
            Position.symbol,
            Position.strategy_id,
            func.max(Position.timestamp).label('max_timestamp')
        ).group_by(Position.symbol, Position.strategy_id).subquery()
        
        # Join to get full position records
        positions = self.session.query(Position).join(
            subq,
            and_(
                Position.symbol == subq.c.symbol,
                Position.strategy_id == subq.c.strategy_id,
                Position.timestamp == subq.c.max_timestamp
            )
        ).filter(Position.position_amount != 0).all()
        
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
    
    # ==================== Order Analysis ====================
    
    def get_order_performance_metrics(
        self,
        strategy_id: Optional[str] = None,
        days: int = 7
    ) -> Dict[str, Any]:
        """
        Get order execution performance metrics.
        
        Args:
            strategy_id: Optional strategy filter
            days: Number of days to analyze
        
        Returns:
            Performance metrics
        """
        start_time = datetime.utcnow() - timedelta(days=days)
        
        query = self.session.query(Order).filter(
            Order.created_at >= start_time
        )
        
        if strategy_id:
            query = query.filter_by(strategy_id=strategy_id)
        
        orders = query.all()
        
        if not orders:
            return {"error": "No orders found"}
        
        total_orders = len(orders)
        filled_orders = [o for o in orders if o.status == "FILLED"]
        partially_filled = [o for o in orders if o.status == "PARTIALLY_FILLED"]
        canceled_orders = [o for o in orders if o.status == "CANCELED"]
        failed_orders = [o for o in orders if o.status == "FAILED"]
        
        # Calculate fill rates
        total_quantity = sum(float(o.quantity) for o in orders)
        filled_quantity = sum(float(o.filled_quantity) for o in orders)
        
        return {
            "period_days": days,
            "total_orders": total_orders,
            "filled_orders": len(filled_orders),
            "partially_filled_orders": len(partially_filled),
            "canceled_orders": len(canceled_orders),
            "failed_orders": len(failed_orders),
            "fill_rate": len(filled_orders) / total_orders if total_orders > 0 else 0,
            "quantity_fill_rate": filled_quantity / total_quantity if total_quantity > 0 else 0,
            "total_quantity": total_quantity,
            "filled_quantity": filled_quantity
        }
    
    def get_recent_signals(
        self,
        strategy_id: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get recent trading signals.
        
        Args:
            strategy_id: Optional strategy filter
            symbol: Optional symbol filter
            limit: Maximum number of signals to return
        
        Returns:
            List of signals
        """
        query = self.session.query(Signal)
        
        if strategy_id:
            query = query.filter_by(strategy_id=strategy_id)
        if symbol:
            query = query.filter_by(symbol=symbol)
        
        signals = query.order_by(desc(Signal.timestamp)).limit(limit).all()
        
        return [{
            "timestamp": s.timestamp.isoformat(),
            "strategy_id": s.strategy_id,
            "symbol": s.symbol,
            "signal_type": s.signal_type,
            "price": float(s.price) if s.price else None,
            "action": s.action,
            "order_mode": s.order_mode,
            "tags": s.tags
        } for s in signals]
