# optimized_config_loader.py
import importlib
import json
import os
import builtins
import logging
from enum import Enum
import sys

from common.config_logging import to_stdout

# Ensure project root is in sys.path so local modules can be imported
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

import os
import json
from common.config_logging import to_stdout


import os
import json
from common.config_logging import to_stdout


def load_config(env: str,submodule_path:str=""):
    """Load JSON config dynamically for the given environment.
    Resolves the path relative to where the main script is run.
    """


    # Base path = where the main script is executed
    base_dir = os.getcwd()

    # Default: look for config folder under engine/config
    config_dir = os.path.join(base_dir, submodule_path)
    config_dir = os.path.join(config_dir, "config")
    filename = os.path.join(config_dir, f"config_{env}.json")

    # Allow override via CONFIG_PATH environment variable
    filename = os.getenv("CONFIG_PATH", filename)

    if not os.path.exists(filename):
        raise FileNotFoundError(f"Config file not found: {filename}")

    with open(filename, "r", encoding="utf-8") as f:
        return json.load(f)


def create_objects(config: dict, verbose: bool = False, test_mode: bool = False):
    """
    Single-phase object creation from JSON config_loader.

    Features:
      - Lists, dicts, single objects
      - @ references with nested attributes
      - Full-path factory support
      - Skips None parameters
      - Immediate injection (phase 1 only)
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

            # 1️⃣ Check in created objects
            obj = created.get(name)

            # 2️⃣ Try importing as module if not found
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
                    log(f"⚠️ Reference '{value}' unresolved (ignored).")
                    return None
            else:
                rest_parts = parts[1:]

            # 3️⃣ Resolve remaining attributes
            try:
                for attr in rest_parts:
                    if isinstance(obj, dict):
                        obj = obj[attr]
                    else:
                        obj = getattr(obj, attr)
                return obj
            except (KeyError, AttributeError):
                log(f"⚠️ Could not resolve nested reference '{value}' (ignored).")
                return None
        return value

    def instantiate(spec, key_name=None):
        """Instantiate a single object with immediate reference injection."""
        module_name = spec.get("module")
        class_name = spec.get("class")
        factory_name = spec.get("factory")

        raw_params = spec.get("params", {})
        params = {}
        for k, v in raw_params.items():
            resolved = resolve_ref(v)
            if resolved is not None:
                params[k] = resolved
            else:
                log(f"Skipped None param '{k}' for '{key_name}'")

        # Built-in objects
        if module_name == "builtins" and class_name in ("dict", "list"):
            cls = getattr(builtins, class_name)
            obj = cls(**params) if class_name == "dict" else cls(params)
            log(f"Created built-in {class_name} '{key_name}' with params {params}")

        # Enum creation
        elif module_name == "enum" and class_name == "Enum":
            name = params.pop("name", None)
            values = params.pop("values", None)
            if name and values:
                obj = Enum(name, dict(values))
                log(f"Created Enum '{name}' for '{key_name}' with values {values}")
            else:
                raise ValueError(f"Enum '{key_name}' missing name/values")

        # Normal class
        elif class_name:
            module = get_module(module_name)
            cls = getattr(module, class_name)
            if test_mode and "test_mode" in cls.__init__.__code__.co_varnames:
                params["test_mode"] = True
            obj = cls(**params)
            log(f"Created class '{class_name}' for '{key_name}' with params {params}")

        # Factory function (supports full dotted path)
        elif factory_name:
            parts = factory_name.split(".")
            module_path, func_name = ".".join(parts[:-1]), parts[-1]

            module = get_module(module_path)
            factory = getattr(module, func_name)

            if test_mode and "test_mode" in factory.__code__.co_varnames:
                params["test_mode"] = True

            filtered_params = {k: v for k, v in params.items() if v is not None}
            obj = factory(**filtered_params)
            log(f"Created factory '{factory_name}' for '{key_name}' with params {filtered_params}")

        else:
            raise ValueError(f"Spec for '{key_name}' must have 'class' or 'factory'")

        # Inject additional resolved refs after creation (skip for frozen dataclasses)
        try:
            # Check if object is a frozen dataclass
            import dataclasses
            is_frozen_dataclass = dataclasses.is_dataclass(obj) and obj.__dataclass_params__.frozen
        except (AttributeError, TypeError):
            is_frozen_dataclass = False

        if not is_frozen_dataclass:
            # Inject additional resolved refs after creation
            for k, v in raw_params.items():
                resolved = resolve_ref(v)
                if resolved is not None:
                    if isinstance(obj, dict):
                        obj[k] = resolved
                    else:
                        try:
                            setattr(obj, k, resolved)
                            log(f"Injected reference for '{key_name}': {k} -> {resolved}")
                        except (AttributeError, dataclasses.FrozenInstanceError) as e:
                            log(f"⚠️ Skipped injection for '{key_name}.{k}' (frozen/immutable): {e}")
                else:
                    log(f"Skipped injection for '{key_name}.{k}' (None)")

        return obj

    # Instantiate all objects
    for key, spec in config.items():
        if isinstance(spec, list):
            created[key] = [instantiate(s, key_name=f"{key}[{i}]") for i, s in enumerate(spec)]
        elif isinstance(spec, dict) and all(isinstance(v, dict) and ("module" in v or "factory" in v) for v in spec.values()):
            created[key] = {subkey: instantiate(s, key_name=f"{key}.{subkey}") for subkey, s in spec.items()}
        else:
            created[key] = instantiate(spec, key_name=key)

    return created
