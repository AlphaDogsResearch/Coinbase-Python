import logging

from engine.market_data.csv_backtest_market_data_client import (
    CSVBacktestMarketDataClient,
)
from common.config_logging import to_stdout
from engine.strategies.inflection_sma_crossover_strategy import (
    InflectionSMACrossoverStrategy,
)
from engine.market_data.candle import CandleAggregator


def main():
    to_stdout()
    logging.info("Running Engine...")
    logging.info("Testing InflectionSMACrossoverStrategy Using Synthetic data...")
    start = True
    strategy = InflectionSMACrossoverStrategy(short_window=20, long_window=100)

    def signal_printer(signal, price):
        print(f"Signal: {signal} at Price: {price}")

    strategy.add_order_event_listener("Test-Signal",signal_printer)

    market_data_client = CSVBacktestMarketDataClient(
        "./engine/synthetic_sma_dataset.csv"
    )
    aggregator = CandleAggregator(interval_milliseconds=100)
    market_data_client.add_order_book_listener(aggregator.on_order_book)
    aggregator.add_candle_created_listener(strategy.on_candle_created)
    market_data_client.start_publishing(10)

    while start:
        continue


if __name__ == "__main__":
    main()
