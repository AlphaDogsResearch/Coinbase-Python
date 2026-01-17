"""
DatabaseManager - SQLite persistence layer for the trading engine.

=============================================================================
TABLE SUMMARY (Write Points Reference)
=============================================================================
#  | Table           | Purpose                          | Write Point
---|-----------------|----------------------------------|----------------------------------
1  | engine_sessions | Engine start/stop audit trail    | main.py startup and shutdown
2  | orders          | All submitted orders             | OrderManager.submit_order_internal()
3  | order_events    | Fill/cancel events from exchange | OrderManager.on_order_event()
4  | positions       | Current position state           | PositionManager.update_or_add_position()
5  | trades          | Completed trade history with PnL | PositionManager.on_realized_pnl_update()
6  | strategy_state  | Crash recovery state             | Strategy.on_stop() / periodic
7  | signals         | Signal audit log with indicators | Strategy.on_signal()
=============================================================================
"""

import json
import logging
import sqlite3
from typing import Any, Dict, List, Optional

from engine.database.database_connection import DatabaseConnectionPool


class DatabaseManager:
    """
    Manages all database operations for the trading engine.

    Responsibilities:
    - Connection pool management
    - Table initialization
    - CRUD operations for all 7 tables
    - Session lifecycle tracking
    """

    def __init__(self, database_path: str = "trading.db", max_connections: int = 10):
        """
        Initialize DatabaseManager with connection pool.

        Args:
            database_path: Path to SQLite database file
            max_connections: Maximum number of pooled connections
        """
        self.database_path = database_path
        self.pool = DatabaseConnectionPool(database_path, max_connections)
        self._current_session_id: Optional[str] = None
        self._initialize_tables()
        logging.info(f"DatabaseManager initialized with database: {database_path}")

    def _initialize_tables(self):
        """Create all required tables on startup."""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()

            # ============================================================
            # TABLE 1: engine_sessions
            # Records engine start/stop events for auditing and debugging
            # ============================================================
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS engine_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT UNIQUE NOT NULL,
                    environment TEXT NOT NULL,
                    started_at INTEGER NOT NULL,
                    stopped_at INTEGER,
                    stop_reason TEXT,
                    config_hash TEXT,
                    symbols TEXT,
                    strategies TEXT,
                    hostname TEXT,
                    version TEXT
                )
            """
            )

            # ============================================================
            # TABLE 2: orders
            # All orders submitted by strategies
            # ============================================================
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    exchange_order_id TEXT,
                    session_id TEXT,
                    strategy_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL,
                    stop_price REAL,
                    filled_qty REAL DEFAULT 0,
                    avg_filled_price REAL DEFAULT 0,
                    status TEXT NOT NULL,
                    action TEXT,
                    tags TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES engine_sessions(session_id)
                )
            """
            )

            # ============================================================
            # TABLE 3: order_events
            # Fill events and status changes from exchange
            # ============================================================
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS order_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL,
                    exchange_order_id TEXT,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    filled_qty REAL DEFAULT 0,
                    filled_price REAL DEFAULT 0,
                    commission REAL DEFAULT 0,
                    commission_asset TEXT,
                    timestamp INTEGER NOT NULL,
                    raw_event TEXT,
                    FOREIGN KEY (order_id) REFERENCES orders(order_id)
                )
            """
            )

            # ============================================================
            # TABLE 4: positions
            # Current position state per strategy/symbol
            # ============================================================
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_id TEXT,
                    symbol TEXT NOT NULL,
                    side TEXT,
                    quantity REAL DEFAULT 0,
                    entry_price REAL DEFAULT 0,
                    mark_price REAL DEFAULT 0,
                    unrealized_pnl REAL DEFAULT 0,
                    realized_pnl REAL DEFAULT 0,
                    total_commission REAL DEFAULT 0,
                    updated_at INTEGER NOT NULL,
                    UNIQUE(strategy_id, symbol)
                )
            """
            )

            # ============================================================
            # TABLE 5: trades
            # Completed trade records (for PnL tracking)
            # ============================================================
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    strategy_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    pnl REAL DEFAULT 0,
                    commission REAL DEFAULT 0,
                    entry_time INTEGER NOT NULL,
                    exit_time INTEGER,
                    holding_bars INTEGER,
                    entry_order_id TEXT,
                    exit_order_id TEXT,
                    FOREIGN KEY (session_id) REFERENCES engine_sessions(session_id)
                )
            """
            )

            # ============================================================
            # TABLE 6: strategy_state
            # Strategy state snapshots for crash recovery
            # ============================================================
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_state (
                    strategy_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    state_json TEXT NOT NULL,
                    indicator_state TEXT,
                    position_json TEXT,
                    updated_at INTEGER NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES engine_sessions(session_id)
                )
            """
            )

            # ============================================================
            # TABLE 7: signals
            # Strategy signal decisions with full indicator context
            # ============================================================
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    strategy_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    signal INTEGER NOT NULL,
                    price REAL NOT NULL,
                    action TEXT,
                    reason TEXT NOT NULL,
                    indicators TEXT NOT NULL,
                    config TEXT,
                    candle_open REAL,
                    candle_high REAL,
                    candle_low REAL,
                    candle_close REAL,
                    candle_volume REAL,
                    timestamp INTEGER NOT NULL,
                    order_id TEXT,
                    FOREIGN KEY (session_id) REFERENCES engine_sessions(session_id)
                )
            """
            )

            # ============================================================
            # INDEXES for performance
            # ============================================================
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_strategy ON orders(strategy_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_session ON orders(session_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_order_events_order ON order_events(order_id)"
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_session ON trades(session_id)")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_signals_strategy ON signals(strategy_id)"
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_session ON signals(session_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp)")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_engine_sessions_env ON engine_sessions(environment)"
            )

            conn.commit()
            logging.info("Database tables and indexes initialized")

    # =========================================================================
    # ENGINE SESSION OPERATIONS
    # =========================================================================

    def start_session(
        self,
        session_id: str,
        environment: str,
        symbols: List[str],
        strategies: List[str],
        config_hash: str = None,
        hostname: str = None,
        version: str = None,
    ) -> bool:
        """
        Record engine session start.

        Args:
            session_id: Unique session identifier (UUID)
            environment: Environment name (development, uat, production)
            symbols: List of traded symbols
            strategies: List of active strategy IDs
            config_hash: Hash of configuration for tracking changes
            hostname: Machine hostname
            version: Application version

        Returns:
            True if successful, False otherwise
        """
        try:
            import time

            with self.pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO engine_sessions 
                    (session_id, environment, started_at, symbols, strategies, 
                     config_hash, hostname, version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        session_id,
                        environment,
                        int(time.time() * 1000),
                        json.dumps(symbols),
                        json.dumps(strategies),
                        config_hash,
                        hostname,
                        version,
                    ),
                )
                conn.commit()
                self._current_session_id = session_id
                logging.info(f"Session started: {session_id}")
                return True
        except sqlite3.Error as e:
            logging.error(f"Failed to start session: {e}")
            return False

    def stop_session(self, session_id: str, stop_reason: str = "graceful") -> bool:
        """
        Record engine session stop.

        Args:
            session_id: Session identifier to update
            stop_reason: Reason for stopping (graceful, crash, signal, etc.)

        Returns:
            True if successful, False otherwise
        """
        try:
            import time

            with self.pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE engine_sessions 
                    SET stopped_at = ?, stop_reason = ?
                    WHERE session_id = ?
                """,
                    (int(time.time() * 1000), stop_reason, session_id),
                )
                conn.commit()
                logging.info(f"Session stopped: {session_id} ({stop_reason})")
                return True
        except sqlite3.Error as e:
            logging.error(f"Failed to stop session: {e}")
            return False

    @property
    def current_session_id(self) -> Optional[str]:
        """Get the current session ID."""
        return self._current_session_id

    # =========================================================================
    # SIGNAL OPERATIONS
    # =========================================================================

    def insert_signal(
        self,
        strategy_id: str,
        symbol: str,
        signal: int,
        price: float,
        reason: str,
        indicators: Dict[str, Any],
        action: str = None,
        config: Dict[str, Any] = None,
        candle: Dict[str, float] = None,
        order_id: str = None,
    ) -> bool:
        """
        Insert a signal record with full indicator context.

        Args:
            strategy_id: Strategy that generated the signal
            symbol: Trading symbol
            signal: Signal value (1=BUY, -1=SELL, 0=HOLD)
            price: Price at signal time
            reason: Human-readable reason for the signal
            indicators: Dict of indicator values at signal time
            action: Action type (ENTRY, CLOSE, STOP_LOSS)
            config: Strategy configuration snapshot
            candle: OHLCV candle data
            order_id: Resulting order ID if order was submitted

        Returns:
            True if successful, False otherwise
        """
        try:
            import time

            with self.pool.get_connection() as conn:
                cursor = conn.cursor()

                candle_open = candle.get("open") if candle else None
                candle_high = candle.get("high") if candle else None
                candle_low = candle.get("low") if candle else None
                candle_close = candle.get("close") if candle else None
                candle_volume = candle.get("volume") if candle else None

                cursor.execute(
                    """
                    INSERT INTO signals 
                    (session_id, strategy_id, symbol, signal, price, action, reason,
                     indicators, config, candle_open, candle_high, candle_low, 
                     candle_close, candle_volume, timestamp, order_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        self._current_session_id,
                        strategy_id,
                        symbol,
                        signal,
                        price,
                        action,
                        reason,
                        json.dumps(indicators),
                        json.dumps(config) if config else None,
                        candle_open,
                        candle_high,
                        candle_low,
                        candle_close,
                        candle_volume,
                        int(time.time() * 1000),
                        order_id,
                    ),
                )
                conn.commit()
                logging.debug(f"Signal recorded: {strategy_id} {signal} {reason}")
                return True
        except sqlite3.Error as e:
            logging.error(f"Failed to insert signal: {e}")
            return False

    def get_signals_by_strategy(self, strategy_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent signals for a strategy."""
        with self.pool.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM signals 
                WHERE strategy_id = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            """,
                (strategy_id, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_signals_by_session(self, session_id: str = None) -> List[Dict[str, Any]]:
        """Get all signals for a session (defaults to current session)."""
        session = session_id or self._current_session_id
        with self.pool.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM signals 
                WHERE session_id = ? 
                ORDER BY timestamp ASC
            """,
                (session,),
            )
            return [dict(row) for row in cursor.fetchall()]

    # =========================================================================
    # ORDER OPERATIONS
    # =========================================================================

    def insert_order(self, order: Dict[str, Any]) -> bool:
        """
        Insert a new order record.

        Args:
            order: Order data dict with keys:
                - order_id, strategy_id, symbol, side, order_type
                - quantity, price (optional), status, timestamp
                - action (optional), tags (optional)

        Returns:
            True if successful, False otherwise
        """
        try:
            with self.pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO orders 
                    (order_id, session_id, strategy_id, symbol, side, order_type, 
                     quantity, price, stop_price, status, action, tags, 
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        order["order_id"],
                        self._current_session_id,
                        order["strategy_id"],
                        order["symbol"],
                        order["side"],
                        order["order_type"],
                        order["quantity"],
                        order.get("price"),
                        order.get("stop_price"),
                        order["status"],
                        order.get("action"),
                        json.dumps(order.get("tags")) if order.get("tags") else None,
                        order["timestamp"],
                        order["timestamp"],
                    ),
                )
                conn.commit()
                logging.debug(f"Order inserted: {order['order_id']}")
                return True
        except sqlite3.Error as e:
            logging.error(f"Failed to insert order: {e}")
            return False

    def update_order_status(
        self,
        order_id: str,
        status: str,
        exchange_order_id: str = None,
        filled_qty: float = None,
        avg_price: float = None,
    ) -> bool:
        """
        Update order status and fill information.

        Args:
            order_id: Internal order ID
            status: New order status
            exchange_order_id: Exchange's order ID (on first ACK)
            filled_qty: Total filled quantity
            avg_price: Average fill price

        Returns:
            True if successful, False otherwise
        """
        try:
            import time

            with self.pool.get_connection() as conn:
                cursor = conn.cursor()
                updates = ["status = ?", "updated_at = ?"]
                params = [status, int(time.time() * 1000)]

                if exchange_order_id is not None:
                    updates.append("exchange_order_id = ?")
                    params.append(exchange_order_id)
                if filled_qty is not None:
                    updates.append("filled_qty = ?")
                    params.append(filled_qty)
                if avg_price is not None:
                    updates.append("avg_filled_price = ?")
                    params.append(avg_price)

                params.append(order_id)
                cursor.execute(
                    f"UPDATE orders SET {', '.join(updates)} WHERE order_id = ?",
                    params,
                )
                conn.commit()
                logging.debug(f"Order updated: {order_id} -> {status}")
                return True
        except sqlite3.Error as e:
            logging.error(f"Failed to update order: {e}")
            return False

    def get_open_orders(self, strategy_id: str = None) -> List[Dict[str, Any]]:
        """Get all open orders, optionally filtered by strategy."""
        with self.pool.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if strategy_id:
                cursor.execute(
                    """
                    SELECT * FROM orders 
                    WHERE status IN ('PENDING_NEW', 'NEW', 'PARTIALLY_FILLED') 
                    AND strategy_id = ?
                """,
                    (strategy_id,),
                )
            else:
                cursor.execute(
                    """
                    SELECT * FROM orders 
                    WHERE status IN ('PENDING_NEW', 'NEW', 'PARTIALLY_FILLED')
                """
                )
            return [dict(row) for row in cursor.fetchall()]

    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get a single order by ID."""
        with self.pool.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # =========================================================================
    # ORDER EVENT OPERATIONS
    # =========================================================================

    def insert_order_event(
        self,
        order_id: str,
        event_type: str,
        status: str,
        exchange_order_id: str = None,
        filled_qty: float = 0,
        filled_price: float = 0,
        commission: float = 0,
        commission_asset: str = None,
        raw_event: str = None,
    ) -> bool:
        """
        Insert an order event (fill, cancel, etc.).

        Args:
            order_id: Internal order ID
            event_type: Event type (NEW, PARTIAL_FILL, FILL, CANCEL, REJECT)
            status: Order status after this event
            exchange_order_id: Exchange's order ID
            filled_qty: Quantity filled in this event
            filled_price: Price of this fill
            commission: Commission charged
            commission_asset: Asset commission was charged in
            raw_event: Raw event JSON from exchange

        Returns:
            True if successful, False otherwise
        """
        try:
            import time

            with self.pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO order_events 
                    (order_id, exchange_order_id, event_type, status, filled_qty,
                     filled_price, commission, commission_asset, timestamp, raw_event)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        order_id,
                        exchange_order_id,
                        event_type,
                        status,
                        filled_qty,
                        filled_price,
                        commission,
                        commission_asset,
                        int(time.time() * 1000),
                        raw_event,
                    ),
                )
                conn.commit()
                logging.debug(f"Order event inserted: {order_id} {event_type}")
                return True
        except sqlite3.Error as e:
            logging.error(f"Failed to insert order event: {e}")
            return False

    def get_order_events(self, order_id: str) -> List[Dict[str, Any]]:
        """Get all events for an order."""
        with self.pool.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM order_events 
                WHERE order_id = ? 
                ORDER BY timestamp ASC
            """,
                (order_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    # =========================================================================
    # POSITION OPERATIONS
    # =========================================================================

    def upsert_position(self, position: Dict[str, Any]) -> bool:
        """
        Insert or update a position.

        Args:
            position: Position data dict with keys:
                - symbol, strategy_id (optional)
                - side, quantity, entry_price
                - unrealized_pnl, realized_pnl (optional)

        Returns:
            True if successful, False otherwise
        """
        try:
            import time

            with self.pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO positions 
                    (strategy_id, symbol, side, quantity, entry_price, mark_price,
                     unrealized_pnl, realized_pnl, total_commission, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(strategy_id, symbol) DO UPDATE SET
                        side = excluded.side,
                        quantity = excluded.quantity,
                        entry_price = excluded.entry_price,
                        mark_price = excluded.mark_price,
                        unrealized_pnl = excluded.unrealized_pnl,
                        realized_pnl = excluded.realized_pnl,
                        total_commission = excluded.total_commission,
                        updated_at = excluded.updated_at
                """,
                    (
                        position.get("strategy_id"),
                        position["symbol"],
                        position.get("side"),
                        position.get("quantity", 0),
                        position.get("entry_price", 0),
                        position.get("mark_price", 0),
                        position.get("unrealized_pnl", 0),
                        position.get("realized_pnl", 0),
                        position.get("total_commission", 0),
                        int(time.time() * 1000),
                    ),
                )
                conn.commit()
                logging.debug(
                    f"Position upserted: {position.get('strategy_id')} {position['symbol']}"
                )
                return True
        except sqlite3.Error as e:
            logging.error(f"Failed to upsert position: {e}")
            return False

    def get_positions(self, strategy_id: str = None) -> List[Dict[str, Any]]:
        """Get all positions, optionally filtered by strategy."""
        with self.pool.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if strategy_id:
                cursor.execute(
                    """
                    SELECT * FROM positions 
                    WHERE strategy_id = ? AND quantity != 0
                """,
                    (strategy_id,),
                )
            else:
                cursor.execute("SELECT * FROM positions WHERE quantity != 0")
            return [dict(row) for row in cursor.fetchall()]

    def get_position(self, symbol: str, strategy_id: str = None) -> Optional[Dict[str, Any]]:
        """Get a specific position."""
        with self.pool.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if strategy_id:
                cursor.execute(
                    """
                    SELECT * FROM positions 
                    WHERE symbol = ? AND strategy_id = ?
                """,
                    (symbol, strategy_id),
                )
            else:
                cursor.execute(
                    """
                    SELECT * FROM positions 
                    WHERE symbol = ? AND strategy_id IS NULL
                """,
                    (symbol,),
                )
            row = cursor.fetchone()
            return dict(row) if row else None

    # =========================================================================
    # TRADE OPERATIONS
    # =========================================================================

    def insert_trade(self, trade: Dict[str, Any]) -> bool:
        """
        Record a completed trade.

        Args:
            trade: Trade data dict with keys:
                - strategy_id, symbol, side, quantity, entry_price
                - exit_price, pnl, commission, entry_time, exit_time
                - holding_bars (optional), entry_order_id, exit_order_id (optional)

        Returns:
            True if successful, False otherwise
        """
        try:
            with self.pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO trades 
                    (session_id, strategy_id, symbol, side, quantity, entry_price,
                     exit_price, pnl, commission, entry_time, exit_time, 
                     holding_bars, entry_order_id, exit_order_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        self._current_session_id,
                        trade["strategy_id"],
                        trade["symbol"],
                        trade["side"],
                        trade["quantity"],
                        trade["entry_price"],
                        trade.get("exit_price"),
                        trade.get("pnl", 0),
                        trade.get("commission", 0),
                        trade["entry_time"],
                        trade.get("exit_time"),
                        trade.get("holding_bars"),
                        trade.get("entry_order_id"),
                        trade.get("exit_order_id"),
                    ),
                )
                conn.commit()
                logging.debug(f"Trade inserted: {trade['strategy_id']} {trade['symbol']}")
                return True
        except sqlite3.Error as e:
            logging.error(f"Failed to insert trade: {e}")
            return False

    def get_trades_by_strategy(self, strategy_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent trades for a strategy."""
        with self.pool.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM trades 
                WHERE strategy_id = ? 
                ORDER BY entry_time DESC 
                LIMIT ?
            """,
                (strategy_id, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_trades_by_session(self, session_id: str = None) -> List[Dict[str, Any]]:
        """Get all trades for a session (defaults to current session)."""
        session = session_id or self._current_session_id
        with self.pool.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM trades 
                WHERE session_id = ? 
                ORDER BY entry_time ASC
            """,
                (session,),
            )
            return [dict(row) for row in cursor.fetchall()]

    # =========================================================================
    # STRATEGY STATE OPERATIONS
    # =========================================================================

    def save_strategy_state(
        self,
        strategy_id: str,
        state: Dict[str, Any],
        indicator_state: Dict[str, Any] = None,
        position: Dict[str, Any] = None,
    ) -> bool:
        """
        Save strategy state for crash recovery.

        Args:
            strategy_id: Strategy identifier
            state: General strategy state dict
            indicator_state: Indicator values and buffers
            position: Current position info

        Returns:
            True if successful, False otherwise
        """
        try:
            import time

            with self.pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO strategy_state 
                    (strategy_id, session_id, state_json, indicator_state, 
                     position_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(strategy_id) DO UPDATE SET
                        session_id = excluded.session_id,
                        state_json = excluded.state_json,
                        indicator_state = excluded.indicator_state,
                        position_json = excluded.position_json,
                        updated_at = excluded.updated_at
                """,
                    (
                        strategy_id,
                        self._current_session_id,
                        json.dumps(state),
                        json.dumps(indicator_state) if indicator_state else None,
                        json.dumps(position) if position else None,
                        int(time.time() * 1000),
                    ),
                )
                conn.commit()
                logging.debug(f"Strategy state saved: {strategy_id}")
                return True
        except sqlite3.Error as e:
            logging.error(f"Failed to save strategy state: {e}")
            return False

    def load_strategy_state(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        """
        Load strategy state for recovery.

        Args:
            strategy_id: Strategy identifier

        Returns:
            Dict with state_json, indicator_state, position_json or None
        """
        with self.pool.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT state_json, indicator_state, position_json, updated_at 
                FROM strategy_state 
                WHERE strategy_id = ?
            """,
                (strategy_id,),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "state": json.loads(row["state_json"]),
                    "indicators": (
                        json.loads(row["indicator_state"]) if row["indicator_state"] else None
                    ),
                    "position": json.loads(row["position_json"]) if row["position_json"] else None,
                    "updated_at": row["updated_at"],
                }
            return None

    def clear_strategy_state(self, strategy_id: str) -> bool:
        """Clear strategy state (e.g., after successful recovery)."""
        try:
            with self.pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM strategy_state WHERE strategy_id = ?",
                    (strategy_id,),
                )
                conn.commit()
                return True
        except sqlite3.Error as e:
            logging.error(f"Failed to clear strategy state: {e}")
            return False

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def close(self):
        """Clean shutdown - close all connections."""
        self.pool.close_all()
        logging.info("DatabaseManager closed")

    def get_session_summary(self, session_id: str = None) -> Dict[str, Any]:
        """Get summary statistics for a session."""
        session = session_id or self._current_session_id
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()

            # Get session info
            cursor.execute("SELECT * FROM engine_sessions WHERE session_id = ?", (session,))
            session_row = cursor.fetchone()

            # Get counts
            cursor.execute("SELECT COUNT(*) FROM orders WHERE session_id = ?", (session,))
            order_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM signals WHERE session_id = ?", (session,))
            signal_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*), SUM(pnl) FROM trades WHERE session_id = ?", (session,))
            trade_row = cursor.fetchone()
            trade_count = trade_row[0] or 0
            total_pnl = trade_row[1] or 0

            return {
                "session_id": session,
                "order_count": order_count,
                "signal_count": signal_count,
                "trade_count": trade_count,
                "total_pnl": total_pnl,
            }
