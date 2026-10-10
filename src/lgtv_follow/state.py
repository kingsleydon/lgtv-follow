"""Small JSON state files under ~/.local/state/lgtv-follow, written atomically."""

import json
import os
from pathlib import Path


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: dict) -> None:
    # Write-then-rename so a crash or a concurrent reader never sees a half-written file.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)
