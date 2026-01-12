from dataclasses import dataclass

from engine.strategies.base import Strategy
from engine.market_data.candle import MidPriceCandle
from common.interface_order import OrderSizeMode
from engine.strategies.models import PositionSide
from engine.strategies.indicators import ADX
from engine.strategies.strategy_action import StrategyAction
from engine.strategies.strategy_order_mode import StrategyOrderMode


@dataclass(frozen=True)
class ADXMeanReversionStrategyConfig:
    """ADX Mean Reversion Strategy configuration."""

    instrument_id: str
    bar_type: str

    # ADX Parameters
    adx_period: int = 22
    adx_smoothing: int = 22

    # Position Management
    quantity: float = 1.0  # Position size (deprecated, use notional_amount)
    notional_amount: float = 500.0  # Order size in notional value
    stop_loss_percent: float = 0.03  # Stop loss distance (decimal: 0.03 = 3%)

    # ADX Thresholds
    adx_low: float = 23.0  # Range-bound threshold
    adx_mid: float = 38.0  # Weak trend threshold
    adx_high: float = 65.0  # Strong trend threshold

    # DI Spread parameters
    di_spread_extreme: float = 8.625853  # +DI/-DI difference for extremes
    di_spread_midline: float = 5.0  # +DI/-DI midline for reversion exits

    # Risk Management
    max_holding_bars: int = 125  # Max holding period in bars


class ADXMeanReversionStrategy(Strategy):
    """
    ADX Mean Reversion Strategy Implementation
    """

    def __init__(self, config: ADXMeanReversionStrategyConfig) -> None:
        super().__init__(config)

        self.config = config
        self.mode = "mean_reversion"

        # ADX Parameters
        self.adx_period = config.adx_period
        self.adx_smoothing = config.adx_smoothing
        self.adx_low = config.adx_low
        self.adx_mid = config.adx_mid
        self.adx_high = config.adx_high

        # DI Spread parameters
        self.di_spread_extreme = config.di_spread_extreme
        self.di_spread_midline = config.di_spread_midline

        # Position Management
        self.quantity = config.quantity  # Deprecated, kept for backward compatibility
        self.notional_amount = config.notional_amount
        self.stop_loss_percent = config.stop_loss_percent

        # Risk Management
        self.max_holding_bars = config.max_holding_bars

        # Initialize custom ADX indicator
        self.adx = ADX(period=self.adx_period)

        # State tracking
        self._previous_plus_di = 0.0
        self._previous_minus_di = 0.0
        self._previous_adx = 0.0
        self._bars_processed = 0
        self._crossover_signal = None
        self._position_side = None
        self._long_entry_bar = None
        self._short_entry_bar = None
        # Stop loss tracking (checked at each bar instead of submitting stop orders)
        self._stop_loss_price = None  # Stop loss price for current position

        self.instrument_id = config.instrument_id
        self.bar_type = config.bar_type
        self.instrument = None

    @property
    def adx_slope(self) -> float:
        """Calculate ADX slope as current - previous."""
        return self.adx.value - self._previous_adx

    def on_start(self) -> None:
        """Initialize strategy on start."""
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument {self.instrument_id} not found in cache \n")
            # In a real system we might request it or fail, here we assume it's pre-loaded or we proceed

        self.subscribe_bars(self.bar_type)

        self.log.info(
            f"ADXMeanReversionStrategy started for {self.instrument_id} with mode: {self.mode}"
        )

    def on_candle_created(self, candle: MidPriceCandle):
        """Handle incoming candle data."""
        self._bars_processed += 1
        self.log.info(
            f"🕯️ Received candle #{self._bars_processed} | "
            f"Time: {candle.start_time} | "
            f"OHLC: O={candle.open:.2f} H={candle.high:.2f} L={candle.low:.2f} C={candle.close:.2f}"
        )

        # Update indicator
        self.adx.handle_bar(candle)

        # Check readiness states
        if not self.adx.initialized:
            return

        # Check stop loss first (before other logic)
        self._check_stop_loss(candle)

        # Detect DI crossovers
        self._detect_crossovers()

        # Execute strategy based on mode
        # Execute momentum mode (ADX strategy is momentum-based)
        self._execute_momentum_mode(candle)

        # Update state for next bar
        self._previous_plus_di = self.adx.pos
        self._previous_minus_di = self.adx.neg
        self._previous_adx = self.adx.value

    def _detect_crossovers(self) -> None:
        """Detect +DI and -DI crossovers."""
        if self._previous_plus_di <= self._previous_minus_di and self.adx.pos > self.adx.neg:
            self._crossover_signal = "long"
            self.log.info("📈 +DI crossed above -DI (BULLISH)")

        elif self._previous_minus_di <= self._previous_plus_di and self.adx.neg > self.adx.pos:
            self._crossover_signal = "short"
            self.log.info("📉 -DI crossed above +DI (BEARISH)")

        else:
            self._crossover_signal = None

    def _execute_momentum_mode(self, candle: MidPriceCandle) -> None:
        """Momentum Mode Logic."""
        # Entry conditions
        if self._crossover_signal == "long":
            self.log.debug(
                f"Long signal: ADX={self.adx.value:.2f} (need >{self.adx_high}), slope={self.adx_slope:.2f}"
            )
            if (
                self.adx.value > self.adx_high
                and self.adx_slope > 0
                and self.cache.is_flat(self.instrument_id)
            ):
                self._enter_long(candle)

        elif self._crossover_signal == "short":
            self.log.debug(
                f"Short signal: ADX={self.adx.value:.2f} (need >{self.adx_high}), slope={self.adx_slope:.2f}"
            )
            if (
                self.adx.value > self.adx_high
                and self.adx_slope > 0
                and self.cache.is_flat(self.instrument_id)
            ):
                self._enter_short(candle)

        # Exit conditions
        else:
            if self._crossover_signal == "short" and not self.cache.is_flat(self.instrument_id):
                self._close_position(candle, "Bearish cross detected")

            elif self._crossover_signal == "long" and not self.cache.is_flat(self.instrument_id):
                self._close_position(candle, "Bullish cross detected")

            elif self.adx.value < self.adx_mid and not self.cache.is_flat(self.instrument_id):
                self._close_position(candle, "ADX weakness detected")

        # Max holding period exits
        if self._position_side == PositionSide.LONG and self._long_entry_bar is not None:
            if (self._bars_processed - self._long_entry_bar) >= self.max_holding_bars:
                self._close_position(candle, "Max holding period reached")

        if self._position_side == PositionSide.SHORT and self._short_entry_bar is not None:
            if (self._bars_processed - self._short_entry_bar) >= self.max_holding_bars:
                self._close_position(candle, "Max holding period reached")

    def _check_stop_loss(self, candle: MidPriceCandle) -> None:
        """Check if stop loss should be triggered at current candle price."""
        if self._stop_loss_price is None or self.cache.is_flat(self.instrument_id):
            return

        close_price = candle.close if candle.close is not None else 0.0
        if close_price == 0.0:
            return

        # Check stop loss for long position
        if self._position_side == PositionSide.LONG and close_price <= self._stop_loss_price:
            self._close_position(candle, f"Stop loss triggered at {close_price:.4f}")

        # Check stop loss for short position
        elif self._position_side == PositionSide.SHORT and close_price >= self._stop_loss_price:
            self._close_position(candle, f"Stop loss triggered at {close_price:.4f}")

    def _enter_long(self, candle: MidPriceCandle, reason: str = "Momentum signal") -> None:
        if self.cache.is_net_long(self.instrument_id):
            self.log.warning("Already in long position")
            return

        close_price = candle.close if candle.close is not None else 0.0
        if close_price == 0.0:
            return

        stop_price = close_price * (1 - self.stop_loss_percent)

        # Create strategy order mode with notional
        strategy_order_mode = StrategyOrderMode(
            order_size_mode=OrderSizeMode.NOTIONAL, notional_value=self.notional_amount
        )

        # Submit order via on_signal
        ok = self.on_signal(
            signal=1,  # BUY
            price=close_price,
            strategy_actions=StrategyAction.OPEN_CLOSE_POSITION,
            strategy_order_mode=strategy_order_mode,
        )

        if ok:
            # Store stop loss price for checking at each bar
            self._stop_loss_price = stop_price
            self.log.info(
                f"🟢 LONG ENTRY | {reason} | Price: {close_price:.4f} | SL: {stop_price:.4f}"
            )
            self._position_side = PositionSide.LONG
            self._long_entry_bar = self._bars_processed
        else:
            self.log.error("Failed to submit long entry order")

    def _enter_short(self, candle: MidPriceCandle, reason: str = "Momentum signal") -> None:
        if self.cache.is_net_short(self.instrument_id):
            self.log.warning("Already in short position")
            return

        close_price = candle.close if candle.close is not None else 0.0
        if close_price == 0.0:
            return

        stop_price = close_price * (1 + self.stop_loss_percent)

        # Create strategy order mode with notional
        strategy_order_mode = StrategyOrderMode(
            order_size_mode=OrderSizeMode.NOTIONAL, notional_value=self.notional_amount
        )

        # Submit order via on_signal
        ok = self.on_signal(
            signal=-1,  # SELL
            price=close_price,
            strategy_actions=StrategyAction.OPEN_CLOSE_POSITION,
            strategy_order_mode=strategy_order_mode,
        )

        if ok:
            # Store stop loss price for checking at each bar
            self._stop_loss_price = stop_price
            self.log.info(
                f"🔴 SHORT ENTRY | {reason} | Price: {close_price:.4f} | SL: {stop_price:.4f}"
            )
            self._position_side = PositionSide.SHORT
            self._short_entry_bar = self._bars_processed
        else:
            self.log.error("Failed to submit short entry order")

    def _close_position(self, candle: MidPriceCandle, reason: str) -> None:
        if self.cache.is_flat(self.instrument_id):
            return

        position = self.cache.position(self.instrument_id)
        if not position:
            return

        tags = [f"reason={reason}"]
        close_price = candle.close if candle.close is not None else 0.0

        # Submit market close order directly
        ok = self._order_manager.submit_market_close(
            strategy_id=self._strategy_id, symbol=self._symbol, price=close_price, tags=tags
        )

        if ok:
            if position.is_long:
                self.log.info(f"🟡 LONG EXIT: {reason} | Price: {close_price:.4f}")
            else:
                self.log.info(f"🟡 SHORT EXIT: {reason} | Price: {close_price:.4f}")

            # Reset position tracking
            self._position_side = None
            self._long_entry_bar = None
            self._short_entry_bar = None
            self._stop_loss_price = None
        else:
            self.log.error("Failed to submit close order")
