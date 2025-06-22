from common.interface_req_res import CommissionRateResponse
from engine.trading_cost.trading_cost import TradingCost


class TradingCostManager:
    def __init__(self):
        self.trading_cost = {}

    def add_trading_cost(self,commission_rate:CommissionRateResponse):
        symbol = commission_rate.symbol
        maker_trading_cost = commission_rate.maker_trading_cost
        taker_trading_cost = commission_rate.taker_trading_cost
        self.trading_cost[symbol] = TradingCost(symbol,maker_trading_cost,taker_trading_cost)

    def get_trading_cost(self,symbol:str)-> TradingCost:
        return self.trading_cost[symbol]

