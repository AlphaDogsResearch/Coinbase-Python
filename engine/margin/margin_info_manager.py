import logging

from common.interface_req_res import MarginInfoResponse
from engine.margin.margin_info import MarginSchedule, MarginBracket
from typing import Optional

class MarginInfoManager:
    def __init__(self):
        self.margin_list = {}

    def update_margin(self, margin_response:MarginInfoResponse):
        symbol = margin_response.symbol
        brackets = margin_response.margin_brackets
        if brackets is not None:
            self.margin_list[symbol] = MarginSchedule(brackets)

        for symbol,margin in self.margin_list.items():
            logging.info("Updated Margin %s -> %s",symbol,margin)

    def get_margin_brackets(self,symbol:str)->Optional[MarginSchedule]:
        return self.margin_list.get(symbol,None)

    def get_margin_bracket_by_notional(self,symbol:str,notional:float)->Optional[MarginBracket]:
        brackets = self.get_margin_brackets(symbol)
        if brackets is None:
            logging.error("Unable to find bracket for %s -> %s",symbol,notional)
            return None
        return brackets.get_bracket(notional)







