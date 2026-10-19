"""Remembers the current and previous TV input, so `switch back` / `toggle` work
no matter how the input was changed (remote, CEC, a console waking the TV...)."""

from pathlib import Path

from .config import STATE_PATH
from .state import read_json, write_json


class History:
    def __init__(self, path: Path = STATE_PATH):
        self.path = path

    def record(self, app_id: str | None):
        """Record `app_id` as the current input. Standby (None) and repeats are ignored."""
        current = read_json(self.path).get("current")
        if app_id and app_id != current:
            write_json(self.path, {"current": app_id, "previous": current})

    def previous_of(self, current: str | None) -> str | None:
        """The input to go back to from `current`."""
        state = read_json(self.path)
        if current and state.get("current") != current:
            # Stale (the service wasn't running): what we knew as current is the way back.
            return state.get("current")
        return state.get("previous")
