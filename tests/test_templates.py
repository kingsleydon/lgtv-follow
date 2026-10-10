import tomllib
from pathlib import Path

import pytest

from lgtv_follow.cli import EXAMPLE_CONFIG
from lgtv_follow.config import ConfigError, parse

ROOT = Path(__file__).parent.parent


def test_init_template_parses():
    text = EXAMPLE_CONFIG.format(host="10.0.0.2", display="LG TV", input="HDMI_2")
    config = parse(tomllib.loads(text))
    assert config.host == "10.0.0.2"
    assert config.rules[0].inputs == ["com.webos.app.hdmi2"]
    assert config.rules[0].audio_on_leave == "previous"


def test_example_config_parses():
    config = parse(tomllib.loads((ROOT / "examples/config.toml").read_text()))
    assert [r.name for r in config.rules] == ["mac", "console"]


@pytest.mark.parametrize("audio", ["x", {"wait_seconds": "soon"}])
def test_bad_audio_table(audio):
    with pytest.raises(ConfigError, match=r"\[audio\]"):
        parse({"tv": {"host": "h"}, "audio": audio, "rule": [{"input": "HDMI_1", "on_enter": "x"}]})
