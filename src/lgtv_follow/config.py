"""Configuration loading and validation."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "lgtv-follow"
CONFIG_PATH = CONFIG_DIR / "config.toml"
KEY_PATH = CONFIG_DIR / "tv-key.sqlite"
STATE_PATH = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "lgtv-follow/state.json"


class ConfigError(Exception):
    pass


def normalize_input(value: str) -> str:
    """Accept `HDMI_4`, `hdmi4`, `HDMI 4` or any webOS app id (e.g. `netflix`)."""
    m = re.fullmatch(r"hdmi[ _-]?(\d+)", value.strip(), re.IGNORECASE)
    return f"com.webos.app.hdmi{m.group(1)}" if m else value.strip()


@dataclass
class Rule:
    name: str
    inputs: List[str]
    display: Optional[str] = None
    audio_output: Optional[str] = None
    audio_on_leave: str = "previous"  # "previous", "builtin", "none", or a device name
    on_enter: List[str] = field(default_factory=list)
    on_leave: List[str] = field(default_factory=list)

    def matches(self, app_id: Optional[str]) -> bool:
        return app_id in self.inputs


@dataclass
class Config:
    host: str
    rules: List[Rule]
    audio_wait: float = 10.0


def _str_list(value, where: str) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return value
    raise ConfigError(f"{where} must be a string or a list of strings")


def parse(data: dict) -> Config:
    tv = data.get("tv")
    if not isinstance(tv, dict) or not isinstance(tv.get("host"), str):
        raise ConfigError("[tv] host is required")

    raw_rules = data.get("rule")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ConfigError("at least one [[rule]] is required")

    known = {"name", "input", "display", "audio_output", "audio_on_leave", "on_enter", "on_leave"}
    rules = []
    for i, r in enumerate(raw_rules, 1):
        name = r.get("name", f"rule {i}")
        unknown = set(r) - known
        if unknown:
            raise ConfigError(f"{name}: unknown keys {sorted(unknown)}")
        if "input" not in r:
            raise ConfigError(f"{name}: `input` is required")
        rule = Rule(
            name=name,
            inputs=[normalize_input(v) for v in _str_list(r["input"], f"{name}.input")],
            display=r.get("display"),
            audio_output=r.get("audio_output"),
            audio_on_leave=r.get("audio_on_leave", "previous"),
            on_enter=_str_list(r.get("on_enter", []), f"{name}.on_enter"),
            on_leave=_str_list(r.get("on_leave", []), f"{name}.on_leave"),
        )
        if not (rule.display or rule.audio_output or rule.on_enter or rule.on_leave):
            raise ConfigError(f"{name}: does nothing; set display, audio_output, on_enter or on_leave")
        rules.append(rule)

    return Config(
        host=tv["host"], rules=rules, audio_wait=float(data.get("audio", {}).get("wait_seconds", 10))
    )


def load(path: Path = CONFIG_PATH) -> Config:
    try:
        with open(path, "rb") as f:
            return parse(tomllib.load(f))
    except FileNotFoundError:
        raise ConfigError(f"no config at {path}; run `lgtv-follow init` first") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from None
