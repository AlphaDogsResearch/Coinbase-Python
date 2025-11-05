"""
Adapter classes to bridge Nautilus Trader components with your system.

These adapters allow Nautilus strategies to interact with your PositionManager,
reference data, and order submission system without modification.
"""

import logging
from typing import Optional, List, Dict
from decimal import Decimal

from nautilus_trader.model.identifiers import InstrumentId, Symbol
from nautilus_trader.model.instruments import CryptoPerpetual, Instrument
from nautilus_trader.model.objects import Money, Price, Quantity, Currency
from nautilus_trader.model.enums import OrderSide

from engine.position.position_manager import PositionManager
from engine.position.position import Position as YourPosition
from engine.strategies.nautilus_converters import extract_symbol_from_instrument_id


class NautilusInstrumentAdapter:
    """
    Adapts your instrument/symbol data to Nautilus Instrument objects.

    Creates Nautilus CryptoPerpetual instruments using real Binance reference data
    including precision, lot sizes, and notional limits.
    """

    def __init__(
        self,
        symbol: str,
        instrument_id_str: str,
        price_precision: int = 2,  # ETHUSDT actual: 2
        size_precision: int = 3,  # ETHUSDT actual: 3 (was 8, now corrected!)
        min_quantity: float = 0.001,  # ETHUSDT actual: 0.001
        min_notional: float = 20.0,  # ETHUSDT actual: 20.0 (was 10.0, now corrected!)
    ):
        """
        Initialize instrument adapter with real Binance reference data.

        Args:
            symbol: Your system's symbol (e.g., "ETHUSDT")
            instrument_id_str: Nautilus instrument ID (e.g., "ETHUSDT.BINANCE")
            price_precision: Decimal places for price (from Binance: 2 for ETHUSDT)
            size_precision: Decimal places for size/quantity (from Binance: 3 for ETHUSDT)
            min_quantity: Minimum order quantity (from Binance: 0.001 for ETHUSDT)
            min_notional: Minimum order notional value (from Binance: 20.0 for ETHUSDT)
        """
        self.symbol = symbol
        self.instrument_id_str = instrument_id_str
        self.instrument_id = InstrumentId.from_str(instrument_id_str)
        self.price_precision = price_precision
        self.size_precision = size_precision
        self.min_quantity = min_quantity
        self.min_notional = min_notional

        # Create Nautilus instrument from real Binance reference data
        self._instrument = self._create_nautilus_instrument()

    def _create_nautilus_instrument(self) -> Instrument:
        """Create a Nautilus Instrument with real Binance reference data."""
        try:
            # Parse base and quote currencies from symbol (e.g., ETHUSDT -> ETH, USDT)
            # Handle common patterns: ETHUSDT, BTCUSDT, etc.
            symbol_clean = self.symbol.replace("USDT", "").replace("USDC", "").replace("USD", "")
            base_currency_str = symbol_clean if symbol_clean else "ETH"

            # Determine quote currency from symbol
            if "USDT" in self.symbol:
                quote_currency_str = "USDT"
            elif "USDC" in self.symbol:
                quote_currency_str = "USDC"
            else:
                quote_currency_str = "USD"

            logging.info(
                f"Creating instrument for {self.symbol}: base={base_currency_str}, quote={quote_currency_str}"
            )

            base_currency = Currency.from_str(base_currency_str)
            quote_currency = Currency.from_str(quote_currency_str)

            # Create CryptoPerpetual with real Binance reference data values
            instrument = CryptoPerpetual(
                instrument_id=self.instrument_id,
                raw_symbol=Symbol(self.symbol),  # Must be Symbol object, not string
                base_currency=base_currency,
                quote_currency=quote_currency,
                settlement_currency=quote_currency,
                is_inverse=False,
                price_precision=self.price_precision,
                size_precision=self.size_precision,
                price_increment=Price(10**-self.price_precision, self.price_precision),
                size_increment=Quantity(10**-self.size_precision, self.size_precision),
                max_quantity=Quantity(1000000, self.size_precision),
                min_quantity=Quantity(self.min_quantity, self.size_precision),
                max_notional=None,
                min_notional=Money(self.min_notional, quote_currency),
                max_price=None,
                min_price=None,
                margin_init=Decimal("0.05"),
                margin_maint=Decimal("0.025"),
                maker_fee=Decimal("0.0002"),
                taker_fee=Decimal("0.0004"),
                ts_event=0,
                ts_init=0,
            )
            logging.info(f"✅ Successfully created Nautilus instrument for {self.symbol}")
            return instrument
        except Exception as e:  # noqa: broad-except
            logging.error(
                "❌ Could not create instrument for %s: %s", self.symbol, e, exc_info=True
            )
            # Return None and handle gracefully
            return None

    def get_instrument(self) -> Optional[Instrument]:
        """Get the Nautilus Instrument object."""
        return self._instrument


class NautilusPositionAdapter:
    """
    Adapter that wraps your Position to look like a Nautilus Position.

    Nautilus strategies query position objects for quantity, side, etc.
    """

    def __init__(self, your_position: YourPosition, instrument_id: InstrumentId):
        self._position = your_position
        self._instrument_id = instrument_id

    @property
    def instrument_id(self) -> InstrumentId:
        return self._instrument_id

    @property
    def quantity(self) -> Quantity:
        """Return position quantity as Nautilus Quantity."""
        return Quantity(abs(self._position.position_amount), precision=8)

    @property
    def side(self):
        """Return position side (LONG/SHORT)."""
        from nautilus_trader.model.enums import PositionSide

        if self._position.position_amount > 0:
            return PositionSide.LONG
        elif self._position.position_amount < 0:
            return PositionSide.SHORT
        else:
            return PositionSide.FLAT

    @property
    def is_long(self) -> bool:
        return self._position.position_amount > 0

    @property
    def is_short(self) -> bool:
        return self._position.position_amount < 0


class NautilusPortfolioAdapter:
    """
    Adapts your PositionManager to the Nautilus Portfolio API.

    Nautilus strategies call methods like:
    - portfolio.is_flat(instrument_id)
    - portfolio.is_net_long(instrument_id)
    - portfolio.positions(instrument_id)
    """

    def __init__(self, position_manager: PositionManager, strategy_id: Optional[str] = None):
        """
        Initialize portfolio adapter.

        Args:
            position_manager: Your system's PositionManager
        """
        self.position_manager = position_manager
        # If provided, restrict portfolio view to this strategy_id
        self.strategy_id = strategy_id

    def is_flat(self, instrument_id: InstrumentId) -> bool:
        """
        Check if position is flat (no position) for the given instrument.

        Args:
            instrument_id: Nautilus InstrumentId

        Returns:
            True if position amount is 0
        """
        symbol = extract_symbol_from_instrument_id(str(instrument_id))
        position = (
            self.position_manager.get_position(symbol, self.strategy_id)
            if self.strategy_id is not None
            else self.position_manager.positions.get(symbol)
        )

        if position is None:
            return True

        return abs(position.position_amount) < 1e-8  # Near zero

    def is_net_long(self, instrument_id: InstrumentId) -> bool:
        """
        Check if net position is long.

        Args:
            instrument_id: Nautilus InstrumentId

        Returns:
            True if position amount > 0
        """
        symbol = extract_symbol_from_instrument_id(str(instrument_id))
        position = (
            self.position_manager.get_position(symbol, self.strategy_id)
            if self.strategy_id is not None
            else self.position_manager.positions.get(symbol)
        )

        if position is None:
            return False

        return position.position_amount > 0

    def is_net_short(self, instrument_id: InstrumentId) -> bool:
        """
        Check if net position is short.

        Args:
            instrument_id: Nautilus InstrumentId

        Returns:
            True if position amount < 0
        """
        symbol = extract_symbol_from_instrument_id(str(instrument_id))
        position = (
            self.position_manager.get_position(symbol, self.strategy_id)
            if self.strategy_id is not None
            else self.position_manager.positions.get(symbol)
        )

        if position is None:
            return False

        return position.position_amount < 0

    def positions(
        self, instrument_id: Optional[InstrumentId] = None
    ) -> List[NautilusPositionAdapter]:
        """
        Get positions for the given instrument.

        Args:
            instrument_id: Nautilus InstrumentId (optional)

        Returns:
            List of adapted position objects
        """
        if instrument_id is None:
            # Return all positions for this strategy (or aggregate if strategy_id is None)
            if self.strategy_id is None:
                return [
                    NautilusPositionAdapter(pos, InstrumentId.from_str(f"{symbol}.BINANCE"))
                    for symbol, pos in self.position_manager.positions.items()
                    if abs(pos.position_amount) > 1e-8
                ]
            else:
                results: List[NautilusPositionAdapter] = []
                for (sid, sym), pos in self.position_manager.positions_by_key.items():
                    if sid == self.strategy_id and abs(pos.position_amount) > 1e-8:
                        results.append(
                            NautilusPositionAdapter(pos, InstrumentId.from_str(f"{sym}.BINANCE"))
                        )
                return results

        symbol = extract_symbol_from_instrument_id(str(instrument_id))
        position = (
            self.position_manager.get_position(symbol, self.strategy_id)
            if self.strategy_id is not None
            else self.position_manager.positions.get(symbol)
        )

        if position is None or abs(position.position_amount) < 1e-8:
            return []

        return [NautilusPositionAdapter(position, instrument_id)]

    def position(self, instrument_id: InstrumentId) -> Optional[NautilusPositionAdapter]:
        """
        Get a single position for the given instrument.

        This is a convenience method that returns the first position from positions().
        Nautilus strategies often call portfolio.position() instead of portfolio.positions().

        Args:
            instrument_id: Nautilus InstrumentId

        Returns:
            Single position adapter or None if no position
        """
        positions = self.positions(instrument_id)
        return positions[0] if positions else None


class NautilusCacheAdapter:
    """
    Adapts to the Nautilus Cache API.

    Nautilus strategies call:
    - cache.instrument(instrument_id)
    - cache.positions(instrument_id)
    """

    def __init__(self, instruments: Dict[str, NautilusInstrumentAdapter]):
        """
        Initialize cache adapter.

        Args:
            instruments: Map of instrument_id_str -> NautilusInstrumentAdapter
        """
        self.instruments = instruments

    def instrument(self, instrument_id: InstrumentId) -> Optional[Instrument]:
        """
        Get instrument from cache.

        Args:
            instrument_id: Nautilus InstrumentId

        Returns:
            Nautilus Instrument or None
        """
        instrument_id_str = str(instrument_id)
        adapter = self.instruments.get(instrument_id_str)

        if adapter:
            return adapter.get_instrument()

        logging.warning("Instrument %s not found in cache", instrument_id_str)
        return None

    def positions(
        self, instrument_id: Optional[InstrumentId] = None
    ) -> List:  # noqa: unused-argument
        """
        Get positions from cache.

        Note: This is typically handled by the portfolio adapter.

        Args:
            instrument_id: Optional instrument ID (unused)
        """
        return []


class NautilusOrderFactoryAdapter:
    """
    Adapts to Nautilus OrderFactory API.

    Creates order objects that work directly with OrderManager.submit_order.
    """

    def __init__(self, strategy_id: str, symbol: str, quantity: str):
        """
        Initialize order factory adapter.

        Args:
            strategy_id: Strategy identifier
            symbol: Trading symbol
            quantity: Position size as string (e.g., "500.000")
        """
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.quantity = quantity
        self._order_id_counter = 0

    def _generate_order_id(self) -> str:
        """Generate a unique order ID."""
        self._order_id_counter += 1
        return f"{self.strategy_id}-{self._order_id_counter}"

    def market(
        self,
        instrument_id: InstrumentId,
        order_side: OrderSide,
        quantity: Quantity,
        time_in_force=None,  # noqa: unused-argument
        reduce_only: bool = False,
        quote_quantity: bool = False,  # noqa: unused-argument
        tags: Optional[str] = None,  # noqa: unused-argument
    ):
        """
        Create a market order object.

        Args:
            instrument_id: Instrument to trade
            order_side: BUY or SELL
            quantity: Order quantity
            time_in_force: Time in force (ignored for market orders)
            reduce_only: Reduce only flag
            quote_quantity: Quote quantity flag
            tags: Order tags

        Returns:
            Order object (will be submitted via intercepted_submit_order)
        """
        # Calculate price from quantity and notional (approximate for market orders)

        # Return order object - submission handled by intercepted_submit_order
        return {
            "type": "MARKET",
            "order_id": self._generate_order_id(),
            "instrument_id": instrument_id,
            "side": order_side,
            "quantity": quantity,
            "reduce_only": reduce_only,
            "tags": tags,
        }

    def stop_market(
        self,
        instrument_id: InstrumentId,
        order_side: OrderSide,
        quantity: Quantity,
        trigger_price: Price,
        time_in_force=None,  # noqa: unused-argument
        reduce_only: bool = False,
        quote_quantity: bool = False,  # noqa: unused-argument
        tags: Optional[str] = None,  # noqa: unused-argument
    ):
        """
        Create a stop market order object.

        Args:
            instrument_id: Instrument to trade
            order_side: BUY or SELL
            quantity: Order quantity
            trigger_price: Stop trigger price
            time_in_force: Time in force
            reduce_only: Reduce only flag
            quote_quantity: Quote quantity flag
            tags: Order tags

        Returns:
            Order object (will be submitted via intercepted_submit_order)
        """
        # Return order object - submission handled by intercepted_submit_order
        return {
            "type": "STOP_MARKET",
            "order_id": self._generate_order_id(),
            "instrument_id": instrument_id,
            "side": order_side,
            "quantity": quantity,
            "trigger_price": trigger_price,
            "reduce_only": reduce_only,
            "tags": tags,
        }

    def limit(
        self,
        instrument_id: InstrumentId,
        order_side: OrderSide,
        quantity: Quantity,
        price: Price,
        time_in_force=None,  # noqa: unused-argument
        post_only: bool = False,
        reduce_only: bool = False,
        quote_quantity: bool = False,  # noqa: unused-argument
        tags: Optional[str] = None,  # noqa: unused-argument
    ):
        """
        Create a limit order object.

        Args:
            instrument_id: Instrument to trade
            order_side: BUY or SELL
            quantity: Order quantity
            price: Limit price
            time_in_force: Time in force
            post_only: Post only flag
            reduce_only: Reduce only flag
            quote_quantity: Quote quantity flag
            tags: Order tags

        Returns:
            Order object (will be submitted via intercepted_submit_order)
        """
        # Return order object - submission handled by intercepted_submit_order
        return {
            "type": "LIMIT",
            "order_id": self._generate_order_id(),
            "instrument_id": instrument_id,
            "side": order_side,
            "quantity": quantity,
            "price": price,
            "post_only": post_only,
            "reduce_only": reduce_only,
            "tags": tags,
        }
