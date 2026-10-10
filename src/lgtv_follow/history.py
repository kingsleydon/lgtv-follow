"""Remembers the current and previous TV input, so `switch back` / `toggle` work
no matter how the input was changed (remote, CEC, a console waking the TV...)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from .config import STATE_PATH


def load(path: Path = STATE_PATH) -> dict:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def record(app_id: Optional[str], path: Path = STATE_PATH) -> dict:
    """Record `app_id` as the current input. Standby (None) and repeats are ignored."""
    state = load(path)
    if not app_id or app_id == state.get("current"):
        return state
    state = {"current": app_id, "previous": state.get("current")}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    os.replace(tmp, path)
    return state


def previous_of(current: Optional[str], path: Path = STATE_PATH) -> Optional[str]:
    """The input to go back to from `current`."""
    state = load(path)
    if current and state.get("current") != current:
        # The history is stale (the service wasn't running); what we knew as current is the way back.
        return state.get("current")
    return state.get("previous")
