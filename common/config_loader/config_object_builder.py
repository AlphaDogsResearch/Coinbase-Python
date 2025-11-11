# optimized_config_loader.py
import importlib
import json
import os
import builtins
import logging
from enum import Enum
import sys

# Ensure project root is in sys.path so local modules can be imported
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Setup default logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

'''
Full creation(Phase 1) + reference injection(Phase 2)
ALLOW circular reference when creating object,
DOES NOT ALLOW variable to call each other during init stage ,such as attaching listener
'''
def load_config(env: str):
    """Load config_loader JSON dynamically for the given environment."""
    filename = f"config_{env}.json"
    if not os.path.exists(filename):
        raise FileNotFoundError(f"Config file {filename} not found.")
    with open(filename, "r") as f:
        return json.load(f)


def create_objects(config: dict, verbose: bool = False, test_mode: bool = False):
    """
    Optimized dynamic object creation from JSON config_loader.

    Features:
      - Single objects, lists, dicts
      - Normal objects like dict/list
      - @key and chained references
      - Supports existing Python Enums and objects
      - Module caching for faster import
      - Handles large configs efficiently
      - Verbose logging: logs creation and reference injection when verbose=True
      - test_mode: skip threads or network operations
    """
    created = {}
    module_cache = {}

    def log(msg):
        if verbose:
            logging.info(msg)

    def get_module(name):
        if name not in module_cache:
            module_cache[name] = importlib.import_module(name)
        return module_cache[name]

    def resolve_ref(value):
        """Resolve @ references supporting nested attributes and created objects."""
        if isinstance(value, str) and value.startswith("@"):
            parts = value[1:].split(".")
            name = parts[0]

            # 1️⃣ Check in top-level created objects
            obj = created.get(name)

            # 2️⃣ If not found, try importing as module
            if obj is None:
                for i in range(len(parts), 0, -1):
                    module_path = ".".join(parts[:i])
                    try:
                        obj = importlib.import_module(module_path)
                        rest_parts = parts[i:]
                        break
                    except ModuleNotFoundError:
                        continue
                else:
                    raise ValueError(f"Cannot resolve reference '{value}'")
            else:
                # Remaining parts to resolve if obj comes from created
                rest_parts = parts[1:]

            # 3️⃣ Resolve remaining attributes
            for attr in rest_parts:
                if isinstance(obj, dict):
                    if attr not in obj:
                        raise ValueError(f"Key '{attr}' not found in dict '{obj}'")
                    obj = obj[attr]
                else:
                    obj = getattr(obj, attr)
            return obj
        return value

    def instantiate(spec, key_name=None):
        """Instantiate a single object with references injected immediately."""
        module_name = spec.get("module")
        class_name = spec.get("class")
        factory_name = spec.get("factory")
        params = {k: (None if isinstance(v, str) and v.startswith("@") else v)
                  for k, v in spec.get("params", {}).items()}

        # Built-in objects
        if module_name == "builtins" and class_name in ("dict", "list"):
            cls = getattr(builtins, class_name)
            obj = cls(**params) if class_name == "dict" else cls(params)
            log(f"Created built-in {class_name} '{key_name}' with params {params}")
        # Enum creation from JSON
        elif module_name == "enum" and class_name == "Enum":
            name = params.pop("name")
            values = dict(params.pop("values"))
            obj = Enum(name, values)
            log(f"Created Enum '{name}' for '{key_name}' with values {values}")
        # Normal class
        elif class_name:
            module = get_module(module_name)
            cls = getattr(module, class_name)
            if test_mode and "test_mode" in cls.__init__.__code__.co_varnames:
                params["test_mode"] = True
            obj = cls(**params)
            log(f"Created class '{class_name}' for '{key_name}' with params {params}")
        # Factory function
        elif factory_name:
            module = get_module(module_name)
            factory = getattr(module, factory_name)
            if test_mode and "test_mode" in factory.__code__.co_varnames:
                params["test_mode"] = True
            obj = factory(**params)
            log(f"Created factory '{factory_name}' for '{key_name}' with params {params}")
        else:
            raise ValueError("Spec must have 'class' or 'factory'")

        # Immediately inject references
        for k, v in spec.get("params", {}).items():
            resolved = resolve_ref(v)
            if isinstance(obj, dict):
                obj[k] = resolved
            else:
                setattr(obj, k, resolved)
            log(f"Injected reference for '{key_name}': {k} -> {resolved}")

        return obj

    # Instantiate all objects (dict, list, single objects, or nested dicts)
    for key, spec in config.items():
        if isinstance(spec, list):
            created[key] = [instantiate(s, key_name=f"{key}[{i}]") for i, s in enumerate(spec)]
        elif isinstance(spec, dict) and all(isinstance(v, dict) and "module" in v for v in spec.values()):
            created[key] = {subkey: instantiate(s, key_name=f"{key}.{subkey}") for subkey, s in spec.items()}
        else:
            created[key] = instantiate(spec, key_name=key)

    return created
