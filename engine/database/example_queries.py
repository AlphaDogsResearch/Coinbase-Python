"""
Example usage and query patterns for the event tracking database.

Demonstrates how to use the EventTracker and EventQueries for common scenarios.
"""

from datetime import datetime, timedelta
from engine.database.event_tracker import EventTracker
from engine.database.event_queries import EventQueries


def example_basic_usage():
    """Basic usage of EventTracker."""
    
    # Initialize tracker
    tracker = EventTracker("data/trading_events.db")
    
    # Log a signal
    signal_id = tracker.log_signal(
        strategy_id="momentum_strategy",
        symbol="BTCUSDT",
        signal_type=1,  # Buy signal
        price=50000.0,
        action="OPEN_LONG",
        tags=["momentum", "breakout"]
    )
    print(f"Logged signal: {signal_id}")
    
    # Create an order
    order_id = tracker.create_order(
        order_id="order_12345",
        symbol="BTCUSDT",
        side="BUY",
        order_type="LIMIT",
        quantity=0.1,
        price=50000.0,
        client_id="client_001",
        strategy_id="momentum_strategy",
        tags=["entry", "long"]
    )
    print(f"Created order: {order_id}")
    
    # Update order status
    tracker.update_order_status(
        order_id="order_12345",
        status="FILLED",
        filled_quantity=0.1,
        avg_fill_price=49995.0
    )
    
    # Record a fill
    fill_id = tracker.record_fill(
        order_id="order_12345",
        symbol="BTCUSDT",
        side="BUY",
        price=49995.0,
        quantity=0.1,
        commission=2.5,
        is_maker=True
    )
    print(f"Recorded fill: {fill_id}")
    
    # Snapshot position
    position_id = tracker.snapshot_position(
        symbol="BTCUSDT",
        position_amount=0.1,
        entry_price=49995.0,
        strategy_id="momentum_strategy",
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        total_trading_cost=2.5
    )
    print(f"Position snapshot: {position_id}")
    
    # Query recent events
    events = tracker.get_recent_events(limit=10)
    print(f"\nRecent events: {len(events)}")
    for event in events:
        print(f"  - {event['timestamp']}: {event['event_type']} ({event['symbol']})")
    
    # Get order details
    order = tracker.get_order("order_12345")
    if order:
        print(f"\nOrder details:")
        print(f"  Symbol: {order['symbol']}")
        print(f"  Side: {order['side']}")
        print(f"  Status: {order['status']}")
        print(f"  Filled: {order['filled_quantity']}/{order['quantity']}")
    
    # Get current positions
    positions = tracker.get_current_positions()
    print(f"\nCurrent positions: {len(positions)}")
    for pos in positions:
        print(f"  - {pos['symbol']}: {pos['position_amount']} @ {pos['entry_price']}")
    
    tracker.close()


def example_audit_trail():
    """Example of getting complete audit trail for an order."""
    
    tracker = EventTracker("data/trading_events.db")
    
    with tracker.session_scope() as session:
        queries = EventQueries(session)
        
        # Get complete audit trail
        audit = queries.get_order_audit_trail("order_12345")
        
        if "error" not in audit:
            print("Order Audit Trail:")
            print(f"  Order ID: {audit['order']['order_id']}")
            print(f"  Symbol: {audit['order']['symbol']}")
            print(f"  Status: {audit['order']['status']}")
            print(f"\n  Events ({len(audit['events'])}):")
            for event in audit['events']:
                print(f"    - {event['timestamp']}: {event['event_type']}")
            print(f"\n  Fills ({len(audit['fills'])}):")
            for fill in audit['fills']:
                print(f"    - {fill['quantity']} @ {fill['price']} (fee: {fill['commission']})")
    
    tracker.close()


def example_performance_analysis():
    """Example of analyzing strategy performance."""
    
    tracker = EventTracker("data/trading_events.db")
    
    with tracker.session_scope() as session:
        queries = EventQueries(session)
        
        # Get strategy performance
        perf = queries.get_strategy_performance("momentum_strategy")
        
        if "error" not in perf:
            print("Strategy Performance:")
            print(f"  Total Fills: {perf['total_fills']}")
            print(f"  Total Volume: {perf['total_volume']}")
            print(f"  Total Commission: {perf['total_commission']}")
            print(f"  Total Realized P&L: {perf['total_realized_pnl']}")
            print(f"  Buy/Sell Ratio: {perf['buy_fills']}/{perf['sell_fills']}")
            print(f"  Maker/Taker Ratio: {perf['maker_fills']}/{perf['taker_fills']}")
        
        # Get symbol statistics
        stats = queries.get_symbol_statistics("BTCUSDT", days=7)
        print(f"\nSymbol Statistics (7 days):")
        print(f"  Total Orders: {stats['total_orders']}")
        print(f"  Fill Rate: {stats['fill_rate']:.2%}")
        print(f"  Total Volume: {stats['total_volume']}")
        print(f"  Total P&L: {stats['total_realized_pnl']}")
    
    tracker.close()


def example_position_tracking():
    """Example of tracking position changes over time."""
    
    tracker = EventTracker("data/trading_events.db")
    
    with tracker.session_scope() as session:
        queries = EventQueries(session)
        
        # Get position timeline
        timeline = queries.get_position_timeline("BTCUSDT", hours=24)
        
        print("Position Timeline (24 hours):")
        for snapshot in timeline:
            print(f"  {snapshot['timestamp']}: "
                  f"Amount={snapshot['position_amount']}, "
                  f"Entry={snapshot['entry_price']}, "
                  f"PnL={snapshot['unrealized_pnl']}")
        
        # Get all current positions
        positions = queries.get_all_current_positions()
        print(f"\nAll Current Positions: {len(positions)}")
        for pos in positions:
            print(f"  {pos['symbol']} ({pos['strategy_id']}): "
                  f"{pos['position_amount']} @ {pos['entry_price']}")
    
    tracker.close()


def example_order_analysis():
    """Example of analyzing order execution performance."""
    
    tracker = EventTracker("data/trading_events.db")
    
    with tracker.session_scope() as session:
        queries = EventQueries(session)
        
        # Get order performance metrics
        metrics = queries.get_order_performance_metrics(days=7)
        
        if "error" not in metrics:
            print("Order Performance Metrics (7 days):")
            print(f"  Total Orders: {metrics['total_orders']}")
            print(f"  Filled: {metrics['filled_orders']}")
            print(f"  Partially Filled: {metrics['partially_filled_orders']}")
            print(f"  Canceled: {metrics['canceled_orders']}")
            print(f"  Failed: {metrics['failed_orders']}")
            print(f"  Fill Rate: {metrics['fill_rate']:.2%}")
            print(f"  Quantity Fill Rate: {metrics['quantity_fill_rate']:.2%}")
        
        # Get recent signals
        signals = queries.get_recent_signals(limit=10)
        print(f"\nRecent Signals: {len(signals)}")
        for signal in signals:
            print(f"  {signal['timestamp']}: "
                  f"{signal['strategy_id']} - {signal['symbol']} "
                  f"(signal={signal['signal_type']})")
    
    tracker.close()


def example_time_range_query():
    """Example of querying events in a specific time range."""
    
    tracker = EventTracker("data/trading_events.db")
    
    # Define time range (last hour)
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=1)
    
    with tracker.session_scope() as session:
        queries = EventQueries(session)
        
        # Get all events in time range
        events = queries.get_events_in_timerange(
            start_time=start_time,
            end_time=end_time,
            symbol="BTCUSDT"
        )
        
        print(f"Events in last hour for BTCUSDT: {len(events)}")
        for event in events:
            print(f"  {event['timestamp']}: {event['event_type']}")
    
    tracker.close()


if __name__ == "__main__":
    print("=== Event Tracker Examples ===\n")
    
    print("1. Basic Usage")
    print("-" * 50)
    example_basic_usage()
    
    print("\n2. Audit Trail")
    print("-" * 50)
    example_audit_trail()
    
    print("\n3. Performance Analysis")
    print("-" * 50)
    example_performance_analysis()
    
    print("\n4. Position Tracking")
    print("-" * 50)
    example_position_tracking()
    
    print("\n5. Order Analysis")
    print("-" * 50)
    example_order_analysis()
    
    print("\n6. Time Range Query")
    print("-" * 50)
    example_time_range_query()
