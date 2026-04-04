"""Parse strategies from config_uat.json."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ParsedStrategy:
    """Parsed strategy definition from config."""

    strategy_id: str  # e.g., "rsi_signal_strategy"
    module: str  # e.g., "engine.strategies.rsi_signal_strategy"
    class_name: str  # e.g., "RSISignalStrategy"
    config_module: str
    config_class: str
    config_params: Dict[str, Any]
    symbol: str
    bar_type: str


class ConfigParser:
    """Parse strategy_map section from config, resolving @ references."""

    def __init__(self, config_path: str):
        self.config_path = config_path
        self._config: Dict[str, Any] = {}

    def load(self) -> None:
        """Load config file."""
        with open(self.config_path, "r") as f:
            self._config = json.load(f)

    def _resolve_reference(self, value: Any) -> Any:
        """Resolve @reference values recursively."""
        if isinstance(value, str) and value.startswith("@"):
            ref_path = value[1:]  # Remove @ prefix
            parts = ref_path.split(".")

            # Navigate to the referenced value
            current = self._config
            for i, part in enumerate(parts):
                if isinstance(current, dict):
                    if part in current:
                        current = current[part]
                    elif "params" in current and part in current["params"]:
                        # Try nested params (e.g., default_settings.selected_symbol
                        # when actual path is default_settings.params.selected_symbol)
                        current = current["params"][part]
                    else:
                        # Reference could not be resolved - return original
                        logger.warning(f"Could not resolve reference: {value}")
                        return value
                else:
                    logger.warning(f"Could not resolve reference: {value}")
                    return value

            # Recursively resolve if the result is also a reference
            return self._resolve_reference(current)

        elif isinstance(value, dict):
            return {k: self._resolve_reference(v) for k, v in value.items()}

        elif isinstance(value, list):
            return [self._resolve_reference(item) for item in value]

        return value

    def _extract_symbol_from_params(
        self, params: Dict[str, Any]
    ) -> Optional[str]:
        """Extract symbol from resolved config params."""
        # Look for instrument_id or selected_symbol
        if "instrument_id" in params:
            return params["instrument_id"]
        if "selected_symbol" in params:
            return params["selected_symbol"]
        return None

    def _extract_bar_type_from_params(
        self, params: Dict[str, Any]
    ) -> Optional[str]:
        """Extract bar_type from resolved config params."""
        return params.get("bar_type")

    def parse(self) -> List[ParsedStrategy]:
        """Parse all strategies from strategy_map."""
        if not self._config:
            self.load()

        strategy_map = self._config.get("strategy_map", {})
        if not strategy_map:
            logger.warning("No strategy_map found in config")
            return []

        strategies = []

        for strategy_id, strategy_def in strategy_map.items():
            try:
                parsed = self._parse_single_strategy(strategy_id, strategy_def)
                if parsed:
                    strategies.append(parsed)
            except Exception as e:
                logger.error(f"Failed to parse strategy {strategy_id}: {e}")

        return strategies

    def _parse_single_strategy(
        self, strategy_id: str, strategy_def: Dict[str, Any]
    ) -> Optional[ParsedStrategy]:
        """Parse a single strategy definition."""
        module = strategy_def.get("module")
        class_name = strategy_def.get("class")

        if not module or not class_name:
            logger.warning(
                f"Strategy {strategy_id} missing module or class"
            )
            return None

        params = strategy_def.get("params", {})
        resolved_params = self._resolve_reference(params)

        # The config param should reference a config object
        config_ref = resolved_params.get("config")

        if isinstance(config_ref, dict):
            # Config was resolved to a dictionary that contains module/class/params
            config_module = config_ref.get("module", module)
            config_class = config_ref.get("class", class_name + "Config")

            # The actual config params are in the "params" sub-key
            if "params" in config_ref:
                raw_params = config_ref.get("params", {})
                config_params = self._resolve_reference(raw_params)
            else:
                # If no params key, filter out module/class keys
                config_params = {
                    k: v for k, v in config_ref.items()
                    if k not in ("module", "class", "_module", "_class")
                }
        elif isinstance(config_ref, str) and config_ref.startswith("@"):
            # Config reference not resolved - try to get the raw reference
            ref_name = config_ref[1:]
            config_obj = self._config.get(ref_name, {})
            config_module = config_obj.get("module", module)
            config_class = config_obj.get("class", class_name + "Config")
            raw_params = config_obj.get("params", {})
            config_params = self._resolve_reference(raw_params)
        else:
            # No config - use defaults
            config_module = module
            config_class = class_name + "Config"
            config_params = {}

        # Extract symbol and bar_type from config params
        symbol = self._extract_symbol_from_params(config_params)
        bar_type = self._extract_bar_type_from_params(config_params)

        if not symbol:
            # Try to get default symbol
            default_settings = self._config.get("default_settings", {})
            if isinstance(default_settings, dict):
                resolved_defaults = self._resolve_reference(default_settings)
                if isinstance(resolved_defaults, dict):
                    symbol = resolved_defaults.get("selected_symbol", "ETHUSDT")
                else:
                    symbol = "ETHUSDT"
            else:
                symbol = "ETHUSDT"

        if not bar_type:
            bar_type = f"{symbol}-1h"

        return ParsedStrategy(
            strategy_id=strategy_id,
            module=module,
            class_name=class_name,
            config_module=config_module,
            config_class=config_class,
            config_params=config_params,
            symbol=symbol,
            bar_type=bar_type,
        )

    def get_default_symbol(self) -> str:
        """Get default symbol from config."""
        if not self._config:
            self.load()

        default_settings = self._config.get("default_settings", {})
        if isinstance(default_settings, dict):
            resolved = self._resolve_reference(default_settings)
            if isinstance(resolved, dict):
                return resolved.get("selected_symbol", "ETHUSDT")

        return "ETHUSDT"
