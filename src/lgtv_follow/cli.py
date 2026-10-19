"""Command line entry point."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from . import __version__, daemon, launchd, tv
from .actions import Actions
from .commands import find_tool
from .config import CONFIG_PATH, KEY_PATH, ConfigError, load, normalize_input
from .history import History
from .keys import KeyStore

EXAMPLE_CONFIG = """\
# lgtv-follow configuration. Docs: https://github.com/kingsleydon/lgtv-follow

[tv]
host = "{host}"

[[rule]]
name = "mac"
# The TV input this Mac is plugged into (HDMI_n, a webOS app id, or a list of them).
input = "{input}"
# BetterDisplay display to connect on enter and disconnect on leave.
display = "{display}"
# macOS audio output to select on enter.
audio_output = "{display}"
# On leave: "previous" (the output used before), "builtin", "none", or a device name.
audio_on_leave = "previous"
# Extra shell commands; they get LGTV_RULE, LGTV_EVENT and LGTV_INPUT in the environment.
# on_enter = ["say 'Mac on TV'"]
# on_leave = []
"""


def with_tv(use):
    """Connect, return `await use(tv)`, disconnect. Every step gives up after a few seconds: a hotkey
    must never hang on a TV that stopped answering."""

    async def go():
        host = load().host
        client = await tv.connect(host, KeyStore().get(host))
        try:
            return await use(client)
        finally:
            await client.close()

    return asyncio.run(go())


def cmd_init(args):
    if CONFIG_PATH.exists() and not args.force:
        sys.exit(f"{CONFIG_PATH} already exists (use --force to overwrite)")
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(EXAMPLE_CONFIG.format(host=args.host, display=args.display, input=args.input))
    print(f"Wrote {CONFIG_PATH}\nEdit it, then run `lgtv-follow pair`.")


def cmd_pair(args):
    host = load().host
    print(f"Connecting to {host} - accept the prompt on the TV if it appears...")

    async def go():
        client, key = await tv.pair(host)
        KeyStore().set(host, key)
        try:
            return await client.current_app()
        finally:
            await client.close()

    current = asyncio.run(go())
    print(f"Paired. Current input: {current}\nKey stored in {KEY_PATH}")


def cmd_inputs(args):
    async def get(client):
        return await client.current_app(), await client.inputs()

    current, inputs = with_tv(get)
    for d in inputs:
        mark = "*" if d["appId"] == current else " "
        print(f"{mark} {d['id']:<8} {d['appId']:<24} {d['label']}")
    print(f"\ncurrent: {current}")


def switch(choose):
    """Switch the TV to `choose(current input, history)`."""
    history = History()

    async def go(client):
        current = await client.current_app()
        target = choose(current, history)
        if not target:
            sys.exit("no previous input recorded yet - is `lgtv-follow run` running?")
        if target == current:
            return f"already on {current}"
        history.record(current)
        await client.launch(target)
        history.record(target)
        return f"{current} -> {target}"

    print(with_tv(go))


def cmd_switch(args):
    target = None if args.input == "back" else normalize_input(args.input)
    switch(lambda current, history: target or history.previous_of(current))


def cmd_toggle(args):
    home = normalize_input(args.input)
    switch(lambda current, history: history.previous_of(current) if current == home else home)


def cmd_check(args):
    config = load()
    print(f"config ok: {len(config.rules)} rule(s), tv {config.host}")
    ok = True
    if any(r.display for r in config.rules):
        ok &= _report_tool("betterdisplaycli", "brew install betterdisplaycli")
    if any(r.audio_output for r in config.rules):
        ok &= _report_tool("SwitchAudioSource", "brew install switchaudio-osx")
    paired = KeyStore().get(config.host) is not None
    print(f"paired with {config.host}: {'yes' if paired else 'no - run `lgtv-follow pair`'}")
    sys.exit(0 if ok and paired else 1)


def _report_tool(name, hint):
    path = find_tool(name)
    print(f"{name}: {path or f'missing - {hint}'}")
    return bool(path)


def cmd_run(args):
    config = load()
    # Shows at a glance which copy is running, e.g. a stale non-editable install.
    logging.info("lgtv-follow %s starting (%s)", __version__, Path(__file__).parent)
    asyncio.run(daemon.run(config, Actions(audio_wait=config.audio_wait, dry_run=args.dry_run)))


def cmd_install(args):
    load()  # fail early on a broken config
    launchd.install()
    print(f"Installed LaunchAgent {launchd.LABEL}\nLogs: {launchd.LOG_PATH}")


def cmd_uninstall(args):
    launchd.uninstall()
    print("Uninstalled.")


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
    s.add_argument("--input", default="HDMI_4", help="TV input this Mac is plugged into")
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
    logging.getLogger("websockets").setLevel(logging.WARNING)
    try:
        args.func(args)
    except ConfigError as e:
        sys.exit(f"config error: {e}")
    except (tv.TVUnreachable, tv.NotPaired) as e:
        sys.exit(str(e))  # e.g. away from home: one line, exit 1, no traceback
    except (TimeoutError, ConnectionError):
        sys.exit("the TV stopped responding")
    except tv.TVError as e:
        sys.exit(f"the TV refused: {e}")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
