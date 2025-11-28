from dataclasses import dataclass

from .base import Strategy
from .models import Bar, PositionSide
from .indicators import PPO
from common.interface_order import OrderSizeMode
from .strategy_action import StrategyAction
from .strategy_order_mode import StrategyOrderMode


@dataclass(frozen=True)
class PPOMomentumStrategyConfig:
    """PPO Momentum Strategy configuration."""

    instrument_id: str
    bar_type: str

    # PPO Parameters
    ppo_fast_period: int = 38
    ppo_slow_period: int = 205
    matype: int = 3  # Moving average type: 0=SMA, 1=EMA, 2=WMA, 3=DEMA
    ppo_upper: float = 1.4  # Upper threshold for momentum
    ppo_lower: float = -0.8  # Lower threshold for momentum
    ppo_mid: float = 0.0  # Midpoint for exit

    # Position Management
    quantity: float = 1.0  # Position size (deprecated, use notional_amount)
    notional_amount: float = 500.0  # Order size in notional value
    stop_loss_percent: float = 0.104  # Stop loss distance (decimal: 0.104 = 10.4%)

    # Risk Management
    max_holding_bars: int = 93  # Max holding period in bars
    use_stop_loss: bool = True


class PPOMomentumStrategy(Strategy):
    """
    PPO Momentum Strategy Implementation
    """

    def __init__(self, config: PPOMomentumStrategyConfig) -> None:
        super().__init__(config)

        self.config = config

        # PPO Parameters
        self.ppo_fast_period = config.ppo_fast_period
        self.ppo_slow_period = config.ppo_slow_period
        self.matype = config.matype
        self.ppo_upper = config.ppo_upper
        self.ppo_lower = config.ppo_lower
        self.ppo_mid = config.ppo_mid

        # Position Management
        self.quantity = config.quantity  # Deprecated, kept for backward compatibility
        self.notional_amount = config.notional_amount
        self.stop_loss_percent = config.stop_loss_percent

        # Risk Management
        self.max_holding_bars = config.max_holding_bars
        self.use_stop_loss = config.use_stop_loss

        # Initialize PPO indicator
        self.ppo = PPO(
            fast_period=self.ppo_fast_period, slow_period=self.ppo_slow_period, ma_type=self.matype
        )

        # State tracking
        self._previous_ppo = 0.0
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
            self.log.error(f"Instrument {self.instrument_id} not found in cache")
            pass

        self.subscribe_bars(self.bar_type)
        self.log.info(f"PPOMomentumStrategy started for {self.instrument_id}")

    def on_bar(self, bar: Bar):
        """Handle incoming bar data."""
        self.ppo.handle_bar(bar)

        if not self.ppo.initialized:
            return

        # Check stop loss first
        if self.use_stop_loss:
            self._check_stop_loss(bar)

        self._execute_momentum_mode(bar)

        self._previous_ppo = self.ppo.value
        self._bars_processed += 1

    def _execute_momentum_mode(self, bar: Bar) -> None:
        """Momentum Mode Logic."""
        current_ppo = self.ppo.value

        # Entry conditions (momentum)
        if self.cache.is_flat(self.instrument_id):
            # Long entry: PPO crosses above upper threshold (momentum breakout)
            if self._previous_ppo < self.ppo_upper and current_ppo >= self.ppo_upper:
                self._enter_long(bar, reason="PPO momentum breakout")

            # Short entry: PPO crosses below lower threshold (momentum breakdown)
            elif self._previous_ppo > self.ppo_lower and current_ppo <= self.ppo_lower:
                self._enter_short(bar, reason="PPO momentum breakdown")

        # Exit conditions (midpoint)
        else:
            # Exit long: PPO crosses below midpoint
            if (
                self._previous_ppo > self.ppo_mid
                and current_ppo <= self.ppo_mid
                and self.cache.is_net_long(self.instrument_id)
            ):
                self._close_position(bar, "PPO returned to midpoint")

            # Exit short: PPO crosses above midpoint
            elif (
                self._previous_ppo < self.ppo_mid
                and current_ppo >= self.ppo_mid
                and self.cache.is_net_short(self.instrument_id)
            ):
                self._close_position(bar, "PPO returned to midpoint")

            # Max holding period exit
            elif self._bars_processed - self._position_entry_bar >= self.max_holding_bars:
                self._close_position(bar, "Max holding period reached")

    def _enter_long(self, bar: Bar, reason: str = "Momentum signal") -> None:
        if self.cache.is_net_long(self.instrument_id):
            self.log.warning("Already in long position")
            return

        close_price = bar.close if bar.close is not None else 0.0
        if close_price == 0.0:
            return

        stop_price = close_price * (1 - self.stop_loss_percent) if self.use_stop_loss else None

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
            if self.use_stop_loss:
                self._stop_loss_price = stop_price
            self.log.info(
                f"🟢 LONG ENTRY | {reason} | Price: {close_price:.4f} | SL: {stop_price:.4f if stop_price else 'N/A'}"
            )
            self._position_side = PositionSide.LONG
            self._position_entry_bar = self._bars_processed
        else:
            self.log.error("Failed to submit long entry order")

    def _enter_short(self, bar: Bar, reason: str = "Momentum signal") -> None:
        if self.cache.is_net_short(self.instrument_id):
            self.log.warning("Already in short position")
            return

        close_price = bar.close if bar.close is not None else 0.0
        if close_price == 0.0:
            return

        stop_price = close_price * (1 + self.stop_loss_percent) if self.use_stop_loss else None

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
            if self.use_stop_loss:
                self._stop_loss_price = stop_price
            self.log.info(
                f"🔴 SHORT ENTRY | {reason} | Price: {close_price:.4f} | SL: {stop_price:.4f if stop_price else 'N/A'}"
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
        ok = self.submit_market_close(
            price=close_price,
            tags=tags,
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
        if (
            self._stop_loss_price is None
            or self.cache.is_flat(self.instrument_id)
            or not self.use_stop_loss
        ):
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
