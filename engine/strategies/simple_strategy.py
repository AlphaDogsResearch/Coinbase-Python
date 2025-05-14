from core.strategy import Strategy

class SimpleStrategy(Strategy):
    def process_data(self, market_data: dict) -> dict:
        # Simple example: go long if price ends in even digit, short otherwise
        signals = {}
        for symbol, data in market_data.items():
            last_digit = int(str(int(data["price"]))[-1])
            signals[symbol] = "long" if last_digit % 2 == 0 else "short"
        return signals
