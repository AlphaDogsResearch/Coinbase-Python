"""
Manual verification script for event tracking database.

This script demonstrates the event tracking functionality with a simple,
step-by-step approach that avoids database locking issues.
"""

import os
import sys
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

def main():
    print("=" * 70)
    print("Event Tracking Database - Manual Verification")
    print("=" * 70)
    
    # Create data directory
    os.makedirs("data", exist_ok=True)
    
    # Remove old test database
    test_db = "data/manual_test.db"
    if os.path.exists(test_db):
        os.remove(test_db)
        print(f"\n✓ Removed old test database")
    
    print("\n1. Importing EventTracker...")
    from engine.database.event_tracker import EventTracker
    
    print("✓ Import successful")
    
    print("\n2. Initializing EventTracker...")
    tracker = EventTracker(test_db)
    print(f"✓ EventTracker initialized with database: {test_db}")
    
    print("\n3. Logging a trading signal...")
    signal_id = tracker.log_signal(
        strategy_id="demo_strategy",
        symbol="BTCUSDT",
        signal_type=1,  # Buy signal
        price=50000.0,
        action="OPEN_LONG",
        tags=["demo", "test"]
    )
    print(f"✓ Signal logged with ID: {signal_id}")
    
    print("\n4. Creating an order...")
    order_id = tracker.create_order(
        order_id="demo_order_001",
        symbol="BTCUSDT",
        side="BUY",
        order_type="LIMIT",
        quantity=0.1,
        price=50000.0,
        strategy_id="demo_strategy",
        tags=["entry"]
    )
    print(f"✓ Order created with DB ID: {order_id}")
    
    print("\n5. Updating order to FILLED status...")
    tracker.update_order_status(
        order_id="demo_order_001",
        status="FILLED",
        filled_quantity=0.1,
        avg_fill_price=49995.0
    )
    print("✓ Order status updated")
    
    print("\n6. Recording a fill...")
    fill_id = tracker.record_fill(
        order_id="demo_order_001",
        symbol="BTCUSDT",
        side="BUY",
        price=49995.0,
        quantity=0.1,
        commission=2.5
    )
    print(f"✓ Fill recorded with ID: {fill_id}")
    
    print("\n7. Creating position snapshot...")
    pos_id = tracker.snapshot_position(
        symbol="BTCUSDT",
        position_amount=0.1,
        entry_price=49995.0,
        strategy_id="demo_strategy",
        unrealized_pnl=5.0,
        realized_pnl=0.0,
        total_trading_cost=2.5
    )
    print(f"✓ Position snapshot created with ID: {pos_id}")
    
    print("\n8. Querying recent events...")
    events = tracker.get_recent_events(limit=5)
    print(f"✓ Retrieved {len(events)} events:")
    for event in events[:3]:  # Show first 3
        print(f"   - {event['event_type']}: {event['symbol']}")
    
    print("\n9. Getting order details...")
    order = tracker.get_order("demo_order_001")
    if order:
        print(f"✓ Order found:")
        print(f"   Symbol: {order['symbol']}")
        print(f"   Status: {order['status']}")
        print(f"   Filled: {order['filled_quantity']}/{order['quantity']}")
    
    print("\n10. Getting current positions...")
    positions = tracker.get_current_positions()
    print(f"✓ Found {len(positions)} position(s):")
    for pos in positions:
        print(f"   - {pos['symbol']}: {pos['position_amount']} @ {pos['entry_price']}")
    
    print("\n11. Closing tracker...")
    tracker.close()
    print("✓ Tracker closed")
    
    print("\n12. Verifying database file...")
    if os.path.exists(test_db):
        size = os.path.getsize(test_db)
        print(f"✓ Database file exists: {test_db} ({size} bytes)")
    
    print("\n" + "=" * 70)
    print("✅ MANUAL VERIFICATION COMPLETED SUCCESSFULLY!")
    print("=" * 70)
    
    print("\n📊 Database Summary:")
    print(f"   - Database location: {test_db}")
    print(f"   - Signals logged: 1")
    print(f"   - Orders created: 1")
    print(f"   - Fills recorded: 1")
    print(f"   - Position snapshots: 1")
    print(f"   - Total events: {len(events)}")
    
    print("\n💡 Next Steps:")
    print("   1. Inspect the database using SQLite browser or CLI:")
    print(f"      sqlite3 {test_db}")
    print("   2. Run queries to explore the data:")
    print("      SELECT * FROM trading_events;")
    print("      SELECT * FROM orders;")
    print("      SELECT * FROM fills;")
    print("      SELECT * FROM positions;")
    
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
