"""What to do on the Mac, decided from what the TV reports. Pure: `step(state, event, rules)`.

The TV's input is derived from two observations of the current session: power and the
foreground app. Off is the input None; on with an app is that app. Until both are known nothing is
decided: a TV in standby still reports its last app, which must not count as being on it.

Each rule is active while the input is one of its inputs. The first input observed applies to every
rule (bringing the Mac in sync at startup); after that only rules whose state changes are acted on,
across reconnects too. Every input change is acted on, in order; none are merged.

Events carry the session (connection) they were observed on, and count until a newer session has
started: the last thing a dropped connection reported, typically "power off", still applies.
"""

from dataclasses import dataclass, replace

from .config import Rule


class _Unknown:
    def __repr__(self):
        return "UNKNOWN"


UNKNOWN = _Unknown()  # an input not known yet


@dataclass(frozen=True)
class State:
    session: int = 0
    power: bool | None = None  # None until the session reports it
    app: str | None = None  # kept through standby, for the wake
    last: str | None | _Unknown = UNKNOWN  # the input last acted on


@dataclass(frozen=True)
class NewSession:
    session: int


@dataclass(frozen=True)
class Power:
    session: int
    on: bool


@dataclass(frozen=True)
class App:
    session: int
    app: str  # "" when the TV reports none


@dataclass(frozen=True)
class Decision:
    input: str | None
    changes: tuple[tuple[Rule, bool], ...]  # (rule, enter?), all leaves before all enters


def step(state: State, event, rules: list[Rule]) -> tuple[State, Decision | None]:
    match event:
        case NewSession(session) if session > state.session:
            return replace(state, session=session, power=None, app=None), None
        case Power(session, on) if session == state.session:
            return _decide(replace(state, power=on), rules)
        case App(session, app) if session == state.session:
            return _decide(replace(state, app=app or None), rules)
    return state, None  # from a superseded session


def current_input(state: State) -> str | None | _Unknown:
    if state.power is False:
        return None
    if state.power and state.app:
        return state.app
    return UNKNOWN


def _decide(state: State, rules: list[Rule]) -> tuple[State, Decision | None]:
    new, old = current_input(state), state.last
    if new is UNKNOWN or new == old:
        return state, None
    changes = [(r, r.matches(new)) for r in rules if old is UNKNOWN or r.matches(old) != r.matches(new)]
    # Leave before enter, so e.g. audio ends up on the entered rule's output. The sort is stable,
    # so config order holds within each group.
    changes.sort(key=lambda change: change[1])
    return replace(state, last=new), Decision(new, tuple(changes))
