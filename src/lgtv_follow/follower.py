"""Tracks the TV's foreground input and fires rule transitions."""

import asyncio
import logging

from bscpylgtv import StorageSqliteDict, WebOsClient

from . import history
from .config import KEY_PATH, Config

log = logging.getLogger(__name__)
CONNECT_TIMEOUT = 3
PING_TIMEOUT = 5
RETRY_SECONDS = 5


class Follower:
    """Pure state machine: feed it the current input, it calls enter/leave on changes.

    The first observation always applies, so the Mac is brought in sync at startup.
    """

    def __init__(self, config: Config, actions):
        self.rules = config.rules
        self.actions = actions
        self.active: dict[str, bool | None] = {r.name: None for r in self.rules}

    def update(self, app_id: str | None):
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


class NotPaired(Exception):
    pass


async def is_paired(host: str) -> bool:
    """Whether a pairing key is stored for this TV address (keys are stored per address)."""
    if not KEY_PATH.exists():
        return False
    storage = await StorageSqliteDict.create(str(KEY_PATH))
    return await storage.get_key(host) is not None


async def connect(host: str, pairing: bool = False) -> WebOsClient:
    """Connect once, giving up within a few seconds (TV off, away from home, wrong network...).

    Without a stored key the TV would show a pairing prompt, so that's only allowed when
    `pairing` is set (the `pair` command); everything else fails with NotPaired instead.
    """
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    client = await WebOsClient.create(
        host,
        key_file_path=str(KEY_PATH),
        states=["power", "current_app"],
        timeout_connect=CONNECT_TIMEOUT,
        connect_retry_attempts=1,
        ping_timeout=PING_TIMEOUT,  # notice a dead connection quickly, e.g. after the Mac wakes
    )
    if client.client_key is None and not pairing:
        raise NotPaired(f"not paired with {host} - run `lgtv-follow pair`")
    try:
        await asyncio.wait_for(client.connect(), None if pairing else CONNECT_TIMEOUT + 2)
    except Exception as e:
        await client.disconnect()
        raise TVUnreachable(f"TV not reachable at {host}") from e
    return client


async def run(config: Config, actions):
    follower = Follower(config, actions)
    last = object()

    # bscpylgtv delivers power and app events on separate tasks; serialize them so actions
    # never interleave, and read the client's latest state inside the lock so the last wins.
    lock = asyncio.Lock()

    async def on_state(client):
        nonlocal last
        async with lock:
            # Treat standby/off as "no input" so rules leave cleanly.
            app_id = client.current_appId if client.is_on else None
            if app_id == "" or app_id == last:
                return
            last = app_id
            log.info("tv input: %s", app_id or "off")
            history.record(app_id)
            await asyncio.to_thread(follower.update, app_id)

    # While the TV is unreachable nothing on the Mac is touched. Retry every few seconds so
    # the Mac follows soon after the TV turns on, but log only when reachability changes.
    reachable = None
    while True:
        client = None
        try:
            client = await connect(config.host)
            log.info("connected to %s", config.host)
            reachable = True
            await client.register_state_update_callback(on_state)
            while client.is_connected():
                await asyncio.sleep(1)
            log.info("connection closed")
        except (TVUnreachable, NotPaired) as e:
            if reachable is not False:
                log.info("%s; retrying quietly in the background", e)
            reachable = False
        except Exception:
            log.exception("unexpected error")
        finally:
            if client:
                await client.disconnect()
        await asyncio.sleep(RETRY_SECONDS)
