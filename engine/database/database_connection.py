import logging
import queue
import sqlite3
import threading
from contextlib import contextmanager


class DatabaseConnectionPool:
    def __init__(self, database_path: str, max_connections: int = 10):
        self.database_path = database_path
        self.max_connections = max_connections
        self._pool = queue.Queue(maxsize=max_connections)
        self._connections_created = 0
        self._lock = threading.Lock()

    def _create_connection(self) -> sqlite3.Connection:
        logging.info("Creating database connection")
        """Create a new database connection"""
        conn = sqlite3.connect(self.database_path)
        self._connections_created += 1
        return conn

    @contextmanager
    def get_connection(self):
        """Get a connection from the pool (context manager)"""
        conn = None
        try:
            # Try to get from pool or create new one
            if not self._pool.empty() or self._connections_created < self.max_connections:
                with self._lock:
                    if self._pool.empty() and self._connections_created < self.max_connections:
                        conn = self._create_connection()
                    else:
                        conn = self._pool.get_nowait()
            else:
                conn = self._pool.get()  # Wait for available connection

            yield conn
        finally:
            if conn:
                try:
                    self._pool.put_nowait(conn)
                except queue.Full:
                    conn.close()  # Close if pool is full

    def close_all(self):
        """Close all connections in the pool"""
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except queue.Empty:
                break