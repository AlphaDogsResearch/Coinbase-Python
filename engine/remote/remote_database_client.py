"""
RemoteDatabaseClient - Read-only REST API that exposes trading.db over HTTP.

Runs a FastAPI server on a configurable host/port so external consumers can
query all 7 tables without direct database access.

Error handling:
  - trading.db missing or inaccessible  → 503 Service Unavailable
  - Row not found (single-item lookups) → 404 Not Found
  - Empty collection (list endpoints)   → 200 with empty list []
"""

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query

# Fields stored as JSON strings in the DB that should be deserialized in responses.
_JSON_FIELDS = {
    "symbols", "strategies", "tags",
    "indicators", "config",
    "state_json", "indicator_state", "position_json",
    "raw_event",
}


def _deserialize_row(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a sqlite3.Row to a plain dict, parsing stored JSON strings."""
    result = dict(row)
    for key, val in result.items():
        if key in _JSON_FIELDS and isinstance(val, str):
            try:
                result[key] = json.loads(val)
            except (json.JSONDecodeError, ValueError):
                pass
    return result


class RemoteDatabaseClient:
    """
    Read-only REST API server that exposes trading.db over HTTP.

    Endpoints
    ---------
    GET /health
    GET /sessions                  ?limit=
    GET /sessions/{session_id}
    GET /orders                    ?strategy_id= &symbol= &status= &limit=
    GET /orders/{order_id}
    GET /orders/{order_id}/events
    GET /positions                 ?strategy_id=
    GET /positions/{symbol}        ?strategy_id=
    GET /trades                    ?strategy_id= &session_id= &limit=
    GET /signals                   ?strategy_id= &session_id= &limit=

    Usage
    -----
        client = RemoteDatabaseClient(database_path="trading.db", host="0.0.0.0", port=8889)
        client.run()   # starts uvicorn in a background daemon thread
    """

    def __init__(
        self,
        database_path: str = "trading.db",
        host: str = "0.0.0.0",
        port: int = 8889,
    ):
        self.database_path = database_path
        self.host = host
        self.port = port
        self.logger = logging.getLogger(self.__class__.__name__)
        self.app = self._build_app()

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    def _db_exists(self) -> bool:
        return os.path.isfile(self.database_path)

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Open a read-only SQLite connection via URI.
        Raises HTTP 503 if the database file is missing or locked.
        """
        if not self._db_exists():
            raise HTTPException(
                status_code=503,
                detail=f"Database not available: '{self.database_path}' does not exist.",
            )
        try:
            uri = f"file:{self.database_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()
        except sqlite3.OperationalError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Database unavailable: {exc}",
            )

    def _fetch_all(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            cursor = conn.execute(sql, params)
            return [_deserialize_row(row) for row in cursor.fetchall()]

    def _fetch_one(self, sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        with self._connection() as conn:
            cursor = conn.execute(sql, params)
            row = cursor.fetchone()
            return _deserialize_row(row) if row else None

    # ------------------------------------------------------------------
    # FastAPI app + routes
    # ------------------------------------------------------------------

    def _build_app(self) -> FastAPI:
        app = FastAPI(
            title="Trading DB API",
            description="Read-only REST API for trading.db",
            version="1.0.0",
        )

        # ----------------------------------------------------------------
        # Health
        # ----------------------------------------------------------------

        @app.get("/health", summary="Database availability check")
        def health():
            available = self._db_exists()
            return {
                "status": "ok" if available else "unavailable",
                "database": self.database_path,
                "available": available,
            }

        # ----------------------------------------------------------------
        # Sessions
        # ----------------------------------------------------------------

        @app.get("/sessions", summary="List engine sessions")
        def get_sessions(limit: int = Query(100, ge=1, le=1000)):
            return self._fetch_all(
                "SELECT * FROM engine_sessions ORDER BY started_at DESC LIMIT ?",
                (limit,),
            )

        @app.get("/sessions/{session_id}", summary="Get a single session with summary stats")
        def get_session(session_id: str):
            row = self._fetch_one(
                "SELECT * FROM engine_sessions WHERE session_id = ?",
                (session_id,),
            )
            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Session '{session_id}' not found.",
                )
            with self._connection() as conn:
                order_count = conn.execute(
                    "SELECT COUNT(*) FROM orders WHERE session_id = ?", (session_id,)
                ).fetchone()[0]
                signal_count = conn.execute(
                    "SELECT COUNT(*) FROM signals WHERE session_id = ?", (session_id,)
                ).fetchone()[0]
                trade_row = conn.execute(
                    "SELECT COUNT(*), SUM(pnl) FROM trades WHERE session_id = ?", (session_id,)
                ).fetchone()
            row["summary"] = {
                "order_count": order_count,
                "signal_count": signal_count,
                "trade_count": trade_row[0] or 0,
                "total_pnl": trade_row[1] or 0.0,
            }
            return row

        # ----------------------------------------------------------------
        # Orders
        # ----------------------------------------------------------------

        @app.get("/orders", summary="List orders")
        def get_orders(
            strategy_id: Optional[str] = None,
            symbol: Optional[str] = None,
            status: Optional[str] = None,
            limit: int = Query(100, ge=1, le=1000),
        ):
            clauses: List[str] = []
            params: List[Any] = []
            if strategy_id:
                clauses.append("strategy_id = ?")
                params.append(strategy_id)
            if symbol:
                clauses.append("symbol = ?")
                params.append(symbol)
            if status:
                clauses.append("status = ?")
                params.append(status)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            params.append(limit)
            return self._fetch_all(
                f"SELECT * FROM orders {where} ORDER BY created_at DESC LIMIT ?",
                tuple(params),
            )

        @app.get("/orders/{order_id}", summary="Get a single order")
        def get_order(order_id: str):
            row = self._fetch_one(
                "SELECT * FROM orders WHERE order_id = ?", (order_id,)
            )
            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Order '{order_id}' not found.",
                )
            return row

        @app.get("/orders/{order_id}/events", summary="Get fill/status events for an order")
        def get_order_events(order_id: str):
            return self._fetch_all(
                "SELECT * FROM order_events WHERE order_id = ? ORDER BY timestamp ASC",
                (order_id,),
            )

        # ----------------------------------------------------------------
        # Positions
        # ----------------------------------------------------------------

        @app.get("/positions", summary="List all positions")
        def get_positions(strategy_id: Optional[str] = None):
            if strategy_id:
                return self._fetch_all(
                    "SELECT * FROM positions WHERE strategy_id = ?", (strategy_id,)
                )
            return self._fetch_all("SELECT * FROM positions ORDER BY updated_at DESC")

        @app.get("/positions/{symbol}", summary="Get position for a symbol")
        def get_position(symbol: str, strategy_id: Optional[str] = None):
            if strategy_id:
                row = self._fetch_one(
                    "SELECT * FROM positions WHERE symbol = ? AND strategy_id = ?",
                    (symbol, strategy_id),
                )
            else:
                row = self._fetch_one(
                    "SELECT * FROM positions WHERE symbol = ? ORDER BY updated_at DESC",
                    (symbol,),
                )
            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Position for '{symbol}' not found.",
                )
            return row

        # ----------------------------------------------------------------
        # Trades
        # ----------------------------------------------------------------

        @app.get("/trades", summary="List completed trades")
        def get_trades(
            strategy_id: Optional[str] = None,
            session_id: Optional[str] = None,
            limit: int = Query(100, ge=1, le=1000),
        ):
            clauses: List[str] = []
            params: List[Any] = []
            if strategy_id:
                clauses.append("strategy_id = ?")
                params.append(strategy_id)
            if session_id:
                clauses.append("session_id = ?")
                params.append(session_id)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            params.append(limit)
            return self._fetch_all(
                f"SELECT * FROM trades {where} ORDER BY entry_time DESC LIMIT ?",
                tuple(params),
            )

        # ----------------------------------------------------------------
        # Signals
        # ----------------------------------------------------------------

        @app.get("/signals", summary="List strategy signals")
        def get_signals(
            strategy_id: Optional[str] = None,
            session_id: Optional[str] = None,
            limit: int = Query(100, ge=1, le=1000),
        ):
            clauses: List[str] = []
            params: List[Any] = []
            if strategy_id:
                clauses.append("strategy_id = ?")
                params.append(strategy_id)
            if session_id:
                clauses.append("session_id = ?")
                params.append(session_id)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            params.append(limit)
            return self._fetch_all(
                f"SELECT * FROM signals {where} ORDER BY timestamp DESC LIMIT ?",
                tuple(params),
            )

        return app

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------

    def run(self):
        """Start the API server in a background daemon thread."""
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="warning",
        )
        server = uvicorn.Server(config)

        thread = threading.Thread(
            target=server.run,
            name="RemoteDatabaseClient",
            daemon=True,
        )
        thread.start()
        self.logger.info(
            f"RemoteDatabaseClient started on http://{self.host}:{self.port}"
        )
