import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List

from common.interface_req_res import AccountResponse
from engine.tracking.telegram_alert import telegramAlert


class Account:
    def __init__(self, alert: telegramAlert,margin_limit:float):
        self.name = "Account"
        self.maint_margin = 0.0
        self.unrealised_pnl = 0.0
        self.wallet_balance = 0.0
        self.margin_balance = 0.0
        self.alert = alert
        self.initalised = False
        self.margin_limit = margin_limit # ratio of margin limit
        self.wallet_balance_listener: List[Callable[[float], None]] = []
        self.margin_ratio_listener: List[Callable[[float], None]] = []

        self.executor = ThreadPoolExecutor(max_workers=1,thread_name_prefix="ACCOUNT")

        self.start_checking()


    def init_account(self,account_response: AccountResponse):
        self.wallet_balance = float(account_response.wallet_balance)
        self.margin_balance = float(account_response.margin_balance)
        self.unrealised_pnl = float(account_response.unrealised_pnl)
        self.maint_margin = float(account_response.maint_margin)
        self.on_wallet_balance_update(self.wallet_balance)
        self.initalised = True

    def start_checking(self):
        self.executor.submit(self.check_margin)

    def add_wallet_balance_listener(self, callback: Callable[[float], None]):
        """Register a callback to receive OrderBook updates"""
        self.wallet_balance_listener.append(callback)

    def add_margin_ratio_listener(self, callback: Callable[[float], None]):
        """Register a callback to receive OrderBook updates"""
        self.margin_ratio_listener.append(callback)

    def on_wallet_balance_update(self, wallet_balance : float):
        logging.info("%s Updated Wallet Balance to %s", self.name,wallet_balance)

        for balance_listener in self.wallet_balance_listener:
            try:
                balance_listener(wallet_balance)
            except Exception as e:
                logging.error(self.name + " Listener raised an exception: %s", e)

    def update_wallet_with_realized_pnl(self,realized_pnl:float):
        self.wallet_balance += realized_pnl
        self.on_wallet_balance_update(self.wallet_balance)
        self.update_margin_balance()

    def update_margin_balance(self):
        self.margin_balance = self.wallet_balance + self.unrealised_pnl
        logging.debug("Updating Margin balance to %s",self.margin_balance)

    def update_maint_margin(self,new_maint_margin:float):
        self.maint_margin = new_maint_margin
        logging.debug("Updating Maint Margin to %s",self.maint_margin)

    def on_maint_margin_update(self,new_maint_margin:float):
        if self.maint_margin!=new_maint_margin:
            self.update_maint_margin(new_maint_margin)

    def on_unrealised_pnl_update(self,new_unrealised_pnl:float):
        if self.unrealised_pnl!=new_unrealised_pnl:
            self.unrealised_pnl = self.unrealised_pnl
            self.update_margin_balance()

    def get_margin_ratio(self):
        try:
            if self.margin_balance == 0:
                logging.error("⚠️  Margin balance is zero. Check account funding.")
                return None

            margin_ratio = self.maint_margin / self.margin_balance
            logging.debug(f"🧾 Margin Ratio: {margin_ratio:.4f} | Maint Margin: {self.maint_margin} | Margin Balance: {self.margin_balance}")
            return margin_ratio

        except Exception as e:
            print("❌ Error:", e)
            return None

    def is_within_margin_limit(self, margin_limit : float)->int:
        margin_ratio = self.get_margin_ratio()
        self.on_margin_ratio_update(margin_ratio)
        if margin_ratio is None:
            logging.error("Unable to get margin ratio")
            self.alert.sendAlert("Unable to get margin ratio")
            return 1
        elif margin_ratio > margin_limit:
            logging.error("Margin Ratio breached")
            self.alert.sendAlert(f"❗ Margin Ratio breached: {margin_ratio:.4f} | Maint Margin: {self.maint_margin} | Margin Balance: {self.margin_balance}")
            return 2
        elif margin_ratio > 0.9:
            logging.error("Margin Ratio is above 90%, consider reducing positions.")
            self.alert.sendAlert("⚠️ Margin Ratio is above 90%, consider reducing positions.")
            return 3
        return 0

    def on_margin_ratio_update(self, margin_ratio: float):
        for listener in self.margin_ratio_listener:
            try:
                listener(margin_ratio)
            except Exception as e:
                logging.error(self.name + " Listener raised an exception: %s", e)

    def check_margin(self):
        while True:
            while self.initalised:
                self.is_within_margin_limit(self.margin_limit)
