import logging
from dataclasses import dataclass

from common.interface_order import OrderSizeMode
from engine.database.models import build_cci_signal_context

from ..market_data.candle import MidPriceCandle
from .base import Strategy
from .indicators import CommodityChannelIndex
from .models import Instrument, PositionSide
from .strategy_action import StrategyAction
from .strategy_order_mode import StrategyOrderMode


@dataclass(frozen=True)
class CCISignalStrategyConfig:
    """CCI Signal Strategy configuration."""

    instrument_id: str
    bar_type: str

    # CCI Parameters (from Results summary)
    cci_period: int = 14
    cci_upper: float = 205.0
    cci_lower: float = -101.0
    cci_mid: float = 12.0

    # Signal Behavior
    signal_mode: str = "momentum"   # mean_reversion | momentum
    exit_mode: str = "midpoint"     # midpoint | breakout

    # Position Management
    quantity: float = 1.0
    notional_amount: float = 500.0
    stop_loss_percent: float = 0.074
    take_profit_percent: float = 0.05
    max_holding_bars: int = 25
    cooldown_bars: int = 0

    # Risk Management
    use_stop_loss: bool = True
    use_take_profit: bool = False
    use_max_holding: bool = True
    allow_flip: bool = True


class CCISignalStrategy(Strategy):
    """
    CCI (Commodity Channel Index) Signal Strategy Implementation.

    Momentum mode (default): enters long when CCI crosses above the upper threshold,
    short when CCI crosses below the lower threshold. Exits at the midpoint.

    Mean reversion mode: enters long when CCI crosses back above the lower threshold,
    short when CCI crosses back below the upper threshold.
    """

    VALID_SIGNAL_MODES = {"mean_reversion", "momentum"}
    VALID_EXIT_MODES = {"midpoint", "breakout"}

    def __init__(self, config: CCISignalStrategyConfig) -> None:
        super().__init__(config)

        self.config = config

        # CCI parameters
        self.cci_period = config.cci_period
        self.cci_upper = config.cci_upper
        self.cci_lower = config.cci_lower
        self.cci_mid = config.cci_mid

        # Signal behavior
        self.signal_mode = config.signal_mode
        if self.signal_mode not in self.VALID_SIGNAL_MODES:
            logging.warning(
                f"Invalid signal_mode={self.signal_mode}, defaulting to momentum"
            )
            self.signal_mode = "momentum"

        self.exit_mode = config.exit_mode
        if self.exit_mode not in self.VALID_EXIT_MODES:
            logging.warning(
                f"Invalid exit_mode={self.exit_mode}, defaulting to midpoint"
            )
            self.exit_mode = "midpoint"

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

        # Initialize CCI indicator
        self.cci = CommodityChannelIndex(period=self.cci_period)

        # State tracking
        self._previous_cci = 0.0
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
        self.log.info(
            f"[SIGNAL] CCISignalStrategy started for {self.instrument_id} "
            f"(mode={self.signal_mode}, exit={self.exit_mode})"
        )

    def on_candle_created(self, candle: MidPriceCandle):
        """Handle incoming candle data."""
        self.cci.handle_bar(candle)
        if not self.cci.initialized:
            return

        current_cci = self.cci.value

        if self._cooldown_left > 0 and self.cache.is_flat(self.instrument_id):
            self._cooldown_left -= 1

        (
            long_entry_signal,
            short_entry_signal,
            long_exit_signal,
            short_exit_signal,
        ) = self._compute_signals(current_cci)

        if self.cache.is_flat(self.instrument_id):
            if self._cooldown_left == 0:
                if long_entry_signal:
                    self._enter_long(candle, current_cci, reason="CCI long entry")
                elif short_entry_signal:
                    self._enter_short(candle, current_cci, reason="CCI short entry")
        else:
            self._sync_position_state()

            if self.cache.is_net_long(self.instrument_id):
                self._handle_long_position(
                    candle=candle,
                    current_cci=current_cci,
                    short_entry_signal=short_entry_signal,
                    long_exit_signal=long_exit_signal,
                )
            elif self.cache.is_net_short(self.instrument_id):
                self._handle_short_position(
                    candle=candle,
                    current_cci=current_cci,
                    long_entry_signal=long_entry_signal,
                    short_exit_signal=short_exit_signal,
                )

        self._previous_cci = current_cci
        self._bars_processed += 1

    def _compute_signals(self, current_cci: float):
        # Mean reversion: enter when CCI crosses back inside the thresholds
        mr_long_signal = (
            self._previous_cci < self.cci_lower and current_cci >= self.cci_lower
        )
        mr_short_signal = (
            self._previous_cci > self.cci_upper and current_cci <= self.cci_upper
        )

        # Momentum: enter when CCI breaks through the thresholds
        mom_long_signal = (
            self._previous_cci < self.cci_upper and current_cci >= self.cci_upper
        )
        mom_short_signal = (
            self._previous_cci > self.cci_lower and current_cci <= self.cci_lower
        )

        if self.signal_mode == "mean_reversion":
            long_entry_signal = mr_long_signal
            short_entry_signal = mr_short_signal
        else:  # momentum
            long_entry_signal = mom_long_signal
            short_entry_signal = mom_short_signal

        # Exit signals
        mr_long_mid_exit = (
            self._previous_cci < self.cci_mid and current_cci >= self.cci_mid
        )
        mr_short_mid_exit = (
            self._previous_cci > self.cci_mid and current_cci <= self.cci_mid
        )
        mom_long_mid_exit = (
            self._previous_cci > self.cci_mid and current_cci <= self.cci_mid
        )
        mom_short_mid_exit = (
            self._previous_cci < self.cci_mid and current_cci >= self.cci_mid
        )

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
        current_cci: float,
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
            if self._close_position(candle, "CCI midpoint exit"):
                self._stopped_out_count = 0
            return

        if self.allow_flip and short_entry_signal and self._cooldown_left == 0:
            if self._reverse_position(
                candle=candle,
                signal=-1,
                current_cci=current_cci,
                reason="Flip to short",
            ):
                self._stopped_out_count = 0
            return

        if self.use_max_holding and self._bars_held() >= self.max_holding_bars:
            self._close_position(candle, "Max holding period reached")

    def _handle_short_position(
        self,
        candle: MidPriceCandle,
        current_cci: float,
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
            if self._close_position(candle, "CCI midpoint exit"):
                self._stopped_out_count = 0
            return

        if self.allow_flip and long_entry_signal and self._cooldown_left == 0:
            if self._reverse_position(
                candle=candle,
                signal=1,
                current_cci=current_cci,
                reason="Flip to long",
            ):
                self._stopped_out_count = 0
            return

        if self.use_max_holding and self._bars_held() >= self.max_holding_bars:
            self._close_position(candle, "Max holding period reached")

    def _enter_long(
        self,
        candle: MidPriceCandle,
        current_cci: float,
        reason: str = "CCI long entry",
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
            current_cci=current_cci,
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
            self._position_side = PositionSide.LONG
            self._entry_bar = self._bars_processed
            self._entry_price = close_price
            self.log.info(f"[SIGNAL] LONG ENTRY | {reason} | Price: {close_price:.4f}")
        else:
            self.log.error("Failed to submit long entry order")

    def _enter_short(
        self,
        candle: MidPriceCandle,
        current_cci: float,
        reason: str = "CCI short entry",
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
            current_cci=current_cci,
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
            self._position_side = PositionSide.SHORT
            self._entry_bar = self._bars_processed
            self._entry_price = close_price
            self.log.info(f"[SIGNAL] SHORT ENTRY | {reason} | Price: {close_price:.4f}")
        else:
            self.log.error("Failed to submit short entry order")

    def _reverse_position(
        self,
        candle: MidPriceCandle,
        signal: int,
        current_cci: float,
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
            current_cci=current_cci,
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
            self._position_side = (
                PositionSide.LONG if signal == 1 else PositionSide.SHORT
            )
            self._entry_bar = self._bars_processed
            self._entry_price = close_price
            side_label = "LONG" if signal == 1 else "SHORT"
            self.log.info(
                f"[SIGNAL] REVERSAL TO {side_label} | {reason} | Price: {close_price:.4f}"
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
                self.log.info(f"[SIGNAL] LONG EXIT | {reason} | Price: {close_price:.4f}")
            else:
                self.log.info(f"[SIGNAL] SHORT EXIT | {reason} | Price: {close_price:.4f}")
            self._position_side = None
            self._entry_bar = None
            self._entry_price = None
        else:
            self.log.error("Failed to submit close order")

        return ok

    def _build_signal_context(
        self,
        reason: str,
        current_cci: float,
        candle: MidPriceCandle,
        action: str,
    ):
        return build_cci_signal_context(
            reason=reason,
            cci=current_cci,
            prev_cci=self._previous_cci,
            cci_upper=self.cci_upper,
            cci_lower=self.cci_lower,
            cci_mid=self.cci_mid,
            signal_mode=self.signal_mode,
            exit_mode=self.exit_mode,
            cci_period=self.cci_period,
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
