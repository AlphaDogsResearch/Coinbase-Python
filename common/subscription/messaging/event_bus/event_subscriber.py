class EventSubscriber:
    """Subscriber that can listen to events"""

    def __init__(self, name, event_bus):
        self.name = name
        self.event_bus = event_bus

    def subscribe(self, event_type):
        """Subscribe to an event type"""
        self.event_bus.subscribe(event_type, self.handle_event)

    def unsubscribe(self, event_type):
        """Unsubscribe from an event type"""
        self.event_bus.unsubscribe(event_type, self.handle_event)

    def handle_event(self, data):
        """Handle incoming event"""
        print(f"[{self.name}] Received event data: {data}")
