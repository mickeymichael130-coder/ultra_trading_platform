"""
Offline protocol tests for the Binance WebSocket/REST client.

Exercises trade/kline/error routing, stream subscription tracking and REST
klines normalization against fakes — no network required.
"""
import asyncio
import json
import time

import pytest
import websockets

from src.broker.binance_client import BinanceClient, _KLINE_INTERVAL
from src.broker.deriv_client import ConnectionState, Tick, Candle


class FakeWebSocket:
    """In-memory stand-in for a websockets.WebSocketClientProtocol."""

    def __init__(self, url=""):
        self.url = url
        self.sent = []
        self.closed = False

    async def send(self, payload: str):
        self.sent.append(payload)

    async def recv(self):
        await asyncio.sleep(3600)

    async def close(self):
        self.closed = True
        return None


@pytest.fixture
def client():
    c = BinanceClient(app_id="0", api_token="")
    c.state = ConnectionState.AUTHENTICATED
    c._running = True
    return c


# === Message routing ===


def test_process_trade_routes_to_tick_handler(client):
    received = []
    client.on_tick(received.append)

    asyncio.run(client._process_message({
        "stream": "btcusdt@trade",
        "data": {
            "e": "trade", "E": 1700000000123, "s": "BTCUSDT",
            "t": 12345, "p": "50000.25", "q": "0.01", "T": 1700000000123,
            "m": True, "M": True,
        },
    }))

    assert len(received) == 1
    tick = received[0]
    assert isinstance(tick, Tick)
    assert tick.symbol == "BTCUSDT"
    assert tick.price == 50000.25
    assert tick.timestamp == 1700000000123
    assert tick.mid == 50000.25  # falls back to price (no bid/ask)
    assert tick.pip_size == 1.0  # crypto-aware


def test_process_kline_routes_to_candle_handler(client):
    received = []
    client.on_candle(received.append)

    asyncio.run(client._process_message({
        "stream": "ethusdt@kline_15m",
        "data": {
            "e": "kline", "E": 1700000000123, "s": "ETHUSDT",
            "k": {
                "t": 1700000000000, "T": 1700000899999, "s": "ETHUSDT",
                "i": "15m", "f": 1, "L": 2, "o": "3000.0", "c": "3010.5",
                "h": "3012.0", "l": "2998.0", "v": "120.5", "n": 2,
                "x": True, "q": "362000", "V": "60", "Q": "180000", "B": "0",
            },
        },
    }))

    assert len(received) == 1
    candle = received[0]
    assert isinstance(candle, Candle)
    assert candle.symbol == "ETHUSDT"
    assert candle.timeframe == "15m"
    assert candle.open == 3000.0
    assert candle.high == 3012.0
    assert candle.close == 3010.5
    assert candle.epoch == 1700000000  # ms -> seconds


def test_process_kline_maps_interval_to_timeframe(client):
    received = []
    client.on_candle(received.append)

    asyncio.run(client._process_message({
        "stream": "ethusdt@kline_1h",
        "data": {
            "e": "kline", "E": 1, "s": "ETHUSDT",
            "k": {"t": 1700000000000, "s": "ETHUSDT", "o": "1", "c": "1",
                  "h": "1", "l": "1", "v": "1", "i": "1h"},
        },
    }))

    assert received[0].timeframe == "1h"


def test_process_api_error_routes_to_error_handler(client):
    received = []
    client.on_error(received.append)

    asyncio.run(client._process_message({
        "stream": "btcusdt@trade",
        "data": {"code": -1003, "msg": "Too many requests"},
    }))

    assert len(received) == 1
    assert received[0]["code"] == -1003


# === Subscription tracking ===


def test_subscribe_ticks_tracks_stream(client, monkeypatch):
    async def fake_connect(url, **kwargs):
        client.websocket = FakeWebSocket(url)
        return client.websocket

    monkeypatch.setattr("websockets.connect", fake_connect)

    asyncio.run(client.subscribe_ticks("BTCUSDT"))

    assert "btcusdt@trade" in client._subscriptions
    assert client.websocket is not None


def test_subscribe_candles_tracks_kline_stream(client, monkeypatch):
    async def fake_connect(url, **kwargs):
        client.websocket = FakeWebSocket(url)
        return client.websocket

    def fake_rest(url):
        return [
            [1700000000000, "50000.0", "50100.0", "49900.0", "50050.0",
             "12.5", 1700000899999, "626000", 100, "100", "0", "0", "0"],
        ]

    monkeypatch.setattr("websockets.connect", fake_connect)
    monkeypatch.setattr(client, "_rest_get", fake_rest)

    asyncio.run(client.subscribe_candles("BTCUSDT", "15m", history_count=500))

    assert "btcusdt@kline_15m" in client._subscriptions


def test_stream_url_contains_all_subscriptions(client, monkeypatch):
    client._subscriptions = ["btcusdt@trade", "btcusdt@kline_15m", "btcusdt@kline_1h"]

    async def fake_connect(url, **kwargs):
        client.websocket = FakeWebSocket(url)
        return client.websocket

    monkeypatch.setattr("websockets.connect", fake_connect)

    asyncio.run(client._ensure_streams())

    assert client.websocket is not None
    url = client.websocket.url
    assert url.startswith("wss://stream.binance.com:9443/stream?streams=")
    assert "btcusdt@trade/btcusdt@kline_15m/btcusdt@kline_1h" in url


def test_ensure_streams_reuses_same_url_without_reconnect(client, monkeypatch):
    client._subscriptions = ["btcusdt@trade"]

    async def fake_connect(url, **kwargs):
        client.websocket = FakeWebSocket(url)
        return client.websocket

    monkeypatch.setattr("websockets.connect", fake_connect)

    asyncio.run(client._ensure_streams())
    first = client.websocket

    asyncio.run(client._ensure_streams())
    assert client.websocket is first  # no reconnect churn


# === REST history normalization ===


def test_fetch_history_normalizes_klines(client, monkeypatch):
    rows = [
        [1700000000000, "50000.0", "50100.0", "49900.0", "50050.0", "12.5", 1700000899999],
        [1700000900000, "50050.0", "50200.0", "50000.0", "50100.0", "8.0", 1700001799999],
    ]

    def fake_rest(url):
        assert "symbol=BTCUSDT" in url
        assert "interval=15m" in url
        assert "limit=500" in url
        return rows

    monkeypatch.setattr(client, "_rest_get", fake_rest)

    history = asyncio.run(client.fetch_history("BTCUSDT", "15m", 500))

    assert history is not None
    assert len(history["candles"]) == 2
    first = history["candles"][0]
    assert first["epoch"] == 1700000000  # ms -> seconds
    assert first["open"] == 50000.0
    assert first["close"] == 50050.0
    assert first["volume"] == 12.5


def test_fetch_history_returns_none_on_error(client, monkeypatch):
    def fake_rest(url):
        raise OSError("boom")

    monkeypatch.setattr(client, "_rest_get", fake_rest)

    assert asyncio.run(client.fetch_history("BTCUSDT", "15m")) is None


def test_unsubscribe_all_clears_streams(client, monkeypatch):
    async def fake_connect(url, **kwargs):
        client.websocket = FakeWebSocket(url)
        return client.websocket

    monkeypatch.setattr("websockets.connect", fake_connect)

    asyncio.run(client.subscribe_ticks("BTCUSDT"))
    assert client._subscriptions

    asyncio.run(client.unsubscribe_all())
    assert client._subscriptions == []
    assert client.websocket is None


# === Misc ===


def test_trading_stubs_return_none(client):
    assert asyncio.run(client.buy_contract()) is None
    assert asyncio.run(client.sell_contract()) is None
    assert asyncio.run(client.get_proposal()) is None


def test_interval_mapping_covers_used_timeframes():
    for tf in ("1m", "5m", "15m", "30m", "1h", "4h", "1d"):
        assert _KLINE_INTERVAL[tf] == tf


def test_is_connected_property(client):
    assert client.is_connected is True
    client.state = ConnectionState.DISCONNECTED
    assert client.is_connected is False


# === Reconnect + stale watchdog ===


class _DroppingWS(FakeWebSocket):
    """A socket whose recv() immediately reports ConnectionClosed."""

    async def recv(self):
        raise websockets.exceptions.ConnectionClosed(None, None)


def test_connection_closed_clears_socket_and_reconnects(client, monkeypatch):
    client.reconnect_delay_base = 0.0
    client.reconnect_attempts = 1
    client._subscriptions = ["btcusdt@trade"]
    connects = []

    async def fake_connect(url, **kwargs):
        ws = _DroppingWS(url)
        client.websocket = ws
        connects.append(url)
        return ws

    monkeypatch.setattr("websockets.connect", fake_connect)

    # Pre-existing dead socket — exactly what a dropped stream leaves behind.
    dead = _DroppingWS("wss://old")
    client.websocket = dead
    client._current_stream_url = "wss://old"

    async def scenario():
        await client._receive_loop()
        assert client.websocket is not dead  # dead socket was replaced
        assert len(connects) == 1  # exactly one reconnect attempt
        assert client.state == ConnectionState.AUTHENTICATED
        if client._receive_task is not None:
            client._receive_task.cancel()

    asyncio.run(scenario())


def test_tick_updates_last_tick_time(client):
    asyncio.run(client._process_message({
        "stream": "btcusdt@trade",
        "data": {
            "e": "trade", "E": 1700000000123, "s": "BTCUSDT",
            "t": 12345, "p": "50000.25", "q": "0.01", "T": 1700000000123,
            "m": True, "M": True,
        },
    }))
    assert client._last_tick_time > 0


def test_heartbeat_forces_reconnect_on_stale_stream(client, monkeypatch):
    client.reconnect_delay_base = 0.0
    client.stale_timeout = 60.0
    client.heartbeat_interval = 0.01
    client._subscriptions = ["btcusdt@trade"]
    connects = []

    async def fake_connect(url, **kwargs):
        ws = FakeWebSocket(url)
        client.websocket = ws
        connects.append(url)
        return ws

    monkeypatch.setattr("websockets.connect", fake_connect)

    async def scenario():
        await client._ensure_streams()
        client._last_tick_time = time.time() - 120.0  # way past stale_timeout
        task = asyncio.create_task(client._heartbeat_loop())
        for _ in range(100):
            if len(connects) >= 2:
                break
            await asyncio.sleep(0.01)
        client._running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert len(connects) >= 2  # initial + forced reconnect

    asyncio.run(scenario())


def test_heartbeat_reconnects_when_socket_is_none(client, monkeypatch):
    client.reconnect_delay_base = 0.0
    client.heartbeat_interval = 0.01
    client._subscriptions = ["btcusdt@trade"]
    client._last_tick_time = 0.0  # no data seen yet
    client.websocket = None
    connects = []

    async def fake_connect(url, **kwargs):
        ws = FakeWebSocket(url)
        client.websocket = ws
        connects.append(url)
        return ws

    monkeypatch.setattr("websockets.connect", fake_connect)

    async def scenario():
        task = asyncio.create_task(client._heartbeat_loop())
        for _ in range(100):
            if len(connects) >= 1:
                break
            await asyncio.sleep(0.01)
        client._running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert len(connects) >= 1

    asyncio.run(scenario())
