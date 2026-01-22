from dataclasses import dataclass

from engine.strategies.base import Strategy
from engine.strategies.models import Bar, PositionSide
from engine.strategies.indicators import APO
from common.interface_order import OrderSizeMode
from engine.strategies.strategy_action import StrategyAction
from engine.strategies.strategy_order_mode import StrategyOrderMode
from engine.database.models import build_apo_signal_context


@dataclass(frozen=True)
class APOMeanReversionStrategyConfig:
    """APO Mean Reversion Strategy configuration."""

    instrument_id: str
    bar_type: str

    # APO Parameters
    apo_fast_period: int = 10
    apo_slow_period: int = 122
    matype: int = 1  # Moving average type: 0=SMA, 1=EMA, 2=WMA, 3=DEMA
    apo_upper: float = 38.0  # Upper threshold for mean reversion
    apo_lower: float = -31.0  # Lower threshold for mean reversion
    apo_mid: float = -2.0  # Midpoint for reference

    # Position Management
    quantity: float = 1.0  # Position size (deprecated, use notional_amount)
    notional_amount: float = 500.0  # Order size in notional value
    stop_loss_percent: float = 0.07  # Stop loss distance (decimal: 0.07 = 7%)

    # Risk Management
    max_holding_bars: int = 175  # Max holding period in bars


class APOMeanReversionStrategy(Strategy):
    """
    APO Mean Reversion Strategy Implementation
    """

    def __init__(self, config: APOMeanReversionStrategyConfig) -> None:
        super().__init__(config)

        self.config = config

        # APO Parameters
        self.apo_fast_period = config.apo_fast_period
        self.apo_slow_period = config.apo_slow_period
        self.matype = config.matype
        self.apo_upper = config.apo_upper
        self.apo_lower = config.apo_lower
        self.apo_mid = config.apo_mid

        # Position Management
        self.quantity = config.quantity  # Deprecated, kept for backward compatibility
        self.notional_amount = config.notional_amount
        self.stop_loss_percent = config.stop_loss_percent

        # Risk Management
        self.max_holding_bars = config.max_holding_bars

        # Initialize APO indicator
        self.apo = APO(
            fast_period=self.apo_fast_period, slow_period=self.apo_slow_period, ma_type=self.matype
        )

        # State tracking
        self._previous_apo = 0.0
        self._bars_processed = 0
        self._position_side = None
        self._position_entry_bar = 0
        self._stop_loss_price = None  # Stop loss price for current position

        self.instrument_id = config.instrument_id
        self.bar_type = config.bar_type
        self.instrument = None

    def on_start(self) -> None:
        """Initialize strategy on start."""
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument {self.instrument_id} not found in cache \n")

        self.subscribe_bars(self.bar_type)
        self.log.info(f"APOMeanReversionStrategy started for {self.instrument_id}")

    def on_bar(self, bar: Bar):
        """Handle incoming bar data."""
        self.apo.handle_bar(bar)

        if not self.apo.initialized:
            return

        # Check stop loss first
        self._check_stop_loss(bar)

        self._execute_mean_reversion_mode(bar)

        self._previous_apo = self.apo.value
        self._bars_processed += 1

    def _execute_mean_reversion_mode(self, bar: Bar) -> None:
        """Mean Reversion Mode Logic."""
        current_apo = self.apo.value

        # Entry conditions (mean reversion)
        if self.cache.is_flat(self.instrument_id):
            # Long entry: APO crosses above lower threshold (oversold recovery)
            if self._previous_apo < self.apo_lower and current_apo >= self.apo_lower:
                self._enter_long(bar, reason="APO oversold recovery")

            # Short entry: APO crosses below upper threshold (overbought decline)
            elif self._previous_apo > self.apo_upper and current_apo <= self.apo_upper:
                self._enter_short(bar, reason="APO overbought decline")

        # Exit conditions (breakout mode - opposite entry signal)
        else:
            # Exit long when short entry signal triggers (APO crosses below upper threshold)
            if (
                self._previous_apo > self.apo_upper
                and current_apo <= self.apo_upper
                and self.cache.is_net_long(self.instrument_id)
            ):
                self._close_position(bar, "APO opposite breakout")

            # Exit short when long entry signal triggers (APO crosses above lower threshold)
            elif (
                self._previous_apo < self.apo_lower
                and current_apo >= self.apo_lower
                and self.cache.is_net_short(self.instrument_id)
            ):
                self._close_position(bar, "APO opposite breakout")

            # Max holding period exit
            elif self._bars_processed - self._position_entry_bar >= self.max_holding_bars:
                self._close_position(bar, "Max holding period reached")

    def _enter_long(self, bar: Bar, reason: str = "Mean reversion signal") -> None:
        if self.cache.is_net_long(self.instrument_id):
            self.log.warning("Already in long position")
            return

        close_price = bar.close if bar.close is not None else 0.0
        if close_price == 0.0:
            return

        stop_price = close_price * (1 - self.stop_loss_percent)

        # Create strategy order mode with notional
        strategy_order_mode = StrategyOrderMode(
            order_size_mode=OrderSizeMode.NOTIONAL, notional_value=self.notional_amount
        )

        # Build signal context with full indicator snapshot
        signal_context = build_apo_signal_context(
            reason=reason,
            apo=self.apo.value,
            prev_apo=self._previous_apo,
            apo_upper=self.apo_upper,
            apo_lower=self.apo_lower,
            apo_mid=self.apo_mid,
            apo_fast_period=self.apo_fast_period,
            apo_slow_period=self.apo_slow_period,
            stop_loss_percent=self.stop_loss_percent,
            max_holding_bars=self.max_holding_bars,
            notional_amount=self.notional_amount,
            candle={
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
            },
            action="ENTRY",
        )

        # Submit order via on_signal
        ok = self.on_signal(
            signal=1,  # BUY
            price=close_price,
            strategy_actions=StrategyAction.OPEN_CLOSE_POSITION,
            strategy_order_mode=strategy_order_mode,
            signal_context=signal_context,
        )

        if ok:
            # Store stop loss price for checking at each bar
            self._stop_loss_price = stop_price
            self.log.info(
                f"🟢 LONG ENTRY | {reason} | Price: {close_price:.4f} | SL: {stop_price:.4f}"
            )
            self._position_side = PositionSide.LONG
            self._position_entry_bar = self._bars_processed
        else:
            self.log.error("Failed to submit long entry order")

    def _enter_short(self, bar: Bar, reason: str = "Mean reversion signal") -> None:
        if self.cache.is_net_short(self.instrument_id):
            self.log.warning("Already in short position")
            return

        close_price = bar.close if bar.close is not None else 0.0
        if close_price == 0.0:
            return

        stop_price = close_price * (1 + self.stop_loss_percent)

        # Create strategy order mode with notional
        strategy_order_mode = StrategyOrderMode(
            order_size_mode=OrderSizeMode.NOTIONAL, notional_value=self.notional_amount
        )

        # Build signal context with full indicator snapshot
        signal_context = build_apo_signal_context(
            reason=reason,
            apo=self.apo.value,
            prev_apo=self._previous_apo,
            apo_upper=self.apo_upper,
            apo_lower=self.apo_lower,
            apo_mid=self.apo_mid,
            apo_fast_period=self.apo_fast_period,
            apo_slow_period=self.apo_slow_period,
            stop_loss_percent=self.stop_loss_percent,
            max_holding_bars=self.max_holding_bars,
            notional_amount=self.notional_amount,
            candle={
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
            },
            action="ENTRY",
        )

        # Submit order via on_signal
        ok = self.on_signal(
            signal=-1,  # SELL
            price=close_price,
            strategy_actions=StrategyAction.OPEN_CLOSE_POSITION,
            strategy_order_mode=strategy_order_mode,
            signal_context=signal_context,
        )

        if ok:
            # Store stop loss price for checking at each bar
            self._stop_loss_price = stop_price
            self.log.info(
                f"🔴 SHORT ENTRY | {reason} | Price: {close_price:.4f} | SL: {stop_price:.4f}"
            )
            self._position_side = PositionSide.SHORT
            self._position_entry_bar = self._bars_processed
        else:
            self.log.error("Failed to submit short entry order")

    def _close_position(self, bar: Bar, reason: str) -> None:
        if self.cache.is_flat(self.instrument_id):
            return

        close_price = bar.close if bar.close is not None else 0.0
        if close_price == 0.0:
            return

        position = self.cache.position(self.instrument_id)
        if not position:
            return

        tags = [f"reason={reason}"]

        # Submit market close order directly
        ok = self._order_manager.submit_market_close(
            strategy_id=self._strategy_id, symbol=self._symbol, price=close_price, tags=tags
        )

        if ok:
            # Clear stop loss tracking
            self._stop_loss_price = None
            if position.is_long:
                self.log.info(f"🟡 LONG EXIT: {reason} | Price: {close_price:.4f}")
            else:
                self.log.info(f"🟡 SHORT EXIT: {reason} | Price: {close_price:.4f}")
        else:
            self.log.error("Failed to submit close order")

    def _check_stop_loss(self, bar: Bar) -> None:
        """Check if stop loss should be triggered at current bar price."""
        if self._stop_loss_price is None or self.cache.is_flat(self.instrument_id):
            return

        close_price = bar.close if bar.close is not None else 0.0
        if close_price == 0.0:
            return

        # Check stop loss for long position
        if self._position_side == PositionSide.LONG and close_price <= self._stop_loss_price:
            self._close_position(bar, f"Stop loss triggered at {close_price:.4f}")

        # Check stop loss for short position
        elif self._position_side == PositionSide.SHORT and close_price >= self._stop_loss_price:
            self._close_position(bar, f"Stop loss triggered at {close_price:.4f}")

        self._position_side = None
