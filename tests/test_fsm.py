"""The decision state machine, driven by event traces."""

from lgtv_follow import fsm
from lgtv_follow.config import parse
from lgtv_follow.fsm import App, NewSession, Power

HDMI1, HDMI2, HDMI4 = "com.webos.app.hdmi1", "com.webos.app.hdmi2", "com.webos.app.hdmi4"


def rules(*specs):
    return parse({"tv": {"host": "tv"}, "rule": [{"on_enter": "x", **s} for s in specs]}).rules


MAC = rules({"name": "mac", "input": "HDMI_4"})


def feed(events, rules=MAC, state=None):
    """Run events through the machine; returns the final state and its decisions as
    (input, [(rule name, enter?)...]) pairs."""
    state = state or fsm.State()
    decisions = []
    for event in events:
        state, decision = fsm.step(state, event, rules)
        if decision:
            decisions.append((decision.input, [(r.name, enter) for r, enter in decision.changes]))
    return state, decisions


def on(session=1, app=HDMI4):
    """A session that just reported the TV on, showing `app`."""
    return [NewSession(session), Power(session, True), App(session, app)]


def test_first_input_syncs_every_rule():
    _, decisions = feed(on(app=HDMI1))
    assert decisions == [(HDMI1, [("mac", False)])]


def test_enter_and_leave_once_per_change():
    apps = [App(1, a) for a in [HDMI4, "netflix", "youtube.leanback.v4"]]
    _, decisions = feed([*on(), *apps, Power(1, False)])
    assert decisions == [
        (HDMI4, [("mac", True)]),
        ("netflix", [("mac", False)]),
        ("youtube.leanback.v4", []),  # still decided (and recorded in history), nothing to do
        (None, []),
    ]


def test_leaves_run_before_enters_in_config_order():
    four = rules(
        {"name": "a", "input": "HDMI_1"},
        {"name": "b", "input": "HDMI_2"},
        {"name": "c", "input": ["HDMI_1", "HDMI_2"]},
        {"name": "d", "input": "HDMI_1"},
    )
    _, decisions = feed([*on(app=HDMI1), App(1, HDMI2)], four)
    assert decisions[1] == (HDMI2, [("a", False), ("d", False), ("b", True)])


def test_nothing_is_decided_until_power_is_known():
    # A TV in standby still reports its last app; that alone must not count as being on it.
    _, decisions = feed([NewSession(1), App(1, HDMI4)])
    assert decisions == []


def test_standby_then_wake_uses_the_app_reported_before():
    _, decisions = feed([NewSession(1), App(1, HDMI4), Power(1, False), Power(1, True)])
    assert decisions == [(None, [("mac", False)]), (HDMI4, [("mac", True)])]


def test_no_app_is_unknown_not_off():
    _, decisions = feed([*on(), App(1, ""), App(1, HDMI4)])
    assert decisions == [(HDMI4, [("mac", True)])]


def test_reconnecting_to_the_same_input_does_nothing():
    _, decisions = feed([*on(1), *on(2)])
    assert decisions == [(HDMI4, [("mac", True)])]


def test_a_new_session_starts_unknown():
    state, _ = feed(on(1))
    # Session 2 hasn't reported power yet, so its app alone decides nothing.
    _, decisions = feed([NewSession(2), App(2, HDMI1)], state=state)
    assert decisions == []


def test_a_dropped_sessions_last_report_counts_until_a_new_session():
    state, _ = feed(on(1))
    state, decisions = feed([Power(1, False)], state=state)  # arrives after the connection died
    assert decisions == [(None, [("mac", False)])]
    state, _ = feed([NewSession(2)], state=state)
    assert fsm.step(state, Power(1, True), MAC) == (state, None)
    assert fsm.step(state, App(1, HDMI1), MAC) == (state, None)


def test_every_change_is_acted_on_in_order():
    # Nothing is merged: hooks are observable, so a quick enter-leave-enter runs in full.
    _, decisions = feed([*on(), App(1, HDMI1), App(1, HDMI4)])
    assert [changes for _, changes in decisions] == [[("mac", True)], [("mac", False)], [("mac", True)]]
