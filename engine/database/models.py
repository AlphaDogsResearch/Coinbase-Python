"""
Database models for the trading engine persistence layer.

These dataclasses define the structure for data passed to DatabaseManager
for persistence, particularly the SignalContext which captures full
indicator state at signal generation time.
"""

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass
class SignalContext:
    """
    Captures full context at the moment a trading signal is generated.

    This is used to record WHY a signal was generated, including:
    - The human-readable reason
    - All indicator values at signal time
    - Strategy configuration
    - Candle data

    Example usage in a strategy:
        signal_context = SignalContext(
            reason="ROC oversold recovery",
            indicators={
                "roc": 1.23,
                "prev_roc": -0.5,
                "roc_upper": 3.4,
                "roc_lower": -3.6,
            },
            config={
                "roc_period": 22,
                "stop_loss_percent": 0.021,
            },
            candle={"open": 3000.0, "high": 3050.0, "low": 2990.0, "close": 3020.0}
        )
    """

    # Human-readable reason for the signal
    reason: str

    # Indicator values at signal time (e.g., {"roc": 1.23, "prev_roc": -0.5})
    indicators: Dict[str, Any]

    # Strategy configuration snapshot (optional)
    config: Optional[Dict[str, Any]] = None

    # Candle OHLCV data (optional)
    candle: Optional[Dict[str, float]] = None

    # Action type: ENTRY, CLOSE, STOP_LOSS, REVERSAL
    action: Optional[str] = None

    # Additional tags (optional)
    tags: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return asdict(self)


@dataclass
class CandleSnapshot:
    """Snapshot of candle data at signal time."""

    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None
    timestamp: Optional[int] = None

    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary."""
        result = {
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
        }
        if self.volume is not None:
            result["volume"] = self.volume
        if self.timestamp is not None:
            result["timestamp"] = self.timestamp
        return result


# ============================================================================
# INDICATOR-SPECIFIC CONTEXT BUILDERS
# ============================================================================
# These helper functions make it easy to build SignalContext for each strategy


def build_roc_signal_context(
    reason: str,
    current_roc: float,
    previous_roc: float,
    roc_upper: float,
    roc_lower: float,
    roc_mid: float,
    roc_period: int,
    stop_loss_percent: float,
    max_holding_bars: int,
    notional_amount: float,
    candle: Optional[Dict[str, float]] = None,
    action: str = None,
) -> SignalContext:
    """
    Build SignalContext for ROC Mean Reversion strategy.

    Args:
        reason: Why the signal was generated
        current_roc: Current ROC value (as percentage, e.g., 1.23)
        previous_roc: Previous bar's ROC value
        roc_upper: Upper threshold
        roc_lower: Lower threshold
        roc_mid: Midpoint threshold
        roc_period: ROC calculation period
        stop_loss_percent: Stop loss percentage
        max_holding_bars: Maximum holding period
        notional_amount: Order notional value
        candle: OHLC data
        action: Action type (ENTRY, CLOSE, etc.)
    """
    return SignalContext(
        reason=reason,
        indicators={
            "roc": current_roc,
            "prev_roc": previous_roc,
            "roc_upper": roc_upper,
            "roc_lower": roc_lower,
            "roc_mid": roc_mid,
        },
        config={
            "roc_period": roc_period,
            "stop_loss_percent": stop_loss_percent,
            "max_holding_bars": max_holding_bars,
            "notional_amount": notional_amount,
        },
        candle=candle,
        action=action,
    )


def build_adx_signal_context(
    reason: str,
    adx: float,
    plus_di: float,
    minus_di: float,
    di_spread: float,
    adx_low: float,
    adx_mid: float,
    adx_high: float,
    di_spread_extreme: float,
    di_spread_midline: float,
    adx_period: int,
    stop_loss_percent: float,
    max_holding_bars: int,
    notional_amount: float,
    candle: Optional[Dict[str, float]] = None,
    action: str = None,
) -> SignalContext:
    """Build SignalContext for ADX Mean Reversion strategy."""
    return SignalContext(
        reason=reason,
        indicators={
            "adx": adx,
            "plus_di": plus_di,
            "minus_di": minus_di,
            "di_spread": di_spread,
            "adx_low": adx_low,
            "adx_mid": adx_mid,
            "adx_high": adx_high,
            "di_spread_extreme": di_spread_extreme,
            "di_spread_midline": di_spread_midline,
        },
        config={
            "adx_period": adx_period,
            "stop_loss_percent": stop_loss_percent,
            "max_holding_bars": max_holding_bars,
            "notional_amount": notional_amount,
        },
        candle=candle,
        action=action,
    )


def build_ppo_signal_context(
    reason: str,
    ppo: float,
    prev_ppo: float,
    ppo_upper: float,
    ppo_lower: float,
    ppo_mid: float,
    ppo_fast_period: int,
    ppo_slow_period: int,
    stop_loss_percent: float,
    max_holding_bars: int,
    notional_amount: float,
    candle: Optional[Dict[str, float]] = None,
    action: str = None,
) -> SignalContext:
    """Build SignalContext for PPO Momentum strategy."""
    return SignalContext(
        reason=reason,
        indicators={
            "ppo": ppo,
            "prev_ppo": prev_ppo,
            "ppo_upper": ppo_upper,
            "ppo_lower": ppo_lower,
            "ppo_mid": ppo_mid,
        },
        config={
            "ppo_fast_period": ppo_fast_period,
            "ppo_slow_period": ppo_slow_period,
            "stop_loss_percent": stop_loss_percent,
            "max_holding_bars": max_holding_bars,
            "notional_amount": notional_amount,
        },
        candle=candle,
        action=action,
    )


def build_apo_signal_context(
    reason: str,
    apo: float,
    prev_apo: float,
    apo_upper: float,
    apo_lower: float,
    apo_mid: float,
    apo_fast_period: int,
    apo_slow_period: int,
    stop_loss_percent: float,
    max_holding_bars: int,
    notional_amount: float,
    candle: Optional[Dict[str, float]] = None,
    action: str = None,
) -> SignalContext:
    """Build SignalContext for APO Mean Reversion strategy."""
    return SignalContext(
        reason=reason,
        indicators={
            "apo": apo,
            "prev_apo": prev_apo,
            "apo_upper": apo_upper,
            "apo_lower": apo_lower,
            "apo_mid": apo_mid,
        },
        config={
            "apo_fast_period": apo_fast_period,
            "apo_slow_period": apo_slow_period,
            "stop_loss_percent": stop_loss_percent,
            "max_holding_bars": max_holding_bars,
            "notional_amount": notional_amount,
        },
        candle=candle,
        action=action,
    )


def build_cci_signal_context(
    reason: str,
    cci: float,
    prev_cci: float,
    cci_upper: float,
    cci_lower: float,
    cci_mid: float,
    signal_mode: str,
    exit_mode: str,
    cci_period: int,
    stop_loss_percent: float,
    take_profit_percent: float,
    max_holding_bars: int,
    cooldown_bars: int,
    notional_amount: float,
    use_stop_loss: bool,
    use_take_profit: bool,
    use_max_holding: bool,
    allow_flip: bool,
    candle: Optional[Dict[str, float]] = None,
    action: str = None,
) -> SignalContext:
    """Build SignalContext for CCI Signal strategy."""
    return SignalContext(
        reason=reason,
        indicators={
            "cci": cci,
            "prev_cci": prev_cci,
            "cci_upper": cci_upper,
            "cci_lower": cci_lower,
            "cci_mid": cci_mid,
            "signal_mode": signal_mode,
            "exit_mode": exit_mode,
        },
        config={
            "cci_period": cci_period,
            "stop_loss_percent": stop_loss_percent,
            "take_profit_percent": take_profit_percent,
            "max_holding_bars": max_holding_bars,
            "cooldown_bars": cooldown_bars,
            "notional_amount": notional_amount,
            "use_stop_loss": use_stop_loss,
            "use_take_profit": use_take_profit,
            "use_max_holding": use_max_holding,
            "allow_flip": allow_flip,
        },
        candle=candle,
        action=action,
    )


def build_bband_signal_context(
    reason: str,
    bband_upper: float,
    bband_middle: float,
    bband_lower: float,
    prev_close: float,
    signal_mode: str,
    exit_mode: str,
    bband_period: int,
    nbdevup: float,
    nbdevdn: float,
    matype: int,
    stop_loss_percent: float,
    take_profit_percent: float,
    max_holding_bars: int,
    cooldown_bars: int,
    notional_amount: float,
    use_stop_loss: bool,
    use_take_profit: bool,
    use_max_holding: bool,
    allow_flip: bool,
    candle: Optional[Dict[str, float]] = None,
    action: str = None,
) -> SignalContext:
    """Build SignalContext for Bollinger Bands Signal strategy."""
    return SignalContext(
        reason=reason,
        indicators={
            "bband_upper": bband_upper,
            "bband_middle": bband_middle,
            "bband_lower": bband_lower,
            "prev_close": prev_close,
            "signal_mode": signal_mode,
            "exit_mode": exit_mode,
        },
        config={
            "bband_period": bband_period,
            "nbdevup": nbdevup,
            "nbdevdn": nbdevdn,
            "matype": matype,
            "stop_loss_percent": stop_loss_percent,
            "take_profit_percent": take_profit_percent,
            "max_holding_bars": max_holding_bars,
            "cooldown_bars": cooldown_bars,
            "notional_amount": notional_amount,
            "use_stop_loss": use_stop_loss,
            "use_take_profit": use_take_profit,
            "use_max_holding": use_max_holding,
            "allow_flip": allow_flip,
        },
        candle=candle,
        action=action,
    )


def build_rsi_signal_context(
    reason: str,
    rsi: float,
    prev_rsi: float,
    rsi_upper: float,
    rsi_lower: float,
    rsi_mid: float,
    signal_mode: str,
    exit_mode: str,
    rsi_period: int,
    stop_loss_percent: float,
    take_profit_percent: float,
    max_holding_bars: int,
    cooldown_bars: int,
    notional_amount: float,
    use_stop_loss: bool,
    use_take_profit: bool,
    use_max_holding: bool,
    allow_flip: bool,
    candle: Optional[Dict[str, float]] = None,
    action: str = None,
) -> SignalContext:
    """Build SignalContext for RSI Signal strategy."""
    return SignalContext(
        reason=reason,
        indicators={
            "rsi": rsi,
            "prev_rsi": prev_rsi,
            "rsi_upper": rsi_upper,
            "rsi_lower": rsi_lower,
            "rsi_mid": rsi_mid,
            "signal_mode": signal_mode,
            "exit_mode": exit_mode,
        },
        config={
            "rsi_period": rsi_period,
            "stop_loss_percent": stop_loss_percent,
            "take_profit_percent": take_profit_percent,
            "max_holding_bars": max_holding_bars,
            "cooldown_bars": cooldown_bars,
            "notional_amount": notional_amount,
            "use_stop_loss": use_stop_loss,
            "use_take_profit": use_take_profit,
            "use_max_holding": use_max_holding,
            "allow_flip": allow_flip,
        },
        candle=candle,
        action=action,
    )


def build_mom_signal_context(
    reason: str,
    mom: float,
    prev_mom: float,
    mom_upper: float,
    mom_lower: float,
    mom_mid: float,
    signal_mode: str,
    exit_mode: str,
    mom_period: int,
    stop_loss_percent: float,
    take_profit_percent: float,
    max_holding_bars: int,
    cooldown_bars: int,
    notional_amount: float,
    use_stop_loss: bool,
    use_take_profit: bool,
    use_max_holding: bool,
    allow_flip: bool,
    candle: Optional[Dict[str, float]] = None,
    action: str = None,
) -> SignalContext:
    """Build SignalContext for Momentum Signal strategy."""
    return SignalContext(
        reason=reason,
        indicators={
            "mom": mom,
            "prev_mom": prev_mom,
            "mom_upper": mom_upper,
            "mom_lower": mom_lower,
            "mom_mid": mom_mid,
            "signal_mode": signal_mode,
            "exit_mode": exit_mode,
        },
        config={
            "mom_period": mom_period,
            "stop_loss_percent": stop_loss_percent,
            "take_profit_percent": take_profit_percent,
            "max_holding_bars": max_holding_bars,
            "cooldown_bars": cooldown_bars,
            "notional_amount": notional_amount,
            "use_stop_loss": use_stop_loss,
            "use_take_profit": use_take_profit,
            "use_max_holding": use_max_holding,
            "allow_flip": allow_flip,
        },
        candle=candle,
        action=action,
    )


def build_tema_signal_context(
    reason: str,
    tema_short: float,
    tema_long: float,
    tema_diff: float,
    prev_tema_diff: float,
    short_window: int,
    long_window: int,
    stop_loss_percent: float,
    take_profit_percent: float,
    max_holding_bars: int,
    cooldown_bars: int,
    notional_amount: float,
    use_stop_loss: bool,
    use_take_profit: bool,
    use_max_holding: bool,
    allow_flip: bool,
    candle: Optional[Dict[str, float]] = None,
    action: str = None,
) -> SignalContext:
    """Build SignalContext for TEMA Crossover strategy."""
    return SignalContext(
        reason=reason,
        indicators={
            "tema_short": tema_short,
            "tema_long": tema_long,
            "tema_diff": tema_diff,
            "prev_tema_diff": prev_tema_diff,
        },
        config={
            "short_window": short_window,
            "long_window": long_window,
            "stop_loss_percent": stop_loss_percent,
            "take_profit_percent": take_profit_percent,
            "max_holding_bars": max_holding_bars,
            "cooldown_bars": cooldown_bars,
            "notional_amount": notional_amount,
            "use_stop_loss": use_stop_loss,
            "use_take_profit": use_take_profit,
            "use_max_holding": use_max_holding,
            "allow_flip": allow_flip,
        },
        candle=candle,
        action=action,
    )
