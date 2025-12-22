"""
Simple test script to verify event tracking database functionality.

Run this script to test the event tracking system:
    python engine/database/test_event_tracker.py
"""

import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from engine.database.event_tracker import EventTracker
from engine.database.event_queries import EventQueries


def test_basic_operations():
    """Test basic event tracking operations."""
    print("=" * 60)
    print("Testing Basic Event Tracking Operations")
    print("=" * 60)
    
    # Initialize tracker with test database
    tracker = EventTracker("data/test_trading_events.db")
    
    # Test 1: Log a signal
    print("\n1. Logging a signal...")
    signal_id = tracker.log_signal(
        strategy_id="test_strategy",
        symbol="BTCUSDT",
        signal_type=1,
        price=50000.0,
        action="OPEN_LONG",
        tags=["test", "momentum"]
    )
    print(f"   ✓ Signal logged with ID: {signal_id}")
    
    # Test 2: Create an order
    print("\n2. Creating an order...")
    order_db_id = tracker.create_order(
        order_id="test_order_001",
        symbol="BTCUSDT",
        side="BUY",
        order_type="LIMIT",
        quantity=0.1,
        price=50000.0,
        client_id="client_001",
        strategy_id="test_strategy",
        tags=["entry", "long"]
    )
    print(f"   ✓ Order created with DB ID: {order_db_id}")
    
    # Test 3: Update order status
    print("\n3. Updating order status to FILLED...")
    tracker.update_order_status(
        order_id="test_order_001",
        status="FILLED",
        filled_quantity=0.1,
        avg_fill_price=49995.0
    )
    print("   ✓ Order status updated")
    
    # Test 4: Record a fill
    print("\n4. Recording a fill...")
    fill_id = tracker.record_fill(
        order_id="test_order_001",
        symbol="BTCUSDT",
        side="BUY",
        price=49995.0,
        quantity=0.1,
        commission=2.5,
        is_maker=True
    )
    print(f"   ✓ Fill recorded with ID: {fill_id}")
    
    # Test 5: Snapshot position
    print("\n5. Creating position snapshot...")
    position_id = tracker.snapshot_position(
        symbol="BTCUSDT",
        position_amount=0.1,
        entry_price=49995.0,
        strategy_id="test_strategy",
        unrealized_pnl=5.0,
        realized_pnl=0.0,
        total_trading_cost=2.5
    )
    print(f"   ✓ Position snapshot created with ID: {position_id}")
    
    # Test 6: Query recent events
    print("\n6. Querying recent events...")
    events = tracker.get_recent_events(limit=5)
    print(f"   ✓ Retrieved {len(events)} recent events:")
    for event in events:
        print(f"      - {event['timestamp']}: {event['event_type']} ({event['symbol']})")
    
    # Test 7: Get order details
    print("\n7. Getting order details...")
    order = tracker.get_order("test_order_001")
    if order:
        print(f"   ✓ Order details:")
        print(f"      Symbol: {order['symbol']}")
        print(f"      Side: {order['side']}")
        print(f"      Status: {order['status']}")
        print(f"      Filled: {order['filled_quantity']}/{order['quantity']}")
        print(f"      Avg Price: {order['avg_fill_price']}")
    
    # Test 8: Get current positions
    print("\n8. Getting current positions...")
    positions = tracker.get_current_positions()
    print(f"   ✓ Retrieved {len(positions)} positions:")
    for pos in positions:
        print(f"      - {pos['symbol']}: {pos['position_amount']} @ {pos['entry_price']}")
    
    tracker.close()
    print("\n" + "=" * 60)
    print("✓ All basic operations completed successfully!")
    print("=" * 60)


def test_advanced_queries():
    """Test advanced query functionality."""
    print("\n" + "=" * 60)
    print("Testing Advanced Query Functionality")
    print("=" * 60)
    
    tracker = EventTracker("data/test_trading_events.db")
    
    with tracker.session_scope() as session:
        queries = EventQueries(session)
        
        # Test 1: Order audit trail
        print("\n1. Getting order audit trail...")
        audit = queries.get_order_audit_trail("test_order_001")
        if "error" not in audit:
            print(f"   ✓ Audit trail retrieved:")
            print(f"      Order ID: {audit['order']['order_id']}")
            print(f"      Events: {len(audit['events'])}")
            print(f"      Fills: {len(audit['fills'])}")
        
        # Test 2: Strategy performance
        print("\n2. Getting strategy performance...")
        perf = queries.get_strategy_performance("test_strategy")
        if "error" not in perf:
            print(f"   ✓ Performance metrics:")
            print(f"      Total Fills: {perf['total_fills']}")
            print(f"      Total Volume: {perf['total_volume']}")
            print(f"      Total Commission: {perf['total_commission']}")
        
        # Test 3: Symbol statistics
        print("\n3. Getting symbol statistics...")
        stats = queries.get_symbol_statistics("BTCUSDT", days=7)
        print(f"   ✓ Symbol statistics:")
        print(f"      Total Orders: {stats['total_orders']}")
        print(f"      Filled Orders: {stats['filled_orders']}")
        print(f"      Fill Rate: {stats['fill_rate']:.2%}")
        
        # Test 4: Position timeline
        print("\n4. Getting position timeline...")
        timeline = queries.get_position_timeline("BTCUSDT", hours=24)
        print(f"   ✓ Retrieved {len(timeline)} position snapshots")
        
        # Test 5: Recent signals
        print("\n5. Getting recent signals...")
        signals = queries.get_recent_signals(limit=5)
        print(f"   ✓ Retrieved {len(signals)} signals")
    
    tracker.close()
    print("\n" + "=" * 60)
    print("✓ All advanced queries completed successfully!")
    print("=" * 60)


def cleanup_test_db():
    """Remove test database."""
    import os
    test_db = "data/test_trading_events.db"
    if os.path.exists(test_db):
        os.remove(test_db)
        print(f"\n✓ Cleaned up test database: {test_db}")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Event Tracking Database Test Suite")
    print("=" * 60)
    
    try:
        # Create data directory if it doesn't exist
        os.makedirs("data", exist_ok=True)
        
        # Run tests
        test_basic_operations()
        test_advanced_queries()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)
        
        # Cleanup
        cleanup_test_db()
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
