import pytest

from lgtv_follow.config import ConfigError, normalize_input, parse
from lgtv_follow.follower import Follower

BASE = {"tv": {"host": "10.0.0.2"}}


def config(*rules):
    return parse({**BASE, "rule": list(rules)})


class Recorder:
    def __init__(self):
        self.calls = []

    def enter(self, rule, app_id):
        self.calls.append(("enter", rule.name, app_id))

    def leave(self, rule, app_id):
        self.calls.append(("leave", rule.name, app_id))


@pytest.mark.parametrize("raw", ["HDMI_4", "hdmi4", "HDMI 4", "hdmi-4"])
def test_normalize_hdmi(raw):
    assert normalize_input(raw) == "com.webos.app.hdmi4"


def test_normalize_passes_app_ids_through():
    assert normalize_input("netflix") == "netflix"


def test_first_observation_syncs_state():
    rec = Recorder()
    f = Follower(config({"name": "mac", "input": "HDMI_4", "display": "TV"}), rec)
    f.update("com.webos.app.hdmi1")
    assert rec.calls == [("leave", "mac", "com.webos.app.hdmi1")]


def test_enter_and_leave_fire_once_per_change():
    rec = Recorder()
    f = Follower(config({"name": "mac", "input": "HDMI_4", "display": "TV"}), rec)
    for app in ["com.webos.app.hdmi4", "com.webos.app.hdmi4", "netflix", "youtube.leanback.v4", None]:
        f.update(app)
    assert rec.calls == [("enter", "mac", "com.webos.app.hdmi4"), ("leave", "mac", "netflix")]


def test_leave_runs_before_enter():
    rec = Recorder()
    f = Follower(
        config(
            {"name": "a", "input": "HDMI_1", "on_enter": "true"},
            {"name": "b", "input": "HDMI_2", "on_enter": "true"},
        ),
        rec,
    )
    f.update("com.webos.app.hdmi1")
    rec.calls.clear()
    f.update("com.webos.app.hdmi2")
    assert rec.calls == [("leave", "a", "com.webos.app.hdmi2"), ("enter", "b", "com.webos.app.hdmi2")]


def test_failing_action_does_not_stop_other_rules():
    class Boom(Recorder):
        def enter(self, rule, app_id):
            if rule.name == "a":
                raise RuntimeError("boom")
            super().enter(rule, app_id)

    rec = Boom()
    f = Follower(
        config(
            {"name": "a", "input": "HDMI_1", "on_enter": "x"},
            {"name": "b", "input": "HDMI_1", "on_enter": "y"},
        ),
        rec,
    )
    f.update("com.webos.app.hdmi1")
    assert ("enter", "b", "com.webos.app.hdmi1") in rec.calls


@pytest.mark.parametrize(
    "data, msg",
    [
        ({"rule": [{"input": "HDMI_1", "on_enter": "x"}]}, "host"),
        ({**BASE}, "at least one"),
        ({**BASE, "rule": [{"display": "TV"}]}, "`input` is required"),
        ({**BASE, "rule": [{"input": "HDMI_1"}]}, "does nothing"),
        ({**BASE, "rule": [{"input": "HDMI_1", "dispaly": "TV"}]}, "unknown keys"),
    ],
)
def test_config_errors(data, msg):
    with pytest.raises(ConfigError, match=msg):
        parse(data)
