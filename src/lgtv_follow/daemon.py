"""The daemon: keeps a connection to the TV and makes the Mac follow its input.

The connection is a state machine with one handler per state, each returning the next state:

    CONNECTING   -> SUBSCRIBING, or WAITING if the TV can't be reached
    SUBSCRIBING  -> CONNECTED, or CLOSING if the TV doesn't answer or report its power state
    CONNECTED    -> CLOSING once a ping fails (pings go on while the TV is in standby)
    CLOSING      -> WAITING
    WAITING      -> CONNECTING, a few seconds later

What the TV reports goes from the connection straight to the Follower, which asks the pure state
machine in fsm.py what to do and runs that on one worker thread: in order and one at a time,
whatever happens to the connection meanwhile. Losing the connection by itself changes nothing.
"""

import asyncio
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum, auto

from . import fsm, tv
from .config import Config, Rule
from .history import History
from .keys import KeyStore

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Timing:
    connect: float = tv.CONNECT_TIMEOUT
    request: float = tv.REQUEST_TIMEOUT
    ping_interval: float = 5
    ping_timeout: float = 5
    retry: float = 5
    # Every wait is bounded, so this long without progress means something unforeseen wedged us.
    watchdog: float = 120


async def run(config: Config, actions, *, timing=None, keys=None, history=None):
    follower = Follower(config.rules, actions, history or History())
    try:
        await Connection(config.host, keys or KeyStore(), timing or Timing(), follower).run()
    finally:
        follower.close()


class Follower:
    """Turns what the TV reports into enters and leaves on the Mac."""

    def __init__(self, rules: list[Rule], actions, history: History):
        self.rules = rules
        self.actions = actions
        self.history = history
        self.state = fsm.State()
        # One worker for the life of the process, so actions never overlap or reorder.
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="actions")

    def new_session(self) -> int:
        """Start following a new connection; reports from earlier ones are ignored from now on."""
        session = self.state.session + 1
        self.observe(fsm.NewSession(session))
        return session

    @property
    def knows_power(self) -> bool:
        return self.state.power is not None

    def observe(self, event):
        """Called for every report, so it returns at once: actions are queued on the worker."""
        try:
            self.state, decision = fsm.step(self.state, event, self.rules)
            if decision:
                log.info("tv input: %s", decision.input or "off")
                if decision.changes:
                    self.worker.submit(self._act, decision)
                try:
                    self.history.record(decision.input)  # only for `switch back`; never in the way
                except OSError as e:
                    log.warning("can't record input history: %s", e)
        except Exception:
            log.exception("handling %r failed", event)

    def _act(self, decision: fsm.Decision):
        for rule, enter in decision.changes:
            try:
                (self.actions.enter if enter else self.actions.leave)(rule, decision.input)
            except Exception:
                log.exception("rule %s failed", rule.name)  # the others still run

    def close(self):
        # A running action can't be interrupted; it finishes on its own.
        self.worker.shutdown(wait=False, cancel_futures=True)


class Conn(Enum):
    CONNECTING = auto()
    SUBSCRIBING = auto()
    CONNECTED = auto()
    CLOSING = auto()
    WAITING = auto()


class Connection:
    def __init__(self, host: str, keys: KeyStore, timing: Timing, follower: Follower):
        self.host = host
        self.keys = keys
        self.timing = timing
        self.follower = follower
        self.tv = None
        # Retrying every few seconds mustn't log every few seconds: remember what was logged.
        self.unreachable = None  # why the last connection attempt failed
        self.unusable = None  # why the last connection failed before it became usable

    async def run(self):
        handlers = {
            Conn.CONNECTING: self.connecting,
            Conn.SUBSCRIBING: self.subscribing,
            Conn.CONNECTED: self.connected,
            Conn.CLOSING: self.closing,
            Conn.WAITING: self.waiting,
        }
        self.watchdog = Watchdog(self.timing.watchdog)
        state = Conn.CONNECTING
        try:
            while True:
                self.watchdog.beat()
                state = await handlers[state]()
        finally:
            # Only on cancellation (tests, Ctrl-C): launchd's SIGTERM ends the process outright.
            self.watchdog.stop()

    async def connecting(self) -> Conn:
        try:
            self.tv = await tv.connect(
                self.host,
                self.keys.get(self.host),
                timeout=self.timing.connect,
                request_timeout=self.timing.request,
            )
        except Exception as e:
            if str(e) != self.unreachable:
                log.info("%s; retrying quietly in the background", e)
            self.unreachable = str(e)
            return Conn.WAITING
        self.unreachable = None
        if not self.unusable:
            log.info("connected to %s", self.host)
        return Conn.SUBSCRIBING

    async def subscribing(self) -> Conn:
        session = self.follower.new_session()
        try:
            await self.tv.follow(
                on_power=lambda on: self.follower.observe(fsm.Power(session, on)),
                on_app=lambda app: self.follower.observe(fsm.App(session, app)),
            )
        except Exception as e:
            problem = f"can't follow the TV's state ({str(e) or type(e).__name__})"
        else:
            if self.follower.knows_power:
                self.unusable = None
                return Conn.CONNECTED
            # Without it standby can't be told from on, so the Mac could never be synced.
            problem = "TV didn't report its power state"
        if problem != self.unusable:
            log.warning("%s; reconnecting", problem)
        self.unusable = problem
        return Conn.CLOSING

    async def connected(self) -> Conn:
        # The TV can drop off the network without closing the socket, and the Mac sleeping can
        # leave a dead connection behind too: only pings tell.
        while await self.tv.ping(self.timing.ping_timeout):
            self.watchdog.beat()
            await asyncio.sleep(self.timing.ping_interval)
        log.info("connection closed")
        return Conn.CLOSING

    async def closing(self) -> Conn:
        await self.tv.close()
        self.tv = None
        return Conn.WAITING

    async def waiting(self) -> Conn:
        await asyncio.sleep(self.timing.retry)
        return Conn.CONNECTING


def restart(reason: str):
    """Exit at once and let launchd's KeepAlive start a fresh process."""
    log.error("%s; exiting so launchd restarts us", reason)
    logging.shutdown()
    os._exit(1)


class Watchdog:
    """Restarts the process if `beat` isn't called for `timeout` seconds of awake time."""

    def __init__(self, timeout: float):
        self.timeout = timeout
        self.stopped = threading.Event()
        self.beat()
        threading.Thread(target=self._watch, name="watchdog", daemon=True).start()

    def beat(self):
        self.last = time.monotonic()

    def stop(self):
        self.stopped.set()

    def _watch(self):
        tick = time.monotonic()
        while not self.stopped.wait(5):
            now = time.monotonic()
            if now - tick > 30:
                self.beat()  # the Mac was asleep: give the loop a chance to catch up first
            tick = now
            if now - self.last > self.timeout:
                restart(f"no progress for {now - self.last:.0f}s")
