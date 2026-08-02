"""
Tests for the ULTRA monitoring/health layer (Phase 14).
"""
import asyncio

import pytest

from src.monitoring.health import HealthMonitor


class FakeBroker:
    def __init__(self, connected=True, latency=12.0):
        self.connected = connected
        self.latency = latency

    @property
    def is_connected(self):
        return self.connected

    async def ping(self):
        return self.latency


class BrokenDb:
    def _get_connection(self):
        raise RuntimeError("db closed")


def _async(value):
    async def _inner():
        return value

    return _inner


@pytest.fixture
def monitor():
    return HealthMonitor()


def test_classify_healthy(monitor):
    status, issues = monitor._classify_status(
        cpu=10, ram=20, disk=30, stale_seconds=1, error_count=0
    )
    assert status == "healthy"
    assert issues == []


def test_classify_high_cpu_is_warning(monitor):
    status, issues = monitor._classify_status(
        cpu=95, ram=20, disk=30, stale_seconds=1, error_count=0
    )
    assert status == "warning"
    assert any("CPU" in i for i in issues)


def test_classify_high_disk_is_critical(monitor):
    status, issues = monitor._classify_status(
        cpu=10, ram=20, disk=99, stale_seconds=1, error_count=0
    )
    assert status == "critical"
    assert any("Disk" in i for i in issues)


def test_classify_db_failure_is_critical(monitor):
    status, issues = monitor._classify_status(
        cpu=10, ram=20, disk=30, stale_seconds=1, error_count=0,
        db_connected=False,
    )
    assert status == "critical"
    assert any("Database" in i for i in issues)


def test_classify_no_internet_is_critical(monitor):
    status, issues = monitor._classify_status(
        cpu=10, ram=20, disk=30, stale_seconds=1, error_count=0,
        internet_connected=False,
    )
    assert status == "critical"
    assert any("internet" in i for i in issues)


def test_classify_high_latency_is_warning(monitor):
    status, issues = monitor._classify_status(
        cpu=10, ram=20, disk=30, stale_seconds=1, error_count=0,
        api_latency_ms=900,
    )
    assert status == "warning"
    assert any("latency" in i for i in issues)


def test_classify_stale_ticks_is_warning(monitor):
    status, issues = monitor._classify_status(
        cpu=10, ram=20, disk=30, stale_seconds=300, error_count=0
    )
    assert status == "warning"
    assert any("Stale" in i for i in issues)


def test_classify_many_errors_is_warning(monitor):
    status, issues = monitor._classify_status(
        cpu=10, ram=20, disk=30, stale_seconds=1, error_count=50
    )
    assert status == "warning"
    assert any("Errors" in i for i in issues)


def test_classify_critical_overrides_warning(monitor):
    status, issues = monitor._classify_status(
        cpu=95, ram=20, disk=30, stale_seconds=1, error_count=0,
        db_connected=False,
    )
    assert status == "critical"


def test_db_check_reports_failure():
    monitor = HealthMonitor(db=BrokenDb())
    assert asyncio.run(monitor._check_database()) is False


def test_db_check_ok_with_temp_db(tmp_path):
    from src.database.manager import DatabaseManager

    db = DatabaseManager(str(tmp_path / "health.db"))
    monitor = HealthMonitor(db=db)
    assert asyncio.run(monitor._check_database()) is True


def test_latency_returns_none_without_broker():
    monitor = HealthMonitor()
    assert asyncio.run(monitor._measure_api_latency()) is None


def test_latency_returns_none_when_disconnected():
    monitor = HealthMonitor(broker=FakeBroker(connected=False))
    assert asyncio.run(monitor._measure_api_latency()) is None


def test_latency_measures_broker_ping():
    monitor = HealthMonitor(broker=FakeBroker(connected=True, latency=23.5))
    assert asyncio.run(monitor._measure_api_latency()) == 23.5


def test_internet_check_returns_bool(monitor):
    # Must never raise; result depends on the environment.
    assert asyncio.run(monitor._check_internet()) in (True, False)


def test_full_check_health_run(monkeypatch):
    """End-to-end async health check with network/DB/latency stubbed."""
    monitor = HealthMonitor(db=None, broker=None)
    monkeypatch.setattr(monitor, "_check_database", _async(True))
    monkeypatch.setattr(monitor, "_check_internet", _async(True))
    monkeypatch.setattr(monitor, "_measure_api_latency", _async(None))
    monkeypatch.setattr(monitor, "_classify_status", lambda **kwargs: ("healthy", []))

    health = asyncio.run(monitor._check_health())
    assert health.status == "healthy"
    assert health.db_connected is True
    assert health.cpu_percent is not None


def test_record_tick_and_history():
    monitor = HealthMonitor()
    monitor.record_tick()
    assert monitor._last_tick_time is not None


def test_alert_handlers_called_on_trigger(monitor):
    calls = []
    monitor.on_alert(lambda msg, data: calls.append(msg))

    class FakeHealth:
        status = "critical"
        to_dict = lambda self: {"status": "critical"}

    asyncio.run(monitor._trigger_alert(FakeHealth()))
    assert calls and "CRITICAL" in calls[0]
