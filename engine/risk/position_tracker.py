# import json
# import os
# from typing import Dict, Callable

# # TODO to be integrated with position.position_manager.py

# class PositionTracker:
#     """
#     Tracks current positions and open orders for each symbol.
#     Persists state to disk for recovery after restarts.
#     """
#     def __init__(self, storage_path: str = "position_tracker_state.json"):
#         self.positions: Dict[str, float] = {}
#         self.open_orders: Dict[str, int] = {}
#         self.position_pnl: Dict[str, float] = {}
#         self.close_position_callback: Callable[[str], None] = lambda symbol: None
#         self.cancel_order_callback: Callable[[str], None] = lambda symbol: None
#         self.storage_path = storage_path
#         self._load_state()

#     def _save_state(self):
#         state = {
#             "positions": self.positions,
#             "open_orders": self.open_orders,
#             "position_pnl": self.position_pnl,
#         }
#         with open(self.storage_path, "w") as f:
#             json.dump(state, f)

#     def _load_state(self):
#         if os.path.exists(self.storage_path):
#             try:
#                 with open(self.storage_path, "r") as f:
#                     state = json.load(f)
#                     self.positions = state.get("positions", {})
#                     self.open_orders = state.get("open_orders", {})
#                     self.position_pnl = state.get("position_pnl", {})
#             except Exception:
#                 self.positions = {}
#                 self.open_orders = {}
#                 self.position_pnl = {}

#     def set_position(self, symbol: str, size: float):
#         if size == 0.0:
#             self._remove_symbol(symbol)
#         else:
#             self.positions[symbol] = size
#             self._save_state()

#     def update_position(self, symbol: str, delta: float):
#         new_size = self.positions.get(symbol, 0.0) + delta
#         if new_size == 0.0:
#             self._remove_symbol(symbol)
#         else:
#             self.positions[symbol] = new_size
#             self._save_state()

#     def _remove_symbol(self, symbol: str):
#         self.positions.pop(symbol, None)
#         self.open_orders.pop(symbol, None)
#         self.position_pnl.pop(symbol, None)
#         self._save_state()

#     def get_position(self, symbol: str) -> float:
#         return self.positions.get(symbol, 0.0)

#     def set_open_orders(self, symbol: str, count: int):
#         self.open_orders[symbol] = count
#         self._save_state()

#     def increment_open_orders(self, symbol: str):
#         self.open_orders[symbol] = self.open_orders.get(symbol, 0) + 1
#         self._save_state()

#     def decrement_open_orders(self, symbol: str):
#         if symbol in self.open_orders and self.open_orders[symbol] > 0:
#             self.open_orders[symbol] -= 1
#             self._save_state()

#     def get_open_orders(self, symbol: str) -> int:
#         return self.open_orders.get(symbol, 0)

#     def set_position_pnl(self, symbol: str, pnl: float):
#         self.position_pnl[symbol] = pnl
#         self._save_state()

#     def get_position_pnl(self, symbol: str) -> float:
#         return self.position_pnl.get(symbol, 0.0)

#     def get_cumulative_pnl(self) -> float:
#         return sum(self.position_pnl.values())

#     def set_close_position_callback(self, callback: Callable[[str], None]):
#         self.close_position_callback = callback

#     def set_cancel_order_callback(self, callback: Callable[[str], None]):
#         self.cancel_order_callback = callback

#     def close_all_positions_and_orders(self):
#         for symbol in list(self.positions.keys()):
#             self.close_position_callback(symbol)
#         for symbol in list(self.open_orders.keys()):
#             self.cancel_order_callback(symbol)

#     def reset(self):
#         self.positions.clear()
#         self.open_orders.clear()
#         self.position_pnl.clear()
#         self._save_state()
