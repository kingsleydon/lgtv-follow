from lgtv_follow import history

H1, H4 = "com.webos.app.hdmi1", "com.webos.app.hdmi4"


def test_record_tracks_previous(tmp_path):
    p = tmp_path / "state.json"
    history.record(H1, p)
    history.record(H4, p)
    assert history.load(p) == {"current": H4, "previous": H1}


def test_record_ignores_standby_and_repeats(tmp_path):
    p = tmp_path / "state.json"
    history.record(H1, p)
    history.record(H4, p)
    history.record(None, p)
    history.record(H4, p)
    assert history.previous_of(H4, p) == H1


def test_previous_of_with_stale_history(tmp_path):
    # Service wasn't running when the TV moved H1 -> netflix; the last known input is the way back.
    p = tmp_path / "state.json"
    history.record(H1, p)
    assert history.previous_of("netflix", p) == H1


def test_previous_of_without_history(tmp_path):
    assert history.previous_of(H4, tmp_path / "missing.json") is None
