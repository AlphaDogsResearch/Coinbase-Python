import json
import logging
from typing import Any, Type

from common.seriallization import Serializable
from common.subscription.messaging.event_handler import EventHandler


class EventHandlerImpl(EventHandler):

    def __init__(self,name:str, callback,*types: Type[Serializable]):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.callback = callback
        self.name = str(name)+"_HANDLER"
        self.register_messages(
            *types
        )

    def handle(self, identity: str, payload: Any) -> None:

        try:
            obj_dict = json.loads(payload.decode())
            class_name = obj_dict["__class__"]
            self.logger.debug("Received event: %s", class_name)
            obj = Serializable.from_dict(obj_dict)
            self.callback(identity,obj)
        except Exception as e:
            self.logger.error(f"[{self.name}] Exception when handling event {payload}",  exc_info=True)

