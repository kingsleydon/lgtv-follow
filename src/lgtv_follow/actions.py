"""Side effects run when a rule's input becomes active or inactive."""

import json
import logging
import os
import shutil
import subprocess
import time

from .config import STATE_PATH, Rule
from .state import read_json, write_json

log = logging.getLogger(__name__)

BUILTIN_UID = "BuiltInSpeakerDevice"
AUDIO_STATE_PATH = STATE_PATH.parent / "audio.json"  # output in use before each rule entered


def find_tool(name: str) -> str | None:
    # launchd starts agents with a minimal PATH, so also look in Homebrew's prefixes.
    return shutil.which(name) or next(
        (p for p in (f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}") if os.access(p, os.X_OK)),
        None,
    )


class Actions:
    def __init__(self, audio_wait: float = 10.0, dry_run: bool = False):
        self.audio_wait = audio_wait
        self.dry_run = dry_run

    def _run(self, args, env=None, shell=False):
        log.info("%s %s", "[dry-run]" if self.dry_run else "run:", args if shell else " ".join(args))
        if self.dry_run:
            return None
        r = subprocess.run(args, shell=shell, env=env, capture_output=True, text=True)
        if r.returncode != 0:
            log.warning("exit %d: %s", r.returncode, (r.stderr or r.stdout).strip())
        return r

    def _tool(self, name: str) -> str:
        path = find_tool(name)
        if not path:
            raise RuntimeError(f"{name} not found on PATH")
        return path

    def set_display(self, name: str, connected: bool) -> bool:
        """Returns False if the display isn't attached to this Mac (e.g. the cable is unplugged)."""
        tool = self._tool("betterdisplaycli")
        state = "on" if connected else "off"
        r = subprocess.run([tool, "get", f"--name={name}", "--connected"], capture_output=True, text=True)
        current = r.stdout.strip()
        if current not in ("on", "off"):
            log.info("display %r not attached to this Mac, skipping", name)
            return False
        if current == state:
            log.info("display %r already %s", name, "connected" if connected else "disconnected")
        else:
            self._run([tool, "set", f"--name={name}", f"--connected={state}"])
        return True

    def _audio(self, *args) -> list[dict]:
        r = subprocess.run(
            [self._tool("SwitchAudioSource"), "-t", "output", "-f", "json", *args],
            capture_output=True,
            text=True,
        )
        return [json.loads(line) for line in r.stdout.splitlines() if line.strip()]

    def current_audio_output(self) -> str | None:
        devices = self._audio("-c")
        return devices[0]["name"] if devices else None

    def set_audio_output(self, name: str):
        # The HDMI audio device shows up a moment after the display connects.
        deadline = time.monotonic() + self.audio_wait
        while not self.dry_run:
            if any(d["name"] == name for d in self._audio("-a")):
                break
            if time.monotonic() > deadline:
                log.info("audio output %r not available, skipping", name)
                return
            time.sleep(0.5)
        self._run([self._tool("SwitchAudioSource"), "-t", "output", "-s", name])

    def restore_audio_output(self, rule: Rule):
        devices = self._audio("-a")
        target = leave_audio_target(
            policy=rule.audio_on_leave,
            current=self.current_audio_output(),
            tv_output=rule.audio_output,
            previous=_load_audio_state().get(rule.name),
            available=[d["name"] for d in devices],
            builtin=next((d["name"] for d in devices if d.get("uid") == BUILTIN_UID), None),
        )
        if target:
            self._run([self._tool("SwitchAudioSource"), "-t", "output", "-s", target])

    def _hooks(self, commands, rule: Rule, event: str, app_id: str | None):
        env = dict(os.environ, LGTV_RULE=rule.name, LGTV_EVENT=event, LGTV_INPUT=app_id or "")
        for cmd in commands:
            self._run(cmd, env=env, shell=True)

    def enter(self, rule: Rule, app_id: str | None):
        log.info("enter %s (%s)", rule.name, app_id)
        attached = self.set_display(rule.display, True) if rule.display else True
        # No point waiting for the TV's audio device if its display isn't plugged into this Mac.
        if rule.audio_output and attached:
            current = self.current_audio_output()
            if current and current != rule.audio_output and not self.dry_run:
                _save_audio_state(rule.name, current)
            self.set_audio_output(rule.audio_output)
        self._hooks(rule.on_enter, rule, "enter", app_id)

    def leave(self, rule: Rule, app_id: str | None):
        log.info("leave %s (now %s)", rule.name, app_id)
        self._hooks(rule.on_leave, rule, "leave", app_id)
        if rule.display:
            self.set_display(rule.display, False)
        if rule.audio_output:
            self.restore_audio_output(rule)


def leave_audio_target(
    policy: str,
    current: str | None,
    tv_output: str | None,
    previous: str | None,
    available: list[str],
    builtin: str | None,
) -> str | None:
    """Which output to switch to when leaving a rule, or None to leave audio alone."""
    if policy == "none" or current != tv_output:
        return None  # disabled, or the user already picked something else
    if policy == "previous":
        wanted = previous
    elif policy == "builtin":
        wanted = builtin
    else:
        wanted = policy  # a specific device name
    if wanted in available and wanted != tv_output:
        return wanted
    return builtin if builtin in available else None


def _load_audio_state() -> dict:
    return read_json(AUDIO_STATE_PATH)


def _save_audio_state(rule_name: str, output: str):
    write_json(AUDIO_STATE_PATH, {**_load_audio_state(), rule_name: output})
