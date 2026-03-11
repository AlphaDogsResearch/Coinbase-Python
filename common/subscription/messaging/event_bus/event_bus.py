from common.subscription.messaging.event_bus.event_publisher import EventPublisher
from common.subscription.messaging.event_bus.event_subscriber import EventSubscriber


class EventBus:
    """Simple event bus for managing pub/sub"""

    def __init__(self):
        self._subscribers = {}

    def subscribe(self, event_type, callback):
        """Subscribe to an event type"""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type, callback):
        """Unsubscribe from an event type"""
        if event_type in self._subscribers:
            self._subscribers[event_type].remove(callback)

    def publish(self, event_type, data=None):
        """Publish an event to all subscribers"""
        if event_type in self._subscribers:
            for callback in self._subscribers[event_type]:
                callback(data)

    def clear(self, event_type=None):
        """Clear subscribers for an event type or all events"""
        if event_type:
            self._subscribers[event_type] = []
        else:
            self._subscribers = {}


# Usage example
if __name__ == "__main__":
    # Create event bus
    event_bus = EventBus()

    # Create publishers
    news_publisher = EventPublisher("News Publisher", event_bus)
    weather_publisher = EventPublisher("Weather Publisher", event_bus)

    # Create subscribers
    subscriber1 = EventSubscriber("Subscriber 1", event_bus)
    subscriber2 = EventSubscriber("Subscriber 2", event_bus)
    subscriber3 = EventSubscriber("Subscriber 3", event_bus)

    # Subscribers subscribe to events
    subscriber1.subscribe("news_update")
    subscriber1.subscribe("weather_update")
    subscriber2.subscribe("news_update")
    subscriber3.subscribe("weather_update")

    # Publish events
    print("\n--- Publishing Events ---")
    news_publisher.publish_event("news_update", "Breaking: New Python Version Released!")
    print()
    weather_publisher.publish_event("weather_update", {"temp": 25, "condition": "Sunny"})
    print()
    news_publisher.publish_event("news_update", "Tech Update: AI Advances")

    # Unsubscribe and test
    print("\n--- After Unsubscribe ---")
    subscriber1.unsubscribe("news_update")
    news_publisher.publish_event("news_update", "Another news item")