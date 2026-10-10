"""Command line entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__, history
from .actions import Actions, find_tool
from .config import CONFIG_PATH, KEY_PATH, ConfigError, load, normalize_input
from .follower import TVUnreachable, connect, run

LABEL = "io.github.kingsleydon.lgtv-follow"
PLIST_PATH = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
LOG_PATH = Path.home() / "Library/Logs/lgtv-follow.log"

EXAMPLE_CONFIG = """\
# lgtv-follow configuration. Docs: https://github.com/kingsleydon/lgtv-follow

[tv]
host = "{host}"

[[rule]]
name = "mac"
input = "HDMI_4"                 # the TV input this Mac is plugged into (or a list / webOS app ids)
display = "{display}"            # BetterDisplay display: connect on enter, disconnect on leave
audio_output = "{display}"       # macOS audio output to select on enter
audio_on_leave = "previous"      # on leave: "previous", "builtin", "none" or a device name
# on_enter = ["say 'Mac on TV'"] # extra shell commands; env: LGTV_RULE, LGTV_EVENT, LGTV_INPUT
# on_leave = []
"""


def cmd_init(args):
    if CONFIG_PATH.exists() and not args.force:
        sys.exit(f"{CONFIG_PATH} already exists (use --force to overwrite)")
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(EXAMPLE_CONFIG.format(host=args.host, display=args.display))
    print(f"Wrote {CONFIG_PATH}\nEdit it, then run `lgtv-follow pair`.")


def cmd_pair(args):
    async def go():
        config = load()
        print(f"Connecting to {config.host} - accept the prompt on the TV if it appears...")
        client = await connect(config.host)
        print(f"Paired. Current input: {client.current_appId}\nKey stored in {KEY_PATH}")
        await client.disconnect()

    asyncio.run(go())


def cmd_inputs(args):
    async def go():
        client = await connect(load().host)
        for d in await client.get_inputs():
            mark = "*" if d["appId"] == client.current_appId else " "
            print(f"{mark} {d['id']:<8} {d['appId']:<24} {d['label']}")
        print(f"\ncurrent: {client.current_appId}")
        await client.disconnect()

    asyncio.run(go())


def _switch(choose):
    """Connect, pick a target from the current input via `choose`, and switch to it."""

    async def go():
        client = await connect(load().host)
        try:
            current = client.current_appId
            target = choose(current)
            if not target:
                sys.exit("no previous input recorded yet - is `lgtv-follow run` running?")
            if target == current:
                print(f"already on {current}")
                return
            history.record(current)
            await client.launch_app(target)
            history.record(target)
            print(f"{current} -> {target}")
        finally:
            await client.disconnect()

    asyncio.run(go())


def cmd_switch(args):
    target = None if args.input == "back" else normalize_input(args.input)
    _switch(lambda current: target or history.previous_of(current))


def cmd_toggle(args):
    home = normalize_input(args.input)
    _switch(lambda current: history.previous_of(current) if current == home else home)


def cmd_check(args):
    config = load()
    print(f"config ok: {len(config.rules)} rule(s), tv {config.host}")
    ok = True
    if any(r.display for r in config.rules):
        ok &= _report_tool("betterdisplaycli", "brew install betterdisplaycli")
    if any(r.audio_output for r in config.rules):
        ok &= _report_tool("SwitchAudioSource", "brew install switchaudio-osx")
    print(f"paired: {'yes' if KEY_PATH.exists() else 'no - run `lgtv-follow pair`'}")
    sys.exit(0 if ok else 1)


def _report_tool(name, hint):
    path = find_tool(name)
    print(f"{name}: {path or f'missing - {hint}'}")
    return bool(path)


def cmd_run(args):
    config = load()
    asyncio.run(run(config, Actions(audio_wait=config.audio_wait, dry_run=args.dry_run)))


def cmd_install(args):
    load()  # fail early on a broken config
    exe = shutil.which("lgtv-follow") or os.path.abspath(sys.argv[0])
    plist = {
        "Label": LABEL,
        "ProgramArguments": [exe, "run"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
        "StandardOutPath": str(LOG_PATH),
        "StandardErrorPath": str(LOG_PATH),
    }
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _bootout()
    with open(PLIST_PATH, "wb") as f:
        plistlib.dump(plist, f)
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(PLIST_PATH)], check=True)
    print(f"Installed LaunchAgent {LABEL}\nLogs: {LOG_PATH}")


def cmd_uninstall(args):
    _bootout()
    PLIST_PATH.unlink(missing_ok=True)
    print("Uninstalled.")


def _bootout():
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="lgtv-follow", description="Make your Mac follow an LG webOS TV's input selection."
    )
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="write an example config")
    s.add_argument("--host", default="192.168.1.50", help="TV IP address")
    s.add_argument("--display", default="LG TV", help="display name as shown in BetterDisplay")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_init)

    sub.add_parser("pair", help="pair with the TV (accept the prompt on screen)").set_defaults(func=cmd_pair)
    sub.add_parser("inputs", help="list TV inputs and the current one").set_defaults(func=cmd_inputs)
    sub.add_parser("check", help="validate config and required tools").set_defaults(func=cmd_check)

    s = sub.add_parser("switch", help="switch the TV to an input, or `back` to the previous one")
    s.add_argument("input", help="HDMI_n, a webOS app id, or `back`")
    s.set_defaults(func=cmd_switch)

    s = sub.add_parser("toggle", help="switch to INPUT, or back to the previous input if already on it")
    s.add_argument("input", help="e.g. HDMI_4 (the Mac's input)")
    s.set_defaults(func=cmd_toggle)

    s = sub.add_parser("run", help="run in the foreground")
    s.add_argument("--dry-run", action="store_true", help="log actions without running them")
    s.set_defaults(func=cmd_run)

    sub.add_parser("install", help="run at login via launchd").set_defaults(func=cmd_install)
    sub.add_parser("uninstall", help="remove the launchd agent").set_defaults(func=cmd_uninstall)

    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    for noisy in ("bscpylgtv", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        args.func(args)
    except ConfigError as e:
        sys.exit(f"config error: {e}")
    except TVUnreachable as e:
        sys.exit(str(e))  # e.g. away from home: one line, exit 1, no traceback
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
