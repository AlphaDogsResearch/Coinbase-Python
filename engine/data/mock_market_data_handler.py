from common.subscription.subscriber import Subscriber
from engine.core.market_data_handler import MarketDataHandler

class MockDataHandler(MarketDataHandler):
    def get_latest_data(self) -> dict:
        return {
            "BTCUSDT": {"price": 58234},
            "ETHUSDT": {"price": 3941},
        }
