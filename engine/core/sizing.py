from common.config_strategy import RISK_PER_TRADE, MIN_ORDER_QTY, QTY_STEP


class SizingPolicy:
    risk_per_trade: float = RISK_PER_TRADE
    min_qty: float = MIN_ORDER_QTY
    qty_step: float = QTY_STEP

    def get_size(self, aum: float) -> float:
        if aum <= 0:
            return 0.0
        return float(aum/QTY_STEP)

    def compute_qty(self, size: float, price: float) -> float:
        if price <= 0:
            return 0.0
        return int(size/price)
