"""
Deriv WebSocket Client
Handles connection, authentication, and message routing.
Isolates all Deriv API communication.
"""
import asyncio
import json
import time
import websockets
from typing import Callable, Dict, Optional, Any, List

from ..core.domain import Account, ConnectionState, MarketTick as Tick, Candle
from ..utils.logger import get_logger
from .base_broker import BaseBroker

# Back-compat re-exports so existing imports keep working during migration
# to the broker-neutral core domain models.
__all__ = ["DerivClient", "ConnectionState", "Tick", "Candle", "MarketTick"]


# Deriv granularity (seconds) keyed by timeframe string.
_GRANULARITY = {
    "1m": 60, "5m": 300, "15m": 900,
    "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400
}


class DerivClient(BaseBroker):
    """
    WebSocket client for Deriv API.

    Responsibilities:
    - Connect/Disconnect
    - Authenticate
    - Subscribe to ticks/candles
    - Reconnect with exponential backoff
    - Route incoming messages to handlers
    """

    def __init__(
        self,
        app_id: str,
        api_token: str,
        websocket_url: str = "wss://ws.derivws.com/websockets/v3",
        reconnect_attempts: int = 10,
        reconnect_delay_base: float = 1.0,
        reconnect_delay_max: float = 60.0,
        heartbeat_interval: int = 30
    ):
        self.app_id = app_id
        self.api_token = api_token
        self.websocket_url = f"{websocket_url}?app_id={app_id}"
        self.reconnect_attempts = reconnect_attempts
        self.reconnect_delay_base = reconnect_delay_base
        self.reconnect_delay_max = reconnect_delay_max
        self.heartbeat_interval = heartbeat_interval

        self.logger = get_logger("broker.deriv")
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.state = ConnectionState.DISCONNECTED

        # Message routing
        self._tick_handlers: List[Callable[[Tick], None]] = []
        self._candle_handlers: List[Callable[[Candle], None]] = []
        self._error_handlers: List[Callable[[Dict], None]] = []
        self._balance_handlers: List[Callable[[Dict], None]] = []

        # Request tracking
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._request_counter = 0
        self._last_request_error: Optional[Dict] = None
        self._auth_warning_logged = False

        # Tasks
        self._receive_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._running = False

        # Connection metadata
        self._last_pong_time: float = 0
        self._account_info: Optional[Dict] = None

        # Active subscriptions (replay order on reconnect)
        self._subscriptions: List[Dict] = []
        self._subscription_failures: Dict[str, int] = {}
        self.max_resubscribe_retries = 5

    # === Registration Methods ===

    def on_tick(self, handler: Callable[[Tick], None]):
        """Register tick handler"""
        self._tick_handlers.append(handler)
        self.logger.debug(f"Tick handler registered. Total: {len(self._tick_handlers)}")

    def on_candle(self, handler: Callable[[Candle], None]):
        """Register candle handler"""
        self._candle_handlers.append(handler)
        self.logger.debug(f"Candle handler registered. Total: {len(self._candle_handlers)}")

    def on_error(self, handler: Callable[[Dict], None]):
        """Register error handler"""
        self._error_handlers.append(handler)

    def on_balance_update(self, handler: Callable[[Dict], None]):
        """Register balance update handler"""
        self._balance_handlers.append(handler)

    # === Connection Management ===

    async def connect(self) -> bool:
        """Establish WebSocket connection with authentication"""
        self._running = True
        self.state = ConnectionState.CONNECTING

        try:
            self.logger.info(f"Connecting to Deriv: {self.websocket_url}")
            self.websocket = await websockets.connect(self.websocket_url)
            self.state = ConnectionState.CONNECTED
            self.logger.info("WebSocket connected")

            # Start receive loop
            self._receive_task = asyncio.create_task(self._receive_loop())

            # Authenticate only when a token is provided. Public market data
            # (ticks/candles) does not require authorization, so paper mode can
            # run without a token. Live trading always requires one.
            if self.api_token:
                if await self._authenticate():
                    self.state = ConnectionState.AUTHENTICATED
                    self.logger.info("Authentication successful")

                    # Start heartbeat
                    self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                    # Get account info
                    await self._get_account_info()

                    return True
                else:
                    self.state = ConnectionState.ERROR
                    return False
            else:
                self.state = ConnectionState.AUTHENTICATED
                self.logger.info("Connected unauthenticated (no API token provided)")

                # Start heartbeat
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

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._receive_task:
            self._receive_task.cancel()

        if self.websocket:
            await self.websocket.close()
            self.websocket = None

        self.logger.info("Disconnected from Deriv")

    async def _reconnect(self):
        """Reconnect with exponential backoff"""
        self.state = ConnectionState.RECONNECTING

        for attempt in range(1, self.reconnect_attempts + 1):
            delay = min(
                self.reconnect_delay_base * (2 ** (attempt - 1)),
                self.reconnect_delay_max
            )

            self.logger.warning(
                f"Reconnecting in {delay:.1f}s (attempt {attempt}/{self.reconnect_attempts})"
            )
            await asyncio.sleep(delay)

            if await self.connect():
                # Resubscribe to previous subscriptions
                await self._resubscribe()
                return True

        self.logger.error("Max reconnection attempts reached")
        self.state = ConnectionState.ERROR
        return False

    # === Authentication ===

    async def _authenticate(self) -> bool:
        """Authorize with API token"""
        response = await self._send_request({
            "authorize": self.api_token
        })

        if response and "authorize" in response:
            self._account_info = response["authorize"]
            return True

        self.logger.error(f"Authentication failed: {response}")
        return False

    async def _get_account_info(self):
        """Fetch account details"""
        response = await self._send_request({"balance": 1})
        if response and "balance" in response:
            self.logger.info(
                f"Account balance: {response['balance']['balance']} "
                f"{response['balance']['currency']}"
            )

    # === Subscription Methods ===

    async def subscribe_ticks(self, symbol: str):
        """Subscribe to real-time ticks"""
        request = {
            "ticks": symbol,
            "subscribe": 1
        }
        # Track BEFORE sending so a mid-request disconnect does not lose the
        # subscription; _resubscribe replays it after reconnect.
        if request not in self._subscriptions:
            self._subscriptions.append(request)
        response = await self._send_request(request)
        if response is not None:
            self.logger.info(f"Subscribed to ticks: {symbol}")
        else:
            self._warn_subscription_failed(symbol, request)
        return response

    async def subscribe_candles(self, symbol: str, timeframe: str = "1m", history_count: int = 500):
        """Subscribe to candle updates (requires auth for streaming)"""
        request = {
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count": history_count,
            "end": "latest",
            "granularity": _GRANULARITY.get(timeframe, 900),
            "style": "candles",
            "subscribe": 1
        }

        # Track BEFORE sending so the subscription survives a mid-request
        # disconnect and is replayed by _resubscribe on reconnect.
        if request not in self._subscriptions:
            self._subscriptions.append(request)
        response = await self._send_request(request)
        if response is not None:
            self.logger.info(f"Subscribed to candles: {symbol} ({timeframe})")
        else:
            self._warn_subscription_failed(symbol, request)
        return response

    async def fetch_history(self, symbol: str, timeframe: str = "1m", count: int = 500) -> Optional[Dict]:
        """One-shot historical candle fetch (no subscription).

        Works without an API token, unlike subscribe_candles. Useful for
        backtests and pre-seeding the candle builder.
        """
        request = {
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count": count,
            "end": "latest",
            "granularity": _GRANULARITY.get(timeframe, 900),
            "style": "candles",
        }
        response = await self._send_request(request)
        if response is None:
            self._warn_subscription_failed(symbol, request)
        return response

    def _warn_subscription_failed(self, symbol: str, request: Dict):
        """Explain a rejected subscription so the operator can act on it."""
        err = self._last_request_error
        if err and err.get("code") == "InvalidSymbol" and not self.api_token:
            if not self._auth_warning_logged:
                self._auth_warning_logged = True
                self.logger.warning(
                    "Streaming market data requires a Deriv API token: the server "
                    f"rejected the subscription for {symbol} with InvalidSymbol on this "
                    "unauthenticated connection. Set DERIV_API_TOKEN in .env to enable "
                    "paper/live streaming (one-shot ticks_history still works without a token)."
                )
            else:
                self.logger.warning(f"Subscription failed for {symbol} ({err.get('code')}); will retry on reconnect.")
        else:
            self.logger.warning(f"Subscription failed for {symbol}: {err or 'no response'}; will retry on reconnect.")

    async def unsubscribe_all(self):
        """Unsubscribe from all streams"""
        await self._send_request({"forget_all": "ticks"})
        await self._send_request({"forget_all": "candles"})
        self._subscriptions.clear()
        self.logger.info("Unsubscribed from all streams")

    # === Trading Operations ===

    async def buy_contract(
        self,
        symbol: str,
        contract_type: str,  # CALL or PUT for forex
        amount: float,
        duration: int,
        duration_unit: str = "m",
        basis: str = "stake"
    ) -> Optional[Dict]:
        """
        Place a buy order (Deriv's contract model).
        For forex, this uses rise/fall or higher/lower contracts.
        """
        request = {
            "buy": 1,
            "price": amount,
            "parameters": {
                "amount": amount,
                "basis": basis,
                "contract_type": contract_type,
                "currency": "USD",
                "duration": duration,
                "duration_unit": duration_unit,
                "symbol": symbol
            }
        }

        self.logger.info(
            f"Placing order: {symbol} | {contract_type} | ${amount} | "
            f"{duration}{duration_unit}"
        )

        return await self._send_request(request)

    async def sell_contract(self, contract_id: str, price: Optional[float] = None) -> Optional[Dict]:
        """Sell/close an open contract"""
        request = {"sell": contract_id}
        if price:
            request["price"] = price

        self.logger.info(f"Closing contract: {contract_id}")
        return await self._send_request(request)

    async def get_proposal(
        self,
        symbol: str,
        contract_type: str,
        amount: float,
        duration: int,
        duration_unit: str = "m",
        barrier: Optional[float] = None
    ) -> Optional[Dict]:
        """Get contract pricing/proposal before buying"""
        parameters = {
            "amount": amount,
            "basis": "stake",
            "contract_type": contract_type,
            "currency": "USD",
            "duration": duration,
            "duration_unit": duration_unit,
            "symbol": symbol
        }

        if barrier:
            parameters["barrier"] = barrier

        request = {
            "proposal": 1,
            "subscribe": 0,
            **parameters
        }

        return await self._send_request(request)

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
        """Route incoming messages to appropriate handlers"""

        # Resolve any pending request future FIRST. Subscription and history
        # responses (tick/ohlc/candles/balance/error) all carry a req_id, so
        # this must run before the data branches or _send_request times out.
        if "req_id" in data:
            req_id = str(data["req_id"])
            if req_id in self._pending_requests:
                future = self._pending_requests.pop(req_id)
                if not future.done():
                    future.set_result(data)

        # Tick update
        if "tick" in data:
            tick_data = data["tick"]
            tick = Tick(
                symbol=tick_data["symbol"],
                price=tick_data["quote"],
                timestamp=tick_data["epoch"] * 1000,
                bid=tick_data.get("bid"),
                ask=tick_data.get("ask")
            )
            for handler in self._tick_handlers:
                try:
                    handler(tick)
                except Exception as e:
                    self.logger.error(f"Tick handler error: {e}")

        # Candle update (ohlc)
        elif "ohlc" in data:
            ohlc = data["ohlc"]
            candle = Candle(
                symbol=ohlc["symbol"],
                timeframe=self._granularity_to_timeframe(ohlc.get("granularity", 900)),
                open=float(ohlc["open"]),
                high=float(ohlc["high"]),
                low=float(ohlc["low"]),
                close=float(ohlc["close"]),
                volume=int(ohlc.get("volume", 0)),
                epoch=ohlc["epoch"]
            )
            for handler in self._candle_handlers:
                try:
                    handler(candle)
                except Exception as e:
                    self.logger.error(f"Candle handler error: {e}")

        # Historical candles (initial load)
        elif "candles" in data:
            for c in data["candles"]:
                candle = Candle(
                    symbol=data.get("echo_req", {}).get("ticks_history", "unknown"),
                    timeframe=self._granularity_to_timeframe(
                        data.get("echo_req", {}).get("granularity", 900)
                    ),
                    open=float(c["open"]),
                    high=float(c["high"]),
                    low=float(c["low"]),
                    close=float(c["close"]),
                    volume=int(c.get("volume", 0)),
                    epoch=c["epoch"]
                )
                for handler in self._candle_handlers:
                    try:
                        handler(candle)
                    except Exception as e:
                        self.logger.error(f"Candle handler error: {e}")

        # Balance update
        elif "balance" in data:
            for handler in self._balance_handlers:
                try:
                    handler(data["balance"])
                except Exception as e:
                    self.logger.error(f"Balance handler error: {e}")

        # Error
        elif "error" in data:
            self.logger.error(f"API Error: {data['error']}")
            for handler in self._error_handlers:
                try:
                    handler(data["error"])
                except Exception as e:
                    self.logger.error(f"Error handler error: {e}")

        # Response to request (resolve pending future)
        elif "req_id" in data:
            req_id = str(data["req_id"])
            if req_id in self._pending_requests:
                future = self._pending_requests.pop(req_id)
                if not future.done():
                    future.set_result(data)

        # Pong
        elif "pong" in data:
            self._last_pong_time = time.time()

    async def _send_request(self, request: Dict) -> Optional[Dict]:
        """Send request and wait for response"""
        if not self.websocket or self.state not in (ConnectionState.CONNECTED, ConnectionState.AUTHENTICATED):
            self.logger.error("Cannot send request: not connected")
            return None

        self._request_counter += 1
        req_id = str(self._request_counter)
        # Send a copy so the caller's dict (e.g. a tracked subscription) is
        # not mutated with a stale req_id.
        request = {**request, "req_id": req_id}

        # Create future for response
        future = asyncio.get_event_loop().create_future()
        self._pending_requests[req_id] = future

        try:
            await self.websocket.send(json.dumps(request))

            # Wait for response with timeout
            response = await asyncio.wait_for(future, timeout=10.0)

            if "error" in response:
                self._last_request_error = response["error"]
                self.logger.error(f"Request error: {response['error']}")
                return None

            return response

        except asyncio.TimeoutError:
            self.logger.error(f"Request timeout: {request}")
            self._pending_requests.pop(req_id, None)
            return None
        except Exception as e:
            self.logger.error(f"Request failed: {e}")
            self._pending_requests.pop(req_id, None)
            return None

    async def _heartbeat_loop(self):
        """Send periodic ping to keep connection alive"""
        while self._running and self.websocket:
            try:
                await self.websocket.send(json.dumps({"ping": 1}))
                await asyncio.sleep(self.heartbeat_interval)
            except Exception as e:
                self.logger.warning(f"Heartbeat error: {e}")
                break

    async def _resubscribe(self):
        """Resubscribe to active streams after reconnect.

        Requests are tracked before they are sent, so subscriptions attempted
        while the connection dropped are still replayed here. A request that
        keeps failing (e.g. an invalid symbol) is dropped after a bounded
        number of attempts instead of retrying forever.
        """
        if not self._subscriptions:
            return

        restored = 0
        failed = 0
        for request in list(self._subscriptions):
            response = await self._send_request(request)
            if response is not None:
                self._subscription_failures.pop(self._sub_key(request), None)
                restored += 1
            else:
                key = self._sub_key(request)
                self._subscription_failures[key] = self._subscription_failures.get(key, 0) + 1
                if self._subscription_failures[key] >= self.max_resubscribe_retries:
                    self._subscriptions.remove(request)
                    self._subscription_failures.pop(key, None)
                    self.logger.warning(f"Dropping persistently failing subscription: {request}")
                else:
                    failed += 1

        self.logger.info(
            f"Resubscribed to {len(self._subscriptions) + restored + failed} tracked streams "
            f"(restored {restored}, pending {failed})"
        )

    @staticmethod
    def _sub_key(request: Dict) -> str:
        """Stable dict key for tracking per-subscription failures."""
        return json.dumps(request, sort_keys=True)

    def _granularity_to_timeframe(self, granularity: int) -> str:
        """Convert Deriv granularity to timeframe string"""
        mapping = {
            60: "1m", 300: "5m", 900: "15m",
            1800: "30m", 3600: "1h", 14400: "4h", 86400: "1d"
        }
        return mapping.get(granularity, "15m")

    async def ping(self) -> Optional[float]:
        """Round-trip latency of a Deriv API request in milliseconds."""
        if not self.websocket or self.state != ConnectionState.AUTHENTICATED:
            return None
        start = time.time()
        response = await self._send_request({"time": 1})
        if response is None:
            return None
        return (time.time() - start) * 1000

    @property
    def is_connected(self) -> bool:
        return self.state == ConnectionState.AUTHENTICATED

    @property
    def account_balance(self) -> Optional[float]:
        if self._account_info:
            return self._account_info.get("balance")
        return None

    async def get_balance(self) -> Optional[Account]:
        if not self._account_info:
            return None
        return Account(
            broker="deriv",
            balance=self._account_info.get("balance", 0.0),
            currency=self._account_info.get("currency", "USD"),
            equity=self._account_info.get("equity"),
        )
