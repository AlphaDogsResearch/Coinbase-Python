"""Risk Engine listener for publish/subscribe messaging.

This module defines a thin pub/sub layer to decouple the risk engine,
strategy, and market data gateway. It uses the existing pub/sub utilities
in `common.subscription.pubusb` to publish and subscribe to topics.

Topics:
- market.mark_price: (exchange: str, symbol: str, mid: float)
- market.depth: (exchange: str, symbol: str, venue_book)
- account.wallet_balance: (snapshot: dict[currency->balance])
- risk.validation.request: (order: common.interface_order.Order)
- risk.validation.response: (allowed: bool, reason: str | None, order_id: str | None)

Usage:
- Strategies subscribe to `risk.validation.response` and publish requests.
- Risk Engine subscribes to `risk.validation.request` and publishes responses.
- Gateway publishes market topics; risk engine subscribes.
"""

from typing import Callable, Optional

# Absolute imports consistent with repo structure
from common.subscription.pubusb.server_publisher import ServerPublisher
from common.subscription.pubusb.client_subscriber import ClientSubscriber

# Topic constants
TOPIC_MARK_PRICE = "market.mark_price"
TOPIC_DEPTH = "market.depth"
TOPIC_WALLET_BALANCE = "account.wallet_balance"
TOPIC_VALIDATION_REQUEST = "risk.validation.request"
TOPIC_VALIDATION_RESPONSE = "risk.validation.response"

class RiskPubSub:
    """Unified publisher/subscriber for risk-related messaging."""

    def __init__(self, channel: str = "risk-engine"):
        # Channel can map to a queue/socket or namespace depending on implementation
        self.publisher = ServerPublisher(channel_name=channel)
        self.subscriber = ClientSubscriber(channel_name=channel)

    # -----------------
    # Publish helpers
    # -----------------
    def publish_mark_price(self, exchange: str, symbol: str, mid: float) -> None:
        self.publisher.publish(TOPIC_MARK_PRICE, {
            "exchange": exchange,
            "symbol": symbol,
            "mid": mid,
        })

    def publish_depth(self, exchange: str, symbol: str, venue_book) -> None:
        self.publisher.publish(TOPIC_DEPTH, {
            "exchange": exchange,
            "symbol": symbol,
            "book": venue_book,
        })

    def publish_wallet_balance(self, snapshot: dict) -> None:
        self.publisher.publish(TOPIC_WALLET_BALANCE, snapshot)

    def publish_validation_response(self, allowed: bool, reason: Optional[str] = None, order_id: Optional[str] = None) -> None:
        self.publisher.publish(TOPIC_VALIDATION_RESPONSE, {
            "allowed": allowed,
            "reason": reason,
            "order_id": order_id,
        })

    # -----------------
    # Subscribe helpers
    # -----------------
    def on_mark_price(self, handler: Callable[[str, str, float], None]) -> None:
        def _wrap(payload):
            handler(payload.get("exchange"), payload.get("symbol"), float(payload.get("mid")))
        self.subscriber.subscribe(TOPIC_MARK_PRICE, _wrap)

    def on_depth(self, handler: Callable[[str, str, object], None]) -> None:
        def _wrap(payload):
            handler(payload.get("exchange"), payload.get("symbol"), payload.get("book"))
        self.subscriber.subscribe(TOPIC_DEPTH, _wrap)

    def on_wallet_balance(self, handler: Callable[[dict], None]) -> None:
        self.subscriber.subscribe(TOPIC_WALLET_BALANCE, handler)

    def on_validation_request(self, handler: Callable[[object], None]) -> None:
        # Handler should accept an Order-like object or dict; pass-through
        self.subscriber.subscribe(TOPIC_VALIDATION_REQUEST, handler)

    # -----------------
    # Strategy-side API
    # -----------------
    def request_validation(self, order_payload: dict) -> None:
        """Strategy publishes a validation request.
        order_payload should be serializable (dict) representing Order.
        """
        self.publisher.publish(TOPIC_VALIDATION_REQUEST, order_payload)
