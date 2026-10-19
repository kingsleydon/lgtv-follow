"""What happens on the Mac when a rule enters (its input is selected) or leaves."""

import json
import logging
import os
import time
from pathlib import Path

from .commands import HOOK_TIMEOUT, Runner
from .config import STATE_PATH, Rule
from .state import read_json, write_json

log = logging.getLogger(__name__)
AUDIO_STATE_PATH = STATE_PATH.parent / "audio.json"  # output in use before each rule entered
BUILTIN_UID = "BuiltInSpeakerDevice"


class Actions:
    def __init__(self, audio_wait: float = 10.0, dry_run: bool = False, audio_state: Path = AUDIO_STATE_PATH):
        runner = Runner(dry_run)
        self.display = Display(runner)
        self.audio = Audio(runner, audio_wait, audio_state)
        self.hooks = Hooks(runner)

    def enter(self, rule: Rule, app_id: str | None):
        log.info("enter %s (%s)", rule.name, app_id)
        attached = self.display.set(rule.display, True) if rule.display else True
        # No point waiting for the TV's audio device if its display isn't plugged into this Mac.
        if rule.audio_output and attached:
            self.audio.enter(rule)
        self.hooks.run(rule.on_enter, rule, "enter", app_id)

    def leave(self, rule: Rule, app_id: str | None):
        log.info("leave %s (now %s)", rule.name, app_id)
        self.hooks.run(rule.on_leave, rule, "leave", app_id)
        # Read the output before disconnecting the display: once the TV's audio device goes away,
        # macOS picks another output itself and it would look like the user had switched away.
        current = self.audio.current() if rule.audio_output else None
        if rule.display:
            self.display.set(rule.display, False)
        if rule.audio_output:
            self.audio.leave(rule, current)


class Display:
    """BetterDisplay's virtual connect/disconnect, through betterdisplaycli."""

    def __init__(self, runner: Runner):
        self.runner = runner

    def set(self, name: str, connected: bool) -> bool:
        """False if the display isn't attached to this Mac (e.g. the cable is unplugged)."""
        tool = self.runner.tool("betterdisplaycli")
        state = "on" if connected else "off"
        current = self.runner.query([tool, "get", f"--name={name}", "--connected"]).strip()
        if current not in ("on", "off"):
            log.info("display %r not attached to this Mac, skipping", name)
            return False
        if current == state:
            log.info("display %r already %s", name, "connected" if connected else "disconnected")
        else:
            self.runner.change([tool, "set", f"--name={name}", f"--connected={state}"])
        return True


class Audio:
    """The macOS audio output, through SwitchAudioSource. Remembers the output in use before each
    rule entered, to go back to it on leave."""

    def __init__(self, runner: Runner, wait: float, state_path: Path):
        self.runner = runner
        self.wait = wait
        self.state_path = state_path

    def current(self) -> str | None:
        devices = self._devices("-c")
        return devices[0]["name"] if devices else None

    def enter(self, rule: Rule):
        current = self.current()
        if current and current != rule.audio_output and not self.runner.dry_run:
            write_json(self.state_path, {**read_json(self.state_path), rule.name: current})
        # The HDMI audio device shows up a moment after the display connects.
        deadline = time.monotonic() + self.wait
        while not self.runner.dry_run and not any(
            d["name"] == rule.audio_output for d in self._devices("-a")
        ):
            if time.monotonic() > deadline:
                log.info("audio output %r not available, skipping", rule.audio_output)
                return
            time.sleep(0.5)
        self._switch(rule.audio_output)

    def leave(self, rule: Rule, current: str | None):
        """`current` is the output in use before the display went away."""
        devices = self._devices("-a")
        target = leave_audio_target(
            policy=rule.audio_on_leave,
            current=current,
            tv_output=rule.audio_output,
            previous=read_json(self.state_path).get(rule.name),
            available=[d["name"] for d in devices],
            builtin=next((d["name"] for d in devices if d.get("uid") == BUILTIN_UID), None),
        )
        if target:
            self._switch(target)

    def _switch(self, name: str):
        self.runner.change([self.runner.tool("SwitchAudioSource"), "-t", "output", "-s", name])

    def _devices(self, *args) -> list[dict]:
        output = self.runner.query(
            [self.runner.tool("SwitchAudioSource"), "-t", "output", "-f", "json", *args]
        )
        devices = []
        for line in output.splitlines():
            try:
                device = json.loads(line)
            except ValueError:
                continue
            if isinstance(device, dict) and "name" in device:
                devices.append(device)
        return devices


class Hooks:
    """The rule's shell commands, with LGTV_RULE, LGTV_EVENT and LGTV_INPUT set."""

    def __init__(self, runner: Runner):
        self.runner = runner

    def run(self, commands: list[str], rule: Rule, event: str, app_id: str | None):
        env = dict(os.environ, LGTV_RULE=rule.name, LGTV_EVENT=event, LGTV_INPUT=app_id or "")
        for command in commands:
            self.runner.change(command, env=env, shell=True, timeout=HOOK_TIMEOUT)


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
