from dataclasses import dataclass

from common.json_model import JsonModel


@dataclass
class AccountState(JsonModel):
    maint_margin: float = 0.0
    unrealised_pnl: float = 0.0
    wallet_balance: float = 0.0
    margin_balance: float = 0.0
    realized_pnl: float = 0.0
    margin_limit: float = 0.0
    margin_ratio: float = 0.0
