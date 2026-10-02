"""Agent configuration: ``Settings``, ``Thresholds``, ``SyncSettings``.

Settings are built once by ``load_settings`` with precedence
process-environment > ``.env`` file > defaults. Exactly one ``.env`` file is
loaded, chosen as ``--env-file`` > ``./.env`` > ``<data dir>/.env``. Invalid
values raise ``ConfigError`` listing every bad key. Secrets are wrapped in
``Secret`` so they cannot leak through logs or status output.

``SyncSettings`` is defined here (not in ``agent.sync``) so that importing
settings never pulls in the HTTP client or the queue (review NIT10).
"""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "Secret",
    "Thresholds",
    "SyncSettings",
    "Settings",
    "ConfigError",
    "load_settings",
    "default_data_dir",
]

_DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
# RFC 1123 hostname label-based pattern (also matches IPv4 literals textually).
_HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(?:\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)
_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


class ConfigError(Exception):
    """Raised when one or more configuration values are invalid.

    The message lists every offending key so the user can fix them all at once.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


class Secret:
    """Wraps a secret string so it never appears in logs or repr output."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        """Return the underlying secret value. Use sparingly."""
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __repr__(self) -> str:
        return "***"

    def __str__(self) -> str:
        return "***"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Secret):
            return self._value == other._value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._value)


@dataclass(frozen=True)
class Thresholds:
    """Health-engine thresholds. Demo mode uses the defaults."""

    cpu_usage_warning_percent: float = 90.0
    memory_usage_warning_percent: float = 90.0
    disk_usage_warning_percent: float = 85.0
    disk_usage_critical_percent: float = 95.0
    latency_warning_ms: float = 150.0
    packet_loss_warning_percent: float = 10.0
    packet_loss_unstable_percent: float = 30.0


@dataclass(frozen=True)
class SyncSettings:
    """Small value object the sync service depends on (not the whole Settings)."""

    batch_size: int = 10
    max_batches: int = 5
    retry_limit: int = 5
    backoff_base_s: int = 60
    backoff_max_s: int = 3600
    http_timeout_s: float = 10.0


@dataclass(frozen=True)
class Settings:
    """Fully resolved, validated agent configuration."""

    api_base_url: str
    api_key: Secret
    device_id: str
    device_name: str
    telemetry_interval_seconds: int
    database_path: Path
    demo_database_path: Path
    log_level: str
    log_file: Path
    cpu_sample_count: int
    cpu_sample_interval_seconds: float
    network_probe_count: int
    network_probe_timeout_seconds: float
    internet_targets: tuple[tuple[str, int], ...]
    dns_test_hostnames: tuple[str, ...]
    thresholds: Thresholds
    sync: SyncSettings
    data_dir: Path
    env_file_loaded: Path | None

    @property
    def sync_enabled(self) -> bool:
        return bool(self.api_base_url)


def default_data_dir() -> Path:
    """Return the per-user data directory for live/demo databases and logs."""
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "LocalToCloudDiagnosticGateway"
    return Path.home() / ".local" / "share" / "local-to-cloud-diagnostic-gateway"


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a simple ``KEY=VALUE`` ``.env`` file (comments, optional quotes)."""
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _discover_env_file(
    env_file: Path | None, data_dir: Path
) -> tuple[Path | None, list[str]]:
    """Choose the single .env to load: --env-file > ./.env > <data dir>/.env."""
    errors: list[str] = []
    if env_file is not None:
        if not env_file.is_file():
            errors.append(f"--env-file: file not found: {env_file}")
            return None, errors
        return env_file, errors
    cwd_env = Path.cwd() / ".env"
    if cwd_env.is_file():
        return cwd_env, errors
    data_env = data_dir / ".env"
    if data_env.is_file():
        return data_env, errors
    return None, errors


class _Reader:
    """Reads values with env > .env > default precedence, collecting errors."""

    def __init__(self, env: Mapping[str, str], file_values: Mapping[str, str]) -> None:
        self._env = env
        self._file = file_values
        self.errors: list[str] = []

    def raw(self, key: str) -> str | None:
        if key in self._env:
            return self._env[key]
        if key in self._file:
            return self._file[key]
        return None

    def string(self, key: str, default: str) -> str:
        value = self.raw(key)
        return default if value is None else value

    def int_in(self, key: str, default: int, lo: int, hi: int) -> int:
        value = self.raw(key)
        if value is None or value == "":
            return default
        try:
            parsed = int(value)
        except ValueError:
            self.errors.append(f"{key}: must be an integer")
            return default
        if parsed < lo or parsed > hi:
            self.errors.append(f"{key}: must be between {lo} and {hi}")
            return default
        return parsed

    def float_in(self, key: str, default: float, lo: float, hi: float) -> float:
        value = self.raw(key)
        if value is None or value == "":
            return default
        try:
            parsed = float(value)
        except ValueError:
            self.errors.append(f"{key}: must be a number")
            return default
        if parsed < lo or parsed > hi:
            self.errors.append(f"{key}: must be between {lo} and {hi}")
            return default
        return parsed


def _parse_target(item: str) -> tuple[str, int]:
    """Parse one ``host:port`` entry. Raises ValueError with a reason."""
    item = item.strip()
    host, sep, port_str = item.rpartition(":")
    if not sep:
        raise ValueError("expected host:port")
    host = host.strip()
    port_str = port_str.strip()
    if host.startswith("["):
        if not host.endswith("]"):
            raise ValueError("bracketed IPv6 literal must end with ']'")
        inner = host[1:-1]
        try:
            ipaddress.IPv6Address(inner)
        except ValueError as exc:
            raise ValueError("invalid IPv6 literal") from exc
        host_value = inner
    elif ":" in host:
        raise ValueError("IPv6 literals must be bracketed")
    else:
        if not _is_ipv4(host) and not _HOSTNAME_PATTERN.match(host):
            raise ValueError("host must be an IPv4 literal or a hostname")
        host_value = host
    try:
        port = int(port_str)
    except ValueError as exc:
        raise ValueError("port must be an integer") from exc
    if port < 1 or port > 65535:
        raise ValueError("port must be between 1 and 65535")
    return host_value, port


def _is_ipv4(value: str) -> bool:
    try:
        ipaddress.IPv4Address(value)
    except ValueError:
        return False
    return True


def _parse_targets(reader: _Reader) -> tuple[tuple[str, int], ...]:
    raw = reader.string("INTERNET_TARGETS", "1.1.1.1:443,8.8.8.8:443")
    items = [part for part in (p.strip() for p in raw.split(",")) if part]
    if not items or len(items) > 5:
        reader.errors.append("INTERNET_TARGETS: must have between 1 and 5 items")
        return (("1.1.1.1", 443), ("8.8.8.8", 443))
    targets: list[tuple[str, int]] = []
    for item in items:
        try:
            targets.append(_parse_target(item))
        except ValueError as exc:
            reader.errors.append(f"INTERNET_TARGETS: '{item}': {exc}")
    return tuple(targets) if targets else (("1.1.1.1", 443), ("8.8.8.8", 443))


def _parse_dns_hostnames(reader: _Reader) -> tuple[str, ...]:
    raw = reader.string("DNS_TEST_HOSTNAMES", "example.com,aws.amazon.com")
    items = [part for part in (p.strip() for p in raw.split(",")) if part]
    if not items or len(items) > 5:
        reader.errors.append("DNS_TEST_HOSTNAMES: must have between 1 and 5 items")
        return ("example.com", "aws.amazon.com")
    for item in items:
        if not _HOSTNAME_PATTERN.match(item):
            reader.errors.append(f"DNS_TEST_HOSTNAMES: '{item}': invalid hostname")
    return tuple(items)


def load_settings(
    env: Mapping[str, str] | None = None,
    env_file: Path | None = None,
) -> Settings:
    """Build and validate ``Settings`` from the environment and a ``.env`` file.

    Raises ``ConfigError`` listing every invalid value.
    """
    env = os.environ if env is None else env
    data_dir = default_data_dir()

    chosen_env_file, discovery_errors = _discover_env_file(env_file, data_dir)
    file_values: dict[str, str] = {}
    if chosen_env_file is not None:
        file_values = _parse_env_file(chosen_env_file)

    reader = _Reader(env, file_values)
    reader.errors.extend(discovery_errors)

    # Identity.
    device_id = reader.string("DEVICE_ID", "").strip()
    if device_id and not _DEVICE_ID_PATTERN.match(device_id):
        reader.errors.append("DEVICE_ID: has an invalid format")
    device_name = reader.string("DEVICE_NAME", "").strip()
    if device_name and not (1 <= len(device_name) <= 64):
        reader.errors.append("DEVICE_NAME: must have between 1 and 64 characters")

    # Cloud sync.
    api_base_url = reader.string("API_BASE_URL", "").strip()
    if api_base_url:
        _validate_api_base_url(api_base_url, reader)
    api_key_raw = reader.string("AGENT_API_KEY", "").strip()
    if api_base_url and not api_key_raw:
        reader.errors.append("AGENT_API_KEY: is required when API_BASE_URL is set")
    if api_key_raw and not (32 <= len(api_key_raw) <= 256):
        reader.errors.append("AGENT_API_KEY: must have between 32 and 256 characters")

    # Paths.
    database_path = _path_or_default(reader, "DATABASE_PATH", data_dir / "agent.db")
    demo_database_path = _path_or_default(
        reader, "DEMO_DATABASE_PATH", data_dir / "demo.db"
    )
    log_file = _path_or_default(reader, "LOG_FILE", data_dir / "logs" / "agent.log")

    # Log level.
    log_level = reader.string("LOG_LEVEL", "INFO").strip().upper()
    if log_level not in _LOG_LEVELS:
        reader.errors.append(f"LOG_LEVEL: must be one of {', '.join(_LOG_LEVELS)}")
        log_level = "INFO"

    # Scheduling.
    telemetry_interval = reader.int_in(
        "TELEMETRY_INTERVAL_SECONDS", 3600, 300, 86400
    )

    # Sync / retry.
    retry_limit = reader.int_in("RETRY_LIMIT", 5, 1, 20)
    backoff_base = reader.int_in("RETRY_BACKOFF_BASE_SECONDS", 60, 1, 3600)
    backoff_max = reader.int_in("RETRY_BACKOFF_MAX_SECONDS", 3600, 1, 86400)
    if backoff_max < backoff_base:
        reader.errors.append(
            "RETRY_BACKOFF_MAX_SECONDS: must be >= RETRY_BACKOFF_BASE_SECONDS"
        )
    batch_size = reader.int_in("SYNC_BATCH_SIZE", 10, 1, 10)
    max_batches = reader.int_in("SYNC_MAX_BATCHES_PER_CYCLE", 5, 1, 100)
    http_timeout = reader.float_in("HTTP_TIMEOUT_SECONDS", 10.0, 1.0, 60.0)

    # CPU sampling.
    cpu_sample_count = reader.int_in("CPU_SAMPLE_COUNT", 3, 1, 10)
    cpu_sample_interval = reader.float_in("CPU_SAMPLE_INTERVAL_SECONDS", 1.0, 0.1, 5.0)

    # Thresholds.
    cpu_warn = reader.float_in("CPU_USAGE_WARNING_PERCENT", 90.0, 1.0, 100.0)
    mem_warn = reader.float_in("MEMORY_USAGE_WARNING_PERCENT", 90.0, 1.0, 100.0)
    disk_warn = reader.float_in("DISK_USAGE_WARNING_PERCENT", 85.0, 1.0, 100.0)
    disk_crit = reader.float_in("DISK_USAGE_CRITICAL_PERCENT", 95.0, 1.0, 100.0)
    if disk_crit <= disk_warn:
        reader.errors.append(
            "DISK_USAGE_CRITICAL_PERCENT: must be greater than "
            "DISK_USAGE_WARNING_PERCENT"
        )
    latency_warn = reader.float_in("LATENCY_WARNING_MS", 150.0, 1.0, 10000.0)
    loss_warn = reader.float_in("PACKET_LOSS_WARNING_PERCENT", 10.0, 0.0, 100.0)
    loss_unstable = reader.float_in("PACKET_LOSS_UNSTABLE_PERCENT", 30.0, 0.0, 100.0)
    if loss_unstable <= loss_warn:
        reader.errors.append(
            "PACKET_LOSS_UNSTABLE_PERCENT: must be greater than "
            "PACKET_LOSS_WARNING_PERCENT"
        )

    # Network probing.
    probe_count = reader.int_in("NETWORK_PROBE_COUNT", 4, 1, 10)
    probe_timeout = reader.float_in("NETWORK_PROBE_TIMEOUT_SECONDS", 2.0, 0.5, 10.0)
    internet_targets = _parse_targets(reader)
    dns_hostnames = _parse_dns_hostnames(reader)

    if reader.errors:
        raise ConfigError(reader.errors)

    thresholds = Thresholds(
        cpu_usage_warning_percent=cpu_warn,
        memory_usage_warning_percent=mem_warn,
        disk_usage_warning_percent=disk_warn,
        disk_usage_critical_percent=disk_crit,
        latency_warning_ms=latency_warn,
        packet_loss_warning_percent=loss_warn,
        packet_loss_unstable_percent=loss_unstable,
    )
    sync = SyncSettings(
        batch_size=batch_size,
        max_batches=max_batches,
        retry_limit=retry_limit,
        backoff_base_s=backoff_base,
        backoff_max_s=backoff_max,
        http_timeout_s=http_timeout,
    )
    return Settings(
        api_base_url=api_base_url,
        api_key=Secret(api_key_raw),
        device_id=device_id,
        device_name=device_name,
        telemetry_interval_seconds=telemetry_interval,
        database_path=database_path,
        demo_database_path=demo_database_path,
        log_level=log_level,
        log_file=log_file,
        cpu_sample_count=cpu_sample_count,
        cpu_sample_interval_seconds=cpu_sample_interval,
        network_probe_count=probe_count,
        network_probe_timeout_seconds=probe_timeout,
        internet_targets=internet_targets,
        dns_test_hostnames=dns_hostnames,
        thresholds=thresholds,
        sync=sync,
        data_dir=data_dir,
        env_file_loaded=chosen_env_file,
    )


def _path_or_default(reader: _Reader, key: str, default: Path) -> Path:
    value = reader.raw(key)
    if value is None or value.strip() == "":
        return default
    return Path(value.strip())


def _validate_api_base_url(url: str, reader: _Reader) -> None:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        reader.errors.append(
            "API_BASE_URL: must start with https:// (or http:// locally)"
        )
        return
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "http" and host not in ("localhost", "127.0.0.1", "::1"):
        reader.errors.append(
            "API_BASE_URL: http:// is only allowed for localhost/127.0.0.1/::1"
        )
    if not host:
        reader.errors.append("API_BASE_URL: must include a host")
