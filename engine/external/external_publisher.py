import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict

from common.json_model import JsonModel
from common.subscription.external_transport.base_message_formatter import BaseMessageFormatter
from common.subscription.external_transport.event_driven_producer import EventDrivenProducer
from common.subscription.external_transport.sse_event_emitter import MultiChannelSSE
from common.subscription.external_transport.websocket import MultiChannelWebSocket
from common.subscription.messaging.event_bus.event_bus import EventBus
from common.subscription.messaging.event_bus.event_publisher import EventPublisher


class ExternalPublisher:
    def __init__(self, event_bus:EventBus, websocket:MultiChannelWebSocket, publish_interval_seconds:int=1):
        self.start =False
        self.publish_interval_seconds = publish_interval_seconds
        self.data_model : Dict[str,JsonModel] = {}
        self.publisher_map: Dict[str, EventPublisher] = {}
        self.event_bus : EventBus = event_bus
        self.websocket = websocket

        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="EXT_PUBLISHER")
        self.executor.submit(self.publish_periodic_data)

    def register_publish_interval(self,key:str,data:JsonModel,formatter:BaseMessageFormatter):
        self.data_model[key] = data
        self.publisher_map[key] = EventPublisher(key,self.event_bus)
        producer = EventDrivenProducer(name=key, event_bus=self.event_bus,
                            event_type=key, formatter=formatter)
        self.websocket.add_channel(key, producer)

    def publish_periodic_data(self):
        while True:
            time.sleep(self.publish_interval_seconds)
            for key,data in self.data_model.items():
                publisher = self.publisher_map[key]
                publisher.publish_event(key, data)
