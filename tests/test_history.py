from lgtv_follow.history import History
from lgtv_follow.state import read_json

H1, H4 = "com.webos.app.hdmi1", "com.webos.app.hdmi4"


def test_record_tracks_previous(tmp_path):
    h = History(tmp_path / "state.json")
    h.record(H1)
    h.record(H4)
    assert read_json(h.path) == {"current": H4, "previous": H1}


def test_record_ignores_standby_and_repeats(tmp_path):
    h = History(tmp_path / "state.json")
    for app in [H1, H4, None, H4]:
        h.record(app)
    assert h.previous_of(H4) == H1


def test_previous_of_with_stale_history(tmp_path):
    # Service wasn't running when the TV moved H1 -> netflix; the last known input is the way back.
    h = History(tmp_path / "state.json")
    h.record(H1)
    assert h.previous_of("netflix") == H1


def test_previous_of_without_history(tmp_path):
    assert History(tmp_path / "missing.json").previous_of(H4) is None
