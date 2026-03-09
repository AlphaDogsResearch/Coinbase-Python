import asyncio

from common.subscription.messaging.event_bus.event_subscriber import EventSubscriber
from common.subscription.external_transport.base_message_formatter import BaseMessageFormatter
from common.subscription.external_transport.base_producer import BaseProducer


class EventDrivenProducer(EventSubscriber, BaseProducer):

    def __init__(self, name, event_bus, event_type, formatter:BaseMessageFormatter):
        super().__init__(name, event_bus)
        self.event_type = event_type
        self.formatter = formatter
        self._publish = None
        self._loop = None
        self._queue = None

    async def run(self, publish):
        self._publish = publish
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()

        self.subscribe(self.event_type)

        consumer_task = asyncio.create_task(self._consumer())

        try:
            await asyncio.Event().wait()
        finally:
            consumer_task.cancel()
            self.unsubscribe(self.event_type)

    async def _consumer(self):
        while True:
            data = await self._queue.get()
            payload = data
            if self.formatter is not None:
                payload = self.formatter.format(data)

            await self._publish(payload)

    def handle_event(self, data):
        if self._publish and self._loop:
            payload = data
            if self.formatter is not None:
                payload = self.formatter.format(data)

            if asyncio.iscoroutinefunction(self._publish):
                asyncio.run_coroutine_threadsafe(
                    self._publish(payload),
                    self._loop
                )
            else:
                self._loop.call_soon_threadsafe(
                    self._publish,
                    payload
                )

