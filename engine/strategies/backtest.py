import random
import math
from typing import List, Dict, Any
from .models import Bar, Order, OrderSide, OrderType, Position, PositionSide, Trade, Instrument
from .base import Strategy


class BacktestEngine:
    def __init__(self):
        self.strategy = None
        self.orders: List[Order] = []
        self.trades: List[Trade] = []
        self.positions: Dict[str, Position] = {}
        self.current_bar: Bar = None
        self.instrument_id = "ETHUSDT.BINANCE"

    def add_strategy(self, strategy: Strategy):
        self.strategy = strategy
        self.strategy.set_engine(self)
        # Initialize cache with instrument
        instrument = Instrument(id=self.instrument_id, symbol="ETHUSDT")
        self.strategy.cache.add_instrument(instrument)

    def subscribe_bars(self, strategy, bar_type):
        pass  # Mock subscription

    def submit_order(self, strategy, order: Order):
        order.status = "ACCEPTED"
        self.orders.append(order)
        self._process_order(order)

    def cancel_all_orders(self, strategy, instrument_id):
        # In this simple engine, we just mark pending orders as cancelled
        # But since we process immediately, there might not be pending orders except stops
        # We'll just clear the list of active orders if we had one
        pass

    def close_all_positions(self, strategy, instrument_id):
        if instrument_id in self.positions:
            pos = self.positions[instrument_id]
            if pos.quantity != 0:
                side = OrderSide.SELL if pos.is_long else OrderSide.BUY
                order = Order(
                    id="close_all",
                    instrument_id=instrument_id,
                    side=side,
                    quantity=pos.quantity,
                    type=OrderType.MARKET,
                )
                self.submit_order(strategy, order)

    def _process_order(self, order: Order):
        if order.type == OrderType.MARKET:
            self._fill_order(order, self.current_bar.close)
        elif order.type == OrderType.STOP_MARKET:
            # We don't support stop orders in this simple loop unless we check every bar
            # For validation, we'll just log it
            print(
                f"[Engine] Stop order accepted: {order.side} {order.quantity} @ {order.trigger_price}"
            )
            pass

    def _fill_order(self, order: Order, price: float):
        print(f"[Engine] Filling order {order.side} {order.quantity} @ {price}")
        trade = Trade(
            id="trade_" + order.id,
            order_id=order.id,
            instrument_id=order.instrument_id,
            side=order.side,
            quantity=order.quantity,
            price=price,
            timestamp=self.current_bar.ts_event,
        )
        self.trades.append(trade)
        self._update_position(trade)

    def _update_position(self, trade: Trade):
        if trade.instrument_id not in self.positions:
            side = PositionSide.LONG if trade.side == OrderSide.BUY else PositionSide.SHORT
            self.positions[trade.instrument_id] = Position(
                instrument_id=trade.instrument_id,
                side=side,
                quantity=trade.quantity,
                entry_price=trade.price,
            )
        else:
            pos = self.positions[trade.instrument_id]
            if (pos.is_long and trade.side == OrderSide.BUY) or (
                pos.is_short and trade.side == OrderSide.SELL
            ):
                # Increasing position
                total_cost = pos.quantity * pos.entry_price + trade.quantity * trade.price
                total_qty = pos.quantity + trade.quantity
                pos.entry_price = total_cost / total_qty
                pos.quantity = total_qty
            else:
                # Decreasing/Closing position
                if trade.quantity >= pos.quantity:
                    # Flip or close
                    remaining = trade.quantity - pos.quantity
                    if remaining == 0:
                        del self.positions[trade.instrument_id]
                        # Update strategy portfolio
                        self.strategy.cache.update_position(
                            Position(trade.instrument_id, PositionSide.FLAT, 0, 0)
                        )
                        return
                    else:
                        side = (
                            PositionSide.SHORT
                            if trade.side == OrderSide.SELL
                            else PositionSide.LONG
                        )
                        self.positions[trade.instrument_id] = Position(
                            instrument_id=trade.instrument_id,
                            side=side,
                            quantity=remaining,
                            entry_price=trade.price,
                        )
                else:
                    pos.quantity -= trade.quantity

        # Update strategy cache
        if trade.instrument_id in self.positions:
            self.strategy.cache.update_position(self.positions[trade.instrument_id])

    def run(self, bars: List[Bar]):
        self.strategy.on_start()
        for bar in bars:
            self.current_bar = bar
            self.strategy.on_bar(bar)
            # Check stops
            # Simple check: if long and low < stop, or short and high > stop
            # This requires tracking stop orders
            pass
        self.strategy.on_stop()


def generate_synthetic_data(num_bars=200) -> List[Bar]:
    bars = []
    price = 100.0
    for i in range(num_bars):
        # Sine wave + noise
        change = math.sin(i / 10.0) + (random.random() - 0.5)
        price += change
        bar = Bar(
            ts_event=i * 3600 * 1000,  # Hourly
            open=price,
            high=price + 1.0,
            low=price - 1.0,
            close=price + 0.5,
            volume=1000,
        )
        bars.append(bar)
    return bars


if __name__ == "__main__":
    from .simple_order_test_strategy import SimpleOrderTestStrategy, SimpleOrderTestStrategyConfig
    from .adx_mean_reversion_strategy import (
        ADXMeanReversionStrategy,
        ADXMeanReversionStrategyConfig,
    )
    from .apo_mean_reversion_strategy import (
        APOMeanReversionStrategy,
        APOMeanReversionStrategyConfig,
    )
    from .ppo_momentum_strategy import PPOMomentumStrategy, PPOMomentumStrategyConfig
    from .cci_momentum_strategy import CCIMomentumStrategy, CCIMomentumStrategyConfig
    from .roc_mean_reversion_strategy import (
        ROCMeanReversionStrategy,
        ROCMeanReversionStrategyConfig,
    )

    print("Running Simple Order Test Strategy...")
    engine = BacktestEngine()
    config = SimpleOrderTestStrategyConfig(
        instrument_id="ETHUSDT.BINANCE", bar_type="ETHUSDT-1h", bars_per_trade=5
    )
    strategy = SimpleOrderTestStrategy(config)
    engine.add_strategy(strategy)
    bars = generate_synthetic_data(50)
    engine.run(bars)

    print("\nRunning ADX Mean Reversion Strategy...")
    engine = BacktestEngine()
    config = ADXMeanReversionStrategyConfig(instrument_id="ETHUSDT.BINANCE", bar_type="ETHUSDT-1h")
    strategy = ADXMeanReversionStrategy(config)
    engine.add_strategy(strategy)
    bars = generate_synthetic_data(200)
    engine.run(bars)

    print("\nRunning APO Mean Reversion Strategy...")
    engine = BacktestEngine()
    config = APOMeanReversionStrategyConfig(instrument_id="ETHUSDT.BINANCE", bar_type="ETHUSDT-1h")
    strategy = APOMeanReversionStrategy(config)
    engine.add_strategy(strategy)
    bars = generate_synthetic_data(200)
    engine.run(bars)

    print("\nRunning PPO Momentum Strategy...")
    engine = BacktestEngine()
    config = PPOMomentumStrategyConfig(instrument_id="ETHUSDT.BINANCE", bar_type="ETHUSDT-1h")
    strategy = PPOMomentumStrategy(config)
    engine.add_strategy(strategy)
    bars = generate_synthetic_data(200)
    engine.run(bars)

    print("\nRunning CCI Momentum Strategy...")
    engine = BacktestEngine()
    config = CCIMomentumStrategyConfig(instrument_id="ETHUSDT.BINANCE", bar_type="ETHUSDT-1h")
    strategy = CCIMomentumStrategy(config)
    engine.add_strategy(strategy)
    bars = generate_synthetic_data(200)
    engine.run(bars)

    print("\nRunning ROC Mean Reversion Strategy...")
    engine = BacktestEngine()
    config = ROCMeanReversionStrategyConfig(instrument_id="ETHUSDT.BINANCE", bar_type="ETHUSDT-1h")
    strategy = ROCMeanReversionStrategy(config)
    engine.add_strategy(strategy)
    bars = generate_synthetic_data(200)
    engine.run(bars)
