import logging
from concurrent.futures import ThreadPoolExecutor

from common.interface_req_res import AccountResponse
from engine.tracking.telegram_alert import telegramAlert


class Account:
    def __init__(self, alert: telegramAlert,margin_limit:float):
        self.maint_margin = None
        self.unrealised_pnl = None
        self.wallet_balance = None
        self.margin_balance = None
        self.alert = alert
        self.initalised = False
        self.margin_limit = margin_limit # ratio of margin limit
        self.executor = ThreadPoolExecutor(max_workers=1,thread_name_prefix="ACC")

        self.start_checking()

    
    def init_account(self,account_response: AccountResponse):
        self.wallet_balance = float(account_response.wallet_balance)
        self.margin_balance = float(account_response.margin_balance)
        self.unrealised_pnl = float(account_response.unrealised_pnl)
        self.maint_margin = float(account_response.maint_margin)
        self.initalised = True

    def start_checking(self):
        self.executor.submit(self.check_margin)
        
    def update_margin_balance(self,unrealised_pnl:float):
        #TODO update wallet balance
        self.margin_balance = self.wallet_balance + unrealised_pnl
        logging.debug("Updating Margin balance to %s",self.margin_balance)

    def update_maint_margin(self,new_maint_margin:float):
        self.maint_margin = new_maint_margin
        logging.debug("Updating Maint Margin to %s",self.maint_margin)

    def on_maint_margin_update(self,new_maint_margin:float):
        if self.maint_margin!=new_maint_margin:
            self.update_maint_margin(new_maint_margin)

    def on_unrealised_pnl_update(self,new_unrealised_pnl:float):
        if self.unrealised_pnl!=new_unrealised_pnl:
            self.update_margin_balance(new_unrealised_pnl)

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
        if margin_ratio is None:
            logging.warning("Unable to get margin ratio")
            self.alert.sendAlert("Unable to get margin ratio")
            return 1
        elif margin_ratio > margin_limit:
            logging.error("Margin Ratio breached")
            self.alert.sendAlert(f"❗ Margin Ratio breached: {margin_ratio:.4f} | Maint Margin: {self.maint_margin} | Margin Balance: {self.margin_balance}")
            return 2
        elif margin_ratio > 0.9:
            logging.warning("Margin Ratio is above 90%, consider reducing positions.")
            self.alert.sendAlert("⚠️ Margin Ratio is above 90%, consider reducing positions.")
            return 3
        return 0

    def check_margin(self):
        while self.initalised:
            self.is_within_margin_limit(self.margin_limit)
