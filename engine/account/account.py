import logging
from typing import Callable, List

from common.interface_req_res import AccountResponse
from common.subscription.messaging.event_bus.event_bus import EventBus
from engine.account.account_state import AccountState


class Account:
    def __init__(self, margin_limit: float):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.name = "Account"
        self.account_state = AccountState()
        self.account_state.margin_limit = margin_limit  # ratio of margin limit
        self.initalised = False
        self.wallet_balance_listener: List[Callable[[float], None]] = []
        self.margin_ratio_listener: List[Callable[[float], None]] = []
        self.margin_warning_listeners: List[Callable[[str], None]] = []

    def init_account(self, account_response: AccountResponse):
        self.account_state.wallet_balance = float(account_response.wallet_balance)
        self.account_state.margin_balance = float(account_response.margin_balance)
        self.account_state.unrealised_pnl = float(account_response.unrealised_pnl)
        self.account_state.maint_margin = float(account_response.maint_margin)
        self.on_wallet_balance_update(self.account_state.wallet_balance)
        self.initalised = True

    def add_wallet_balance_listener(self, callback: Callable[[float], None]):
        """Register a callback to receive wallet balance updates"""
        self.wallet_balance_listener.append(callback)

    def add_margin_ratio_listener(self, callback: Callable[[float], None]):
        """Register a callback to receive margin ratio updates"""
        self.margin_ratio_listener.append(callback)

    def add_margin_warning_listener(self, callback: Callable[[str], None]):
        """Register a callback to receive margin warning messages"""
        self.margin_warning_listeners.append(callback)
        self.logger.info(f"Added margin warning listener: {callback.__name__}")

    def on_wallet_balance_update(self, wallet_balance: float):
        self.logger.info("%s Updated Wallet Balance to %s", self.name, wallet_balance)

        for balance_listener in self.wallet_balance_listener:
            try:
                balance_listener(wallet_balance)
            except Exception as e:
                self.logger.error(self.name + " Listener raised an exception: %s", e)

    def update_wallet_with_realized_pnl(self, realized_pnl: float):
        self.account_state.wallet_balance += realized_pnl
        self.account_state.realized_pnl += realized_pnl
        self.on_wallet_balance_update(self.account_state.wallet_balance)
        self.update_margin_balance()

    def update_margin_balance(self):
        self.account_state.margin_balance = self.account_state.wallet_balance + self.account_state.unrealised_pnl
        self.logger.debug("Updating Margin balance to %s", self.account_state.margin_balance)

    def update_maint_margin(self, new_maint_margin: float):
        self.account_state.maint_margin = new_maint_margin
        self.logger.debug("Updating Maint Margin to %s", self.account_state.maint_margin)
        self.is_within_margin_limit(self.account_state.margin_limit)

    def on_maint_margin_update(self, new_maint_margin: float):
        if self.account_state.maint_margin != new_maint_margin:
            self.update_maint_margin(new_maint_margin)

    def on_unrealised_pnl_update(self, new_unrealised_pnl: float):
        if self.account_state.unrealised_pnl != new_unrealised_pnl:
            self.account_state.unrealised_pnl = new_unrealised_pnl
            self.update_margin_balance()
            self.is_within_margin_limit(self.account_state.margin_limit)

    def get_margin_ratio(self):
        try:
            if self.account_state.margin_balance == 0:
                self.logger.error("⚠️  Margin balance is zero. Check account funding.")
                return None

            margin_ratio = self.account_state.maint_margin / self.account_state.margin_balance
            # self.logger.debug(f"🧾 Margin Ratio: {margin_ratio:.4f} | Maint Margin: {self.maint_margin} | Margin Balance: {self.margin_balance}")
            return margin_ratio

        except Exception as e:
            print("❌ Error:", e)
            return None

    def is_within_margin_limit(self, margin_limit: float) -> int:
        margin_ratio = self.get_margin_ratio()
        self.account_state.margin_ratio = margin_ratio
        self.on_margin_ratio_update(margin_ratio)
        if margin_ratio is None:
            self.logger.error("Unable to get margin ratio")
            self._notify_margin_warning("Unable to get margin ratio")
            return 1
        elif margin_ratio > margin_limit:
            self.logger.error("Margin Ratio breached")
            message = (
                f"❗ Margin Ratio breached: {margin_ratio:.4f} | "
                f"Maint Margin: {self.account_state.maint_margin} | Margin Balance: {self.account_state.margin_balance}"
            )
            self._notify_margin_warning(message)
            return 2
        elif margin_ratio > 0.9:
            self.logger.error("Margin Ratio is above 90%, consider reducing positions.")
            self._notify_margin_warning("⚠️ Margin Ratio is above 90%, consider reducing positions.")
            return 3
        return 0

    def _notify_margin_warning(self, message: str):
        """Notify all margin warning listeners."""
        for listener in self.margin_warning_listeners:
            try:
                listener(message)
            except Exception as e:
                self.logger.error(f"{self.name} margin warning listener raised an exception: {e}")

    def on_margin_ratio_update(self, margin_ratio: float):
        for listener in self.margin_ratio_listener:
            try:
                listener(margin_ratio)
            except Exception as e:
                self.logger.error(self.name + " Listener raised an exception: %s", e)
