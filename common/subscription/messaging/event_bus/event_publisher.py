import logging


class EventPublisher:
    """Publisher that can emit events"""

    def __init__(self, name, event_bus):
        self.name = name
        self.event_bus = event_bus

    def publish_event(self, event_type, data=None):
        """Publish an event"""
        logging.debug(f"[{self.name}] Publishing event: {event_type}")
        self.event_bus.publish(event_type, data)
