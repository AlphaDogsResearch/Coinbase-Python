import logging


class EventPublisher:
    """Publisher that can emit events"""

    def __init__(self, name, event_bus):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.name = name
        self.event_bus = event_bus

    def publish_event(self, event_type, data=None):
        """Publish an event"""
        self.logger.debug(f"[{self.name}] Publishing event: {event_type} -> {data}")
        self.event_bus.publish(event_type, data)
