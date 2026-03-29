import time
from enum import Enum

import orjson
from abc import ABC
from dataclasses import asdict, is_dataclass


class JsonModel(ABC):

    def to_external_json(self, include_timestamp: bool = False):
        if not is_dataclass(self):
            raise TypeError(f"{self.__class__.__name__} must be a dataclass")

        data = asdict(self)

        # Convert enums to string names
        for k, v in data.items():
            if isinstance(v, Enum):
                data[k] = v.name

        if include_timestamp:
            data["timestamp"] = int(time.time() * 1000)

        return data

    def to_json_external_with_time_stamp(self):
        return self.to_json_external(include_timestamp=True)

    def to_json_external(self, include_timestamp: bool = False):
        return orjson.dumps(
            self.to_external_json(include_timestamp)
        ).decode()