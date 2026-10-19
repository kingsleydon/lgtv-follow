import time

import pytest

from lgtv_follow.actions import Actions, leave_audio_target, run_command
from lgtv_follow.config import Rule

TV, SPK, PODS = "LG TV", "MacBook Pro Speakers", "AirPods"
ALL = [TV, SPK, PODS]


@pytest.mark.parametrize(
    "policy, current, previous, available, expected",
    [
        ("previous", TV, PODS, ALL, PODS),  # back to what was used before
        ("previous", TV, PODS, [TV, SPK], SPK),  # previous gone -> built-in
        ("previous", TV, None, ALL, SPK),  # nothing recorded -> built-in
        ("previous", TV, TV, ALL, SPK),  # never go "back" to the TV itself
        ("previous", PODS, SPK, ALL, None),  # user picked something else: leave it
        ("builtin", TV, PODS, ALL, SPK),
        ("AirPods", TV, None, ALL, PODS),  # a fixed device
        ("AirPods", TV, None, [TV, SPK], SPK),  # fixed device missing -> built-in
        ("none", TV, PODS, ALL, None),
    ],
)
def test_leave_audio_target(policy, current, previous, available, expected):
    assert leave_audio_target(policy, current, TV, previous, available, SPK) == expected


def test_leave_reads_audio_before_disconnecting_display(monkeypatch):
    # Once the display is gone macOS switches audio itself, which would hide that we were on the TV.
    events = []
    a = Actions()
    monkeypatch.setattr(a, "current_audio_output", lambda: events.append("read") or "LG TV")
    monkeypatch.setattr(a, "set_display", lambda name, on: events.append("display off"))
    monkeypatch.setattr(a, "restore_audio_output", lambda rule, current: events.append(("restore", current)))
    a.leave(Rule(name="mac", inputs=[], display="LG TV", audio_output="LG TV"), None)
    assert events == ["read", "display off", ("restore", "LG TV")]


def test_stuck_command_times_out():
    assert run_command(["sleep", "5"], timeout=0.2) is None


def test_timeout_kills_everything_the_command_started(tmp_path):
    marker = tmp_path / "late"
    assert run_command(f"(sleep 1; touch {marker}) & wait", shell=True, timeout=0.3) is None
    time.sleep(1.5)
    assert not marker.exists()


def test_run_command_returns_output():
    r = run_command(["sh", "-c", "echo out; echo err >&2; exit 3"])
    assert (r.returncode, r.stdout, r.stderr) == (3, "out\n", "err\n")


def test_background_programs_dont_hold_up_the_command():
    start = time.monotonic()
    r = run_command("sleep 3 &", shell=True, timeout=10)
    assert r.returncode == 0 and time.monotonic() - start < 1
