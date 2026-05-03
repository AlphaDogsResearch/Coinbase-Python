import logging
from dataclasses import dataclass

from common.interface_order import OrderSizeMode
from engine.database.models import build_bband_signal_context

from ..market_data.candle import MidPriceCandle
from .base import Strategy
from .indicators import BollingerBands
from .models import Instrument, PositionSide
from .strategy_action import StrategyAction
from .strategy_order_mode import StrategyOrderMode


@dataclass(frozen=True)
class BBANDSignalStrategyConfig:
    """Bollinger Bands Signal Strategy configuration."""

    instrument_id: str
    bar_type: str

    # Bollinger Bands Parameters (from Results summary)
    bband_period: int = 20
    nbdevup: float = 1.09
    nbdevdn: float = 1.10
    matype: int = 0  # TA-Lib: 0=SMA, 1=EMA, 2=WMA, 3=DEMA, 4=TEMA

    # Signal Behavior
    signal_mode: str = "momentum"  # mean_reversion | momentum
    exit_mode: str = "midpoint"  # midpoint | breakout

    # Position Management
    quantity: float = 1.0
    notional_amount: float = 500.0
    stop_loss_percent: float = 0.06
    take_profit_percent: float = 0.05
    max_holding_bars: int = 21
    cooldown_bars: int = 0

    # Risk Management
    use_stop_loss: bool = True
    use_take_profit: bool = False
    use_max_holding: bool = True
    allow_flip: bool = True


class BBANDSignalStrategy(Strategy):
    """
    Bollinger Bands Signal Strategy Implementation.

    Momentum mode (default): enters long when price breaks above the upper band,
    short when price breaks below the lower band.

    Mean reversion mode: enters long when price crosses back above the lower band,
    short when price crosses back below the upper band.
    """

    VALID_SIGNAL_MODES = {"mean_reversion", "momentum"}
    VALID_EXIT_MODES = {"midpoint", "breakout"}

    def __init__(self, config: BBANDSignalStrategyConfig) -> None:
        super().__init__(config)

        self.config = config

        # Bollinger Bands parameters
        self.bband_period = config.bband_period
        self.nbdevup = config.nbdevup
        self.nbdevdn = config.nbdevdn
        self.matype = config.matype

        # Signal behavior
        self.signal_mode = config.signal_mode
        if self.signal_mode not in self.VALID_SIGNAL_MODES:
            self.logger.warning(f"Invalid signal_mode={self.signal_mode}, defaulting to momentum")
            self.signal_mode = "momentum"

        self.exit_mode = config.exit_mode
        if self.exit_mode not in self.VALID_EXIT_MODES:
            self.logger.warning(f"Invalid exit_mode={self.exit_mode}, defaulting to breakout")
            self.exit_mode = "breakout"

        # Position Management
        self.quantity = config.quantity
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

        # Initialize Bollinger Bands indicator
        self.bband = BollingerBands(
            period=self.bband_period,
            nbdevup=self.nbdevup,
            nbdevdn=self.nbdevdn,
            matype=self.matype,
        )

        # State tracking
        self._previous_close = 0.0
        self._bars_processed = 0
        self._entry_bar = None
        self._entry_price = None
        self._position_side = None
        self._cooldown_left = 0
        self._stopped_out_count = 0
        self._previous_upper = None
        self._previous_middle = None
        self._previous_lower = None

        self.instrument_id = config.instrument_id
        instrument = Instrument(id=self.instrument_id, symbol=self.instrument_id)
        self.cache.add_instrument(instrument)
        self.bar_type = config.bar_type
        self.instrument = None

    def on_start(self) -> None:
        """Initialize strategy on start."""
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.logger.error(f"Instrument {self.instrument_id} not found in cache\n")

        self.subscribe_bars(self.bar_type)
        self.logger.info(
            f"[SIGNAL] BBANDSignalStrategy started for {self.instrument_id} "
            f"(mode={self.signal_mode}, exit={self.exit_mode})"
        )
        super().on_start()

    def on_candle_created(self, candle: MidPriceCandle):
        """Handle incoming candle data."""
        self.bband.handle_bar(candle)

        if not self.is_started():
            return

        if not self.bband.initialized:
            self._previous_close = self._candle_close(candle)
            return

        current_close = self._candle_close(candle)

        if self._cooldown_left > 0 and self.cache.is_flat(self.instrument_id):
            self._cooldown_left -= 1

        if not self.cache.is_flat(self.instrument_id):
            current_side = (
                PositionSide.LONG
                if self.cache.is_net_long(self.instrument_id)
                else PositionSide.SHORT
            )
            if self._entry_bar is None or self._position_side != current_side:
                self._entry_bar = self._bars_processed
                self._position_side = current_side
        else:
            self._entry_bar = None
            self._position_side = None

        (
            long_entry_signal,
            short_entry_signal,
            long_exit_signal,
            short_exit_signal,
        ) = self._compute_signals(current_close)

        if self.cache.is_flat(self.instrument_id):
            if self._cooldown_left == 0:
                if long_entry_signal:
                    self._enter_long(candle, current_close, reason="BBAND long entry")
                elif short_entry_signal:
                    self._enter_short(candle, current_close, reason="BBAND short entry")
        else:
            if self.cache.is_net_long(self.instrument_id):
                self._handle_long_position(
                    candle=candle,
                    current_close=current_close,
                    short_entry_signal=short_entry_signal,
                    long_exit_signal=long_exit_signal,
                )
            elif self.cache.is_net_short(self.instrument_id):
                self._handle_short_position(
                    candle=candle,
                    current_close=current_close,
                    long_entry_signal=long_entry_signal,
                    short_exit_signal=short_exit_signal,
                )

        self._previous_close = current_close
        self._previous_upper = self.bband.upper
        self._previous_middle = self.bband.middle
        self._previous_lower = self.bband.lower
        self._bars_processed += 1

    def _compute_signals(self, current_close: float):
        if (
            self._previous_upper is None
            or self._previous_middle is None
            or self._previous_lower is None
        ):
            return (False, False, False, False)

        upper = self.bband.upper
        middle = self.bband.middle
        lower = self.bband.lower
        prev = self._previous_close
        prev_upper = self._previous_upper
        prev_middle = self._previous_middle
        prev_lower = self._previous_lower

        # Mean reversion: enter when price crosses back inside the bands
        mr_long_signal = prev < prev_lower and current_close >= lower
        mr_short_signal = prev > prev_upper and current_close <= upper

        # Momentum: enter when price breaks out through the bands
        mom_long_signal = prev < prev_upper and current_close >= upper
        mom_short_signal = prev > prev_lower and current_close <= lower

        if self.signal_mode == "mean_reversion":
            long_entry_signal = mr_long_signal
            short_entry_signal = mr_short_signal
        else:  # momentum
            long_entry_signal = mom_long_signal
            short_entry_signal = mom_short_signal

        # Exit signals (midpoint mode only)
        mr_long_mid_exit = prev < prev_middle and current_close >= middle
        mr_short_mid_exit = prev > prev_middle and current_close <= middle
        mom_long_mid_exit = prev > prev_middle and current_close <= middle
        mom_short_mid_exit = prev < prev_middle and current_close >= middle

        if self.exit_mode == "midpoint":
            if self.signal_mode == "mean_reversion":
                long_exit_signal = mr_long_mid_exit
                short_exit_signal = mr_short_mid_exit
            else:
                long_exit_signal = mom_long_mid_exit
                short_exit_signal = mom_short_mid_exit
        else:  # breakout
            long_exit_signal = False
            short_exit_signal = False

        return (
            long_entry_signal,
            short_entry_signal,
            long_exit_signal,
            short_exit_signal,
        )

    def _handle_long_position(
        self,
        candle: MidPriceCandle,
        current_close: float,
        short_entry_signal: bool,
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
            if self._close_position(candle, "BBAND midpoint exit"):
                self._stopped_out_count = 0
            return

        if self.allow_flip and short_entry_signal and self._cooldown_left == 0:
            if self._reverse_position(
                candle=candle,
                signal=-1,
                current_close=current_close,
                reason="Flip to short",
            ):
                self._stopped_out_count = 0
            return

        if self.use_max_holding and self._bars_held() >= self.max_holding_bars:
            self._close_position(candle, "Max holding period reached")

    def _handle_short_position(
        self,
        candle: MidPriceCandle,
        current_close: float,
        long_entry_signal: bool,
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
            if self._close_position(candle, "BBAND midpoint exit"):
                self._stopped_out_count = 0
            return

        if self.allow_flip and long_entry_signal and self._cooldown_left == 0:
            if self._reverse_position(
                candle=candle,
                signal=1,
                current_close=current_close,
                reason="Flip to long",
            ):
                self._stopped_out_count = 0
            return

        if self.use_max_holding and self._bars_held() >= self.max_holding_bars:
            self._close_position(candle, "Max holding period reached")

    def _enter_long(
        self,
        candle: MidPriceCandle,
        current_close: float,
        reason: str = "BBAND long entry",
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
            current_close=current_close,
            candle=candle,
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
            self.logger.info(f"[SIGNAL] LONG ENTRY | {reason} | Price: {close_price:.4f}")
        else:
            self.logger.error("Failed to submit long entry order")

    def _enter_short(
        self,
        candle: MidPriceCandle,
        current_close: float,
        reason: str = "BBAND short entry",
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
            current_close=current_close,
            candle=candle,
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
            self.logger.info(f"[SIGNAL] SHORT ENTRY | {reason} | Price: {close_price:.4f}")
        else:
            self.logger.error("Failed to submit short entry order")

    def _reverse_position(
        self,
        candle: MidPriceCandle,
        signal: int,
        current_close: float,
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
            current_close=current_close,
            candle=candle,
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
            side_label = "LONG" if signal == 1 else "SHORT"
            self.logger.info(
                f"[SIGNAL] REVERSAL TO {side_label} | {reason} | Price: {close_price:.4f}"
            )
        else:
            self.logger.error("Failed to submit reversal order")

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
                self.logger.info(f"[SIGNAL] LONG EXIT | {reason} | Price: {close_price:.4f}")
            else:
                self.logger.info(f"[SIGNAL] SHORT EXIT | {reason} | Price: {close_price:.4f}")
        else:
            self.logger.error("Failed to submit close order")

        return ok

    def _build_signal_context(
        self,
        reason: str,
        current_close: float,
        candle: MidPriceCandle,
        action: str,
    ):
        return build_bband_signal_context(
            reason=reason,
            bband_upper=self.bband.upper,
            bband_middle=self.bband.middle,
            bband_lower=self.bband.lower,
            prev_close=self._previous_close,
            signal_mode=self.signal_mode,
            exit_mode=self.exit_mode,
            bband_period=self.bband_period,
            nbdevup=self.nbdevup,
            nbdevdn=self.nbdevdn,
            matype=self.matype,
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
