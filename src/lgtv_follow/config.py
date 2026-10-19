"""Configuration loading and validation."""

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

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
    inputs: list[str]
    display: str | None = None
    audio_output: str | None = None
    audio_on_leave: str = "previous"  # "previous", "builtin", "none", or a device name
    on_enter: list[str] = field(default_factory=list)
    on_leave: list[str] = field(default_factory=list)

    def matches(self, app_id: str | None) -> bool:
        return app_id in self.inputs


@dataclass
class Config:
    host: str
    rules: list[Rule]
    audio_wait: float = 10.0


def _str_list(value, where: str) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return value
    raise ConfigError(f"{where} must be a string or a list of strings")


def _opt_str(r: dict, key: str, name: str) -> str | None:
    value = r.get(key)
    if value is not None and not (isinstance(value, str) and value.strip()):
        raise ConfigError(f"{name}.{key} must be a non-empty string")
    return value


def parse(data: dict) -> Config:
    tv = data.get("tv")
    if not isinstance(tv, dict) or not isinstance(tv.get("host"), str) or not tv["host"].strip():
        raise ConfigError("[tv] host is required")

    raw_rules = data.get("rule")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ConfigError("at least one [[rule]] is required")

    known = {"name", "input", "display", "audio_output", "audio_on_leave", "on_enter", "on_leave"}
    rules = []
    for i, r in enumerate(raw_rules, 1):
        if not isinstance(r, dict):
            raise ConfigError(f"rule {i} must be a table")
        name = r.get("name", f"rule {i}")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"rule {i}: name must be a non-empty string")
        if any(other.name == name for other in rules):
            raise ConfigError(f"{name}: duplicate rule name")
        unknown = set(r) - known
        if unknown:
            raise ConfigError(f"{name}: unknown keys {sorted(unknown)}")
        if "input" not in r:
            raise ConfigError(f"{name}: `input` is required")
        rule = Rule(
            name=name,
            inputs=[normalize_input(v) for v in _str_list(r["input"], f"{name}.input")],
            display=_opt_str(r, "display", name),
            audio_output=_opt_str(r, "audio_output", name),
            audio_on_leave=_opt_str(r, "audio_on_leave", name) or "previous",
            on_enter=_str_list(r.get("on_enter", []), f"{name}.on_enter"),
            on_leave=_str_list(r.get("on_leave", []), f"{name}.on_leave"),
        )
        if not (rule.display or rule.audio_output or rule.on_enter or rule.on_leave):
            raise ConfigError(f"{name}: does nothing; set display, audio_output, on_enter or on_leave")
        rules.append(rule)

    return Config(host=tv["host"].strip(), rules=rules, audio_wait=_audio_wait(data.get("audio", {})))


def _audio_wait(audio) -> float:
    if not isinstance(audio, dict):
        raise ConfigError("[audio] must be a table")
    try:
        return float(audio.get("wait_seconds", 10))
    except (TypeError, ValueError):
        raise ConfigError("[audio] wait_seconds must be a number") from None


def load(path: Path = CONFIG_PATH) -> Config:
    try:
        with open(path, "rb") as f:
            return parse(tomllib.load(f))
    except FileNotFoundError:
        raise ConfigError(f"no config at {path}; run `lgtv-follow init` first") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from None
