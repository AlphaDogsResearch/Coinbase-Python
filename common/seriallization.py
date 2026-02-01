import inspect
import logging
from enum import Enum
from typing import Type, Dict, Any
# Add sys import if not already present
import sys

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
                    "__module__": value.__class__.__module__,
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
            return SerializableRegistry.get_or_restore_enum(enum_dict)
        except (ValueError, AttributeError) as e:
            logging.warning(f"Failed to restore enum: {e}")
            # If nothing works, return a proxy object that can compare with both value and name
            return EnumProxy(enum_dict)

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


class EnumProxy:
    """Proxy for enum values that failed to deserialize properly."""

    def __init__(self, enum_dict: Dict[str, Any]):
        self.enum_dict = enum_dict
        self.name = enum_dict.get("name")
        self.value = enum_dict.get("value")
        self.enum_name = enum_dict.get("__enum__")

    def __eq__(self, other):
        if isinstance(other, Enum):
            return self.name == other.name and self.value == other.value
        elif isinstance(other, EnumProxy):
            return self.name == other.name and self.value == other.value
        elif self.value is not None:
            return self.value == other
        return False

    def __repr__(self):
        return f"EnumProxy({self.enum_name}.{self.name}={self.value})"


class SerializableRegistry:
    """Registry for dynamically reconstructing classes and enums by name."""
    _registry: Dict[str, Type] = {}
    _enum_registry: Dict[str, Type[Enum]] = {}
    _global_enum_cache: Dict[str, Type[Enum]] = {}

    @classmethod
    def register(cls, klass):
        """Register a class."""
        cls._registry[klass.__name__] = klass
        return klass

    @classmethod
    def get_class(cls, name):
        return cls._registry.get(name, None)

    @classmethod
    def get_or_restore_enum(cls, enum_data: Dict[str, Any]) -> Enum:
        """
        Get an existing enum member or find the original enum class.
        """
        if not isinstance(enum_data, dict) or "__enum__" not in enum_data:
            raise ValueError("Invalid enum data format")

        enum_name = enum_data["__enum__"]
        member_name = enum_data["name"]
        member_value = enum_data["value"]
        module_name = enum_data.get("__module__")

        # 1. Check if enum is already registered in our registry
        if enum_name in cls._enum_registry:
            enum_class = cls._enum_registry[enum_name]
            try:
                return enum_class[member_name]
            except KeyError:
                # Check by value
                for member in enum_class:
                    if member.value == member_value:
                        return member

        # 2. Try to find the enum in the global scope (module where it was defined)
        if module_name:
            try:
                # Try to import the module and find the enum
                module = __import__(module_name, fromlist=[enum_name])
                if hasattr(module, enum_name):
                    enum_class = getattr(module, enum_name)
                    if issubclass(enum_class, Enum):
                        cls._enum_registry[enum_name] = enum_class
                        try:
                            return enum_class[member_name]
                        except KeyError:
                            # Try to find by value
                            for member in enum_class:
                                if member.value == member_value:
                                    return member
            except (ImportError, AttributeError) as e:
                logging.debug(f"Could not import enum {enum_name} from {module_name}: {e}")

        # 3. Try to find enum in already loaded modules by scanning
        for module_name in sys.modules:
            module = sys.modules[module_name]
            if hasattr(module, enum_name):
                enum_class = getattr(module, enum_name)
                if isinstance(enum_class, type) and issubclass(enum_class, Enum):
                    cls._enum_registry[enum_name] = enum_class
                    try:
                        return enum_class[member_name]
                    except KeyError:
                        # Try to find by value
                        for member in enum_class:
                            if member.value == member_value:
                                return member

        # 4. Last resort: create a temporary enum (for comparison purposes)
        logging.warning(f"Creating temporary enum {enum_name} for deserialization")

        # Check if we've already created a temporary enum with this name
        if enum_name in cls._enum_registry:
            temp_enum = cls._enum_registry[enum_name]
        else:
            # Create a new temporary enum
            temp_enum = Enum(enum_name, {member_name: member_value})
            cls._enum_registry[enum_name] = temp_enum

        # Return the member
        try:
            return temp_enum[member_name]
        except KeyError:
            # If member doesn't exist in temp enum, recreate with this member
            # Get all existing members
            members = {}
            for m in temp_enum:
                members[m.name] = m.value

            # Add the new member if not already present
            if member_name not in members:
                members[member_name] = member_value

            # Create new enum with all members
            new_temp_enum = Enum(enum_name, members)
            cls._enum_registry[enum_name] = new_temp_enum
            return new_temp_enum[member_name]

    @classmethod
    def register_enum_from_instance(cls, enum_instance: Enum) -> None:
        """Register an enum from an instance (used during serialization)."""
        if enum_instance:
            enum_class = enum_instance.__class__
            enum_name = enum_class.__name__

            if enum_name not in cls._enum_registry:
                cls._enum_registry[enum_name] = enum_class

            # Also store in global cache for lookup
            cls._global_enum_cache[enum_name] = enum_class

    @classmethod
    def get_enum(cls, name):
        """Get a registered enum by name."""
        return cls._enum_registry.get(name, None)

    @classmethod
    def clear_registry(cls):
        """Clear the registry (mainly for testing)."""
        cls._registry.clear()
        cls._enum_registry.clear()
        cls._global_enum_cache.clear()


