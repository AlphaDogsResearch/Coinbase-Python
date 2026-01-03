from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from collections import deque
import numpy as np


# =========================
# Config + State
# =========================

@dataclass
class ShockRiskConfig:
    symbol: str                      # e.g. "ETHUSDT" (REST symbol)
    ws_symbol: str                   # e.g. "ethusdt" (stream symbol)
    jump_window_sec: int = 20        # lookback window for sharp moves
    jump_abs_sum: float = 0.010      # summed |returns| threshold (1.0% in 20s)
    lockout_sec: int = 15 * 60       # block re-entry after a shock exit
    max_loss_pct: float = 0.020      # optional: hard stop from entry (2%)
    min_samples: int = 5             # min points needed to evaluate


@dataclass
class PositionState:
    qty: float            # signed position qty (+long, -short)
    entry_price: float | None
    # optionally include: leverage, positionSide, etc.


class LiveWindow:
    """
    Stores a rolling window of mark prices (preferred) to detect shocks.
    """
    def __init__(self, maxlen: int = 5000):
        self.ts = deque(maxlen=maxlen)
        self.px = deque(maxlen=maxlen)

    def add(self, t: float, px: float) -> None:
        self.ts.append(t)
        self.px.append(px)

    def abs_return_sum(self, window_sec: int, min_samples: int) -> float:
        if len(self.ts) < min_samples:
            return 0.0
        t_now = self.ts[-1]
        # find first index within window
        idx0 = None
        for i, t in enumerate(self.ts):
            if t >= t_now - window_sec:
                idx0 = i
                break
        if idx0 is None:
            return 0.0
        p = np.asarray(list(self.px)[idx0:], dtype=float)
        if p.size < min_samples:
            return 0.0
        r = p[1:] / p[:-1] - 1.0
        return float(np.sum(np.abs(r)))

    def last_price(self) -> float | None:
        return float(self.px[-1]) if self.px else None


# =========================
# Risk Engine
# =========================

class ShockRiskEngine:
    """
    Intrabar risk overlay:
    - monitors mark price stream
    - triggers FLATTEN on sharp moves
    - enforces lockout after shock events
    """
    def __init__(self, cfg: ShockRiskConfig):
        self.cfg = cfg
        self.live = LiveWindow()
        self.lockout_until = 0.0
        self.last_reason: str | None = None

    # ---- feed market data ----
    def on_mark_price(self, mark_price: float, event_time_ms: int | None = None) -> None:
        now = time.time() if event_time_ms is None else event_time_ms / 1000.0
        self.live.add(now, float(mark_price))

    # ---- decision ----
    def in_lockout(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return now < self.lockout_until

    def check_override(self, pos: PositionState, now: float | None = None) -> tuple[str, str | None]:
        """
        Returns: (action, reason)
          action ∈ {"HOLD", "FLATTEN"}
        """
        now = time.time() if now is None else now

        if pos.qty == 0:
            return "HOLD", None

        if self.in_lockout(now):
            return "HOLD", None

        # A) Jump / velocity detector
        abs_sum = self.live.abs_return_sum(self.cfg.jump_window_sec, self.cfg.min_samples)
        if abs_sum >= self.cfg.jump_abs_sum:
            self.lockout_until = now + self.cfg.lockout_sec
            self.last_reason = f"jump_abs_sum={abs_sum:.4f}"
            return "FLATTEN", self.last_reason

        # B) Optional: hard max loss from entry (uses mark price)
        if pos.entry_price is not None:
            px = self.live.last_price()
            if px is not None:
                pnl_pct = (px / pos.entry_price - 1.0) * (1 if pos.qty > 0 else -1)
                if pnl_pct <= -self.cfg.max_loss_pct:
                    self.lockout_until = now + self.cfg.lockout_sec
                    self.last_reason = f"max_loss pnl_pct={pnl_pct:.4f}"
                    return "FLATTEN", self.last_reason

        return "HOLD", None


# =========================
# Binance Wiring (WS + REST)
# =========================

class BinanceUSDMShockRiskModule:
    """
    Plug-in module:
      - subscribes to markPrice@1s (and optionally aggTrade)
      - runs ShockRiskEngine decisions
      - executes reduceOnly market order to flatten
    """

    def __init__(self, cfg: ShockRiskConfig, *, rest_client, ws_client_factory):
        """
        rest_client: your Binance UM Futures REST client wrapper
        ws_client_factory: function that returns a running WS client
        """
        self.cfg = cfg
        self.engine = ShockRiskEngine(cfg)
        self.rest = rest_client
        self.ws_client_factory = ws_client_factory
        self._stop = threading.Event()

    def start(self):
        # Subscribe to mark price @1s: <symbol>@markPrice@1s  [oai_citation:5‡Binance Developers](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Mark-Price-Stream?utm_source=chatgpt.com)
        # Combine streams if you want (Binance supports combined streams)  [oai_citation:6‡Binance Developers](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams?utm_source=chatgpt.com)
        self.ws = self.ws_client_factory(on_mark_price=self._handle_mark_price)
        self.ws.subscribe_mark_price_1s(self.cfg.ws_symbol)  # implement in your WS wrapper
        self.ws.start()

    def stop(self):
        self._stop.set()
        if hasattr(self, "ws"):
            self.ws.stop()

    def _handle_mark_price(self, mark_price: float, event_time_ms: int | None = None):
        self.engine.on_mark_price(mark_price, event_time_ms)

    # ---- called by your main trading loop (e.g., every second) ----
    def maybe_override(self, pos: PositionState):
        action, reason = self.engine.check_override(pos)
        if action == "FLATTEN":
            self.flatten_reduce_only(pos, reason=reason)

    def flatten_reduce_only(self, pos: PositionState, reason: str | None = None):
        """
        Reduce-only MARKET to flat.
        Binance new order supports reduceOnly on /fapi/v1/order  [oai_citation:7‡Binance Developers](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api)
        """
        if pos.qty == 0:
            return

        side = "SELL" if pos.qty > 0 else "BUY"
        qty = abs(pos.qty)

        # IMPORTANT: reduceOnly cannot be sent in hedge mode (Binance note).  [oai_citation:8‡Binance Developers](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api)
        # If you're in hedge mode, you should send positionSide + closePosition/other approach.
        self.rest.new_order(
            symbol=self.cfg.symbol,
            side=side,
            type="MARKET",
            quantity=qty,
            reduceOnly="true",  #  [oai_citation:9‡Binance Developers](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api)
            newOrderRespType="RESULT",
        )
        # also: set a local flag so you don't spam orders in the same shock window