from abc import ABC, abstractmethod
from typing import Any, Type

from common.seriallization import Serializable, SerializableRegistry


class EventHandler(ABC):
    """
    Base class for all handlers.
    """

    @abstractmethod
    def handle(self,identity:str, payload: Any) -> None:
        """
        Handle an incoming event/payload.
        Must be implemented by subclasses.
        """
        pass


    @classmethod
    def register_messages(self,*types: Type[Serializable]) -> None:
        for t in types:
            SerializableRegistry.register(t)
