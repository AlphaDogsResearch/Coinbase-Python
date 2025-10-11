from engine.database.database_connection import DatabaseConnectionPool


def main():
    pool = DatabaseConnectionPool("crypto.db", max_connections=100)

    # Use the pool
    with pool.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS crypto_order_table ("+
                        "order_id TEXT PRIMARY KEY,"+
                        "side TEXT NOT NULL,"+
                        "quantity REAL NOT NULL,"+
                        "leaves_qty REAL NOT NULL,"+
                        "filled_qty REAL DEFAULT 0,"+
                        "symbol TEXT NOT NULL,"+
                        "timestamp INTEGER NOT NULL,"+
                        "price REAL NOT NULL,"+
                        "avg_filled_price REAL DEFAULT 0,"+
                        "total_amount REAL DEFAULT 0,"+
                        "type TEXT NOT NULL,"+
                        "order_status TEXT NOT NULL,"+
                        "strategy_id TEXT NOT NULL)")

        cursor.execute("CREATE TABLE IF NOT EXISTS crypto_order_event_table ("+
                        "id INTEGER PRIMARY KEY AUTOINCREMENT,"+
                        "contract_name TEXT NOT NULL,"+
                        "order_id TEXT NOT NULL,"+
                        "client_id TEXT NOT NULL,"+
                        "execution_type TEXT NOT NULL,"+
                        "status TEXT NOT NULL,"+
                        "canceled_reason TEXT,"+
                        "order_type TEXT NOT NULL,"+
                        "side TEXT,"+
                        "last_filled_time INTEGER,"+
                        "last_filled_price REAL DEFAULT 0,"+
                        "last_filled_quantity REAL DEFAULT 0,"+
                        "FOREIGN KEY (order_id) REFERENCES order_table(order_id))")
        conn.commit()
