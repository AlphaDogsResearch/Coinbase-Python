from abc import abstractmethod, ABC


class Recyclable(ABC):
    @abstractmethod
    def recycle(self):
        pass