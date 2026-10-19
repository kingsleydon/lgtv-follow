"""A small client for the TV's webOS SSAP protocol: JSON messages over a websocket.

One reader task owns the socket's incoming side: it resolves each request's future and calls
subscription callbacks directly, in the order messages arrive. Every wait is bounded, and when the
connection drops every pending request fails with ConnectionError.
"""

import asyncio
import itertools
import json
import logging
import ssl
from collections.abc import Callable

import websockets

log = logging.getLogger(__name__)
CONNECT_TIMEOUT = 3
REQUEST_TIMEOUT = 10
PAIRING_TIMEOUT = 60  # time to accept the prompt on the TV
CLOSE_TIMEOUT = 2

POWER = "com.webos.service.tvpower/power/getPowerState"
FOREGROUND_APP = "com.webos.applicationManager/getForegroundAppInfo"
INPUTS = "tv/getExternalInputList"
LAUNCH = "system.launcher/launch"
ON_STATES = {"Active", "Screen Off", "Screen Saver"}  # "Screen Off": input still selected, picture off
OFF_STATES = {"Power Off", "Suspend", "Active Standby"}


class TVUnreachable(Exception):
    pass


class NotPaired(Exception):
    pass


class TVError(Exception):
    """The TV answered with an error."""


def url(host: str) -> str:
    """The TV's address: an IP or name (secure websocket on port 3001), or a full ws(s):// URL."""
    return host if "://" in host else f"wss://{host}:3001"


async def connect(host: str, key: str | None, *, timeout=CONNECT_TIMEOUT, request_timeout=REQUEST_TIMEOUT):
    """Connect with a stored pairing key, giving up within `timeout` (TV off, away from home...).

    Never without a key: the TV would show a pairing prompt. Only `pair` may do that.
    """
    if key is None:
        raise NotPaired(f"not paired with {host} - run `lgtv-follow pair`")
    tv, _ = await TV.open(host, key, timeout, request_timeout)
    return tv


async def pair(host: str) -> tuple["TV", str]:
    """Connect without a key; the TV asks for permission. Returns the connection and the new key."""
    return await TV.open(host, None, PAIRING_TIMEOUT, REQUEST_TIMEOUT)


class TV:
    def __init__(self, ws, request_timeout: float):
        self._ws = ws
        self._request_timeout = request_timeout
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._subscribers: dict[int, Callable[[dict], None]] = {}
        self._reader = asyncio.create_task(self._read())

    @classmethod
    async def open(cls, host, key, timeout, request_timeout) -> tuple["TV", str]:
        try:
            async with asyncio.timeout(timeout):
                ws = await websockets.connect(
                    url(host),
                    ssl=_INSECURE if url(host).startswith("wss:") else None,  # TVs have self-signed certs
                    proxy=None,  # the TV is on the local network, whatever the environment says
                    ping_interval=None,  # we ping ourselves, also in standby
                    close_timeout=CLOSE_TIMEOUT,
                    max_size=None,
                )
                try:
                    key = await _register(ws, key)
                except BaseException:
                    await ws.close()
                    raise
        except (OSError, TimeoutError, websockets.WebSocketException) as e:
            raise TVUnreachable(f"TV not reachable at {host}") from e
        return cls(ws, request_timeout), key

    @property
    def connected(self) -> bool:
        return not self._reader.done()

    async def request(self, uri: str, payload: dict | None = None, *, on_update=None) -> dict:
        """Send a request (a subscription if `on_update` is given) and return the response payload.
        A subscription's updates, starting with that first response, go to `on_update(payload)`."""
        if not self.connected:
            raise ConnectionError("connection closed")
        id = next(self._ids)
        self._pending[id] = response = asyncio.get_running_loop().create_future()
        if on_update:
            self._subscribers[id] = on_update
        message = {"id": id, "type": "subscribe" if on_update else "request", "uri": f"ssap://{uri}"}
        try:
            async with asyncio.timeout(self._request_timeout):
                await self._ws.send(json.dumps({**message, "payload": payload or {}}))
                return await response
        except websockets.ConnectionClosed:
            raise ConnectionError("connection closed") from None
        except BaseException:
            self._subscribers.pop(id, None)
            raise
        finally:
            self._pending.pop(id, None)

    async def current_app(self) -> str:
        return (await self.request(FOREGROUND_APP)).get("appId", "")

    async def inputs(self) -> list[dict]:
        return (await self.request(INPUTS)).get("devices", [])

    async def launch(self, app_id: str):
        await self.request(LAUNCH, {"id": app_id})

    async def follow(self, on_power: Callable[[bool], None], on_app: Callable[[str], None]):
        """Report power (on/off) and the foreground app ("" for none) as they change, starting with
        their current values, power first. Unrecognized power states are ignored."""

        def power(payload):
            on = power_on(payload)
            if on is None:
                log.debug("ignoring power payload %r", payload)
            else:
                on_power(on)

        await self.request(POWER, on_update=power)
        await self.request(FOREGROUND_APP, on_update=lambda payload: on_app(payload.get("appId") or ""))

    async def ping(self, timeout: float) -> bool:
        """Whether the TV still answers (also in standby)."""
        try:
            async with asyncio.timeout(timeout):
                await (await self._ws.ping())
            return True
        except Exception:
            return False

    async def close(self):
        try:
            async with asyncio.timeout(CLOSE_TIMEOUT + 1):
                await self._ws.close()
                await self._reader
        except Exception as e:
            log.debug("close: %r", e)
        self._reader.cancel()

    async def _read(self):
        try:
            async for raw in self._ws:
                try:
                    message = json.loads(raw)
                    id, payload = message.get("id"), message.get("payload") or {}
                except (ValueError, AttributeError):
                    continue
                error = message.get("error") if message.get("type") == "error" else None
                if error is None and (on_update := self._subscribers.get(id)):
                    try:
                        on_update(payload)
                    except Exception:
                        log.exception("handling %r failed", payload)
                response = self._pending.get(id)
                if response and not response.done():
                    if error is None:
                        response.set_result(payload)
                    else:
                        response.set_exception(TVError(error))
        except websockets.ConnectionClosed:
            pass
        finally:
            for response in self._pending.values():
                if not response.done():
                    response.set_exception(ConnectionError("connection closed"))


async def _register(ws, key: str | None) -> str:
    payload = {"forcePairing": False, "pairingType": "PROMPT", "manifest": MANIFEST, "client-key": key}
    await ws.send(json.dumps({"type": "register", "id": "register_0", "payload": payload}))
    while True:  # possibly a "response" first (e.g. while the TV shows its prompt), then "registered"
        message = json.loads(await ws.recv())
        if message.get("type") == "registered":
            return message["payload"]["client-key"]
        if message.get("type") == "error":
            raise TVError(message.get("error") or "registration refused")


def power_on(payload) -> bool | None:
    """True/False for a known power state; None for anything else (an error response, "Unknown"),
    so a guess can never count as the TV being on."""
    state = payload.get("state") if isinstance(payload, dict) else None
    if not isinstance(state, str):
        return None
    return True if state in ON_STATES else False if state in OFF_STATES else None


_INSECURE = ssl.create_default_context()
_INSECURE.check_hostname = False
_INSECURE.verify_mode = ssl.CERT_NONE

# The app manifest the TV shows and grants permissions to. Taken from bscpylgtv
# (https://github.com/chros73/bscpylgtv, MIT, (c) 2017 Dennis Karpienski, 2019 Josh Bendavid) and
# unchanged, so keys paired with earlier versions stay valid.
MANIFEST = {
    "appVersion": "1.1",
    "manifestVersion": 1,
    "deviceName": "bscpylgtv",
    "permissions": [
        "LAUNCH",
        "LAUNCH_WEBAPP",
        "APP_TO_APP",
        "CLOSE",
        "TEST_OPEN",
        "TEST_PROTECTED",
        "CONTROL_AUDIO",
        "CONTROL_DISPLAY",
        "CONTROL_INPUT_JOYSTICK",
        "CONTROL_INPUT_MEDIA_RECORDING",
        "CONTROL_INPUT_MEDIA_PLAYBACK",
        "CONTROL_INPUT_TV",
        "CONTROL_POWER",
        "CONTROL_TV_SCREEN",
        "READ_APP_STATUS",
        "READ_CURRENT_CHANNEL",
        "READ_INPUT_DEVICE_LIST",
        "READ_NETWORK_STATE",
        "READ_RUNNING_APPS",
        "READ_TV_CHANNEL_LIST",
        "WRITE_NOTIFICATION_TOAST",
        "READ_POWER_STATE",
        "READ_COUNTRY_INFO",
        "CONTROL_INPUT_TEXT",
        "CONTROL_MOUSE_AND_KEYBOARD",
        "READ_INSTALLED_APPS",
        "READ_SETTINGS",
        "READ_STORAGE_DEVICE_LIST",
    ],
    "signatures": [
        {
            "signature": (
                "eyJhbGdvcml0aG0iOiJSU0EtU0hBMjU2Iiwia2V5SWQiOiJ0ZXN0LXNpZ25pbm"
                "ctY2VydCIsInNpZ25hdHVyZVZlcnNpb24iOjF9.hrVRgjCwXVvE2OOSpDZ58hR"
                "+59aFNwYDyjQgKk3auukd7pcegmE2CzPCa0bJ0ZsRAcKkCTJrWo5iDzNhMBWRy"
                "aMOv5zWSrthlf7G128qvIlpMT0YNY+n/FaOHE73uLrS/g7swl3/qH/BGFG2Hu4"
                "RlL48eb3lLKqTt2xKHdCs6Cd4RMfJPYnzgvI4BNrFUKsjkcu+WD4OO2A27Pq1n"
                "50cMchmcaXadJhGrOqH5YmHdOCj5NSHzJYrsW0HPlpuAx/ECMeIZYDh6RMqaFM"
                "2DXzdKX9NmmyqzJ3o/0lkk/N97gfVRLW5hA29yeAwaCViZNCP8iC9aO0q9fQoj"
                "oa7NQnAtw=="
            ),
            "signatureVersion": 1,
        }
    ],
    "signed": {
        "appId": "com.lge.test",
        "created": "20140509",
        "localizedAppNames": {"": "LG Remote App", "ko-KR": "리모컨 앱", "zxx-XX": "ЛГ Rэмotэ AПП"},
        "localizedVendorNames": {"": "LG Electronics"},
        "permissions": [
            "TEST_SECURE",
            "CONTROL_INPUT_TEXT",
            "CONTROL_MOUSE_AND_KEYBOARD",
            "READ_INSTALLED_APPS",
            "READ_LGE_SDX",
            "READ_NOTIFICATIONS",
            "SEARCH",
            "WRITE_SETTINGS",
            "WRITE_NOTIFICATION_ALERT",
            "CONTROL_POWER",
            "READ_CURRENT_CHANNEL",
            "READ_RUNNING_APPS",
            "READ_UPDATE_INFO",
            "UPDATE_FROM_REMOTE_APP",
            "READ_LGE_TV_INPUT_EVENTS",
            "READ_TV_CURRENT_TIME",
        ],
        "serial": "2f930e2d2cfe083771f68e4fe7bb07",
        "vendorId": "com.lge",
    },
}
