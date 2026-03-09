import time
import orjson
from abc import ABC
from dataclasses import asdict, is_dataclass


class JsonModel(ABC):

    def to_dict(self, include_timestamp: bool = False):
        if not is_dataclass(self):
            raise TypeError(f"{self.__class__.__name__} must be a dataclass")

        data = asdict(self)

        if include_timestamp:
            data["timestamp"] = int(time.time() * 1000)

        return data

    def to_json_with_time_stamp(self):
        return self.to_json(include_timestamp=True)

    def to_json(self, include_timestamp: bool = False):
        return orjson.dumps(
            self.to_dict(include_timestamp)
        ).decode()