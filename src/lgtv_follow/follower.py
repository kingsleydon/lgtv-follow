"""Tracks the TV's foreground input and fires rule transitions."""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, Optional

from bscpylgtv import WebOsClient

from . import history
from .config import KEY_PATH, Config

log = logging.getLogger(__name__)
CONNECT_TIMEOUT = 3
RETRY_MIN, RETRY_MAX = 5, 60


class Follower:
    """Pure state machine: feed it the current input, it calls enter/leave on changes.

    The first observation always applies, so the Mac is brought in sync at startup.
    """

    def __init__(self, config: Config, actions):
        self.rules = config.rules
        self.actions = actions
        self.active: Dict[str, Optional[bool]] = {r.name: None for r in self.rules}

    def update(self, app_id: Optional[str]):
        changes = [(r, r.matches(app_id)) for r in self.rules]
        changes = [(r, now) for r, now in changes if self.active[r.name] != now]
        # Leave before enter, so e.g. audio ends up on the newly entered rule's output.
        for rule, now in sorted(changes, key=lambda c: c[1]):
            self.active[rule.name] = now
            try:
                (self.actions.enter if now else self.actions.leave)(rule, app_id)
            except Exception:
                log.exception("rule %s failed", rule.name)


class TVUnreachable(Exception):
    pass


async def connect(host: str) -> WebOsClient:
    """Connect once, giving up within a few seconds (TV off, away from home, wrong network...)."""
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    client = await WebOsClient.create(
        host,
        key_file_path=str(KEY_PATH),
        states=["power", "current_app"],
        timeout_connect=CONNECT_TIMEOUT,
        connect_retry_attempts=1,
    )
    try:
        await asyncio.wait_for(client.connect(), CONNECT_TIMEOUT + 2)
    except Exception as e:
        await client.disconnect()
        raise TVUnreachable(f"TV not reachable at {host}") from e
    return client


async def run(config: Config, actions):
    follower = Follower(config, actions)
    last = object()

    async def on_state(client):
        nonlocal last
        # Treat standby/off as "no input" so rules leave cleanly.
        app_id = client.current_appId if client.is_on else None
        if app_id == "" or app_id == last:
            return
        last = app_id
        log.info("tv input: %s", app_id or "off")
        history.record(app_id)
        await asyncio.to_thread(follower.update, app_id)

    # While the TV is unreachable nothing on the Mac is touched; retry with backoff and
    # log only when reachability changes, so being away from home stays quiet.
    delay, reachable = RETRY_MIN, None
    while True:
        client = None
        try:
            client = await connect(config.host)
            log.info("connected to %s", config.host)
            reachable, delay = True, RETRY_MIN
            await client.register_state_update_callback(on_state)
            while client.is_connected():
                await asyncio.sleep(1)
            log.info("connection closed")
        except TVUnreachable as e:
            if reachable is not False:
                log.info("%s; retrying quietly in the background", e)
            reachable, delay = False, min(delay * 2, RETRY_MAX)
        except Exception:
            log.exception("unexpected error")
        finally:
            if client:
                await client.disconnect()
        await asyncio.sleep(delay)
