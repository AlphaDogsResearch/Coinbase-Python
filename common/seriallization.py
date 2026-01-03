import inspect
import logging
from enum import Enum
from typing import Type, Dict, Any


class Serializable:
    """Base class for objects that can serialize/deserialize themselves to/from dict."""

    def to_dict(self) -> Dict[str, Any]:
        """Convert object (including nested objects) to dict with __class__ info."""
        result = {"__class__": self.__class__.__name__, "data": {}}

        # Register the class for future deserialization
        SerializableRegistry.register(self.__class__)

        for key, value in self.__dict__.items():
            if isinstance(value, dict):
                # Handle dictionary values
                result["data"][key] = {
                    k: v.to_dict() if hasattr(v, "to_dict") else v
                    for k, v in value.items()
                }
            elif isinstance(value, list):
                result["data"][key] = [
                    v.to_dict() if hasattr(v, "to_dict") else v for v in value
                ]
            elif isinstance(value, Enum):
                # Handle enum serialization and register the enum type
                SerializableRegistry.register_enum_from_instance(value)
                result["data"][key] = {
                    "__enum__": value.__class__.__name__,
                    "name": value.name,
                    "value": value.value
                }
            elif hasattr(value, "to_dict"):
                result["data"][key] = value.to_dict()
            else:
                result["data"][key] = value
        return result

    @classmethod
    def from_dict(cls, d: Dict[str, Any]):
        """Dynamically reconstruct object from dict (supports nested objects/lists/dicts)."""
        # Handle wrapped {"__class__", "data"} structure
        if "__class__" in d and "data" in d:
            class_name = d["__class__"]
            data = d["data"]
            # print("class_name:", class_name)
            # print("data:", data)

            # Look up the real class from registry
            klass = SerializableRegistry.get_class(class_name)
            if klass is None:
                raise ValueError(f"Unknown class {class_name}")

            return klass.from_dict(data)

        # Base case: construct object without calling __init__
        obj = cls.__new__(cls)
        for key, value in d.items():
            setattr(obj, key, cls._convert_item(value))
        return obj

    @classmethod
    def _convert_item(cls, value: Any) -> Any:
        """Recursively convert dict/list items back to objects."""
        if isinstance(value, dict):
            # Check if this dict represents a Serializable object
            if "__class__" in value and "data" in value:
                class_name = value["__class__"]
                data = value["data"]
                klass = SerializableRegistry.get_class(class_name)
                if klass:
                    return klass.from_dict(data)

            # Check if this dict represents an Enum
            if "__enum__" in value and "name" in value and "value" in value:
                return cls._convert_enum(value)

            # Regular dict - convert its values recursively
            return {k: cls._convert_item(v) for k, v in value.items()}

        elif isinstance(value, list):
            return [cls._convert_item(item) for item in value]

        else:
            return value

    @classmethod
    def _convert_enum(cls, enum_dict: Dict[str, Any]) -> Any:
        """Convert serialized enum dict back to Enum object using the new registry."""
        try:
            # Use the new get_or_create_enum method
            return SerializableRegistry.get_or_create_enum(enum_dict)
        except (ValueError, AttributeError) as e:
            # Fallback: try to find existing enum class
            enum_name = enum_dict.get("__enum__")
            enum_class = SerializableRegistry.get_enum(enum_name)

            if enum_class and issubclass(enum_class, Enum):
                # Try to get by name
                if "name" in enum_dict:
                    try:
                        return getattr(enum_class, enum_dict["name"])
                    except AttributeError:
                        pass

                # Fall back to value
                if "value" in enum_dict:
                    return enum_class(enum_dict["value"])

            # If nothing works, return the original dict
            return enum_dict

    def to_json(self, indent: int = 2) -> str:
        """Convert directly to JSON string."""
        import json
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, json_str: str):
        """Create object from JSON string."""
        import json
        data = json.loads(json_str)
        return cls.from_dict(data)


class SerializableRegistry:
    """Registry for dynamically reconstructing classes and enums by name."""
    _registry: Dict[str, Type] = {}
    _enum_registry: Dict[str, Type[Enum]] = {}

    @classmethod
    def register(cls, klass):
        """Register a class."""
        cls._registry[klass.__name__] = klass
        return klass

    @classmethod
    def get_class(cls, name):
        return cls._registry.get(name, None)

    @classmethod
    def get_or_create_enum(cls, enum_data: Dict[str, Any]) -> Enum:
        """
        Get an existing enum member or create/update enum dynamically from serialized data.

        Expected format: {"__enum__": "EnumName", "name": "MEMBER_NAME", "value": value}
        """
        if not isinstance(enum_data, dict) or "__enum__" not in enum_data:
            raise ValueError("Invalid enum data format")

        enum_name = enum_data["__enum__"]
        member_name = enum_data["name"]
        member_value = enum_data["value"]

        # 1. Check if enum is already registered
        if enum_name in cls._enum_registry:
            enum_class = cls._enum_registry[enum_name]

            # Try to get existing member
            try:
                return enum_class[member_name]
            except KeyError:
                # Member doesn't exist, need to create new enum with additional member
                logging.info(f"Adding new member {member_name}:{member_value} to existing enum {enum_name}")

                # Get all existing members
                members_dict = {m.name: m.value for m in enum_class}

                # Check if value already exists with different name
                for existing_name, existing_value in members_dict.items():
                    if existing_value == member_value:
                        logging.warning(f"Value {member_value} already exists as {existing_name} in {enum_name}")
                        return enum_class(existing_value)

                # Add new member
                logging.info(f"Adding new member {member_name}:{member_value} to {enum_name}")
                members_dict[member_name] = member_value

                # Create new enum class with all members
                new_enum_class = Enum(enum_name, members_dict)
                cls._enum_registry[enum_name] = new_enum_class

                return new_enum_class[member_name]

        # 2. Create enum dynamically and register it
        logging.info(f"Creating new enum {enum_name} : {member_name} : {member_value}")
        enum_class = Enum(enum_name, {member_name: member_value})
        cls._enum_registry[enum_name] = enum_class

        return enum_class[member_name]

    @classmethod
    def register_enum_from_instance(cls, enum_instance: Enum) -> None:
        """Register an enum from an instance (used during serialization)."""
        if enum_instance:
            enum_class = enum_instance.__class__
            if enum_class.__name__ not in cls._enum_registry:
                cls._enum_registry[enum_class.__name__] = enum_class

    @classmethod
    def get_enum(cls, name):
        """Get a registered enum by name."""
        return cls._enum_registry.get(name, None)

    @classmethod
    def clear_registry(cls):
        """Clear the registry (mainly for testing)."""
        cls._registry.clear()
        cls._enum_registry.clear()

