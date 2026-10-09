"""Factories in app.core.dependencies must read settings when they build.

A module-level settings snapshot goes stale when tests or CI clear the
settings cache and rebind values after the module has already been imported.
"""

from datetime import timedelta

from app.core import dependencies
from app.core.config import get_settings


def _rebind_factory_settings(
    monkeypatch,
    *,
    broker: str,
    qos: str,
    retention: str,
    remote: str,
    prefix: str,
) -> None:
    monkeypatch.setenv("MQTT_BROKER_URL", broker)
    monkeypatch.setenv("MQTT_DEFAULT_QOS", qos)
    monkeypatch.setenv("TELEMETRY_RETENTION_HOURS", retention)
    monkeypatch.setenv("GIT_REMOTE_URL", remote)
    monkeypatch.setenv("GIT_BRANCH_PREFIX", prefix)
    get_settings.cache_clear()
    dependencies.get_iot_bridge.cache_clear()
    dependencies.get_autonomous_pm.cache_clear()


def test_singleton_factories_read_settings_after_rebind(monkeypatch):
    """A settings rebind after import must reach the next factory build."""
    try:
        _rebind_factory_settings(
            monkeypatch,
            broker="mqtt://rebound.example:1883",
            qos="0",
            retention="12",
            remote="https://git.example/rebound.git",
            prefix="rebound/",
        )
        bridge = dependencies.get_iot_bridge()
        pm = dependencies.get_autonomous_pm()
        assert bridge.mqtt.broker_url == "mqtt://rebound.example:1883"
        assert bridge.mqtt.default_qos == 0
        assert pm.event_store._retention == timedelta(hours=12)
        assert pm.pr_generator.git_remote == "https://git.example/rebound.git"
        assert pm.pr_generator.branch_prefix == "rebound/"
        # The cache still returns one instance until it is cleared.
        assert dependencies.get_iot_bridge() is bridge
        assert dependencies.get_autonomous_pm() is pm

        _rebind_factory_settings(
            monkeypatch,
            broker="mqtt://rebound-again.example:1883",
            qos="2",
            retention="3",
            remote="https://git.example/again.git",
            prefix="again/",
        )
        rebuilt = dependencies.get_iot_bridge()
        rebuilt_pm = dependencies.get_autonomous_pm()
        assert rebuilt is not bridge
        assert rebuilt.mqtt.broker_url == "mqtt://rebound-again.example:1883"
        assert rebuilt.mqtt.default_qos == 2
        assert rebuilt_pm.event_store._retention == timedelta(hours=3)
        assert rebuilt_pm.pr_generator.git_remote == "https://git.example/again.git"
        assert rebuilt_pm.pr_generator.branch_prefix == "again/"
    finally:
        dependencies.get_iot_bridge.cache_clear()
        dependencies.get_autonomous_pm.cache_clear()
        get_settings.cache_clear()
