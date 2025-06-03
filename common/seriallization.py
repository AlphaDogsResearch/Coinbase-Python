class Serializable:
    def to_dict(self):
        result = {}
        for key, value in self.__dict__.items():
            if isinstance(value, list):
                result[key] = [v.to_dict() if hasattr(v, "to_dict") else v for v in value]
            elif hasattr(value, "to_dict"):
                result[key] = value.to_dict()
            else:
                result[key] = value
        return result

    @classmethod
    def from_dict(cls, d):
        obj = cls.__new__(cls)  # Don't call __init__
        for key, value in d.items():
            attr = getattr(cls, key, None)
            if isinstance(value, list):
                setattr(obj, key, [cls._convert_item(v) for v in value])
            else:
                setattr(obj, key, cls._convert_item(value))
        return obj

    @staticmethod
    def _convert_item(v):
        if isinstance(v, dict) and "__class__" in v:
            klass = globals()[v["__class__"]]
            return klass.from_dict(v["data"])
        return v
