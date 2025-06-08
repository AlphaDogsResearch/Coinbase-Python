from dataclasses import dataclass
from typing import List, Optional

@dataclass
class MarginBracket:
    bracket: int
    initialLeverage: float
    notionalCap: float
    notionalFloor: float
    maintMarginRatio: float
    cum: float

    def contains(self, notional: float) -> bool:
        return self.notionalFloor <= notional < self.notionalCap


class MarginSchedule:
    def __init__(self, brackets: List[dict]):
        self.brackets = [MarginBracket(**b) for b in brackets]

    def get_bracket(self, notional: float) -> Optional[MarginBracket]:
        for bracket in self.brackets:
            if bracket.contains(notional):
                return bracket
        return None  # or raise an exception

    def __repr__(self):
        return f"MarginSchedule({len(self.brackets)} brackets)"