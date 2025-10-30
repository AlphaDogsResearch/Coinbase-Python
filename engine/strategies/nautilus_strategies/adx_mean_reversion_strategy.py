from decimal import Decimal
import uuid

from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.enums import OrderSide, PositionSide, TimeInForce
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.core.datetime import dt_to_unix_nanos
from nautilus_trader.core.uuid import UUID4

from .indicators import ADX


class ADXMeanReversionStrategyConfig(StrategyConfig, frozen=True):
    """ADX Mean Reversion Strategy configuration."""

    instrument_id: str
    bar_type: str

    # ADX Parameters
    adx_period: int = 22
    adx_smoothing: int = 22

    # Position Management
    quantity: str = "1.000"  # Position size (100%)
    stop_loss_percent: float = 3.0  # Stop loss distance (3% as per provided values)

    # ADX Thresholds
    adx_low: float = 23.0  # Range-bound threshold
    adx_mid: float = 38.0  # Weak trend threshold
    adx_high: float = 65.0  # Strong trend threshold

    # DI Spread parameters
    di_spread_extreme: float = 8.625853  # +DI/-DI difference for extremes
    di_spread_midline: float = 5.0  # +DI/-DI midline for reversion exits

    # Risk Management
    max_holding_bars: int = 125  # Max holding period in bars


# Strategy definition
class ADXMeanReversionStrategy(Strategy):
    """
    ADX Mean Reversion Strategy Implementation

    Momentum Mode:
    - Enter long when +DI crosses above -DI, ADX > high threshold, ADX slope > 0
    - Enter short when -DI crosses above +DI, ADX > high threshold, ADX slope > 0
    - Exit when opposite cross occurs or ADX weakens

    Mean Reversion Mode:
    - Enter when DI spread is extreme and ADX shows range conditions
    - Exit when price returns to midline or DI normalizes
    """

    def __init__(self, config: ADXMeanReversionStrategyConfig) -> None:
        # Always initialize the parent Strategy class
        super().__init__(config)

        # ADX strategy is always mean reversion mode
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
        self.quantity = Quantity.from_str(config.quantity)
        self.stop_loss_percent = config.stop_loss_percent

        # Risk Management
        self.max_holding_bars = config.max_holding_bars

        # Initialize audit logger
        self.audit_logger = StrategyAuditLogger(
            strategy_name=self.__class__.__name__, symbol=config.instrument_id.split(".")[0]
        )
        # Initialize custom ADX indicator (with proper ADX calculation)
        self.adx = ADX(period=self.adx_period)

        # State tracking
        self._previous_plus_di = 0.0
        self._previous_minus_di = 0.0
        self._previous_adx = 0.0  # Track previous ADX for slope calculation
        self._bars_processed = 0
        self._crossover_signal = None  # "long", "short", or None
        self._position_side = None  # Track current position
        self._long_entry_bar = None
        self._short_entry_bar = None

    @property
    def adx_slope(self) -> float:
        """Calculate ADX slope as current - previous."""
        return self.adx.value - self._previous_adx

    def on_start(self) -> None:
        """Initialize strategy on start - fetch instruments and subscribe to data."""
        # Parse instrument and bar type from config strings
        self.instrument_id = InstrumentId.from_str(self.config.instrument_id)
        self.bar_type = BarType.from_str(self.config.bar_type)

        # Fetch the instrument
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument {self.instrument_id} not found in cache")
            return

        # Register the indicators for updating
        self.register_indicator_for_bars(self.bar_type, self.adx)

        # Subscribe to bars for the configured bar type
        self.subscribe_bars(self.bar_type)

        # Log strategy initialization
        self.log.info(
            f"ADXMeanReversionStrategy started for {self.instrument.id} with mode: {self.mode}"
        )
        self.log.info(f"Subscribed to {self.bar_type}")

    def on_bars_loaded(self, request_id: UUID4):
        """Called when the bars request completes"""
        self.log.info(f"Bars loaded successfully for request {request_id}")

    def on_bar(self, bar: Bar):
        """Handle incoming bar data."""
        # Check readiness states
        if not self.adx.initialized:
            return

        # Detect DI crossovers
        self._detect_crossovers()

        # Execute strategy based on mode
        # Execute momentum mode (ADX strategy is momentum-based)
        self._execute_momentum_mode(bar)

        # Log audit information
        self._log_audit(bar)

        # Update state for next bar
        self._previous_plus_di = self.adx.pos
        self._previous_minus_di = self.adx.neg
        self._previous_adx = self.adx.value

    def _detect_crossovers(self) -> None:
        """Detect +DI and -DI crossovers."""
        # Check for +DI > -DI crossover (bullish)
        if self._previous_plus_di <= self._previous_minus_di and self.adx.pos > self.adx.neg:
            self._crossover_signal = "long"
            self.log.info("📈 +DI crossed above -DI (BULLISH)")

        # Check for -DI > +DI crossover (bearish)
        elif self._previous_minus_di <= self._previous_plus_di and self.adx.neg > self.adx.pos:
            self._crossover_signal = "short"
            self.log.info("📉 -DI crossed above +DI (BEARISH)")

        else:
            self._crossover_signal = None

    def _execute_momentum_mode(self, bar: Bar) -> None:
        """
        Momentum Mode Logic:
        - Enter when crossover occurs + ADX > high threshold + ADX slope > 0
        - Exit when opposite crossover or ADX weakens
        """
        # Entry conditions
        if self._crossover_signal == "long":
            self.log.info(
                f"Long signal: ADX={self.adx.value:.2f} (need >{self.adx_high}), slope={self.adx_slope:.2f}"
            )
            if (
                self.adx.value > self.adx_high
                and self.adx_slope > 0
                and self.portfolio.is_flat(self.instrument.id)
            ):
                self._enter_long(bar)

        elif self._crossover_signal == "short":
            self.log.info(
                f"Short signal: ADX={self.adx.value:.2f} (need >{self.adx_high}), slope={self.adx_slope:.2f}"
            )
            if (
                self.adx.value > self.adx_high
                and self.adx_slope > 0
                and self.portfolio.is_flat(self.instrument.id)
            ):
                self._enter_short(bar)

        # Exit conditions
        else:
            # Exit long on bearish cross
            if self._crossover_signal == "short" and not self.portfolio.is_flat(self.instrument.id):
                self._close_position(bar, "Bearish cross detected")

            # Exit short on bullish cross
            elif self._crossover_signal == "long" and not self.portfolio.is_flat(
                self.instrument.id
            ):
                self._close_position(bar, "Bullish cross detected")

            # Exit on ADX weakening
            elif self.adx.value < self.adx_mid and not self.portfolio.is_flat(self.instrument.id):
                self._close_position(bar, "ADX weakness detected")

        # Max holding period exits
        if self._position_side == PositionSide.LONG and self._long_entry_bar is not None:
            if (self._bars_processed - self._long_entry_bar) >= self.max_holding_bars:
                self._close_position(bar, "Max holding period reached")

        if self._position_side == PositionSide.SHORT and self._short_entry_bar is not None:
            if (self._bars_processed - self._short_entry_bar) >= self.max_holding_bars:
                self._close_position(bar, "Max holding period reached")

    def _execute_mean_reversion_mode(self, bar: Bar) -> None:
        """
        Mean Reversion Mode Logic:
        - Enter when DI spread is extreme and ADX < low threshold (range-bound)
        - Exit when price returns toward midline or DI normalizes
        """
        di_spread = abs(self.adx.pos - self.adx.neg)

        # Entry conditions (extreme DI spread + low ADX)
        if self.adx.value < self.adx_low and di_spread > self.di_spread_extreme:
            # +DI much higher than -DI → mean reversion to short
            if self.adx.pos > self.adx.neg + self.di_spread_extreme and self.portfolio.is_flat(
                self.instrument.id
            ):
                self._enter_short(bar, reason="Mean reversion: +DI extreme")

            # -DI much higher than +DI → mean reversion to long
            elif self.adx.neg > self.adx.pos + self.di_spread_extreme and self.portfolio.is_flat(
                self.instrument.id
            ):
                self._enter_long(bar, reason="Mean reversion: -DI extreme")

        # Exit conditions
        else:
            # Close positions when spread normalizes
            if di_spread < self.di_spread_midline:
                if not self.portfolio.is_flat(self.instrument.id):
                    self._close_position(bar, "DI spread normalized")

            # Close positions when ADX trends up (market no longer range-bound)
            if self.adx.value > self.adx_mid and self.adx_slope > 0:
                if not self.portfolio.is_flat(self.instrument.id):
                    self._close_position(bar, "ADX trend detected, exiting reversion trade")

        # Max holding period exits
        if self._position_side == PositionSide.LONG and self._long_entry_bar is not None:
            if (self._bars_processed - self._long_entry_bar) >= self.max_holding_bars:
                self._close_position(bar, "Max holding period reached")

        if self._position_side == PositionSide.SHORT and self._short_entry_bar is not None:
            if (self._bars_processed - self._short_entry_bar) >= self.max_holding_bars:
                self._close_position(bar, "Max holding period reached")

    def _enter_long(self, bar: Bar, reason: str = "Momentum signal") -> None:
        """Enter long position with stop loss."""
        if self.portfolio.is_net_long(self.instrument.id):
            self.log.warning("Already in long position")
            return

        # Calculate stop loss
        stop_price = float(bar.close) * (1 - self.stop_loss_percent / 100)

        # Generate signal_id for this trade
        signal_id = str(uuid.uuid4())

        # Prepare indicator values for tags
        bars_held = self._bars_processed - self._long_entry_bar if self._long_entry_bar else 0
        tags = [
            f"signal_id={signal_id}",
            f"reason={reason}",
            f"adx={self.adx.value:.2f}",
            f"dmi_pos={self.adx.pos:.2f}",
            f"dmi_neg={self.adx.neg:.2f}",
            f"adx_threshold={self.adx_high:.2f}",
            f"bars_held={bars_held}",
            "action=ENTRY",
        ]

        order = self.order_factory.market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.BUY,
            quantity=self.quantity,
            time_in_force=TimeInForce.GTC,
            tags=tags,
        )
        self.submit_order(order)

        # Submit stop loss order
        stop_order = self.order_factory.stop_market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.SELL,
            quantity=self.quantity,
            trigger_price=Price.from_str(f"{stop_price:.2f}"),
            time_in_force=TimeInForce.GTC,
            tags=[f"signal_id={signal_id}", "action=STOP_LOSS"],
        )
        self.submit_order(stop_order)

        self.log.info(
            f"🟢 LONG ENTRY | {reason}\n"
            f"   Price: {float(bar.close):.4f} | Qty: {self.quantity.as_double():.4f} | "
            f"SL: {stop_price:.4f}\n"
            f"   +DI: {self.adx.pos:.2f} | -DI: {self.adx.neg:.2f} | "
            f"ADX: {self.adx.value:.2f}"
        )

        self._position_side = PositionSide.LONG
        self._long_entry_bar = self._bars_processed

    def _enter_short(self, bar: Bar, reason: str = "Momentum signal") -> None:
        """Enter short position with stop loss."""
        if self.portfolio.is_net_short(self.instrument.id):
            self.log.warning("Already in short position")
            return

        # Calculate stop loss
        stop_price = float(bar.close) * (1 + self.stop_loss_percent / 100)

        # Generate signal_id for this trade
        signal_id = str(uuid.uuid4())

        # Prepare indicator values for tags
        bars_held = self._bars_processed - self._short_entry_bar if self._short_entry_bar else 0
        tags = [
            f"signal_id={signal_id}",
            f"reason={reason}",
            f"adx={self.adx.value:.2f}",
            f"dmi_pos={self.adx.pos:.2f}",
            f"dmi_neg={self.adx.neg:.2f}",
            f"adx_threshold={self.adx_high:.2f}",
            f"bars_held={bars_held}",
            "action=ENTRY",
        ]

        order = self.order_factory.market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.SELL,
            quantity=self.quantity,
            time_in_force=TimeInForce.GTC,
            tags=tags,
        )
        self.submit_order(order)

        # Submit stop loss order
        stop_order = self.order_factory.stop_market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.BUY,
            quantity=self.quantity,
            trigger_price=Price.from_str(f"{stop_price:.2f}"),
            time_in_force=TimeInForce.GTC,
            tags=[f"signal_id={signal_id}", "action=STOP_LOSS"],
        )
        self.submit_order(stop_order)

        self.log.info(
            f"🔴 SHORT ENTRY | {reason}\n"
            f"   Price: {float(bar.close):.4f} | Qty: {self.quantity.as_double():.4f} | "
            f"SL: {stop_price:.4f}\n"
            f"   +DI: {self.adx.pos:.2f} | -DI: {self.adx.neg:.2f} | "
            f"ADX: {self.adx.value:.2f}"
        )

        self._position_side = PositionSide.SHORT
        self._short_entry_bar = self._bars_processed

    def _close_position(self, bar: Bar, reason: str) -> None:
        """Close current position and cancel any pending orders."""
        if self.portfolio.is_flat(self.instrument.id):
            return

        # Cancel any pending orders
        self.cancel_all_orders(self.instrument.id)

        # Get the actual position to determine side
        positions = self.cache.positions(instrument_id=self.instrument.id)
        if not positions:
            return

        position = positions[0]  # Get first (should be only one per instrument)

        # Prepare indicator values for tags
        bars_held = (
            self._bars_processed - self._long_entry_bar
            if position.is_long and self._long_entry_bar
            else self._bars_processed - self._short_entry_bar if self._short_entry_bar else 0
        )
        tags = [
            f"reason={reason}",
            f"adx={self.adx.value:.2f}",
            f"dmi_pos={self.adx.pos:.2f}",
            f"dmi_neg={self.adx.neg:.2f}",
            f"adx_threshold={self.adx_high:.2f}",
            f"bars_held={bars_held}",
            "action=CLOSE",
        ]

        order = self.order_factory.market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.SELL if position.is_long else OrderSide.BUY,
            quantity=position.quantity,
            time_in_force=TimeInForce.GTC,
            tags=tags,
        )

        self.submit_order(order)

        if position.is_long:
            self.log.info(f"🟡 LONG EXIT: {reason} | Price: {float(bar.close):.4f}")
        else:
            self.log.info(f"🟡 SHORT EXIT: {reason} | Price: {float(bar.close):.4f}")

        self._position_side = None
        self._long_entry_bar = None
        self._short_entry_bar = None

    def _log_indicator_state(self, bar: Bar) -> None:
        """Log current indicator values."""
        self.log.debug(
            f"Bar #{self._bars_processed} | Close: {bar.close:.4f} | "
            f"+DI: {self.adx.pos:.2f} | -DI: {self.adx.neg:.2f} | "
            f"ADX: {self.adx.value:.2f} (slope: {self.adx_slope:.2f})"
        )

    def _log_audit(self, bar: Bar) -> None:
        """Log audit information for this bar."""
        try:
            # Calculate current position state
            position_state = "flat"
            bars_held = 0
            entry_price = 0.0
            stop_loss_price = 0.0

            if not self.portfolio.is_flat(self.instrument.id):
                if self.portfolio.is_net_long(self.instrument.id):
                    position_state = "long"
                else:
                    position_state = "short"
                bars_held = getattr(self, "_bars_processed", 0) - getattr(
                    self, "_position_entry_bar", 0
                )
                entry_price = getattr(self, "_entry_price", 0.0)
                stop_loss_price = getattr(self, "_stop_loss_price", 0.0)

            # Basic indicators (strategy-specific indicators will be added per strategy)
            indicators = {}

            # Basic conditions
            conditions = {
                "max_bars_triggered": bars_held >= getattr(self, "max_holding_bars", 1000)
            }

            # Log to audit logger
            self.audit_logger.log(
                bar=bar,
                action="",  # Will be determined by strategy logic
                indicators=indicators,
                position_state={
                    "state": position_state,
                    "bars_held": bars_held,
                    "entry_price": entry_price,
                    "stop_loss_price": stop_loss_price,
                },
                conditions=conditions,
            )
        except Exception as e:
            self.log.error(f"Error in audit logging: {e}")

    def on_stop(self) -> None:
        """Called when strategy is stopped."""
        # Unsubscribe from bars
        self.unsubscribe_bars(self.bar_type)

        # Cancel all orders
        self.cancel_all_orders(self.instrument.id)

        # Close all positions
        self.close_all_positions(self.instrument.id)

        # Close audit logger
        if self.audit_logger:
            self.audit_logger.close()

        self.log.info(f"Strategy stopped | Bars processed: {self._bars_processed}")


from datetime import datetime
from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue, Symbol, InstrumentId
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USDT, ETH
from engine.strategies.audit_logger import StrategyAuditLogger


def run_backtest():
    """Run backtest using research-aligned methodology"""

    print("\n" + "=" * 80)
    print("🔬 RESEARCH-ALIGNED NAUTILUS BACKTEST")
    print("Matching research notebook methodology:")
    print("- 1-hour aggregated bars")
    print("- Full position allocations")
    print("- 0.05% trading costs")
    print("- Log return calculations")
    print("=" * 80)

    # Load and aggregate data to 1-hour bars
    bars = load_and_aggregate_to_hourly(
        csv_path="data/ETHUSD_1m_Combined_Index.csv",
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2025, 7, 7),
    )

    # Create backtest engine
    config = BacktestEngineConfig(logging=LoggingConfig(log_level="INFO"))
    engine = BacktestEngine(config=config)

    # Add venue with research-aligned settings
    venue = Venue("BINANCE")
    engine.add_venue(
        venue=venue,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USDT,
        starting_balances=[Money(10000, USDT)],
    )

    # Create instrument with research-aligned fees (0.05% total)
    instrument = CryptoPerpetual(
        instrument_id=InstrumentId(Symbol("ETHUSDT"), venue),
        raw_symbol=Symbol("ETHUSDT"),
        base_currency=ETH,
        quote_currency=USDT,
        settlement_currency=USDT,
        is_inverse=False,
        price_precision=2,
        size_precision=8,
        price_increment=Price.from_str("0.01"),
        size_increment=Quantity.from_str("0.00000001"),
        max_quantity=Quantity.from_str("10000"),
        min_quantity=Quantity.from_str("0.001"),
        max_price=Price.from_str("1000000"),
        min_price=Price.from_str("0.01"),
        margin_init=Decimal("0.1"),
        margin_maint=Decimal("0.05"),
        maker_fee=Decimal("0.00025"),  # 0.025% (half of 0.05%)
        taker_fee=Decimal("0.00025"),  # 0.025% (half of 0.05%)
        ts_event=0,
        ts_init=0,
    )
    engine.add_instrument(instrument)

    # Add hourly bar data
    engine.add_data(bars)

    # Create and add research-aligned ADX strategy
    strategy_config = ADXStrategyConfig(
        instrument_id=str(instrument.id), bar_type=f"{instrument.id}-1-HOUR-LAST-EXTERNAL"
    )
    strategy = ADXStrategy(config=strategy_config)
    engine.add_strategy(strategy)

    # Run backtest
    print("\n🚀 Running research-aligned backtest...")
    engine.run()

    # Generate reports
    print("\n📊 Generating backtest reports...")

    # Create job ID based on strategy name and timestamp
    strategy_name = strategy_config.strategy_id
    job_id = f"{strategy_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Initialize local saver
    saver = LocalBacktestSaver(base_dir="reports")

    # Save all reports as CSV
    print(f"\n💾 Saving reports to: {saver.get_job_directory_path(job_id)}")

    # Orders report
    orders_report = engine.trader.generate_orders_report()
    if orders_report is not None and not orders_report.empty:
        saver.save_csv_content(job_id, "orders", orders_report.to_csv())

    # Fills report
    fills_report = engine.trader.generate_order_fills_report()
    if fills_report is not None and not fills_report.empty:
        saver.save_csv_content(job_id, "fills", fills_report.to_csv())

    # Positions report
    positions_report = engine.trader.generate_positions_report()
    if positions_report is not None and not positions_report.empty:
        saver.save_csv_content(job_id, "positions", positions_report.to_csv())

    # Account report
    account_report = engine.trader.generate_account_report(venue)
    if account_report is not None and not account_report.empty:
        saver.save_csv_content(job_id, "account", account_report.to_csv())

    # Collect performance stats
    stats_pnls = engine.portfolio.analyzer.get_performance_stats_pnls()
    stats_returns = engine.portfolio.analyzer.get_performance_stats_returns()
    stats_general = engine.portfolio.analyzer.get_performance_stats_general()

    # Create comprehensive summary
    summary = {
        "job_id": job_id,
        "timestamp": datetime.now().isoformat(),
        "strategy": {
            "name": "ResearchAlignedADXStrategy",
            "mode": strategy_config.mode,
            "instrument_id": strategy_config.instrument_id,
            "bar_type": strategy_config.bar_type,
        },
        "performance": {
            "pnls": stats_pnls,
            "returns": stats_returns,
            "general": stats_general,
        },
    }

    # Save summary
    saver.save_summary(job_id, summary)

    print(f"\n✅ All reports saved to: {saver.get_job_directory_path(job_id)}")
    print("=" * 80)

    return strategy, summary


import pandas as pd
from typing import List


def load_and_aggregate_to_hourly(
    csv_path: str, start_date: datetime, end_date: datetime
) -> List[Bar]:
    """Load 1-minute data and aggregate to 1-hour bars like research notebooks"""

    print(f"Loading 1-minute data from {csv_path}...")
    df = pd.read_csv(csv_path)
    df["Open time"] = pd.to_datetime(df["Open time"])

    # Filter date range
    if start_date:
        df = df[df["Open time"] >= start_date]
    if end_date:
        df = df[df["Open time"] <= end_date]

    print(f"Loaded {len(df)} 1-minute bars")

    # Aggregate to hourly (like research notebooks)
    df.set_index("Open time", inplace=True)
    df_1h = (
        df.resample("1H")
        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
        .dropna()
    )

    print(f"Aggregated to {len(df_1h)} 1-hour bars")

    # Create venue and instrument for bar creation
    venue = Venue("BINANCE")
    instrument_id = InstrumentId(Symbol("ETHUSDT"), venue)
    bar_type = BarType.from_str(f"{instrument_id}-1-HOUR-LAST-EXTERNAL")

    # Convert to Nautilus Bar objects
    bars = []
    for timestamp, row in df_1h.iterrows():
        bar = Bar(
            bar_type=bar_type,
            open=Price(row["Open"], precision=2),
            high=Price(row["High"], precision=2),
            low=Price(row["Low"], precision=2),
            close=Price(row["Close"], precision=2),
            volume=Quantity(row["Volume"], precision=8),
            ts_event=dt_to_unix_nanos(timestamp),
            ts_init=dt_to_unix_nanos(timestamp),
        )
        bars.append(bar)

    return bars


import os
import json


class LocalBacktestSaver:
    """Local file system service for saving backtest reports and summaries"""

    def __init__(self, base_dir: str = "reports"):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def create_job_directory(self, job_id: str) -> str:
        """Create job-specific directory"""
        job_dir = os.path.join(self.base_dir, job_id)
        os.makedirs(job_dir, exist_ok=True)
        return job_dir

    def save_csv_report(self, job_id: str, report_name: str, df: pd.DataFrame) -> str:
        """Save DataFrame as CSV to local file system"""
        try:
            job_dir = self.create_job_directory(job_id)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_path = os.path.join(job_dir, f"{report_name}_{timestamp}.csv")

            df.to_csv(file_path, index=True)
            print(f"✅ Saved {report_name} to: {file_path} ({len(df)} rows)")
            return file_path

        except Exception as e:
            print(f"❌ Error saving {report_name}: {e}")
            return None

    def save_csv_content(self, job_id: str, report_name: str, csv_content: str) -> str:
        """Save raw CSV content to local file system"""
        try:
            job_dir = self.create_job_directory(job_id)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_path = os.path.join(job_dir, f"{report_name}_{timestamp}.csv")

            with open(file_path, "w") as f:
                f.write(csv_content)

            line_count = len(csv_content.splitlines())
            print(f"✅ Saved {report_name} CSV to: {file_path} ({line_count} lines)")
            return file_path

        except Exception as e:
            print(f"❌ Error saving {report_name} CSV: {e}")
            return None

    def save_summary(self, job_id: str, summary: dict) -> str:
        """Save job summary as JSON to local file system"""
        try:
            job_dir = self.create_job_directory(job_id)
            file_path = os.path.join(job_dir, "summary.json")

            with open(file_path, "w") as f:
                json.dump(summary, f, indent=2, default=str)

            print(f"✅ Saved summary to: {file_path}")
            return file_path

        except Exception as e:
            print(f"❌ Error saving summary: {e}")
            return None

    def get_job_directory_path(self, job_id: str) -> str:
        """Get the full path to job directory"""
        return os.path.join(self.base_dir, job_id)


if __name__ == "__main__":
    strategy, summary = run_backtest()
