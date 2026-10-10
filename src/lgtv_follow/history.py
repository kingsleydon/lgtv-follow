"""Remembers the current and previous TV input, so `switch back` / `toggle` work
no matter how the input was changed (remote, CEC, a console waking the TV...)."""

from pathlib import Path

from .config import STATE_PATH
from .state import read_json, write_json


def load(path: Path = STATE_PATH) -> dict:
    return read_json(path)


def record(app_id: str | None, path: Path = STATE_PATH) -> dict:
    """Record `app_id` as the current input. Standby (None) and repeats are ignored."""
    state = load(path)
    if not app_id or app_id == state.get("current"):
        return state
    state = {"current": app_id, "previous": state.get("current")}
    write_json(path, state)
    return state


def previous_of(current: str | None, path: Path = STATE_PATH) -> str | None:
    """The input to go back to from `current`."""
    state = load(path)
    if current and state.get("current") != current:
        # The history is stale (the service wasn't running); what we knew as current is the way back.
        return state.get("current")
    return state.get("previous")
