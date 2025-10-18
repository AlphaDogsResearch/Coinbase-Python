import logging
import unittest
from decimal import Decimal, ROUND_CEILING

from common.config_logging import to_stdout


class TestReferenceDataStepSizeCalculation(unittest.TestCase):

    def test_get_min_step(self):
        current_price = Decimal(3985.51)
        min_notional = Decimal(20)
        min_qty_by_notional = min_notional / current_price
        logging.info(f"min_qty_by_notional: {min_qty_by_notional}")
        stepSize = 0.001
        rounded_value = self.round_up_decimal(min_qty_by_notional, stepSize)
        self.assertEqual(str(rounded_value),str(0.006))

    #TODO use Decimal to keep precision
    def round_up_decimal(self,value:float, step)->Decimal:
        value = Decimal(str(value))
        step = Decimal(str(step))
        return (value / step).to_integral_value(rounding=ROUND_CEILING) * step

if __name__ == "__main__":
    to_stdout()
    unittest.main()
