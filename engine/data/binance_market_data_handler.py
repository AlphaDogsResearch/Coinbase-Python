from common.subscription.subscriber import Subscriber
from engine.core.market_data_handler import MarketDataHandler


class BinanceMarketDataHandler(MarketDataHandler):
    def __init__(self, port: int):
        self.localhost = "tcp://localhost"
        self.address = self.localhost + ":" + str(port)
        self.subscriber = Subscriber([self.address], name="Binance Market Data Handler")

    def listen(self):
        try:
            self.subscriber.listen(callback=self.handle_message)
        except KeyboardInterrupt:
            self.subscriber.close()

    def stop_listening(self):
        self.subscriber.close()

    def handle_message(self, msg):
        print(f"[Callback] Got: {msg}")

    def get_latest_data(self) -> dict:
        return {
            "BTCUSDT": {"price": 58234},
            "ETHUSDT": {"price": 3941},
        }
