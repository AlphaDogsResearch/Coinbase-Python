class ReferenceData(object):
    def __init__(self,
                 symbol: str,
                 status: str,
                 base_asset: str,
                 quote_asset: str,
                 price_precision: int,
                 quantity_precision: int,
                 min_price: float,
                 max_price: float,
                 price_tick_size: float,
                 min_lot_size: float,
                 max_lot_size: float,
                 lot_step_size: float,
                 min_market_lot_size: float,
                 max_market_lot_size: float,
                 market_lot_step_size: float,
                 min_notional: float,
                 ):
        self.symbol = symbol
        self.status = status
        self.base_asset = base_asset
        self.quote_asset = quote_asset
        self.price_precision = int(price_precision)
        self.quantity_precision = int(quantity_precision)
        self.min_price = float(min_price)
        self.max_price = float(max_price)
        self.price_tick_size = float(price_tick_size) # price step size
        self.min_lot_size = float(min_lot_size) # min lot size for RESTING order
        self.max_lot_size = float(max_lot_size) # max lot size for RESTING order
        self.lot_step_size = float(lot_step_size) # lot step size for RESTING order
        self.min_market_lot_size = float(min_market_lot_size) # min lot size for MARKET order
        self.max_market_lot_size = float(max_market_lot_size) # max lot size for MARKET order
        self.market_lot_step_size = float(market_lot_step_size) # lot step size for MARKET order
        self.min_notional = float(min_notional) # min notional size

    def __str__(self):
        return (
            f"ReferenceData(\n"
            f"  symbol='{self.symbol}',\n"
            f"  status='{self.status}',\n"
            f"  base_asset='{self.base_asset}',\n"
            f"  quote_asset='{self.quote_asset}',\n"
            f"  price_precision={self.price_precision},\n"
            f"  quantity_precision={self.quantity_precision},\n"
            f"  min_price={self.min_price},\n"
            f"  max_price={self.max_price},\n"
            f"  price_tick_size={self.price_tick_size},\n"
            f"  min_lot_size={self.min_lot_size},\n"
            f"  max_lot_size={self.max_lot_size},\n"
            f"  lot_step_size={self.lot_step_size},\n"
            f"  min_market_lot_size={self.min_market_lot_size},\n"
            f"  max_market_lot_size={self.max_market_lot_size},\n"
            f"  market_lot_step_size={self.market_lot_step_size},\n"
            f"  min_notional={self.min_notional}\n"
            f")"
        )
