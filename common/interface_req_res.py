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

    def handle(self,balances: dict) -> WalletResponse:
        return WalletResponse(balances)