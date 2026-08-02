"""
Binance WebSocket + REST Client
Provides token-free public market data (ticks/candles/history) for paper mode.
Implements the same public interface as DerivClient so the orchestrator treats
both brokers interchangeably. Trading methods are stubbed out: Binance order
placement is not needed for paper validation and is out of scope here.
"""
import asyncio
import json
import time
import urllib.request
from typing import Callable, Dict, Optional, Any, List

import websockets

from ..core.domain import ConnectionState, MarketTick as Tick, Candle
from ..utils.logger import get_logger
from ..utils.pips import get_pip_size
from .base_broker import BaseBroker

# Binance kline interval for a timeframe string (subset used by the stack).
_KLINE_INTERVAL = {
    "1m": "1m", "5m": "5m", "15m": "15m",
    "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d",
}
_INTERVAL_TO_TIMEFRAME = {v: k for k, v in _KLINE_INTERVAL.items()}

_REST_BASE = "https://api.binance.com"
_STREAM_BASE = "wss://stream.binance.com:9443"


class BinanceClient(BaseBroker):
    """
    Token-free Binance market data client.

    Responsibilities:
    - Connect/Disconnect
    - Subscribe to trade ticks and kline streams (combined stream URL)
    - One-shot REST klines history for backfills and backtests
    - Reconnect with exponential backoff
    - Route incoming messages to handlers (same shape as DerivClient)
    """

    def __init__(
        self,
        app_id: str = "0",
        api_token: str = "",
        websocket_url: str = "",
        reconnect_attempts: int = 10,
        reconnect_delay_base: float = 1.0,
        reconnect_delay_max: float = 60.0,
        heartbeat_interval: int = 30,
        rest_base: str = _REST_BASE,
        stream_base: str = _STREAM_BASE,
        request_timeout: float = 10.0
    ):
        # Params mirror DerivClient's signature for drop-in wiring.
        self.app_id = app_id
        self.api_token = api_token
        self.reconnect_attempts = reconnect_attempts
        self.reconnect_delay_base = reconnect_delay_base
        self.reconnect_delay_max = reconnect_delay_max
        self.heartbeat_interval = heartbeat_interval
        self.rest_base = rest_base.rstrip("/")
        self.stream_base = stream_base.rstrip("/")
        self.request_timeout = request_timeout

        self.logger = get_logger("broker.binance")
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.state = ConnectionState.DISCONNECTED

        # Message routing (same registration API as DerivClient)
        self._tick_handlers: List[Callable[[Tick], None]] = []
        self._candle_handlers: List[Callable[[Candle], None]] = []
        self._error_handlers: List[Callable[[Dict], None]] = []
        self._balance_handlers: List[Callable[[Dict], None]] = []

        # Tasks
        self._receive_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._refresh_task: Optional[asyncio.Task] = None
        self._running = False

        # Connection metadata
        self._last_pong_time: float = 0
        self._current_stream_url: Optional[str] = None

        # Active subscriptions: Binance stream names (e.g. "btcusdt@trade"),
        # combined into the stream URL. Tracked before sending so a mid-request
        # disconnect does not lose them; _ensure_streams replays after reconnect.
        self._subscriptions: List[str] = []
        self._subscription_failures: Dict[str, int] = {}
        self.max_resubscribe_retries = 5
        self._refresh_debounce_seconds = 0.3
        self._reconnecting = False

    # === Registration Methods (same API as DerivClient) ===

    def on_tick(self, handler: Callable[[Tick], None]):
        self._tick_handlers.append(handler)

    def on_candle(self, handler: Callable[[Candle], None]):
        self._candle_handlers.append(handler)

    def on_error(self, handler: Callable[[Dict], None]):
        self._error_handlers.append(handler)

    def on_balance_update(self, handler: Callable[[Dict], None]):
        self._balance_handlers.append(handler)

    # === Connection Management ===

    async def connect(self) -> bool:
        """Connect: verify REST reachability, then open the stream socket."""
        self._running = True
        self.state = ConnectionState.CONNECTING

        try:
            self.logger.info(f"Connecting to Binance (public market data): {self.rest_base}")
            ping = await asyncio.get_event_loop().run_in_executor(
                None, self._rest_get, f"{self.rest_base}/api/v3/ping"
            )
            if ping != {}:
                self.logger.error(f"Unexpected ping response: {ping}")
                self.state = ConnectionState.ERROR
                return False

            self.state = ConnectionState.AUTHENTICATED
            self.logger.info("Connected to Binance (no auth required for market data)")

            await self._ensure_streams()
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            return True

        except Exception as e:
            self.logger.error(f"Connection failed: {e}")
            self.state = ConnectionState.ERROR
            return False

    async def disconnect(self):
        """Graceful disconnect"""
        self._running = False
        self.state = ConnectionState.DISCONNECTED
        self._reconnecting = False

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._refresh_task:
            self._refresh_task.cancel()
        await self._close_ws()
        self.logger.info("Disconnected from Binance")

    async def _close_ws(self):
        """Close the stream socket and its receive loop (bounded, never hangs)."""
        if self._receive_task:
            self._receive_task.cancel()
            self._receive_task = None
        ws = self.websocket
        self.websocket = None
        self._current_stream_url = None
        if ws is not None:
            try:
                await asyncio.wait_for(ws.close(), timeout=1.5)
            except Exception:
                pass

    async def _reconnect(self):
        """Reconnect with exponential backoff (streams are re-derived from
        _subscriptions). Concurrent callers are coalesced onto one attempt."""
        if self._reconnecting:
            return False
        self._reconnecting = True
        self.state = ConnectionState.RECONNECTING

        try:
            for attempt in range(1, self.reconnect_attempts + 1):
                if not self._running:
                    return False
                delay = min(
                    self.reconnect_delay_base * (2 ** (attempt - 1)),
                    self.reconnect_delay_max
                )
                self.logger.warning(
                    f"Reconnecting in {delay:.1f}s (attempt {attempt}/{self.reconnect_attempts})"
                )
                await asyncio.sleep(delay)

                try:
                    await self._ensure_streams()
                    if self.websocket is not None:
                        self.state = ConnectionState.AUTHENTICATED
                        self.logger.info("Reconnected to Binance")
                        return True
                except Exception as e:
                    self.logger.warning(f"Reconnect attempt failed: {e}")

            self.logger.error("Max reconnection attempts reached")
            self.state = ConnectionState.ERROR
            return False
        finally:
            self._reconnecting = False

    # === Subscription Methods ===

    async def subscribe_ticks(self, symbol: str):
        """Subscribe to real-time trade ticks."""
        stream = f"{symbol.lower()}@trade"
        if stream not in self._subscriptions:
            self._subscriptions.append(stream)
        await self._refresh_streams()
        if self.websocket is not None:
            self.logger.info(f"Subscribed to ticks: {symbol}")
        else:
            self.logger.warning(f"Tick stream for {symbol} not yet connected")
        return {"ok": True}

    async def subscribe_candles(self, symbol: str, timeframe: str = "1m", history_count: int = 500):
        """Subscribe to kline stream and backfill history via REST.

        Returns a Deriv-shaped history dict ({"candles": [...]}) so the
        orchestrator's _seed_history works unchanged. Streaming kline updates
        are delivered to candle handlers as they arrive.
        """
        interval = _KLINE_INTERVAL.get(timeframe, "15m")
        stream = f"{symbol.lower()}@kline_{interval}"
        if stream not in self._subscriptions:
            self._subscriptions.append(stream)

        history = await self.fetch_history(symbol, timeframe, history_count)
        if history is None:
            self._warn_subscription_failed(symbol)

        await self._refresh_streams()
        return history

    async def _refresh_streams(self):
        """Reconnect the combined stream socket, coalescing bursts of
        subscribe calls so a startup burst shares a single connection.

        subscribe_ticks/candles are called back-to-back for each symbol;
        debouncing keeps them to one reconnect instead of one per stream.
        """
        if self._refresh_task is not None and not self._refresh_task.done():
            await self._refresh_task
            return

        async def _delayed():
            await asyncio.sleep(self._refresh_debounce_seconds)
            await self._ensure_streams()

        self._refresh_task = asyncio.create_task(_delayed())
        try:
            await self._refresh_task
        finally:
            self._refresh_task = None

    async def fetch_history(self, symbol: str, timeframe: str = "1m", count: int = 500) -> Optional[Dict]:
        """One-shot historical klines via REST (no subscription, no auth)."""
        interval = _KLINE_INTERVAL.get(timeframe, "15m")
        url = (
            f"{self.rest_base}/api/v3/klines?"
            f"symbol={symbol}&interval={interval}&limit={min(int(count), 1000)}"
        )
        try:
            rows = await asyncio.get_event_loop().run_in_executor(
                None, self._rest_get, url
            )
        except Exception as e:
            self.logger.error(f"History fetch failed for {symbol}: {e}")
            return None

        candles = []
        for row in rows:
            # Binance kline row:
            # [openTime, open, high, low, close, volume, closeTime, ...]
            candles.append({
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "epoch": int(row[0]) // 1000,  # ms -> seconds (Deriv epoch)
            })
        return {"candles": candles}

    def _warn_subscription_failed(self, symbol: str):
        err = getattr(self, "_last_request_error", None)
        self.logger.warning(f"Subscription/history failed for {symbol}: {err or 'no response'}")

    async def unsubscribe_all(self):
        """Unsubscribe from all streams"""
        self._subscriptions.clear()
        await self._close_ws()
        self.logger.info("Unsubscribed from all streams")

    # === Trading Operations (stubbed: paper data broker) ===

    async def buy_contract(self, *args, **kwargs) -> Optional[Dict]:
        self.logger.warning("buy_contract is not supported on Binance (paper data broker)")
        return None

    async def sell_contract(self, *args, **kwargs) -> Optional[Dict]:
        self.logger.warning("sell_contract is not supported on Binance (paper data broker)")
        return None

    async def get_proposal(self, *args, **kwargs) -> Optional[Dict]:
        self.logger.warning("get_proposal is not supported on Binance (paper data broker)")
        return None

    # === Stream Management ===

    async def _ensure_streams(self):
        """Open (or refresh) the combined stream socket for _subscriptions."""
        if not self._running or not self._subscriptions:
            return

        url = f"{self.stream_base}/stream?streams=" + "/".join(self._subscriptions)
        if self.websocket is not None and self._current_stream_url == url:
            return

        await self._close_ws()
        self._current_stream_url = url

        try:
            self.websocket = await websockets.connect(
                url, open_timeout=15, close_timeout=2, max_queue=None
            )
            self.state = ConnectionState.AUTHENTICATED
            self._receive_task = asyncio.create_task(self._receive_loop())
            self.logger.info(f"Stream connected ({len(self._subscriptions)} streams)")
        except Exception as e:
            self.logger.error(f"Stream connection failed: {e}")
            self.state = ConnectionState.ERROR

    async def _resubscribe(self):
        """Re-open the stream socket for all tracked subscriptions."""
        await self._ensure_streams()
        return True

    # === Message Handling ===

    async def _receive_loop(self):
        """Main message receiving loop"""
        while self._running and self.websocket:
            try:
                message = await self.websocket.recv()
                data = json.loads(message)
                await self._process_message(data)
            except websockets.exceptions.ConnectionClosed:
                self.logger.warning("WebSocket connection closed")
                if self._running:
                    await self._reconnect()
                break
            except Exception as e:
                self.logger.error(f"Receive error: {e}")
                await asyncio.sleep(1)

    async def _process_message(self, data: Dict):
        """Route a combined-stream payload to the appropriate handlers."""
        payload = data.get("data", data)
        event = payload.get("e")

        if event == "trade":
            symbol = payload["s"]
            tick = Tick(
                symbol=symbol,
                price=float(payload["p"]),
                timestamp=int(payload["T"]),
                bid=None,
                ask=None,
                pip_size=get_pip_size(symbol),
            )
            for handler in self._tick_handlers:
                try:
                    handler(tick)
                except Exception as e:
                    self.logger.error(f"Tick handler error: {e}")

        elif event == "kline":
            k = payload["k"]
            candle = Candle(
                symbol=k["s"],
                timeframe=_INTERVAL_TO_TIMEFRAME.get(k["i"], "15m"),
                open=float(k["o"]),
                high=float(k["h"]),
                low=float(k["l"]),
                close=float(k["c"]),
                volume=float(k["v"]),
                epoch=int(k["t"]) // 1000,
            )
            for handler in self._candle_handlers:
                try:
                    handler(candle)
                except Exception as e:
                    self.logger.error(f"Candle handler error: {e}")

        elif "code" in payload and "msg" in payload:
            self.logger.error(f"Binance API error: {payload}")
            for handler in self._error_handlers:
                try:
                    handler(payload)
                except Exception as e:
                    self.logger.error(f"Error handler error: {e}")
        else:
            self.logger.debug(f"Unhandled stream message: {event or data}")

    # === REST Helper ===

    def _rest_get(self, url: str) -> Any:
        """Blocking GET returning parsed JSON. Runs in an executor by callers."""
        req = urllib.request.Request(url, headers={"User-Agent": "ultra-trading/1.0"})
        with urllib.request.urlopen(req, timeout=self.request_timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # === Heartbeat / Liveness ===

    async def _heartbeat_loop(self):
        """Keep-alive: verify the stream socket is alive. websockets handles
        protocol-level ping/pong, so this just guards the receive loop and
        never races an in-flight refresh/reconnect."""
        while self._running:
            await asyncio.sleep(self.heartbeat_interval)
            refresh_pending = self._refresh_task is not None and not self._refresh_task.done()
            if (self.websocket is None and self._running and self._subscriptions
                    and not refresh_pending):
                self.logger.warning("Stream socket is dead; reconnecting")
                await self._reconnect()

    async def ping(self) -> Optional[float]:
        """Round-trip latency of a public REST ping in milliseconds."""
        start = time.time()
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, self._rest_get, f"{self.rest_base}/api/v3/ping"
            )
            return (time.time() - start) * 1000
        except Exception:
            return None

    # === Properties ===

    @property
    def is_connected(self) -> bool:
        return self.state in (ConnectionState.CONNECTED, ConnectionState.AUTHENTICATED)

    @property
    def account_balance(self) -> Optional[float]:
        return None
