from abc import ABC, abstractmethod
from typing import Callable, Awaitable


class BaseMessageFormatter(ABC):

    @abstractmethod
    def format(self, data)->str|None:
        """
        Implement your streaming logic here.
        Call publish(message) whenever you want to send data.
        """
        return data