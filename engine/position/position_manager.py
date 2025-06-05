import logging

from common.interface_req_res import PositionResponse
from engine.position.position import Position


class PositionManager:
    def __init__(self):
        self.positions = {}

    def add_position(self,position_response:PositionResponse):
        all_pos = position_response.positions

        for pos in all_pos:
            symbol = pos['symbol']
            position_amt = float(pos['positionAmt'])
            entry_price = float(pos['entryPrice'])
            unrealized_pnl = float(pos['unRealizedProfit'])
            maint_margin = float(pos['maintMargin'])

            if symbol in self.positions:
                position = self.positions[symbol]
                position.update_unrealised_pnl(unrealized_pnl)
                position.add_position_amount(position_amt)
            else:
                self.positions[symbol] = Position(symbol,position_amt,entry_price,unrealized_pnl,maint_margin)

        logging.info("Current Position %s",self.positions)

