import telegram
import logging
import asyncio

class telegramAlert:
    def __init__(self, api_key, user_id):
        self.api_key = api_key
        self.user_id = user_id
        try:
            self.bot = telegram.Bot(token=self.api_key)
        except Exception as e:
            logging.error("[Telegram Bot] Registration failed: ", e)


    def sendAlert(self, bot_message):
        logging.info("Sending Telegram Sell Alert: {}".format(bot_message))
        asyncio.run(self.bot.send_message(chat_id=self.user_id, text="{}".format(bot_message)))
