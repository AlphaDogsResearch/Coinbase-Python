from dataclasses import dataclass

from common.interface_order import OrderSizeMode
from engine.database.models import build_tema_signal_context

from ..market_data.candle import MidPriceCandle
from .base import Strategy
from .indicators import TripleExponentialMovingAverage
from .models import Instrument, PositionSide
from .strategy_action import StrategyAction
from .strategy_order_mode import StrategyOrderMode


@dataclass(frozen=True)
class TEMACrossoverStrategyConfig:
    """TEMA Crossover Strategy configuration."""

    instrument_id: str
    bar_type: str

    # TEMA Parameters
    short_window: int = 14
    long_window: int = 51

    # Position Management
    quantity: float = 1.0  # Position size (deprecated, use notional_amount)
    notional_amount: float = 500.0
    stop_loss_percent: float = 0.09054410998184012  # decimal: 0.09 = 9%
    take_profit_percent: float = 0.05  # decimal: 0.05 = 5%
    max_holding_bars: int = 21
    cooldown_bars: int = 0

    # Risk Management
    use_stop_loss: bool = True
    use_take_profit: bool = False
    use_max_holding: bool = True
    allow_flip: bool = True


class TEMACrossoverStrategy(Strategy):
    """
    TEMA Crossover Strategy Implementation
    """

    def __init__(self, config: TEMACrossoverStrategyConfig) -> None:
        super().__init__(config)

        self.config = config

        # TEMA Parameters
        self.short_window = config.short_window
        self.long_window = config.long_window

        # Position Management
        self.quantity = config.quantity  # Deprecated, kept for backward compatibility
        self.notional_amount = config.notional_amount
        self.stop_loss_percent = config.stop_loss_percent
        self.take_profit_percent = config.take_profit_percent
        self.max_holding_bars = config.max_holding_bars
        self.cooldown_bars = config.cooldown_bars

        # Risk Management
        self.use_stop_loss = config.use_stop_loss
        self.use_take_profit = config.use_take_profit
        self.use_max_holding = config.use_max_holding
        self.allow_flip = config.allow_flip

        # Indicators
        self.tema_short = TripleExponentialMovingAverage(period=self.short_window)
        self.tema_long = TripleExponentialMovingAverage(period=self.long_window)

        # State tracking
        self._previous_tema_diff = 0.0
        self._bars_processed = 0
        self._entry_bar = None
        self._entry_price = None
        self._position_side = None
        self._cooldown_left = 0
        self._stopped_out_count = 0

        self.instrument_id = config.instrument_id
        instrument = Instrument(id=self.instrument_id, symbol=self.instrument_id)
        self.cache.add_instrument(instrument)
        self.bar_type = config.bar_type
        self.instrument = None

    def on_start(self) -> None:
        """Initialize strategy on start."""
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument {self.instrument_id} not found in cache\n")

        self.subscribe_bars(self.bar_type)
        self.log.info(f"TEMACrossoverStrategy started for {self.instrument_id}")

    def on_candle_created(self, candle: MidPriceCandle):
        """Handle incoming candle data."""
        self.tema_short.handle_bar(candle)
        self.tema_long.handle_bar(candle)

        if not self.tema_short.initialized or not self.tema_long.initialized:
            return

        current_tema_short = self.tema_short.value
        current_tema_long = self.tema_long.value
        current_tema_diff = current_tema_short - current_tema_long

        if self._cooldown_left > 0 and self.cache.is_flat(self.instrument_id):
            self._cooldown_left -= 1

        long_entry_signal = self._previous_tema_diff < 0 and current_tema_diff > 0
        short_entry_signal = self._previous_tema_diff > 0 and current_tema_diff < 0

        long_exit_signal = short_entry_signal
        short_exit_signal = long_entry_signal

        if self.cache.is_flat(self.instrument_id):
            if self._cooldown_left == 0:
                if long_entry_signal:
                    self._enter_long(
                        candle=candle,
                        tema_short=current_tema_short,
                        tema_long=current_tema_long,
                        tema_diff=current_tema_diff,
                        reason="TEMA long crossover",
                    )
                elif short_entry_signal:
                    self._enter_short(
                        candle=candle,
                        tema_short=current_tema_short,
                        tema_long=current_tema_long,
                        tema_diff=current_tema_diff,
                        reason="TEMA short crossover",
                    )
        else:
            self._sync_position_state()

            if self.cache.is_net_long(self.instrument_id):
                self._handle_long_position(
                    candle=candle,
                    tema_short=current_tema_short,
                    tema_long=current_tema_long,
                    tema_diff=current_tema_diff,
                    long_exit_signal=long_exit_signal,
                )
            elif self.cache.is_net_short(self.instrument_id):
                self._handle_short_position(
                    candle=candle,
                    tema_short=current_tema_short,
                    tema_long=current_tema_long,
                    tema_diff=current_tema_diff,
                    short_exit_signal=short_exit_signal,
                )

        self._previous_tema_diff = current_tema_diff
        self._bars_processed += 1

    def _handle_long_position(
        self,
        candle: MidPriceCandle,
        tema_short: float,
        tema_long: float,
        tema_diff: float,
        long_exit_signal: bool,
    ) -> None:
        entry_price = self._resolve_entry_price()
        if entry_price <= 0.0:
            return

        low_price = self._candle_low(candle)
        high_price = self._candle_high(candle)
        long_stop = entry_price * (1 - self.stop_loss_percent)
        long_tp = entry_price * (1 + self.take_profit_percent)

        if self.use_stop_loss and low_price <= long_stop:
            if self._close_position(candle, f"Stop loss triggered at {long_stop:.4f}"):
                self._stopped_out_count += 1
                self._cooldown_left = self.cooldown_bars
            return

        if self.use_take_profit and high_price >= long_tp:
            if self._close_position(candle, f"Take profit triggered at {long_tp:.4f}"):
                self._stopped_out_count = 0
            return

        if long_exit_signal:
            if self.allow_flip and self._cooldown_left == 0:
                if self._reverse_position(
                    candle=candle,
                    signal=-1,
                    tema_short=tema_short,
                    tema_long=tema_long,
                    tema_diff=tema_diff,
                    reason="Flip to short",
                ):
                    self._stopped_out_count = 0
            else:
                if self._close_position(candle, "Reverse exit"):
                    self._stopped_out_count = 0
            return

        if self.use_max_holding and self._bars_held() > self.max_holding_bars:
            self._close_position(candle, "Max holding period reached")

    def _handle_short_position(
        self,
        candle: MidPriceCandle,
        tema_short: float,
        tema_long: float,
        tema_diff: float,
        short_exit_signal: bool,
    ) -> None:
        entry_price = self._resolve_entry_price()
        if entry_price <= 0.0:
            return

        low_price = self._candle_low(candle)
        high_price = self._candle_high(candle)
        short_stop = entry_price * (1 + self.stop_loss_percent)
        short_tp = entry_price * (1 - self.take_profit_percent)

        if self.use_stop_loss and high_price >= short_stop:
            if self._close_position(candle, f"Stop loss triggered at {short_stop:.4f}"):
                self._stopped_out_count += 1
                self._cooldown_left = self.cooldown_bars
            return

        if self.use_take_profit and low_price <= short_tp:
            if self._close_position(candle, f"Take profit triggered at {short_tp:.4f}"):
                self._stopped_out_count = 0
            return

        if short_exit_signal:
            if self.allow_flip and self._cooldown_left == 0:
                if self._reverse_position(
                    candle=candle,
                    signal=1,
                    tema_short=tema_short,
                    tema_long=tema_long,
                    tema_diff=tema_diff,
                    reason="Flip to long",
                ):
                    self._stopped_out_count = 0
            else:
                if self._close_position(candle, "Reverse exit"):
                    self._stopped_out_count = 0
            return

        if self.use_max_holding and self._bars_held() > self.max_holding_bars:
            self._close_position(candle, "Max holding period reached")

    def _enter_long(
        self,
        candle: MidPriceCandle,
        tema_short: float,
        tema_long: float,
        tema_diff: float,
        reason: str,
    ) -> None:
        if not self.cache.is_flat(self.instrument_id):
            return

        close_price = self._candle_close(candle)
        if close_price == 0.0:
            return

        strategy_order_mode = StrategyOrderMode(
            order_size_mode=OrderSizeMode.NOTIONAL,
            notional_value=self.notional_amount,
        )

        signal_context = self._build_signal_context(
            reason=reason,
            candle=candle,
            tema_short=tema_short,
            tema_long=tema_long,
            tema_diff=tema_diff,
            action="ENTRY",
        )

        ok = self.on_signal(
            signal=1,
            price=close_price,
            strategy_actions=StrategyAction.OPEN_CLOSE_POSITION,
            strategy_order_mode=strategy_order_mode,
            signal_context=signal_context,
        )

        if ok:
            self._position_side = PositionSide.LONG
            self._entry_bar = self._bars_processed
            self._entry_price = close_price
            self.log.info(f"🟢 LONG ENTRY | {reason} | Price: {close_price:.4f}")
        else:
            self.log.error("Failed to submit long entry order")

    def _enter_short(
        self,
        candle: MidPriceCandle,
        tema_short: float,
        tema_long: float,
        tema_diff: float,
        reason: str,
    ) -> None:
        if not self.cache.is_flat(self.instrument_id):
            return

        close_price = self._candle_close(candle)
        if close_price == 0.0:
            return

        strategy_order_mode = StrategyOrderMode(
            order_size_mode=OrderSizeMode.NOTIONAL,
            notional_value=self.notional_amount,
        )

        signal_context = self._build_signal_context(
            reason=reason,
            candle=candle,
            tema_short=tema_short,
            tema_long=tema_long,
            tema_diff=tema_diff,
            action="ENTRY",
        )

        ok = self.on_signal(
            signal=-1,
            price=close_price,
            strategy_actions=StrategyAction.OPEN_CLOSE_POSITION,
            strategy_order_mode=strategy_order_mode,
            signal_context=signal_context,
        )

        if ok:
            self._position_side = PositionSide.SHORT
            self._entry_bar = self._bars_processed
            self._entry_price = close_price
            self.log.info(f"🔴 SHORT ENTRY | {reason} | Price: {close_price:.4f}")
        else:
            self.log.error("Failed to submit short entry order")

    def _reverse_position(
        self,
        candle: MidPriceCandle,
        signal: int,
        tema_short: float,
        tema_long: float,
        tema_diff: float,
        reason: str,
    ) -> bool:
        close_price = self._candle_close(candle)
        if close_price == 0.0:
            return False

        strategy_order_mode = StrategyOrderMode(
            order_size_mode=OrderSizeMode.NOTIONAL,
            notional_value=self.notional_amount,
        )

        signal_context = self._build_signal_context(
            reason=reason,
            candle=candle,
            tema_short=tema_short,
            tema_long=tema_long,
            tema_diff=tema_diff,
            action="REVERSAL",
        )

        ok = self.on_signal(
            signal=signal,
            price=close_price,
            strategy_actions=StrategyAction.POSITION_REVERSAL,
            strategy_order_mode=strategy_order_mode,
            signal_context=signal_context,
        )

        if ok:
            self._position_side = (
                PositionSide.LONG if signal == 1 else PositionSide.SHORT
            )
            self._entry_bar = self._bars_processed
            self._entry_price = close_price
            side_label = "LONG" if signal == 1 else "SHORT"
            self.log.info(
                f"🟠 REVERSAL TO {side_label} | {reason} | Price: {close_price:.4f}"
            )
        else:
            self.log.error("Failed to submit reversal order")

        return ok

    def _close_position(self, candle: MidPriceCandle, reason: str) -> bool:
        if self.cache.is_flat(self.instrument_id):
            return False

        close_price = self._candle_close(candle)
        if close_price == 0.0:
            return False

        position = self.cache.position(self.instrument_id)
        if not position:
            return False

        tags = [f"reason={reason}"]
        ok = self._order_manager.submit_market_close(
            strategy_id=self._strategy_id,
            symbol=self._symbol,
            price=close_price,
            tags=tags,
        )

        if ok:
            if position.is_long:
                self.log.info(f"🟡 LONG EXIT: {reason} | Price: {close_price:.4f}")
            else:
                self.log.info(f"🟡 SHORT EXIT: {reason} | Price: {close_price:.4f}")
            self._position_side = None
            self._entry_bar = None
            self._entry_price = None
        else:
            self.log.error("Failed to submit close order")

        return ok

    def _build_signal_context(
        self,
        reason: str,
        candle: MidPriceCandle,
        tema_short: float,
        tema_long: float,
        tema_diff: float,
        action: str,
    ):
        return build_tema_signal_context(
            reason=reason,
            tema_short=tema_short,
            tema_long=tema_long,
            tema_diff=tema_diff,
            prev_tema_diff=self._previous_tema_diff,
            short_window=self.short_window,
            long_window=self.long_window,
            stop_loss_percent=self.stop_loss_percent,
            take_profit_percent=self.take_profit_percent,
            max_holding_bars=self.max_holding_bars,
            cooldown_bars=self.cooldown_bars,
            notional_amount=self.notional_amount,
            use_stop_loss=self.use_stop_loss,
            use_take_profit=self.use_take_profit,
            use_max_holding=self.use_max_holding,
            allow_flip=self.allow_flip,
            candle={
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
            },
            action=action,
        )

    def _sync_position_state(self) -> None:
        position = self.cache.position(self.instrument_id)
        if not position:
            return

        if position.is_long:
            self._position_side = PositionSide.LONG
        elif position.is_short:
            self._position_side = PositionSide.SHORT
        else:
            self._position_side = None

        if position.entry_price and position.entry_price > 0:
            self._entry_price = position.entry_price

    def _resolve_entry_price(self) -> float:
        position = self.cache.position(self.instrument_id)
        if position and position.entry_price and position.entry_price > 0:
            return position.entry_price
        return self._entry_price if self._entry_price is not None else 0.0

    def _bars_held(self) -> int:
        if self._entry_bar is None:
            return 0
        return self._bars_processed - self._entry_bar

    def _candle_close(self, candle: MidPriceCandle) -> float:
        return candle.close if candle.close is not None else 0.0

    def _candle_low(self, candle: MidPriceCandle) -> float:
        if candle.low == float("inf"):
            return self._candle_close(candle)
        return candle.low

    def _candle_high(self, candle: MidPriceCandle) -> float:
        if candle.high == float("-inf"):
            return self._candle_close(candle)
        return candle.high
