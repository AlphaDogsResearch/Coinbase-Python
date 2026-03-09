from abc import ABC, abstractmethod
from typing import Callable, Awaitable


class BaseProducer(ABC):

    @abstractmethod
    async def run(self, publish: Callable[[str], Awaitable[None]]) -> None:
        """
        Implement your streaming logic here.
        Call publish(message) whenever you want to send data.
        """
        pass