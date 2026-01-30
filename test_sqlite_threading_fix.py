"""
Test to verify SQLite threading fix.

This test demonstrates that the database connection pool can now be used
safely across multiple threads without raising the threading error.
"""
import os
import tempfile
import threading
import time
from engine.database.database_connection import DatabaseConnectionPool


def test_cross_thread_connection_usage():
    """Test that connections can be used across different threads."""
    # Create a temporary database file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.db') as f:
        db_path = f.name
    
    try:
        # Create connection pool
        pool = DatabaseConnectionPool(db_path, max_connections=2)
        
        # Create a table using connection from thread 1
        def create_table():
            with pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS test_table (
                        id INTEGER PRIMARY KEY,
                        value TEXT,
                        thread_id INTEGER
                    )
                """)
                conn.commit()
                print(f"Table created in thread {threading.current_thread().ident}")
        
        # Insert data using connection from thread 2
        def insert_data(value):
            with pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO test_table (value, thread_id) VALUES (?, ?)",
                    (value, threading.current_thread().ident)
                )
                conn.commit()
                print(f"Data inserted in thread {threading.current_thread().ident}")
        
        # Query data using connection from thread 3
        def query_data():
            with pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM test_table")
                count = cursor.fetchone()[0]
                print(f"Data queried in thread {threading.current_thread().ident}: {count} rows")
                return count
        
        # Run operations in different threads
        t1 = threading.Thread(target=create_table)
        t1.start()
        t1.join()
        
        threads = []
        for i in range(5):
            t = threading.Thread(target=insert_data, args=(f"value_{i}",))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        t3 = threading.Thread(target=query_data)
        t3.start()
        t3.join()
        
        # Verify data was inserted correctly
        with pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM test_table")
            count = cursor.fetchone()[0]
            assert count == 5, f"Expected 5 rows, got {count}"
            print(f"✓ Test passed: {count} rows inserted successfully across multiple threads")
        
        # Close all connections
        pool.close_all()
        
    finally:
        # Clean up temporary database file
        if os.path.exists(db_path):
            os.unlink(db_path)


if __name__ == "__main__":
    print("Testing SQLite threading fix...")
    try:
        test_cross_thread_connection_usage()
        print("\n✓ All tests passed! The SQLite threading bug has been fixed.")
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
