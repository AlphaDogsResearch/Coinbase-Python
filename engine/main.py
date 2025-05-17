import os
import time
import logging

from dotenv import load_dotenv

from common.subscription.publisher import Publisher
from engine.core.strategy import Strategy
from engine.execution.executor import Executor
from gateways.binance.binance_gateway import BinanceGateway, ProductType
from portfolio.basic_portfolio_manager import BasicPortfolioManager
from risk.basic_risk_manager import BasicRiskManager
from orders.simple_order_manager import SimpleOrderManager
from tracking.in_memory_tracker import InMemoryTracker

def main():
    # Initialize components
    dotenv_path = 'vault/binance_keys'
    load_dotenv(dotenv_path=dotenv_path)
    API_KEY = os.getenv('BINANCE_API_KEY')
    API_SECRET = os.getenv('BINANCE_API_SECRET')
    contract = 'BTCUSDT'

    start = True
    market_data = {'price': [], 'ask': [], 'bid': []}

    binance = BinanceGateway(symbol=contract, api_key=API_KEY, api_secret=API_SECRET, product_type=ProductType.FUTURE)
    binance.connect()
    publisherPort = 8080
    publisher = Publisher(publisherPort, "Binance Publisher")
    binance.register_depth_callback(publisher.depth_callback)

    while start:
        time.sleep(2)
        if binance.not_ready():
            logging.info("Not ready to trade")
        else:
            # data_handler = BinanceMarketDataHandler(subscriber_port)
            strategy = Strategy()

            portfolio_manager = BasicPortfolioManager(capital_fraction=0.1)
            risk_manager = BasicRiskManager(max_order_value=5000)
            order_manager = SimpleOrderManager()
            executor = Executor(API_KEY, API_SECRET)
            tracker = InMemoryTracker()

            # Simulate capital
            aum = 100000.0
            market_order_book = binance.get_order_book(contract)
            logging.info('Depth: %s' % market_order_book)
            # Process orderbook TODO
            market_data['ask'].append(market_order_book.get_best_ask())
            market_data['bid'].append(market_order_book.get_best_bid())
            market_data['price'].append((market_order_book.get_best_bid() + market_order_book.get_best_ask()) / 2)
            print(market_data)

            # Step 2: Generate signals
            signals = strategy.process_data(market_data)
            if signals is None:
                print("No signals generated.")
            else:
                # Step 3: Portfolio manager calculates orders
                orders = portfolio_manager.evaluate_signals(contract, signals, aum)

                # Step 4: Risk check and queue orders
                for asset, order in list(orders.items()):
                    # if risk_manager and not risk_manager.validate_order(order, aum):
                    #     print(f"Order for {asset} failed risk check. Removing.")
                    #     del orders[asset]
                    # else:
                    order_manager.queue_orders({asset: order})

                # Step 5: Get queued orders
                queued_orders = order_manager.get_queued_orders()

                # Step 6: Place orders
                executor.place_orders(queued_orders)

                # Step 7: Update position tracker (mock fill price assumed)
                for asset, order in queued_orders.items():
                    mock_fill_price = market_data["price"][-1] # Use the last price as fill price
                    tracker.update_position(order, fill_price=mock_fill_price)

                # Final: Print current positions and PnL
                print("Positions:", tracker.get_positions())
                print("PnL:", tracker.get_pnl())

if __name__ == "__main__":
    main()
