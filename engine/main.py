from strategies.simple_strategy import SimpleStrategy
from portfolio.basic_portfolio_manager import BasicPortfolioManager
from risk.basic_risk_manager import BasicRiskManager
from execution.mock_executor import MockExecutor
from data.mock_data_handler import MockDataHandler
from orders.simple_order_manager import SimpleOrderManager
from tracking.in_memory_tracker import InMemoryTracker

def main():
    # Initialize components
    data_handler = MockDataHandler()
    strategy = SimpleStrategy()
    portfolio_manager = BasicPortfolioManager(capital_fraction=0.1)
    risk_manager = BasicRiskManager(max_order_value=5000)
    order_manager = SimpleOrderManager()
    executor = MockExecutor()
    tracker = InMemoryTracker()

    # Simulate capital
    aum = 100000.0

    # Step 1: Fetch market data
    market_data = data_handler.get_latest_data()

    # Step 2: Generate signals
    signals = strategy.process_data(market_data)

    # Step 3: Portfolio manager calculates orders
    orders = portfolio_manager.evaluate_signals(signals, aum)

    # Step 4: Risk check and queue orders
    for asset, order in list(orders.items()):
        if risk_manager and not risk_manager.validate_order(order, aum):
            print(f"Order for {asset} failed risk check. Removing.")
            del orders[asset]
        else:
            order_manager.queue_orders({asset: order})

    # Step 5: Get queued orders
    queued_orders = order_manager.get_queued_orders()

    # Step 6: Place orders
    executor.place_orders(queued_orders)

    # Step 7: Update position tracker (mock fill price assumed)
    for asset, order in queued_orders.items():
        mock_fill_price = market_data[asset]["price"]
        tracker.update_position(order, fill_price=mock_fill_price)

    # Final: Print current positions and PnL
    print("Positions:", tracker.get_positions())
    print("PnL:", tracker.get_pnl())

if __name__ == "__main__":
    main()
