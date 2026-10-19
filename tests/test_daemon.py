"""The daemon, end to end against a fake webOS TV on localhost."""

import asyncio
import json
import logging
import threading
import time

import pytest
import websockets

from lgtv_follow import daemon, fsm
from lgtv_follow.config import parse
from lgtv_follow.daemon import Timing
from lgtv_follow.history import History
from lgtv_follow.keys import KeyStore

HDMI1, HDMI4 = "com.webos.app.hdmi1", "com.webos.app.hdmi4"


class FakeTV:
    def __init__(self):
        self.power = "Active"
        self.app = HDMI4
        self.answer_subscriptions = True
        self.reject_power = False
        self.requests = []
        self.reachable = True
        self.sockets = []
        self.subs = {}

    async def handler(self, ws):
        if not self.reachable:
            ws.transport.abort()
            return
        self.sockets.append(ws)
        async for raw in ws:
            m = json.loads(raw)
            if m["type"] == "register":
                assert m["payload"]["client-key"] == "k"  # a missing key would mean a pairing prompt
                await ws.send(
                    json.dumps({"type": "response", "id": m["id"], "payload": {"pairingType": "PROMPT"}})
                )
                await ws.send(
                    json.dumps({"type": "registered", "id": m["id"], "payload": {"client-key": "k"}})
                )
            elif self.requests.append(m["uri"]) or not self.answer_subscriptions:
                continue
            elif "getPowerState" in m["uri"] and self.reject_power:
                await ws.send(json.dumps({"type": "error", "id": m["id"], "error": "401", "payload": {}}))
            elif "getPowerState" in m["uri"]:
                self.subs["power"] = m["id"]
                await self._send(ws, "power", {"state": self.power})
            elif "getForegroundAppInfo" in m["uri"]:
                self.subs["app"] = m["id"]
                await self._send(ws, "app", {"appId": self.app})
            else:
                await ws.send(json.dumps({"type": "error", "id": m["id"], "error": "404", "payload": {}}))

    async def _send(self, ws, sub, payload):
        await ws.send(
            json.dumps({"type": "response", "id": self.subs[sub], "payload": {"subscribed": True, **payload}})
        )

    async def set(self, power=None, app=None):
        if power is not None:
            self.power = power
            await self._send(self.sockets[-1], "power", {"state": power})
        if app is not None:
            self.app = app
            await self._send(self.sockets[-1], "app", {"appId": app})


class Recorder:
    """Slow actions that notice if two ever run at the same time."""

    def __init__(self, delay=0.0):
        self.delay = delay
        self.calls = []
        self.running = 0
        self.overlapped = False
        self.lock = threading.Lock()

    def _act(self, event, app_id):
        with self.lock:
            self.running += 1
            self.overlapped |= self.running > 1
        time.sleep(self.delay)
        with self.lock:
            self.running -= 1
            self.calls.append((event, app_id))

    def enter(self, rule, app_id):
        self._act("enter", app_id)

    def leave(self, rule, app_id):
        self._act("leave", app_id)


FAST = Timing(connect=1, request=1, ping_interval=0.1, ping_timeout=0.3, retry=0.1)


@pytest.fixture
def harness(tmp_path):
    def start(tv, actions, scenario, paired=True, timing=FAST):
        async def main():
            server = await websockets.serve(tv.handler, "127.0.0.1", 0)
            host = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
            keys = KeyStore(tmp_path / "keys.json", tmp_path / "none.sqlite")
            if paired:
                keys.set(host, "k")
            config = parse({"tv": {"host": host}, "rule": [{"input": "HDMI_4", "on_enter": "x"}]})
            history = History(tmp_path / "state.json")
            task = asyncio.create_task(daemon.run(config, actions, timing=timing, keys=keys, history=history))
            try:
                await asyncio.wait_for(scenario(), 10)
            finally:
                task.cancel()
                for ws in tv.sockets:
                    ws.transport.abort()
                server.close()

        asyncio.run(main())

    return start


async def until(cond, timeout=5):
    async with asyncio.timeout(timeout):
        while not cond():
            await asyncio.sleep(0.02)


@pytest.mark.parametrize("how", ["close", "drop", "silent"])
def test_follows_again_after_tv_powers_off(harness, how):
    tv, rec = FakeTV(), Recorder(delay=0.3)

    async def scenario():
        await until(lambda: rec.calls == [("enter", HDMI4)])
        await tv.set(power="Active Standby", app="")
        ws = tv.sockets[-1]
        if how == "close":
            await ws.close()
        elif how == "drop":
            ws.transport.abort()
        else:
            ws.transport.pause_reading()  # stops answering, pings included
        tv.power, tv.app = "Active", HDMI4  # what the next connection will see
        await until(lambda: len(tv.sockets) == 2)
        await until(lambda: rec.calls[-1:] == [("enter", HDMI4)] and len(rec.calls) == 3)

    harness(tv, rec, scenario)
    assert rec.calls == [("enter", HDMI4), ("leave", None), ("enter", HDMI4)]


def test_connecting_to_tv_in_standby_does_not_enter(harness):
    tv, rec = FakeTV(), Recorder()
    tv.power = "Active Standby"  # still reports the last input

    async def scenario():
        await until(lambda: rec.calls)
        await asyncio.sleep(0.3)
        await tv.set(power="Active")
        await until(lambda: len(rec.calls) == 2)

    harness(tv, rec, scenario)
    assert rec.calls == [("leave", None), ("enter", HDMI4)]


def test_actions_never_overlap_across_reconnects(harness):
    tv, rec = FakeTV(), Recorder(delay=0.5)

    async def scenario():
        await until(lambda: rec.calls == [("enter", HDMI4)])
        await tv.set(app=HDMI1)  # leave starts...
        await asyncio.sleep(0.05)
        tv.app = HDMI4
        tv.sockets[-1].transport.abort()  # ...and the connection drops mid-action
        await until(lambda: len(rec.calls) == 3)

    harness(tv, rec, scenario)
    assert rec.calls == [("enter", HDMI4), ("leave", HDMI1), ("enter", HDMI4)]
    assert not rec.overlapped


def test_power_off_right_before_disconnect_still_leaves(harness):
    tv, rec = FakeTV(), Recorder(delay=0.5)

    async def scenario():
        await until(lambda: rec.running)  # the initial enter is still running when...
        tv.reachable = False
        await tv.set(power="Power Off")  # ...the TV says it's turning off and drops off the network
        tv.sockets[-1].transport.abort()
        await until(lambda: len(rec.calls) == 2)

    harness(tv, rec, scenario)
    assert rec.calls == [("enter", HDMI4), ("leave", None)]


def test_reconnects_when_tv_ignores_subscriptions(harness):
    tv, rec = FakeTV(), Recorder()
    tv.answer_subscriptions = False

    async def scenario():
        await until(lambda: len(tv.sockets) == 2)
        tv.answer_subscriptions = True
        await until(lambda: rec.calls == [("enter", HDMI4)])

    harness(tv, rec, scenario)


def test_never_connects_without_a_stored_key(harness, caplog):
    caplog.set_level(logging.INFO)
    tv, rec = FakeTV(), Recorder()

    async def scenario():
        await asyncio.sleep(0.5)  # several retries

    harness(tv, rec, scenario, paired=False)
    assert tv.sockets == [] and rec.calls == []  # a keyless connection would prompt on the TV
    logged = [r.message for r in caplog.records if r.name == "lgtv_follow.daemon"]
    assert len(logged) == 1 and logged[0].startswith("not paired with ws://127.0.0.1:")


def test_tv_rejecting_power_subscription_is_retried_without_acting(harness, caplog):
    caplog.set_level(logging.INFO)
    tv, rec = FakeTV(), Recorder()
    tv.reject_power = True

    async def scenario():
        await until(lambda: len(tv.sockets) >= 3)

    harness(tv, rec, scenario)
    assert rec.calls == []  # without power state it can't tell standby from on
    logged = [r.message for r in caplog.records if r.name == "lgtv_follow.daemon"]
    assert logged[0].startswith("connected to ws://127.0.0.1:")
    assert len(logged) == 2 and "reconnecting" in logged[1]  # once, not on every retry


def test_connection_dropping_mid_subscribe_reconnects_promptly(harness):
    # The pending subscribe request must fail at once, not strand the daemon until the request
    # timeout (made long here) or the watchdog.
    tv, rec = FakeTV(), Recorder()
    tv.answer_subscriptions = False

    async def scenario():
        await until(lambda: tv.requests)
        tv.answer_subscriptions = True
        tv.sockets[-1].transport.abort()
        await until(lambda: rec.calls == [("enter", HDMI4)], timeout=3)

    harness(
        tv,
        rec,
        scenario,
        timing=Timing(connect=1, request=60, ping_interval=0.1, ping_timeout=0.3, retry=0.1),
    )


def test_history_failure_does_not_block_actions(harness, monkeypatch):
    def broken(self, app_id):
        raise PermissionError("read-only")

    monkeypatch.setattr(History, "record", broken)
    tv, rec = FakeTV(), Recorder()

    async def scenario():
        await until(lambda: rec.calls == [("enter", HDMI4)])

    harness(tv, rec, scenario)


def test_failing_rule_does_not_stop_the_others(tmp_path):
    calls = []

    class Actions:
        def enter(self, rule, app_id):
            if rule.name == "a":
                raise RuntimeError("boom")
            calls.append(rule.name)

    rules = parse(
        {"tv": {"host": "h"}, "rule": [{"name": n, "input": "HDMI_1", "on_enter": "x"} for n in "ab"]}
    ).rules
    follower = daemon.Follower(rules, Actions(), History(tmp_path / "state.json"))
    session = follower.new_session()
    follower.observe(fsm.Power(session, True))
    follower.observe(fsm.App(session, HDMI1))
    follower.worker.shutdown(wait=True)
    assert calls == ["b"]
