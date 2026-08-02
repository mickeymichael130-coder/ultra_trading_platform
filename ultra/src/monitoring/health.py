"""
ULTRA Monitoring Layer
Runs alongside the bot.
Checks: CPU, RAM, API, Database, Internet, Latency.
If something fails: Alert → Restart → Notify User.
"""
import asyncio
import psutil
import socket
import time
from typing import Dict, Optional, Callable, List, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass

from ..utils.logger import get_logger


@dataclass
class HealthStatus:
    """System health snapshot"""
    timestamp: datetime
    cpu_percent: float
    ram_percent: float
    disk_percent: float
    api_latency_ms: Optional[float] = None
    db_connected: bool = True
    internet_connected: bool = True
    last_tick_seconds_ago: Optional[float] = None
    active_trades: int = 0
    total_errors: int = 0
    status: str = "healthy"  # healthy, warning, critical

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "cpu_percent": self.cpu_percent,
            "ram_percent": self.ram_percent,
            "disk_percent": self.disk_percent,
            "api_latency_ms": self.api_latency_ms,
            "db_connected": self.db_connected,
            "internet_connected": self.internet_connected,
            "last_tick_seconds_ago": self.last_tick_seconds_ago,
            "active_trades": self.active_trades,
            "total_errors": self.total_errors,
            "status": self.status
        }


class HealthMonitor:
    """
    System Health Monitor.

    Monitors:
    - CPU usage (alert > 80%)
    - RAM usage (alert > 85%)
    - Disk usage (alert > 90%)
    - API latency (alert > 500ms)
    - Database connectivity
    - Internet connectivity
    - Tick staleness (alert > 60s)
    - Error rate

    Actions:
    - Log warnings
    - Trigger alerts
    - Optionally restart components
    """

    def __init__(
        self,
        db=None,
        broker=None,
        max_cpu: float = 80.0,
        max_ram: float = 85.0,
        max_disk: float = 90.0,
        max_latency_ms: int = 500,
        max_stale_seconds: int = 60,
        check_interval: int = 30
    ):
        self.db = db
        self.broker = broker
        self.max_cpu = max_cpu
        self.max_ram = max_ram
        self.max_disk = max_disk
        self.max_latency_ms = max_latency_ms
        self.max_stale_seconds = max_stale_seconds
        self.check_interval = check_interval

        self.logger = get_logger("monitoring.health")

        # State
        self._running = False
        self._last_tick_time: Optional[datetime] = None
        self._error_count = 0
        self._active_trades = 0

        # Alert handlers
        self._alert_handlers: List[Callable[[str, Dict], None]] = []

        # History
        self._status_history: List[HealthStatus] = []
        self._max_history = 1000

        self.logger.info(f"HealthMonitor initialized | Check interval: {check_interval}s")

    def on_alert(self, handler: Callable[[str, Dict], None]):
        """Register alert handler"""
        self._alert_handlers.append(handler)

    def record_tick(self):
        """Record tick receipt time"""
        self._last_tick_time = datetime.utcnow()

    def record_error(self):
        """Record an error"""
        self._error_count += 1

    def set_active_trades(self, count: int):
        """Update active trade count"""
        self._active_trades = count

    async def start(self):
        """Start monitoring loop"""
        self._running = True
        self.logger.info("Health monitoring started")

        while self._running:
            try:
                status = await self._check_health()
                self._status_history.append(status)

                # Trim history
                if len(self._status_history) > self._max_history:
                    self._status_history = self._status_history[-self._max_history:]

                # Check thresholds and alert
                if status.status != "healthy":
                    await self._trigger_alert(status)

                await asyncio.sleep(self.check_interval)

            except Exception as e:
                self.logger.error(f"Health check error: {e}")
                await asyncio.sleep(self.check_interval)

    async def stop(self):
        """Stop monitoring"""
        self._running = False
        self.logger.info("Health monitoring stopped")

    async def _check_health(self) -> HealthStatus:
        """Perform health check"""
        now = datetime.utcnow()

        # System resources
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage('/').percent

        # Real connectivity checks
        db_connected = await self._check_database()
        internet_connected = await self._check_internet()
        api_latency = await self._measure_api_latency()

        # Check tick staleness
        stale_seconds = None
        if self._last_tick_time:
            stale_seconds = (now - self._last_tick_time).total_seconds()

        # Classify overall status from all signals
        status, issues = self._classify_status(
            cpu=cpu,
            ram=ram,
            disk=disk,
            stale_seconds=stale_seconds,
            error_count=self._error_count,
            db_connected=db_connected,
            internet_connected=internet_connected,
            api_latency_ms=api_latency,
            active_trades=self._active_trades,
        )

        health = HealthStatus(
            timestamp=now,
            cpu_percent=cpu,
            ram_percent=ram,
            disk_percent=disk,
            api_latency_ms=api_latency,
            db_connected=db_connected,
            internet_connected=internet_connected,
            last_tick_seconds_ago=stale_seconds,
            active_trades=self._active_trades,
            total_errors=self._error_count,
            status=status
        )

        if issues:
            self.logger.warning(f"Health issues: {', '.join(issues)}")

        return health

    async def _check_database(self) -> bool:
        """Check the database is reachable with a trivial query."""
        if self.db is None:
            return True
        try:
            conn = self.db._get_connection()
            conn.execute("SELECT 1").fetchone()
            return True
        except Exception as e:
            self.logger.error(f"Database health check failed: {e}")
            return False

    async def _check_internet(self, host: str = "8.8.8.8", port: int = 53, timeout: float = 2.0) -> bool:
        """Check internet connectivity by opening a TCP socket."""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError as e:
            self.logger.warning(f"Internet health check failed: {e}")
            return False

    async def _measure_api_latency(self) -> Optional[float]:
        """Measure Deriv API round-trip latency (ms) via a ping."""
        if self.broker is None or not getattr(self.broker, "is_connected", False):
            return None
        try:
            return await self.broker.ping()
        except Exception as e:
            self.logger.error(f"API latency check failed: {e}")
            return None

    def _classify_status(
        self,
        cpu: float,
        ram: float,
        disk: float,
        stale_seconds: Optional[float],
        error_count: int,
        db_connected: bool = True,
        internet_connected: bool = True,
        api_latency_ms: Optional[float] = None,
        active_trades: int = 0,
    ) -> Tuple[str, List[str]]:
        """Pure status classification — easy to unit test."""
        status = "healthy"
        issues: List[str] = []

        if cpu > self.max_cpu:
            status = "warning"
            issues.append(f"CPU: {cpu:.1f}%")

        if ram > self.max_ram:
            status = "warning"
            issues.append(f"RAM: {ram:.1f}%")

        if disk > self.max_disk:
            status = "critical"
            issues.append(f"Disk: {disk:.1f}%")

        if not db_connected:
            status = "critical"
            issues.append("Database unreachable")

        if not internet_connected:
            status = "critical"
            issues.append("No internet connection")

        if api_latency_ms is not None and api_latency_ms > self.max_latency_ms:
            status = "warning"
            issues.append(f"API latency: {api_latency_ms:.0f}ms")

        if stale_seconds is not None and stale_seconds > self.max_stale_seconds:
            status = "warning"
            issues.append(f"Stale ticks: {stale_seconds:.0f}s")

        if error_count > 10:
            status = "warning"
            issues.append(f"Errors: {error_count}")

        return status, issues

    async def _trigger_alert(self, status: HealthStatus):
        """Trigger alert to all handlers"""
        message = f"ULTRA Health Alert: {status.status.upper()}"

        for handler in self._alert_handlers:
            try:
                handler(message, status.to_dict())
            except Exception as e:
                self.logger.error(f"Alert handler error: {e}")

    def get_current_status(self) -> Optional[HealthStatus]:
        """Get most recent status"""
        if self._status_history:
            return self._status_history[-1]
        return None

    def get_status_history(self, minutes: int = 60) -> List[Dict]:
        """Get status history for last N minutes"""
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        return [
            s.to_dict() for s in self._status_history
            if s.timestamp >= cutoff
        ]

    def get_uptime_stats(self) -> Dict:
        """Get uptime statistics"""
        if not self._status_history:
            return {"uptime_percent": 0, "total_checks": 0}

        total = len(self._status_history)
        healthy = sum(1 for s in self._status_history if s.status == "healthy")
        warning = sum(1 for s in self._status_history if s.status == "warning")
        critical = sum(1 for s in self._status_history if s.status == "critical")

        return {
            "uptime_percent": (healthy / total * 100) if total > 0 else 0,
            "total_checks": total,
            "healthy_checks": healthy,
            "warning_checks": warning,
            "critical_checks": critical
        }


class AlertManager:
    """
    Alert Manager.
    Routes alerts to configured channels.
    """

    def __init__(self, email: Optional[str] = None, webhook: Optional[str] = None):
        self.email = email
        self.webhook = webhook
        self.logger = get_logger("monitoring.alerts")

    def send_console_alert(self, message: str, data: Dict):
        """Log alert to console"""
        self.logger.warning(f"ALERT: {message} | Data: {data}")

    def send_email_alert(self, message: str, data: Dict):
        """Send email alert (placeholder)"""
        if not self.email:
            return
        # Would integrate with SMTP here
        self.logger.info(f"Email alert would send to {self.email}: {message}")

    def send_webhook_alert(self, message: str, data: Dict):
        """Send webhook alert (placeholder)"""
        if not self.webhook:
            return
        # Would integrate with requests here
        self.logger.info(f"Webhook alert would send to {self.webhook}: {message}")

    def register_default_handlers(self, monitor: HealthMonitor):
        """Register all alert handlers with monitor"""
        monitor.on_alert(self.send_console_alert)
        if self.email:
            monitor.on_alert(self.send_email_alert)
        if self.webhook:
            monitor.on_alert(self.send_webhook_alert)
