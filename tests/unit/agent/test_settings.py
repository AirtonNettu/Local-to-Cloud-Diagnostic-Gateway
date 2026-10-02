"""Tests for agent configuration loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.config.settings import (
    ConfigError,
    Secret,
    Settings,
    SyncSettings,
    Thresholds,
    load_settings,
)


def _load(env: dict[str, str], env_file: Path | None = None) -> Settings:
    return load_settings(env=env, env_file=env_file)


def test_defaults_disable_sync() -> None:
    settings = _load({})
    assert settings.api_base_url == ""
    assert settings.sync_enabled is False
    assert settings.telemetry_interval_seconds == 3600
    assert isinstance(settings.thresholds, Thresholds)
    assert isinstance(settings.sync, SyncSettings)


def test_env_overrides_defaults() -> None:
    settings = _load({"TELEMETRY_INTERVAL_SECONDS": "600", "LOG_LEVEL": "debug"})
    assert settings.telemetry_interval_seconds == 600
    assert settings.log_level == "DEBUG"


def test_api_requires_key() -> None:
    with pytest.raises(ConfigError) as exc:
        _load({"API_BASE_URL": "https://api.example.com"})
    assert any("AGENT_API_KEY" in e for e in exc.value.errors)


def test_https_required_for_remote_host() -> None:
    with pytest.raises(ConfigError) as exc:
        _load({"API_BASE_URL": "http://api.example.com", "AGENT_API_KEY": "k" * 40})
    assert any("API_BASE_URL" in e for e in exc.value.errors)


def test_http_allowed_for_localhost() -> None:
    settings = _load(
        {"API_BASE_URL": "http://localhost:8787", "AGENT_API_KEY": "k" * 40}
    )
    assert settings.sync_enabled is True


def test_secret_is_redacted() -> None:
    settings = _load(
        {"API_BASE_URL": "https://api.example.com", "AGENT_API_KEY": "k" * 40}
    )
    assert repr(settings.api_key) == "***"
    assert str(settings.api_key) == "***"
    assert settings.api_key.reveal() == "k" * 40
    assert "kkkk" not in repr(settings)


def test_secret_wrapper_direct() -> None:
    secret = Secret("value")
    assert "value" not in repr(secret)
    assert bool(secret) is True
    assert bool(Secret("")) is False


def test_invalid_values_collected() -> None:
    with pytest.raises(ConfigError) as exc:
        _load(
            {
                "TELEMETRY_INTERVAL_SECONDS": "10",  # below range
                "LOG_LEVEL": "LOUD",  # invalid
                "DEVICE_ID": "x",  # too short
            }
        )
    joined = "; ".join(exc.value.errors)
    assert "TELEMETRY_INTERVAL_SECONDS" in joined
    assert "LOG_LEVEL" in joined
    assert "DEVICE_ID" in joined


def test_disk_critical_must_exceed_warning() -> None:
    with pytest.raises(ConfigError) as exc:
        _load({"DISK_USAGE_WARNING_PERCENT": "95", "DISK_USAGE_CRITICAL_PERCENT": "90"})
    assert any("DISK_USAGE_CRITICAL_PERCENT" in e for e in exc.value.errors)


def test_bracketed_ipv6_target_accepted() -> None:
    settings = _load({"INTERNET_TARGETS": "[2606:4700:4700::1111]:443"})
    assert settings.internet_targets == (("2606:4700:4700::1111", 443),)


def test_unbracketed_ipv6_target_rejected() -> None:
    with pytest.raises(ConfigError) as exc:
        _load({"INTERNET_TARGETS": "2606:4700:4700::1111:443"})
    assert any("INTERNET_TARGETS" in e for e in exc.value.errors)


def test_bad_port_rejected() -> None:
    with pytest.raises(ConfigError) as exc:
        _load({"INTERNET_TARGETS": "1.1.1.1:70000"})
    assert any("INTERNET_TARGETS" in e for e in exc.value.errors)


def test_missing_host_port_separator_rejected() -> None:
    with pytest.raises(ConfigError):
        _load({"INTERNET_TARGETS": "1.1.1.1"})


def test_dns_hostnames_parsed() -> None:
    settings = _load({"DNS_TEST_HOSTNAMES": "example.com, aws.amazon.com"})
    assert settings.dns_test_hostnames == ("example.com", "aws.amazon.com")


def test_bad_dns_hostname_rejected() -> None:
    with pytest.raises(ConfigError):
        _load({"DNS_TEST_HOSTNAMES": "not a hostname"})


def test_env_file_explicit_missing_errors() -> None:
    with pytest.raises(ConfigError) as exc:
        _load({}, env_file=Path("does-not-exist.env"))
    assert any("--env-file" in e for e in exc.value.errors)


def test_env_file_loaded_recorded(tmp_path: Path) -> None:
    env_file = tmp_path / "custom.env"
    env_file.write_text("LOG_LEVEL=DEBUG\n", encoding="utf-8")
    settings = _load({}, env_file=env_file)
    assert settings.env_file_loaded == env_file
    assert settings.log_level == "DEBUG"


def test_process_env_wins_over_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / "custom.env"
    env_file.write_text("LOG_LEVEL=ERROR\n", encoding="utf-8")
    settings = _load({"LOG_LEVEL": "WARNING"}, env_file=env_file)
    assert settings.log_level == "WARNING"


def test_env_file_quotes_and_comments(tmp_path: Path) -> None:
    env_file = tmp_path / "custom.env"
    env_file.write_text(
        '# comment\nDEVICE_NAME="My Device"\nLOG_LEVEL=INFO\n', encoding="utf-8"
    )
    settings = _load({}, env_file=env_file)
    assert settings.device_name == "My Device"


def test_no_env_file_when_none_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = _load({})
    assert settings.env_file_loaded is None
