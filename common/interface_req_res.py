# Wallet response
from abc import ABC, abstractmethod
from typing import Dict

from common.interface_reference_data import ReferenceData
from common.seriallization import Serializable
from common.time_utils import current_milli_time


class WalletResponse(Serializable):
    def __init__(self, balances: dict):
        self.balances = balances  # e.g., {"USD": 1523.45, "BTC": 0.042, "ETH": 1.8}

    def get_balance(self, currency: str):
        return self.balances.get(currency, 0.0)

    def __str__(self):
        return "Balances=" + str(self.balances)


# Wallet request class
class WalletRequest(Serializable):
    def __init__(self):
        super().__init__()
        self.time = current_milli_time()

    def handle(self, balances: dict) -> WalletResponse:
        return WalletResponse(balances)


class PositionResponse(Serializable):
    def __init__(self, positions: dict):
        self.positions = positions

    def __str__(self):
        return "Positions=" + str(self.positions)


class PositionRequest(Serializable):
    def __init__(self):
        self.time = current_milli_time()

    def handle(self, positions: dict) -> PositionResponse:
        return PositionResponse(positions)


class MarginInfoResponse(Serializable):
    def __init__(self, symbol: str, margin_brackets: list):
        self.margin_brackets = margin_brackets
        self.symbol = symbol

    def __str__(self):
        return "Symbol=" + self.symbol + \
            ", Margin Brackets=" + str(self.margin_brackets)


class MarginInfoRequest(Serializable):
    def __init__(self, symbol: str):
        super().__init__()
        self.time = current_milli_time()
        self.symbol = symbol

    def handle(self, symbol: str, margin_brackets: list) -> MarginInfoResponse:
        return MarginInfoResponse(symbol, margin_brackets)


class AccountResponse(Serializable):
    def __init__(self, wallet_balance: float, margin_balance: float, unrealised_pnl: float, maint_margin: float):
        self.wallet_balance = wallet_balance
        self.margin_balance = margin_balance
        self.unrealised_pnl = unrealised_pnl
        self.maint_margin = maint_margin


class AccountRequest(Serializable):
    def __init__(self):
        self.time = current_milli_time()

    def handle(self, wallet_balance: float, margin_balance: float, unrealised_pnl: float,
               maint_margin: float) -> AccountResponse:
        return AccountResponse(wallet_balance, margin_balance, unrealised_pnl, maint_margin)


class CommissionRateResponse(Serializable):
    def __init__(self, symbol: str, maker_trading_cost: float,taker_trading_cost:float):
        self.symbol = symbol
        self.maker_trading_cost = maker_trading_cost
        self.taker_trading_cost = taker_trading_cost

    def __str__(self):
        return "Symbol=" + self.symbol + \
            ", Maker Trading Cost=" + str(self.maker_trading_cost) + \
            ", Taker Trading Cost=" + str(self.taker_trading_cost)


class CommissionRateRequest(Serializable):
    def __init__(self, symbol: str):
        self.time = current_milli_time()
        self.symbol = symbol

    def handle(self, symbol: str, maker_trading_cost: float,taker_trading_cost:float) -> CommissionRateResponse:
        return CommissionRateResponse(symbol, maker_trading_cost,taker_trading_cost)


class TradesResponse(Serializable):
    def __init__(self, symbol: str, trades: list):
        self.symbol = symbol
        self.trades = trades

    def __str__(self):
        return "Symbol=" + self.symbol + \
            ", Trades=" + str(self.trades)


class TradesRequest(Serializable):
    def __init__(self, symbol: str):
        self.time = current_milli_time()
        self.symbol = symbol

    def handle(self, symbol: str, trades: list) -> TradesResponse:
        return TradesResponse(symbol, trades)

class ReferenceDataResponse(Serializable):
    def __init__(self, reference_data: Dict[str, ReferenceData]):
        self.reference_data = reference_data

    def __str__(self):
        return "ReferenceResponse={\n" + "\n".join(
            f"  {symbol}: {info}" for symbol, info in self.reference_data.items()
        ) + "\n}"


class ReferenceDataRequest(Serializable):
    def __init__(self):
        self.time = current_milli_time()

    def handle(self, reference_data: Dict[str, ReferenceData]) -> ReferenceDataResponse:
        return ReferenceDataResponse(reference_data)





