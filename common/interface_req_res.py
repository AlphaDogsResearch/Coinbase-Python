# Wallet response
from common.time_utils import current_milli_time


class WalletResponse:
    def __init__(self, balances: dict):
        self.balances = balances  # e.g., {"USD": 1523.45, "BTC": 0.042, "ETH": 1.8}

    def get_balance(self, currency: str):
        return self.balances.get(currency, 0.0)

    def __str__(self):
        return "Balances=" + str(self.balances)


# Wallet request class
class WalletRequest:
    def __init__(self):
        self.time = current_milli_time()

    def handle(self, balances: dict) -> WalletResponse:
        return WalletResponse(balances)


class PositionResponse:
    def __init__(self, positions: dict):
        self.positions = positions

    def __str__(self):
        return "Positions=" + str(self.positions)


class PositionRequest:
    def __init__(self):
        self.time = current_milli_time()

    def handle(self, positions: dict) -> PositionResponse:
        return PositionResponse(positions)


class MarginInfoResponse:
    def __init__(self, symbol: str, margin_brackets: list):
        self.margin_brackets = margin_brackets
        self.symbol = symbol

    def __str__(self):
        return "Symbol=" + self.symbol + \
            ", Margin Brackets=" + str(self.margin_brackets)


class MarginInfoRequest:
    def __init__(self, symbol: str):
        self.time = current_milli_time()
        self.symbol = symbol

    def handle(self, symbol: str, margin_brackets: list) -> MarginInfoResponse:
        return MarginInfoResponse(symbol, margin_brackets)


class AccountResponse:
    def __init__(self, wallet_balance: float, margin_balance: float, unrealised_pnl: float, maint_margin: float):
        self.wallet_balance = wallet_balance
        self.margin_balance = margin_balance
        self.unrealised_pnl = unrealised_pnl
        self.maint_margin = maint_margin


class AccountRequest:
    def __init__(self):
        self.time = current_milli_time()

    def handle(self, wallet_balance: float, margin_balance: float, unrealised_pnl: float,
               maint_margin: float) -> AccountResponse:
        return AccountResponse(wallet_balance, margin_balance, unrealised_pnl, maint_margin)
