"""
Trading Orchestrator
The main engine that coordinates all layers.
Connects the pipeline: Ticks → Candles → Indicators → Signals → Risk → Execution → Positions → Database
"""
import asyncio
import os
import signal as os_signal
from datetime import datetime, timedelta
from typing import Dict, Optional

from .core.domain import Tick, Candle
from .broker.broker_factory import get_broker_class
from .data_engine.candle_builder import CandleBuilder
from .indicators.technical import IndicatorEngine, MarketSnapshot
from .strategies.ema_crossover import EMACrossoverStrategy, TradeSignal, SignalDirection
from .risk.manager import RiskManager, RiskResult, RiskDecision
from .execution.engine import ExecutionEngine, ExecutionMode
from .position_manager.manager import PositionManager, ExitReason
from .database.manager import DatabaseManager
from .ai_lab.signal_enhancer import SignalEnhancer
from .utils.logger import get_logger
from config.settings import BotConfig, config as default_config


# Default symbols per broker. Crypto pairs trade 24/7 and need no token.
_DEFAULT_SYMBOLS = {
    "deriv": ["frxEURUSD", "frxGBPUSD", "frxUSDJPY", "frxAUDUSD"],
    "binance": ["BTCUSDT", "ETHUSDT"],
}


class TradingOrchestrator:
    """
    Main trading engine orchestrator.

    Runtime Flow:
    1. Connect to Deriv
    2. Subscribe to ticks/candles for configured symbols
    3. On each tick: update candle builder
    4. On each completed candle: calculate indicators, generate signals
    5. On each signal: risk evaluation
    6. On approved signal: execute trade
    7. Position manager monitors open trades
    8. Database persists everything
    9. Health checks run continuously

    Handles graceful shutdown and state recovery.
    """

    def __init__(
        self,
        app_id: str = None,
        api_token: str = None,
        symbols: list = None,
        mode: str = "paper",
        db_path: str = "data/ultra.db",
        broker_cls=None,
        broker_type: str = None,
        settings: BotConfig = None
    ):
        # Credentials
        self.app_id = app_id or os.getenv("DERIV_APP_ID", "1089")
        self.api_token = api_token or os.getenv("DERIV_API_TOKEN", "")
        self.settings = settings if settings is not None else default_config
        self.broker_type = (broker_type or self.settings.broker.broker_type or "deriv").lower()
        self.broker_cls = broker_cls or get_broker_class(self.broker_type)
        self.symbols = symbols or list(_DEFAULT_SYMBOLS.get(self.broker_type, _DEFAULT_SYMBOLS["deriv"]))
        self.mode = ExecutionMode.PAPER if mode == "paper" else ExecutionMode.LIVE

        self.logger = get_logger("orchestrator")
        self.logger.info(f"Orchestrator initializing | Mode: {mode} | Broker: {self.broker_type} | Symbols: {self.symbols}")

        # Initialize all layers
        self._init_layers(db_path)

        # State tracking
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._last_snapshots: Dict[str, MarketSnapshot] = {}  # symbol -> snapshot
        self._last_signals: Dict[str, TradeSignal] = {}  # symbol -> signal
        self._confirmation_snapshots: Dict[str, MarketSnapshot] = {}  # symbol -> 1h snapshot
        self._health_status = {"status": "initializing", "last_tick": None}

        # Statistics
        self._stats = {
            "ticks_received": 0,
            "candles_completed": 0,
            "signals_generated": 0,
            "signals_approved": 0,
            "trades_executed": 0,
            "errors": 0,
            "start_time": None
        }

    def _init_layers(self, db_path: str):
        """Initialize all system layers"""
        s = self.settings

        # Layer 1: Database (foundation)
        self.db = DatabaseManager(db_path or s.database.sqlite_path)
        self.logger.info("✅ Database layer initialized")

        # Layer 2: Broker
        bc = s.broker
        self.broker = self.broker_cls(
            app_id=self.app_id or bc.app_id,
            api_token=self.api_token or bc.api_token,
            reconnect_attempts=bc.reconnect_attempts,
            reconnect_delay_base=bc.reconnect_delay_base,
            reconnect_delay_max=bc.reconnect_delay_max,
            heartbeat_interval=bc.heartbeat_interval,
        )
        self.broker.on_tick(self._on_tick)
        self.broker.on_candle(self._on_candle)
        self.logger.info("✅ Broker layer initialized")

        # Layer 3: Data Engine
        dec = s.data_engine
        self.candle_builder = CandleBuilder(
            timeframes=dec.candle_timeframes,
            tick_buffer_size=dec.tick_buffer_size,
            max_candles=dec.max_candles_in_memory,
        )
        self.candle_builder.on_candle_complete(self._on_candle_complete)
        self.logger.info("✅ Data engine initialized")

        # Layer 4: Indicators
        ic = s.indicators
        self.indicator_engine = IndicatorEngine(
            ema_fast=ic.ema_fast,
            ema_slow=ic.ema_slow,
            ema_trend=ic.ema_trend,
            rsi_period=ic.rsi_period,
            atr_period=ic.atr_period,
            macd_fast=ic.macd_fast,
            macd_slow=ic.macd_slow,
            macd_signal=ic.macd_signal,
            bb_period=ic.bb_period,
            bb_std=ic.bb_std,
            adx_period=ic.adx_period,
        )
        self.logger.info("✅ Indicator engine initialized")

        # Layer 5: Strategy
        sc = s.strategy
        self.strategy = EMACrossoverStrategy(
            min_atr_pips=sc.min_atr_pips,
            min_confidence=sc.min_confidence,
            rsi_overbought=ic.rsi_overbought,
            rsi_oversold=ic.rsi_oversold,
            adx_threshold=ic.adx_threshold,
            trade_london=sc.trade_london,
            trade_ny=sc.trade_ny,
            trade_asian=sc.trade_asian,
        )
        self.logger.info("✅ Strategy engine initialized")

        # Layer 6: Risk (load persisted state)
        rc = s.risk
        risk_state = self.db.load_risk_state()
        self.risk_manager = RiskManager(
            initial_capital=risk_state.get('current_balance', rc.initial_capital),
            max_risk_per_trade_pct=rc.max_risk_per_trade_pct,
            max_risk_per_trade_abs=rc.max_risk_per_trade_absolute,
            max_daily_loss_pct=rc.max_daily_loss_pct,
            max_daily_loss_abs=rc.max_daily_loss_absolute,
            max_drawdown_pct=rc.max_drawdown_pct,
            max_drawdown_abs=rc.max_drawdown_absolute,
            max_open_trades=rc.max_open_trades,
            max_trades_per_day=rc.max_trades_per_day,
            cooldown_after_loss_minutes=rc.cooldown_after_loss_minutes,
            max_correlated_trades=rc.max_correlated_trades,
            effective_leverage=rc.effective_leverage,
        )
        # Restore state if available
        if risk_state:
            self.risk_manager._peak_balance = risk_state.get('peak_balance', 2000.0)
            self.risk_manager._daily_pnl = risk_state.get('daily_pnl', 0.0)
            self.risk_manager._today_date = datetime.strptime(risk_state.get('today_date', datetime.utcnow().date().isoformat()), "%Y-%m-%d").date()
            self.risk_manager._kill_switch_active = risk_state.get('kill_switch_active', False)
        self.logger.info("✅ Risk engine initialized (state loaded from DB)")

        # Layer 7: Execution
        ec = s.execution
        self.execution_engine = ExecutionEngine(
            broker=self.broker,
            mode=self.mode,
            max_retries=ec.max_order_retries,
            retry_delay=ec.retry_delay_seconds,
            order_timeout=ec.order_timeout_seconds,
        )
        self.logger.info("✅ Execution engine initialized")

        # Layer 8: Position Manager
        self.position_manager = PositionManager(
            execution_engine=self.execution_engine
        )
        self.logger.info("✅ Position manager initialized")

        # Layer 9: AI Research Lab (Phase 16)
        self.signal_enhancer = SignalEnhancer()
        self.logger.info("✅ AI research lab initialized")

    # === Event Handlers ===

    def _on_tick(self, tick: Tick):
        """Handle incoming tick"""
        try:
            self._stats["ticks_received"] += 1
            self._health_status["last_tick"] = datetime.utcnow().isoformat()

            # Feed to candle builder
            self.candle_builder.on_tick(tick)

            # Feed to position manager for monitoring
            self.position_manager.on_price_update(tick.symbol, tick.mid)

        except Exception as e:
            self._stats["errors"] += 1
            self.logger.error(f"Tick handler error: {e}")

    def _on_candle(self, candle: Candle):
        """Handle incoming candle from broker"""
        # Candle builder already processes ticks, but we can also receive
        # historical candles directly from broker
        pass

    def _seed_history(self, symbol: str, timeframe: str, response: Optional[Dict]):
        """Seed candle builder from a subscribe_candles history response"""
        if not response or "candles" not in response:
            return
        candles = [
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                open=float(c["open"]),
                high=float(c["high"]),
                low=float(c["low"]),
                close=float(c["close"]),
                volume=int(c.get("volume", 0)),
                epoch=c["epoch"]
            )
            for c in response["candles"]
        ]
        self.candle_builder.seed_history(symbol, timeframe, candles)

    def _on_candle_complete(self, candle: Candle):
        """Handle completed candle (from candle builder)"""
        try:
            self._stats["candles_completed"] += 1

            # Save to database
            df = self.candle_builder.get_candles(candle.symbol, candle.timeframe, count=1)
            if not df.empty:
                self.db.save_candles(df, candle.symbol, candle.timeframe)

            # Only process primary timeframe (15m) for signals
            if candle.timeframe == "15m":
                self._process_signal_cycle(candle.symbol)

            # Also calculate indicators for confirmation timeframe (1h)
            if candle.timeframe == "1h":
                self._update_confirmation_snapshot(candle.symbol)

        except Exception as e:
            self._stats["errors"] += 1
            self.logger.error(f"Candle complete handler error: {e}")

    def _process_signal_cycle(self, symbol: str):
        """Full signal generation and execution cycle"""

        # 1. Get candle data
        df_15m = self.candle_builder.get_candles(symbol, "15m", count=500)
        if df_15m is None or len(df_15m) < 200:
            self.logger.debug(f"Insufficient 15m data for {symbol}")
            return

        # 2. Calculate indicators
        snapshot = self.indicator_engine.calculate(df_15m, symbol, "15m")
        if snapshot is None:
            return

        # 3. Get session info
        session_info = self.candle_builder.is_session_active(symbol)

        # 4. Get previous snapshot for crossover detection.
        #    Must read BEFORE storing, otherwise previous == current and
        #    a crossover can never be detected.
        previous = self._last_snapshots.get(symbol)
        self._last_snapshots[symbol] = snapshot

        # 5. Generate signal
        signal = self.strategy.generate_signal(snapshot, session_info, previous)
        self._stats["signals_generated"] += 1

        # 5b. AI Research Lab: calibrate confidence and attach a research note.
        if signal.direction != SignalDirection.HOLD:
            ht_snapshot = self._confirmation_snapshots.get(symbol)
            signal = self.signal_enhancer.enhance(signal, snapshot, higher_tf_snapshot=ht_snapshot)

        self._last_signals[symbol] = signal

        # 6. Risk evaluation (if not HOLD)
        risk_result = None
        if signal.direction != SignalDirection.HOLD:
            current_balance = self.risk_manager._current_balance
            risk_result = self.risk_manager.evaluate(signal, current_balance)

            # Persist risk state
            self.db.save_risk_state(self.risk_manager.get_status())

            if risk_result.is_approved:
                self._stats["signals_approved"] += 1
                self.logger.info(
                    f"🟢 APPROVED: {symbol} {signal.direction.value} | "
                    f"Confidence: {signal.confidence:.2f}"
                )

                # 8. Execute trade
                asyncio.create_task(self._execute_trade(risk_result))
            else:
                self.logger.info(
                    f"🔴 REJECTED: {symbol} {signal.direction.value} | "
                    f"Reason: {risk_result.reason}"
                )

        # 7. Persist signal record exactly once (HOLD signals use DB defaults)
        self.db.save_signal(
            signal.to_dict(),
            risk_decision=risk_result.decision.value if risk_result else "HOLD",
            risk_reason=risk_result.reason if risk_result else ""
        )

    def _update_confirmation_snapshot(self, symbol: str):
        """Update 1h snapshot for multi-timeframe confirmation"""
        df_1h = self.candle_builder.get_candles(symbol, "1h", count=200)
        if df_1h is not None and len(df_1h) >= 200:
            snapshot_1h = self.indicator_engine.calculate(df_1h, symbol, "1h")
            if snapshot_1h:
                self._confirmation_snapshots[symbol] = snapshot_1h

    async def _execute_trade(self, risk_result: RiskResult):
        """Execute approved trade"""
        try:
            execution = await self.execution_engine.execute(risk_result)

            if execution and execution.status.value == "filled":
                self._stats["trades_executed"] += 1

                # Save to database
                self.db.save_trade(execution.to_dict())

                # Add to position manager
                self.position_manager.add_position(execution)

                # Update risk manager
                self.risk_manager.on_trade_opened({
                    'id': execution.id,
                    'symbol': execution.signal.symbol,
                    'direction': execution.signal.direction.value,
                    'entry_price': execution.fill_price,
                    'risk_amount': execution.signal.risk_amount
                })

                # Save balance snapshot
                self.db.save_balance(self.risk_manager._current_balance)

                self.logger.info(
                    f"✅ TRADE EXECUTED: {execution.signal.symbol} | "
                    f"ID: {execution.id} | Mode: {execution.mode.value}"
                )
            else:
                self.logger.warning(f"Trade execution failed or not filled")

        except Exception as e:
            self._stats["errors"] += 1
            self.logger.error(f"Trade execution error: {e}")

    # === Main Lifecycle ===

    async def start(self):
        """Start the trading engine"""
        self._running = True
        self._stats["start_time"] = datetime.utcnow().isoformat()
        self._health_status["status"] = "running"

        self.logger.info("=" * 60)
        self.logger.info("🚀 TRADING ENGINE STARTING")
        self.logger.info(f"Mode: {self.mode.value}")
        self.logger.info(f"Symbols: {self.symbols}")
        self.logger.info(f"Database: {self.db.db_path}")
        self.logger.info("=" * 60)

        # Setup graceful shutdown
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()

        for sig in (os_signal.SIGINT, os_signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
            except NotImplementedError:
                self.logger.warning("Signal handlers are not supported on this platform; use Ctrl+C to stop.")
                break

        try:
            # Connect to broker
            if not await self.broker.connect():
                self.logger.error("Failed to connect to Deriv. Aborting.")
                return

            # Subscribe to all symbols
            for symbol in self.symbols:
                self.candle_builder.register_symbol(symbol)
                await self.broker.subscribe_ticks(symbol)

                # Subscribe to candle streams with historical backfill so the
                # indicator and strategy engines have enough data immediately
                for tf in ("15m", "1h"):
                    response = await self.broker.subscribe_candles(symbol, tf, history_count=500)
                    self._seed_history(symbol, tf, response)

                self.logger.info(f"Subscribed to: {symbol}")

            # Start position monitoring
            await self.position_manager.start_monitoring()

            # Start health check loop
            health_task = asyncio.create_task(self._health_check_loop())

            # Start database persistence loop
            persist_task = asyncio.create_task(self._persistence_loop())

            # Start account balance sync loop
            balance_task = asyncio.create_task(self._balance_sync_loop())

            # Wait for shutdown signal
            await self._shutdown_event.wait()

            # Cancel background tasks
            health_task.cancel()
            persist_task.cancel()
            balance_task.cancel()

        except Exception as e:
            self.logger.error(f"Orchestrator error: {e}")
        finally:
            await self._cleanup()

    async def shutdown(self):
        """Graceful shutdown"""
        self.logger.info("🛑 Shutdown signal received...")
        self._running = False
        self._health_status["status"] = "shutting_down"

        # Close all positions
        self.logger.info("Closing all open positions...")
        for exec_id in list(self.position_manager.get_all_positions().keys()):
            await self.position_manager._close_position(
                exec_id,
                self.candle_builder.get_latest_price(
                    self.position_manager.get_position(exec_id).execution.signal.symbol
                ) or 0,
                ExitReason.MANUAL
            )

        # Persist final state
        self.db.save_risk_state(self.risk_manager.get_status())

        # Disconnect
        await self.broker.disconnect()
        await self.position_manager.stop_monitoring()

        self._health_status["status"] = "stopped"
        self._shutdown_event.set()

        self.logger.info("=" * 60)
        self.logger.info("📊 FINAL STATISTICS")
        self.logger.info(f"Ticks received: {self._stats['ticks_received']}")
        self.logger.info(f"Candles completed: {self._stats['candles_completed']}")
        self.logger.info(f"Signals generated: {self._stats['signals_generated']}")
        self.logger.info(f"Signals approved: {self._stats['signals_approved']}")
        self.logger.info(f"Trades executed: {self._stats['trades_executed']}")
        self.logger.info(f"Errors: {self._stats['errors']}")
        self.logger.info("=" * 60)
        self.logger.info("✅ Trading engine stopped gracefully")

    async def _cleanup(self):
        """Cleanup resources"""
        try:
            await self.broker.disconnect()
            await self.position_manager.stop_monitoring()
            self.db.cleanup_old_data()
        except Exception as e:
            self.logger.error(f"Cleanup error: {e}")

    # === Background Tasks ===

    async def _health_check_loop(self):
        """Periodic health checks"""
        while self._running:
            try:
                await asyncio.sleep(30)

                # Check last tick time
                if self._health_status["last_tick"]:
                    last_tick = datetime.fromisoformat(self._health_status["last_tick"])
                    stale_seconds = (datetime.utcnow() - last_tick).total_seconds()

                    if stale_seconds > 60:
                        self.logger.warning(f"Stale tick data: {stale_seconds:.0f}s since last tick")

                # Log heartbeat
                self.logger.info(
                    f"💓 Heartbeat | Ticks: {self._stats['ticks_received']} | "
                    f"Candles: {self._stats['candles_completed']} | "
                    f"Signals: {self._stats['signals_generated']} | "
                    f"Trades: {self._stats['trades_executed']}"
                )

            except Exception as e:
                self.logger.error(f"Health check error: {e}")

    async def _persistence_loop(self):
        """Periodic state persistence"""
        while self._running:
            try:
                await asyncio.sleep(60)  # Every minute

                # Persist risk state
                self.db.save_risk_state(self.risk_manager.get_status())

                # Persist balance
                self.db.save_balance(self.risk_manager._current_balance)

                self.logger.debug("State persisted to database")

            except Exception as e:
                self.logger.error(f"Persistence error: {e}")

    async def _balance_sync_loop(self):
        """Periodically refresh the risk manager's balance from a broker
        Account snapshot (BaseBroker.get_balance). Falls back silently to the
        internal paper balance when the broker reports none."""
        while self._running:
            await asyncio.sleep(60)
            try:
                await self._sync_balance_once()
            except Exception as e:
                self.logger.debug(f"Balance sync unavailable: {e}")

    async def _sync_balance_once(self):
        """Single balance refresh from the broker's Account snapshot."""
        account = await self.broker.get_balance()
        if account and account.balance is not None:
            old = self.risk_manager._current_balance
            if account.balance != old:
                self.risk_manager._current_balance = account.balance
                self.risk_manager._peak_balance = max(
                    self.risk_manager._peak_balance, account.balance
                )
                self.logger.info(
                    f"💰 Balance synced from broker: {old:.2f} → "
                    f"{account.balance:.2f} {account.currency}"
                )
            self.db.save_balance(account.balance)

    # === Status & Control ===

    def get_status(self) -> Dict:
        """Get current system status"""
        return {
            "running": self._running,
            "health": self._health_status,
            "stats": self._stats,
            "risk": self.risk_manager.get_status(),
            "positions": self.position_manager.get_position_summary(),
            "active_trades": len(self.execution_engine.get_active_trades()),
            "database": self.db.get_stats()
        }

    def get_latest_snapshot(self, symbol: str) -> Optional[Dict]:
        """Get latest market snapshot for a symbol"""
        snapshot = self._last_snapshots.get(symbol)
        return snapshot.to_dict() if snapshot else None

    def get_latest_signal(self, symbol: str) -> Optional[Dict]:
        """Get latest signal for a symbol"""
        signal = self._last_signals.get(symbol)
        return signal.to_dict() if signal else None
