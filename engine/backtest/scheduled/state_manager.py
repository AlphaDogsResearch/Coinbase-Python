"""Position state persistence to JSON files."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import PositionState

logger = logging.getLogger(__name__)


class PositionStateManager:
    """Persist open positions to JSON files per strategy."""

    def __init__(self, state_dir: str):
        self.state_dir = Path(state_dir)
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        """Ensure state directory exists."""
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _state_file_path(self, strategy_id: str) -> Path:
        """Get path to state file for a strategy."""
        return self.state_dir / f"{strategy_id}_position.json"

    def load(self, strategy_id: str, symbol: str) -> PositionState:
        """
        Load position state for a strategy.

        Returns flat position if no state file exists.
        """
        path = self._state_file_path(strategy_id)

        if not path.exists():
            logger.debug(f"No state file for {strategy_id}, returning flat")
            return PositionState.flat(strategy_id, symbol)

        try:
            with open(path, "r") as f:
                data = json.load(f)

            state = PositionState.from_dict(data)
            logger.info(
                f"Loaded position state for {strategy_id}: "
                f"{state.side} {state.quantity} @ {state.entry_price}"
            )
            return state

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to load state for {strategy_id}: {e}")
            return PositionState.flat(strategy_id, symbol)

    def save(self, state: PositionState) -> None:
        """Save position state to JSON file."""
        path = self._state_file_path(state.strategy_id)

        # Update last_updated timestamp
        state.last_updated = datetime.now(timezone.utc)

        try:
            with open(path, "w") as f:
                json.dump(state.to_dict(), f, indent=2)

            logger.info(
                f"Saved position state for {state.strategy_id}: "
                f"{state.side} {state.quantity} @ {state.entry_price}"
            )

        except (OSError, IOError) as e:
            logger.error(f"Failed to save state for {state.strategy_id}: {e}")

    def delete(self, strategy_id: str) -> None:
        """Delete position state file."""
        path = self._state_file_path(strategy_id)

        if path.exists():
            try:
                os.remove(path)
                logger.info(f"Deleted position state for {strategy_id}")
            except OSError as e:
                logger.error(f"Failed to delete state for {strategy_id}: {e}")

    def list_strategies(self) -> list[str]:
        """List all strategies with saved state."""
        strategies = []

        if not self.state_dir.exists():
            return strategies

        for path in self.state_dir.glob("*_position.json"):
            strategy_id = path.stem.replace("_position", "")
            strategies.append(strategy_id)

        return strategies

    def load_all(self, symbol: str) -> dict[str, PositionState]:
        """Load all position states."""
        states = {}

        for strategy_id in self.list_strategies():
            states[strategy_id] = self.load(strategy_id, symbol)

        return states
