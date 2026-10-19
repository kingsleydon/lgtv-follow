"""Running `lgtv-follow run` at login, as a launchd LaunchAgent."""

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

LABEL = "io.github.kingsleydon.lgtv-follow"
PLIST_PATH = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
LOG_PATH = Path.home() / "Library/Logs/lgtv-follow.log"


def install():
    exe = shutil.which("lgtv-follow") or os.path.abspath(sys.argv[0])
    plist = {
        "Label": LABEL,
        "ProgramArguments": [exe, "run"],
        "RunAtLoad": True,
        "KeepAlive": True,  # also restarts it after the watchdog gives up on a wedged process
        "ProcessType": "Background",
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
        "StandardOutPath": str(LOG_PATH),
        "StandardErrorPath": str(LOG_PATH),
    }
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    uninstall()
    with open(PLIST_PATH, "wb") as f:
        plistlib.dump(plist, f)
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(PLIST_PATH)], check=True)


def uninstall():
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
    PLIST_PATH.unlink(missing_ok=True)
