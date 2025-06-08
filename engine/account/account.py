import logging

from engine.tracking.telegram_alert import telegramAlert


class Account:
    def __init__(self, wallet_balance: float, margin_balance: float, unrealised_pnl: float, maint_margin: float, alert_message: telegramAlert):
        self.wallet_balance = wallet_balance
        self.margin_balance = margin_balance
        self.unrealised_pnl = unrealised_pnl
        self.maint_margin = maint_margin
        self.alert_message = alert_message

    def get_margin_ratio(self):
        try:
            if self.margin_balance == 0:
                print("⚠️  Margin balance is zero. Check account funding.")
                return None

            margin_ratio = self.maint_margin / self.margin_balance
            print(f"🧾 Margin Ratio: {margin_ratio:.4f} | Maint Margin: {self.maint_margin} | Margin Balance: {self.margin_balance}")
            return margin_ratio

        except Exception as e:
            print("❌ Error:", e)
            return None

    def is_within_margin_limit(self, margin_limit : float)->int:
        margin_ratio = self.get_margin_ratio()
        if margin_ratio is None:
            logging.warning("Unable to get margin ratio")
            self.alert_message.sendAlert("Unable to get margin ratio")
            return 1
        elif margin_ratio > margin_limit:
            logging.error("Margin Ratio breached")
            self.alert_message.sendAlert(f"❗ Margin Ratio breached: {margin_ratio:.4f} | Maint Margin: {self.maint_margin} | Margin Balance: {self.margin_balance}")
            return 2
        elif margin_ratio > 0.9:
            logging.warning("Margin Ratio is above 90%, consider reducing positions.")
            self.alert_message.sendAlert("⚠️ Margin Ratio is above 90%, consider reducing positions.")
            return 3
        return 0