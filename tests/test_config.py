import pytest

from lgtv_follow.config import ConfigError, normalize_input, parse

BASE = {"tv": {"host": "10.0.0.2"}}


def config(*rules):
    return parse({**BASE, "rule": list(rules)})


@pytest.mark.parametrize("raw", ["HDMI_4", "hdmi4", "HDMI 4", "hdmi-4"])
def test_normalize_hdmi(raw):
    assert normalize_input(raw) == "com.webos.app.hdmi4"


def test_normalize_passes_app_ids_through():
    assert normalize_input("netflix") == "netflix"


@pytest.mark.parametrize(
    "data, msg",
    [
        ({"rule": [{"input": "HDMI_1", "on_enter": "x"}]}, "host"),
        ({**BASE}, "at least one"),
        ({**BASE, "rule": [{"display": "TV"}]}, "`input` is required"),
        ({**BASE, "rule": [{"input": "HDMI_1"}]}, "does nothing"),
        ({**BASE, "rule": [{"input": "HDMI_1", "dispaly": "TV"}]}, "unknown keys"),
        ({"tv": {"host": " "}, "rule": [{"input": "HDMI_1", "on_enter": "x"}]}, "host"),
        ({**BASE, "rule": [{"input": "HDMI_1", "display": 4}]}, "display must be"),
        ({**BASE, "rule": [{"input": "HDMI_1", "display": "TV", "audio_on_leave": ""}]}, "audio_on_leave"),
        (
            {**BASE, "rule": [{"name": "a", "input": "HDMI_1", "on_enter": "x"}] * 2},
            "duplicate rule name",
        ),
    ],
)
def test_config_errors(data, msg):
    with pytest.raises(ConfigError, match=msg):
        parse(data)
