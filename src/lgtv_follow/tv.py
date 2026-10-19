"""Talking to the TV through bscpylgtv, with every wait bounded.

bscpylgtv's own state tracking is never used: its power handler disconnects from inside its own
callback task, which deadlocks the client. We subscribe to what we need ourselves.
"""

import asyncio
import logging

from bscpylgtv import StorageSqliteDict, WebOsClient

from .config import KEY_PATH

log = logging.getLogger(__name__)
CONNECT_TIMEOUT = 3
REQUEST_TIMEOUT = 10
PING_TIMEOUT = 5
ON_STATES = {"Active", "Screen Off", "Screen Saver"}  # "Screen Off": input still selected, picture off
OFF_STATES = {"Power Off", "Suspend", "Active Standby"}


class TVUnreachable(Exception):
    pass


class NotPaired(Exception):
    pass


async def call(awaitable):
    """Await a request to the TV. bscpylgtv cancels pending requests when the connection drops;
    report that as ConnectionError, so only a genuine cancellation of our task propagates."""
    try:
        return await awaitable
    except asyncio.CancelledError:
        if asyncio.current_task().cancelling():
            raise
        raise ConnectionError("connection closed") from None


_storage = None


async def _key_storage() -> StorageSqliteDict:
    # One handle per process: bscpylgtv would otherwise open the database (and a thread) per client.
    global _storage
    if _storage is None:
        KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _storage = await StorageSqliteDict.create(str(KEY_PATH))
    return _storage


async def is_paired(host: str) -> bool:
    """Whether a pairing key is stored for this TV address (keys are stored per address)."""
    return KEY_PATH.exists() and await (await _key_storage()).get_key(host) is not None


async def connect(host: str, pairing: bool = False) -> WebOsClient:
    """Connect once, giving up within a few seconds (TV off, away from home, wrong network...).

    Without a stored key the TV would show a pairing prompt, so that's only allowed when
    `pairing` is set (the `pair` command); everything else fails with NotPaired instead.
    """
    async with asyncio.timeout(None if pairing else CONNECT_TIMEOUT):
        if not pairing and not await is_paired(host):
            raise NotPaired(f"not paired with {host} - run `lgtv-follow pair`")
        client = await WebOsClient.create(
            host,
            storage=await _key_storage(),
            states=[],
            timeout_connect=CONNECT_TIMEOUT,
            connect_retry_attempts=1,
            ping_interval=None,
        )
    if client.client_key is None and not pairing:
        raise NotPaired(f"not paired with {host} - run `lgtv-follow pair`")
    try:
        await call(asyncio.wait_for(client.connect(), None if pairing else CONNECT_TIMEOUT + 2))
    except BaseException as e:
        await close(client)  # even when cancelled: never leave a half-open client behind
        if isinstance(e, Exception):
            raise TVUnreachable(f"TV not reachable at {host}") from e
        raise
    return client


async def close(client: WebOsClient) -> bool:
    """Disconnect, waiting a few seconds at most. False if the client is stuck and was left behind."""
    task = asyncio.ensure_future(client.disconnect())
    done, _ = await asyncio.wait([task], timeout=CONNECT_TIMEOUT + 2)
    # Fetch any exception so it isn't reported as never retrieved.
    task.add_done_callback(lambda t: t.cancelled() or t.exception())
    return bool(done)


def power_on(payload) -> bool | None:
    """True/False for a known power state; None for anything else (an error response, "Unknown"),
    so a guess can never count as the TV being on."""
    state = payload.get("state") if isinstance(payload, dict) else None
    if not isinstance(state, str):
        return None
    return True if state in ON_STATES else False if state in OFF_STATES else None


async def subscribe(client: WebOsClient, on_power, on_app):
    """Follow power (on_power(bool)) and the foreground app (on_app(str), "" for none).

    Power comes first. Each subscription's first response is delivered before it returns.
    """

    async def power(payload):
        on = power_on(payload)
        if on is None:
            log.debug("ignoring power payload %r", payload)
        else:
            on_power(on)

    async def app(app_id):
        on_app(app_id or "")

    async with asyncio.timeout(REQUEST_TIMEOUT):
        await call(client.subscribe_power(power))
        await call(client.subscribe_current_app(app))


async def ping(client: WebOsClient) -> bool:
    """Whether the TV still answers. Works in standby too, unlike bscpylgtv's own pings."""
    if not client.is_connected():
        return False
    try:
        async with asyncio.timeout(PING_TIMEOUT):
            pong = await call(client.connection.ping())
            await call(pong)
        return True
    except Exception:
        return False
