"""The webOS client, against small fake TVs."""

import asyncio
import json

import pytest
import websockets

from lgtv_follow import tv


def run_with(handler, use):
    """Serve `handler` on localhost and return `await use(url)`."""

    async def main():
        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            return await use(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}")

    return asyncio.run(main())


async def registers(ws, key="k"):
    message = json.loads(await ws.recv())
    assert message["type"] == "register"
    await ws.send(json.dumps({"type": "response", "id": "register_0", "payload": {"pairingType": "PROMPT"}}))
    await ws.send(json.dumps({"type": "registered", "id": "register_0", "payload": {"client-key": key}}))
    return message["payload"]


def test_pairing_returns_the_new_key():
    sent = {}

    async def handler(ws):
        sent.update(await registers(ws, key="new"))
        await ws.wait_closed()

    async def use(url):
        client, key = await tv.pair(url)
        await client.close()
        return key

    assert run_with(handler, use) == "new"
    assert sent["client-key"] is None and sent["manifest"]["signed"]["appId"] == "com.lge.test"


def test_request_and_error_responses():
    async def handler(ws):
        await registers(ws)
        async for raw in ws:
            m = json.loads(raw)
            if m["uri"].endswith(tv.FOREGROUND_APP):
                await ws.send(
                    json.dumps({"type": "response", "id": m["id"], "payload": {"appId": "netflix"}})
                )
            else:
                await ws.send(json.dumps({"type": "error", "id": m["id"], "error": "404 no such service"}))

    async def use(url):
        client = await tv.connect(url, "k")
        try:
            assert await client.current_app() == "netflix"
            with pytest.raises(tv.TVError, match="404"):
                await client.inputs()
        finally:
            await client.close()

    run_with(handler, use)


def test_requests_fail_at_once_when_the_connection_drops():
    async def handler(ws):
        await registers(ws)
        await ws.recv()  # the request, never answered...
        ws.transport.abort()  # ...because the TV goes away

    async def use(url):
        client = await tv.connect(url, "k", request_timeout=30)
        with pytest.raises(ConnectionError):
            async with asyncio.timeout(2):
                await client.current_app()
        with pytest.raises(ConnectionError):
            await client.current_app()
        assert not await client.ping(1)
        await client.close()

    run_with(handler, use)


def test_never_connects_without_a_key():
    with pytest.raises(tv.NotPaired):
        asyncio.run(tv.connect("192.0.2.1", None))  # fails before any network traffic


def test_unreachable_tv():
    with pytest.raises(tv.TVUnreachable):
        asyncio.run(tv.connect("ws://127.0.0.1:9", "k", timeout=1))


def test_url():
    assert tv.url("192.168.1.5") == "wss://192.168.1.5:3001"
    assert tv.url("ws://192.168.1.5:3000") == "ws://192.168.1.5:3000"


@pytest.mark.parametrize(
    "payload, on",
    [
        ({"state": "Active"}, True),
        ({"state": "Screen Off"}, True),
        ({"state": "Screen Saver"}, True),
        ({"state": "Active Standby", "processing": "Request Active Standby"}, False),
        ({"state": "Power Off"}, False),
        ({"state": "Suspend"}, False),
        ({"state": "Unknown"}, None),  # a guess must never count as on
        ({"state": ""}, None),
        ({"state": ["Active"]}, None),
        ({}, None),
        (None, None),
    ],
)
def test_power_payloads(payload, on):
    assert tv.power_on(payload) == on
