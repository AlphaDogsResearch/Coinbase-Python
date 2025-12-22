"""
SQLAlchemy ORM models for event tracking database.

Provides comprehensive tracking of trading events from order intent to fill,
with full audit trail and position tracking capabilities.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, DateTime, Numeric, Boolean, JSON, Index,
    create_engine, event
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import json

Base = declarative_base()


class TradingEvent(Base):
    """Master event log capturing all trading-related events."""
    
    __tablename__ = 'trading_events'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(50), nullable=False)  # ORDER_INTENT, ORDER_SUBMITTED, etc.
    timestamp = Column(DateTime, nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    strategy_id = Column(String(50), nullable=True)
    order_id = Column(String(100), nullable=True, index=True)
    client_id = Column(String(100), nullable=True)
    event_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_events_timestamp', 'timestamp'),
        Index('idx_events_symbol', 'symbol'),
        Index('idx_events_order_id', 'order_id'),
    )
    
    def __repr__(self):
        return f"<TradingEvent(id={self.id}, type={self.event_type}, symbol={self.symbol}, timestamp={self.timestamp})>"


class Order(Base):
    """Order lifecycle tracking with current state."""
    
    __tablename__ = 'orders'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(100), unique=True, nullable=False, index=True)
    client_id = Column(String(100), nullable=True)
    symbol = Column(String(20), nullable=False, index=True)
    strategy_id = Column(String(50), nullable=True, index=True)
    side = Column(String(10), nullable=False)  # BUY, SELL
    order_type = Column(String(20), nullable=False)  # MARKET, LIMIT, etc.
    price = Column(Numeric(20, 8), nullable=True)
    quantity = Column(Numeric(20, 8), nullable=False)
    filled_quantity = Column(Numeric(20, 8), nullable=False, default=0)
    remaining_quantity = Column(Numeric(20, 8), nullable=False)
    avg_fill_price = Column(Numeric(20, 8), nullable=True, default=0)
    status = Column(String(20), nullable=False, index=True)  # PENDING_NEW, NEW, FILLED, etc.
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    tags = Column(JSON, nullable=True)
    
    __table_args__ = (
        Index('idx_orders_symbol_status', 'symbol', 'status'),
        Index('idx_orders_strategy', 'strategy_id'),
    )
    
    def __repr__(self):
        return f"<Order(id={self.order_id}, symbol={self.symbol}, side={self.side}, status={self.status})>"


class Fill(Base):
    """Trade execution records."""
    
    __tablename__ = 'fills'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(100), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(10), nullable=False)  # BUY, SELL
    price = Column(Numeric(20, 8), nullable=False)
    quantity = Column(Numeric(20, 8), nullable=False)
    commission = Column(Numeric(20, 8), nullable=True, default=0)
    realized_pnl = Column(Numeric(20, 8), nullable=True, default=0)
    timestamp = Column(DateTime, nullable=False, index=True)
    is_maker = Column(Boolean, nullable=True)
    
    __table_args__ = (
        Index('idx_fills_order_id', 'order_id'),
        Index('idx_fills_timestamp', 'timestamp'),
    )
    
    def __repr__(self):
        return f"<Fill(order_id={self.order_id}, symbol={self.symbol}, qty={self.quantity}@{self.price})>"


class Position(Base):
    """Position state snapshots over time."""
    
    __tablename__ = 'positions'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    strategy_id = Column(String(50), nullable=True)
    position_amount = Column(Numeric(20, 8), nullable=False)
    entry_price = Column(Numeric(20, 8), nullable=True)
    unrealized_pnl = Column(Numeric(20, 8), nullable=True, default=0)
    realized_pnl = Column(Numeric(20, 8), nullable=True, default=0)
    total_trading_cost = Column(Numeric(20, 8), nullable=True, default=0)
    timestamp = Column(DateTime, nullable=False, index=True, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_positions_symbol_strategy', 'symbol', 'strategy_id', 'timestamp'),
    )
    
    def __repr__(self):
        return f"<Position(symbol={self.symbol}, strategy={self.strategy_id}, amount={self.position_amount})>"


class Signal(Base):
    """Trading signals generated by strategies."""
    
    __tablename__ = 'signals'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(String(50), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    signal_type = Column(Integer, nullable=False)  # -1, 0, 1
    price = Column(Numeric(20, 8), nullable=True)
    action = Column(String(20), nullable=True)  # Strategy action
    order_mode = Column(String(20), nullable=True)  # Order mode
    tags = Column(JSON, nullable=True)
    timestamp = Column(DateTime, nullable=False, index=True, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_signals_strategy', 'strategy_id'),
        Index('idx_signals_timestamp', 'timestamp'),
    )
    
    def __repr__(self):
        return f"<Signal(strategy={self.strategy_id}, symbol={self.symbol}, signal={self.signal_type})>"




def create_tables(engine):
    """Create all tables in the database."""
    Base.metadata.create_all(engine)


def get_session_maker(database_url: str):
    """
    Create a session maker for the database.
    
    Args:
        database_url: SQLAlchemy database URL (e.g., 'sqlite:///trading_events.db')
    
    Returns:
        SQLAlchemy sessionmaker
    """
    engine = create_engine(
        database_url,
        echo=False,  # Set to True for SQL debugging
        pool_pre_ping=True,  # Verify connections before using
        connect_args={"check_same_thread": False, "timeout": 30}  # SQLite specific settings
    )
    create_tables(engine)
    return sessionmaker(bind=engine), engine
