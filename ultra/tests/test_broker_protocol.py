"""
Offline protocol tests for the Deriv WebSocket client (Phase 2).

Exercises message routing, request/response correlation, subscription
tracking and ping latency against a fake websocket — no network required.
"""
import asyncio
import json
import logging

import pytest

from src.broker.deriv_client import DerivClient, ConnectionState, Tick, Candle


class FakeWebSocket:
    """In-memory stand-in for a websockets.WebSocketClientProtocol."""

    def __init__(self):
        self.sent = []
        self.on_send = None

    async def send(self, payload: str):
        request = json.loads(payload)
        self.sent.append(request)
        if self.on_send:
            await self.on_send(request)

    async def recv(self):
        await asyncio.sleep(3600)

    async def close(self):
        return None


@pytest.fixture
def client():
    c = DerivClient(app_id="1089", api_token="")
    c.websocket = FakeWebSocket()
    c.state = ConnectionState.AUTHENTICATED
    return c


# === Message routing ===


def test_process_tick_routes_to_handler(client):
    received = []
    client.on_tick(received.append)

    asyncio.run(client._process_message({
        "tick": {"symbol": "frxEURUSD", "quote": 1.12345, "epoch": 1700000000,
                 "bid": 1.1234, "ask": 1.1235},
        "req_id": 5,
    }))

    assert len(received) == 1
    tick = received[0]
    assert isinstance(tick, Tick)
    assert tick.symbol == "frxEURUSD"
    assert tick.price == 1.12345
    assert tick.mid == pytest.approx((1.1234 + 1.1235) / 2)
    assert tick.timestamp == 1700000000 * 1000


def test_process_tick_request_future_resolved(client):
    loop = asyncio.new_event_loop()
    future = loop.create_future()
    client._pending_requests["5"] = future

    loop.run_until_complete(client._process_message({
        "tick": {"symbol": "frxEURUSD", "quote": 1.1, "epoch": 1700000000},
        "req_id": 5,
    }))

    assert future.done()
    assert future.result()["tick"]["quote"] == 1.1
    assert "5" not in client._pending_requests
    loop.close()


def test_process_ohlc_routes_to_candle_handler(client):
    received = []
    client.on_candle(received.append)

    asyncio.run(client._process_message({
        "ohlc": {"symbol": "frxEURUSD", "granularity": 900,
                 "open": 1.10, "high": 1.11, "low": 1.09, "close": 1.105,
                 "volume": 10, "epoch": 1700000000},
        "req_id": 7,
    }))

    assert len(received) == 1
    candle = received[0]
    assert isinstance(candle, Candle)
    assert candle.symbol == "frxEURUSD"
    assert candle.timeframe == "15m"
    assert candle.high == 1.11


def test_process_history_candles_routes_to_handler(client):
    received = []
    client.on_candle(received.append)

    asyncio.run(client._process_message({
        "echo_req": {"ticks_history": "frxUSDJPY", "granularity": 3600},
        "candles": [
            {"epoch": 1700000000, "open": 150.0, "high": 150.5, "low": 149.5,
             "close": 150.2, "volume": 5},
            {"epoch": 1700003600, "open": 150.2, "high": 150.8, "low": 150.0,
             "close": 150.7, "volume": 8},
        ],
    }))

    assert len(received) == 2
    assert received[0].symbol == "frxUSDJPY"
    assert received[0].timeframe == "1h"
    assert received[1].close == 150.7


def test_process_error_routes_to_handler(client):
    errors = []
    client.on_error(errors.append)

    asyncio.run(client._process_message({
        "error": {"code": "AuthorizationRequired", "message": "not authorized"},
        "req_id": 99,
    }))

    assert len(errors) == 1
    assert errors[0]["code"] == "AuthorizationRequired"


def test_process_balance_routes_to_handler(client):
    balances = []
    client.on_balance_update(balances.append)

    asyncio.run(client._process_message({"balance": {"balance": 1234.5}}))

    assert balances == [{"balance": 1234.5}]


def test_process_pong_updates_last_pong(client):
    before = client._last_pong_time
    asyncio.run(client._process_message({"pong": 123}))
    assert client._last_pong_time >= before


# === Request / response correlation ===


def test_send_request_returns_correlated_response(client):
    async def go():
        async def respond(request):
            await asyncio.sleep(0.01)
            await client._process_message({"time": 1234567, "req_id": request["req_id"]})
        client.websocket.on_send = respond
        return await client._send_request({"time": 1})

    response = asyncio.run(go())
    assert response["time"] == 1234567
    assert response["req_id"] in ("1", "2")


def test_send_request_returns_none_on_error(client):
    async def go():
        async def respond(request):
            await asyncio.sleep(0.01)
            await client._process_message({
                "error": {"code": "BadRequest"}, "req_id": request["req_id"]})
        client.websocket.on_send = respond
        return await client._send_request({"ticks": "frxEURUSD"})

    assert asyncio.run(go()) is None


def test_send_request_returns_none_when_disconnected(client):
    client.state = ConnectionState.DISCONNECTED
    assert asyncio.run(client._send_request({"ping": 1})) is None


def test_ping_returns_latency(client):
    async def go():
        async def respond(request):
            await asyncio.sleep(0.005)
            await client._process_message({"time": 12345, "req_id": request["req_id"]})
        client.websocket.on_send = respond
        latency = await client.ping()
        return latency

    latency = asyncio.run(go())
    assert latency is not None
    assert latency >= 0


def test_ping_returns_none_when_not_authenticated(client):
    client.state = ConnectionState.CONNECTED
    assert asyncio.run(client.ping()) is None


# === Subscription tracking / resubscribe ===


def test_subscribe_ticks_records_subscription(client):
    async def go():
        async def respond(request):
            await client._process_message({"req_id": request["req_id"], "subscription": {"id": "abc"}})
        client.websocket.on_send = respond
        return await client.subscribe_ticks("frxEURUSD")

    asyncio.run(go())
    assert client._subscriptions and client._subscriptions[0]["ticks"] == "frxEURUSD"


def test_subscribe_candles_builds_granularity_request(client):
    async def go():
        async def respond(request):
            await client._process_message({"req_id": request["req_id"], "candles": []})
        client.websocket.on_send = respond
        return await client.subscribe_candles("frxEURUSD", "1h", history_count=500)

    asyncio.run(go())
    req = client._subscriptions[0]
    assert req["granularity"] == 3600
    assert req["count"] == 500
    assert req["style"] == "candles"


def test_fetch_history_sends_oneshot_request_without_subscribe(client):
    async def go():
        async def respond(request):
            await client._process_message({"req_id": request["req_id"], "candles": []})
        client.websocket.on_send = respond
        return await client.fetch_history("frxEURUSD", "15m", count=300)

    resp = asyncio.run(go())
    sent = client.websocket.sent[0]
    assert "subscribe" not in sent
    assert sent["granularity"] == 900
    assert sent["count"] == 300
    assert resp is not None
    # One-shot fetch must not be treated as a tracked subscription
    assert client._subscriptions == []


def test_resubscribe_replays_saved_subscriptions(client):
    async def go():
        async def respond(request):
            await client._process_message({"req_id": request["req_id"], "subscription": {"id": "x"}})
        client.websocket.on_send = respond
        await client.subscribe_ticks("frxEURUSD")
        await client.subscribe_candles("frxEURUSD", "15m", history_count=300)
        sent_before = len(client.websocket.sent)
        await client._resubscribe()
        return len(client.websocket.sent) - sent_before

    resent = asyncio.run(go())
    assert resent == 2


def test_unsubscribe_all_clears_subscriptions(client):
    async def go():
        async def respond(request):
            await client._process_message({"req_id": request["req_id"], "forget_all": 1})
        client.websocket.on_send = respond
        client._subscriptions = [{"ticks": "frxEURUSD"}]
        await client.unsubscribe_all()
        return client._subscriptions

    assert asyncio.run(go()) == []


def test_subscribe_tracks_failed_request_for_replay(client):
    """A subscription that fails must still be tracked so it is replayed on
    reconnect instead of being silently lost."""
    async def go():
        async def respond(request):
            await client._process_message({
                "error": {"code": "InvalidSymbol", "message": "Symbol frxEURUSD is invalid."},
                "req_id": request["req_id"]})
        client.websocket.on_send = respond
        return await client.subscribe_ticks("frxEURUSD")

    assert asyncio.run(go()) is None
    assert client._subscriptions == [{"ticks": "frxEURUSD", "subscribe": 1}]


def test_resubscribe_keeps_transiently_failing_subscription(client):
    """A single failed replay must not drop the subscription."""
    async def go():
        async def fail(request):
            await client._process_message({
                "error": {"code": "ServiceUnavailable", "message": "try again"},
                "req_id": request["req_id"]})
        client.websocket.on_send = fail
        client._subscriptions = [{"ticks": "frxEURUSD", "subscribe": 1}]
        await client._resubscribe()
        return client._subscriptions

    subs = asyncio.run(go())
    assert subs == [{"ticks": "frxEURUSD", "subscribe": 1}]


def test_resubscribe_drops_persistently_failing_subscription(client):
    """After max_resubscribe_retries failures a subscription is dropped so it
    is not retried forever."""
    client.max_resubscribe_retries = 2
    key = DerivClient._sub_key({"ticks": "frxEURUSD", "subscribe": 1})
    client._subscription_failures = {key: 2}

    async def go():
        async def fail(request):
            await client._process_message({
                "error": {"code": "ServiceUnavailable", "message": "down"},
                "req_id": request["req_id"]})
        client.websocket.on_send = fail
        client._subscriptions = [{"ticks": "frxEURUSD", "subscribe": 1}]
        await client._resubscribe()
        return client._subscriptions

    assert asyncio.run(go()) == []
    assert key not in client._subscription_failures


def test_unauthenticated_stream_rejection_logs_auth_hint(client, caplog):
    """A rejected subscription on a token-less connection must point the
    operator at DERIV_API_TOKEN instead of just dumping InvalidSymbol."""
    async def go():
        async def respond(request):
            await client._process_message({
                "error": {"code": "InvalidSymbol", "message": "Symbol frxEURUSD is invalid."},
                "req_id": request["req_id"]})
        client.websocket.on_send = respond
        return await client.subscribe_ticks("frxEURUSD")

    with caplog.at_level(logging.WARNING, logger="broker.deriv"):
        asyncio.run(go())

    assert client._auth_warning_logged is True
    assert "DERIV_API_TOKEN" in caplog.text


# === Helpers ===


def test_granularity_to_timeframe_mapping(client):
    assert client._granularity_to_timeframe(60) == "1m"
    assert client._granularity_to_timeframe(900) == "15m"
    assert client._granularity_to_timeframe(3600) == "1h"
    assert client._granularity_to_timeframe(12345) == "15m"


def test_is_connected(client):
    assert client.is_connected is True
    client.state = ConnectionState.DISCONNECTED
    assert client.is_connected is False
