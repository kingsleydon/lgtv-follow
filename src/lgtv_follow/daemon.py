"""The daemon: keeps a connection to the TV and makes the Mac follow its input.

The connection is a state machine with one handler per state, each returning the next state:

    CONNECTING   -> SUBSCRIBING, or WAITING if the TV can't be reached
    SUBSCRIBING  -> CONNECTED, or CLOSING if the TV doesn't answer or report its power state
    CONNECTED    -> CLOSING once a ping fails (pings go on while the TV is in standby)
    CLOSING      -> WAITING
    WAITING      -> CONNECTING, a few seconds later

What the TV reports goes from the library's callbacks straight into the pure state machine in
fsm.py. Its decisions run on one worker thread, in order and one at a time, whatever happens to the
connection meanwhile. Losing the connection by itself changes nothing on the Mac.
"""

import asyncio
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from enum import Enum, auto

from . import fsm, history, tv
from .config import Config

log = logging.getLogger(__name__)
PING_INTERVAL = 5
RETRY_SECONDS = 5
# Every wait is bounded, so this long without progress means something unforeseen has wedged us.
WATCHDOG_SECONDS = 120
MAX_STUCK_CLOSES = 3


class Conn(Enum):
    CONNECTING = auto()
    SUBSCRIBING = auto()
    CONNECTED = auto()
    CLOSING = auto()
    WAITING = auto()


async def run(config: Config, actions):
    await Daemon(config, actions).run()


class Daemon:
    def __init__(self, config: Config, actions):
        self.config = config
        self.actions = actions
        self.state = fsm.State()
        self.session = 0
        self.client = None
        self.stuck_closes = 0
        # Retrying every few seconds mustn't log every few seconds: remember what was logged.
        self.unreachable = None  # why the last connection attempt failed
        self.unusable = None  # why the last session failed before it became usable
        # One worker for the life of the process, so actions never overlap or reorder.
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="actions")

    async def run(self):
        handlers = {
            Conn.CONNECTING: self.connecting,
            Conn.SUBSCRIBING: self.subscribing,
            Conn.CONNECTED: self.connected,
            Conn.CLOSING: self.closing,
            Conn.WAITING: self.waiting,
        }
        self.watchdog = Watchdog(WATCHDOG_SECONDS)
        conn = Conn.CONNECTING
        try:
            while True:
                self.watchdog.beat()
                conn = await handlers[conn]()
        finally:
            # Only on cancellation (tests, Ctrl-C): launchd's SIGTERM ends the process outright.
            self.watchdog.stop()
            self.worker.shutdown(wait=False, cancel_futures=True)

    async def connecting(self) -> Conn:
        try:
            self.client = await tv.connect(self.config.host)
        except (tv.TVUnreachable, tv.NotPaired) as e:
            if str(e) != self.unreachable:
                log.info("%s; retrying quietly in the background", e)
            self.unreachable = str(e)
            return Conn.WAITING
        self.unreachable = None
        if not self.unusable:
            log.info("connected to %s", self.config.host)
        self.session += 1
        self.observe(fsm.NewSession(self.session))
        return Conn.SUBSCRIBING

    async def subscribing(self) -> Conn:
        session = self.session
        try:
            await tv.subscribe(
                self.client,
                on_power=lambda on: self.observe(fsm.Power(session, on)),
                on_app=lambda app: self.observe(fsm.App(session, app)),
            )
        except Exception as e:
            problem = f"can't follow the TV's state ({str(e) or type(e).__name__})"
        else:
            if self.state.power is not None:
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
        while await tv.ping(self.client):
            self.watchdog.beat()
            await asyncio.sleep(PING_INTERVAL)
        log.info("connection closed")
        return Conn.CLOSING

    async def closing(self) -> Conn:
        client, self.client = self.client, None
        if not await tv.close(client):
            self.stuck_closes += 1
            log.warning("disconnect is stuck (%d so far)", self.stuck_closes)
            if self.stuck_closes >= MAX_STUCK_CLOSES:
                restart("too many stuck disconnects")
        return Conn.WAITING

    async def waiting(self) -> Conn:
        await asyncio.sleep(RETRY_SECONDS)
        return Conn.CONNECTING

    def observe(self, event):
        """Feed a TV report to the state machine and carry out its decision. Called from the
        library's callbacks, so it returns at once: actions are queued on the worker thread."""
        try:
            self.state, decision = fsm.step(self.state, event, self.config.rules)
            if decision:
                log.info("tv input: %s", decision.input or "off")
                if decision.changes:
                    self.worker.submit(act, self.actions, decision)
                try:
                    history.record(decision.input)  # only for `switch back`; never in the way
                except OSError as e:
                    log.warning("can't record input history: %s", e)
        except Exception:
            log.exception("handling %r failed", event)


def act(actions, decision: fsm.Decision):
    """Run a decision's leaves and enters; one failing rule doesn't stop the others."""
    for rule, enter in decision.changes:
        try:
            (actions.enter if enter else actions.leave)(rule, decision.input)
        except Exception:
            log.exception("rule %s failed", rule.name)


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
