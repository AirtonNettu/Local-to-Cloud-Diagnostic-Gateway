"""Demo mode: deterministic scenarios over simulated inputs (design B.12).

``diagnostic-agent demo [--scenario NAME | --all] [--json]`` runs the real
``DiagnosticPipeline``, rules, serializer and report over *simulated* collector
and probe providers, so the output is deterministic and touches neither the real
network, the live database, PowerShell nor psutil. Six scenarios cover the
headline health/network outcomes; ``OFFLINE_MODE`` additionally demonstrates the
sync queue going PENDING with one OFFLINE attempt per event.

Safety (review M1 + NIT4):
- The demo identity is a fixed ``DEMO_DEVICE_ID`` inserted directly into a fresh
  demo database (``resolve_device_id`` is never called), so ``.env`` cannot
  change it.
- ``DemoRunner`` deletes ``demo.db``/``-wal``/``-shm`` at the start of each run,
  but only after opening the file read-only and confirming its
  ``PRAGMA application_id`` equals ``DEMO_DB_APPLICATION_ID``. A foreign SQLite
  file or a non-SQLite file is left untouched and the command exits 2.
- The command refuses (exit 2) when ``DEMO_DATABASE_PATH`` resolves to the same
  file as ``DATABASE_PATH``.
- Thresholds, sync settings and the device identity are constants, so ``.env``
  values cannot change demo output.
"""

from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.collectors.cpu import CpuInfo
from agent.collectors.hardware import GpuInfo, PhysicalDiskInfo
from agent.collectors.memory import MemoryInfo
from agent.collectors.network import InterfaceInfo, NetworkInfo
from agent.collectors.storage import VolumeInfo
from agent.collectors.system import SystemInfo
from agent.config.settings import Secret, Settings, SyncSettings, Thresholds
from agent.diagnostics.health import HealthEvaluator
from agent.diagnostics.probes import ProbeOutcome, ProbeResult, ResolveResult
from agent.pipeline import Clock, CollectorSet, DiagnosticPipeline
from agent.storage import local_db
from agent.storage.local_db import (
    DEMO_DB_APPLICATION_ID,
    LocalStore,
    read_application_id,
)
from agent.sync.client import ApiClient, ConnectivityError, HttpResponse
from agent.sync.service import SyncService
from shared.models.diagnostic import DiagnosticResult, RunSource
from shared.utils.timeutil import to_iso, utc_now

__all__ = [
    "DEMO_DEVICE_ID",
    "DEMO_DEVICE_NAME",
    "DEMO_SYNC_SETTINGS",
    "DEMO_RNG_SEED",
    "DemoScenario",
    "SimulatedCollectors",
    "ScriptedProber",
    "UnreachableTransport",
    "DemoRunner",
    "SCENARIOS",
    "scenario_names",
]

# NIT4: a fixed identity so the demo output never depends on the live identity
# or on ``.env``. Inserted directly into the fresh demo DB (``is_local = 1``).
DEMO_DEVICE_ID = "demo-device-0001"
DEMO_DEVICE_NAME = "DEMO-PC"

# Constant sync settings so ``.env`` cannot change demo output (§B.12).
DEMO_SYNC_SETTINGS = SyncSettings(
    batch_size=10,
    max_batches=1,
    retry_limit=5,
    backoff_base_s=60,
    backoff_max_s=3600,
    http_timeout_s=5.0,
)
DEMO_RNG_SEED = 0

# A demo-only cloud identity. ``demo.invalid`` is an RFC 2606 reserved TLD and
# the transport is unreachable, so nothing is ever sent to a real host.
_DEMO_API_BASE_URL = "https://demo.invalid"
_DEMO_API_KEY = "demo-" + "x" * 32

_GIB = 1024**3

# Shared hardware defaults (§B.12): one GPU, one NVMe SSD, 4 logical CPUs,
# 16 GiB RAM, hostname DEMO-PC.
_DEMO_SYSTEM = SystemInfo(
    hostname=DEMO_DEVICE_NAME,
    os_name="Windows",
    os_version="10.0.22631",
    os_release="11",
    architecture="AMD64",
    boot_time="2024-01-01T00:00:00.000Z",
    uptime_seconds=2 * 86400 + 4 * 3600,  # 2d 04h
)
_DEMO_GPU = GpuInfo(
    name="Demo GPU", driver_version="31.0.0.0", adapter_ram_bytes=8 * _GIB
)
_DEMO_DISK = PhysicalDiskInfo(
    friendly_name="Demo SSD",
    media_type="SSD",
    bus_type="NVMe",
    health_status="Healthy",
    operational_status="OK",
    size_bytes=512 * _GIB,
)
_MEMORY_TOTAL = 16 * _GIB


def _cpu(percent: float) -> CpuInfo:
    return CpuInfo(
        model="Demo CPU @ 3.00GHz",
        logical_cpus=4,
        physical_cores=4,
        current_percent=percent,
        average_percent=percent,
        samples=(percent,),
        frequency_current_mhz=3000.0,
        frequency_max_mhz=3600.0,
    )


def _memory(percent: float) -> MemoryInfo:
    used = int(_MEMORY_TOTAL * percent / 100)
    return MemoryInfo(
        total_bytes=_MEMORY_TOTAL,
        available_bytes=_MEMORY_TOTAL - used,
        used_bytes=used,
        percent=percent,
    )


def _volume(mountpoint: str, percent: float, total_gib: int) -> VolumeInfo:
    total = total_gib * _GIB
    used = int(total * percent / 100)
    return VolumeInfo(
        device=mountpoint,
        mountpoint=mountpoint,
        filesystem="NTFS",
        total_bytes=total,
        free_bytes=total - used,
        used_bytes=used,
        percent=percent,
    )


_DEMO_INTERFACE = InterfaceInfo(
    name="Demo Ethernet",
    is_up=True,
    speed_mbps=1000,
    ipv4=("192.0.2.10",),
    ipv6=(),
)
_DEMO_NETWORK = NetworkInfo(
    hostname=DEMO_DEVICE_NAME,
    interfaces=(_DEMO_INTERFACE,),
    gateways=("192.0.2.1",),
    dns_servers=("192.0.2.53",),
)


@dataclass(frozen=True)
class ProbeScript:
    """Scripted probe behavior for one scenario (consumed by ScriptedProber).

    ``gateway_rtt_ms`` of ``None`` means the gateway does not reply.
    ``internet_success_ratio`` is the fraction of internet TCP probes that
    succeed; ``internet_no_reply`` makes the failures NO_REPLY rather than
    reducing the count (so a 0.0 ratio with ``internet_no_reply`` yields OFFLINE).
    ``dns_success`` is how many of the resolved hostnames succeed.
    """

    gateway_rtt_ms: float | None
    internet_success_ratio: float
    internet_rtt_ms: float
    dns_success_count: int


@dataclass(frozen=True)
class DemoScenario:
    """A frozen demo scenario: fixed facts plus a scripted prober."""

    name: str
    description: str
    system: SystemInfo
    cpu: CpuInfo
    memory: MemoryInfo
    volumes: tuple[VolumeInfo, ...]
    disks: tuple[PhysicalDiskInfo, ...]
    gpus: tuple[GpuInfo, ...]
    network_info: NetworkInfo
    probe_script: ProbeScript


class SimulatedCollectors:
    """Builds a ``CollectorSet`` returning a scenario's fixed OK results.

    The callables return the scenario's dataclasses directly; ``run_collector``
    wraps them as OK ``CollectorResult``s in the pipeline. Nothing here calls
    ``get_platform()``, ``run_powershell_json``, psutil or sockets.
    """

    def __init__(self, scenario: DemoScenario) -> None:
        self._scenario = scenario

    def collector_set(self) -> CollectorSet:
        s = self._scenario
        return CollectorSet(
            cpu=lambda: s.cpu,
            memory=lambda: s.memory,
            storage=lambda: list(s.volumes),
            disks=lambda: list(s.disks),
            system=lambda: s.system,
            gpus=lambda: list(s.gpus),
            network=lambda: s.network_info,
        )


class ScriptedProber:
    """A ``Prober`` with predetermined results (never touches the network)."""

    def __init__(self, script: ProbeScript) -> None:
        self._script = script
        self._internet_calls = 0
        self._dns_calls = 0

    def icmp_ping(self, host: str, timeout_s: float) -> ProbeResult:
        rtt = self._script.gateway_rtt_ms
        if rtt is None:
            return ProbeResult(host, ProbeOutcome.NO_REPLY, None, "no reply")
        return ProbeResult(host, ProbeOutcome.SUCCESS, rtt, f"reply in {rtt:.0f} ms")

    def tcp_connect(self, host: str, port: int, timeout_s: float) -> ProbeResult:
        # Spread successes evenly over the probes so a 0.75 ratio gives 3 of
        # every 4 as SUCCESS, deterministically.
        self._internet_calls += 1
        if _ratio_hit(self._internet_calls, self._script.internet_success_ratio):
            rtt = self._script.internet_rtt_ms
            return ProbeResult(
                host, ProbeOutcome.SUCCESS, rtt, f"connected in {rtt:.0f} ms"
            )
        return ProbeResult(host, ProbeOutcome.NO_REPLY, None, "no reply")

    def resolve(self, hostname: str, timeout_s: float) -> ResolveResult:
        self._dns_calls += 1
        if self._dns_calls <= self._script.dns_success_count:
            return ResolveResult(
                hostname, ProbeOutcome.SUCCESS, ("192.0.2.100",), 5.0
            )
        return ResolveResult(hostname, ProbeOutcome.NO_REPLY, (), 5.0)


def _ratio_hit(index_1based: int, ratio: float) -> bool:
    """Return True for ``round(index*ratio) > round((index-1)*ratio)``.

    This spreads successes evenly: ratio 0.75 over 1..8 yields 6 successes
    (positions 1,2,4,5,7,8), ratio 1.0 yields all, 0.0 yields none.
    """
    return round(index_1based * ratio) > round((index_1based - 1) * ratio)


# --- Scenarios (§B.12) -------------------------------------------------------


def _scenario(
    name: str,
    description: str,
    *,
    cpu_percent: float = 18.0,
    memory_percent: float = 45.0,
    volumes: tuple[VolumeInfo, ...] | None = None,
    gateway_rtt_ms: float | None = 2.0,
    internet_success_ratio: float = 1.0,
    internet_rtt_ms: float = 18.0,
    dns_success_count: int = 2,
) -> DemoScenario:
    return DemoScenario(
        name=name,
        description=description,
        system=_DEMO_SYSTEM,
        cpu=_cpu(cpu_percent),
        memory=_memory(memory_percent),
        volumes=volumes or (_volume("C:\\", 52.0, 512),),
        disks=(_DEMO_DISK,),
        gpus=(_DEMO_GPU,),
        network_info=_DEMO_NETWORK,
        probe_script=ProbeScript(
            gateway_rtt_ms=gateway_rtt_ms,
            internet_success_ratio=internet_success_ratio,
            internet_rtt_ms=internet_rtt_ms,
            dns_success_count=dns_success_count,
        ),
    )


SCENARIOS: tuple[DemoScenario, ...] = (
    _scenario(
        "HEALTHY",
        "Everything within thresholds: HEALTHY overall and network.",
    ),
    _scenario(
        "DEGRADED_NETWORK",
        "25% internet probe loss and high latency: DEGRADED.",
        internet_success_ratio=0.75,
        internet_rtt_ms=240.0,
    ),
    _scenario(
        "LOW_DISK",
        "C: critically full: CRITICAL overall.",
        volumes=(_volume("C:\\", 96.5, 512), _volume("D:\\", 70.0, 1024)),
    ),
    _scenario(
        "HIGH_MEMORY",
        "Memory under pressure: DEGRADED overall.",
        memory_percent=94.0,
    ),
    _scenario(
        "DNS_FAILURE",
        "Internet reachable but DNS fails: DEGRADED network.",
        dns_success_count=0,
    ),
    _scenario(
        "OFFLINE_MODE",
        "No internet and no DNS: OFFLINE network; queued events stay PENDING.",
        internet_success_ratio=0.0,
        dns_success_count=0,
    ),
)

_BY_NAME = {s.name: s for s in SCENARIOS}


def scenario_names() -> tuple[str, ...]:
    """Return the ordered scenario names (for ``--scenario`` validation)."""
    return tuple(s.name for s in SCENARIOS)


# --- Demo-only sync transport ------------------------------------------------


class UnreachableTransport:
    """A demo-only ``HttpTransport`` that always raises ``ConnectivityError``.

    ``demo.invalid`` is an RFC 2606 reserved TLD, so even a wiring mistake could
    never reach a real host; this transport makes that structural.
    """

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        raise ConnectivityError("simulated: network unreachable")


# --- Fixed clock -------------------------------------------------------------


class _DemoClock:
    """A clock advancing by one millisecond per call for stable ordering."""

    def __init__(self) -> None:
        self._base = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        self._tick = 0

    def now(self) -> datetime:
        from datetime import timedelta

        value = self._base + timedelta(milliseconds=self._tick)
        self._tick += 1
        return value


# --- Runner ------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioResult:
    """The outcome shown for one scenario."""

    scenario: DemoScenario
    result: DiagnosticResult


class DemoRunner:
    """Runs demo scenarios against a fresh, guarded demo database (§B.12)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Demo thresholds and sync settings are constants, not from ``.env``.
        # Fixed, demo-only cloud identity so ``SyncService`` treats sync as
        # enabled and runs the OFFLINE cycle. The transport is unreachable and
        # ``demo.invalid`` is an RFC 2606 reserved TLD, so nothing is sent.
        self._demo_settings = replace(
            settings,
            thresholds=Thresholds(),
            sync=DEMO_SYNC_SETTINGS,
            device_id=DEMO_DEVICE_ID,
            device_name=DEMO_DEVICE_NAME,
            api_base_url=_DEMO_API_BASE_URL,
            api_key=Secret(_DEMO_API_KEY),
        )

    def prepare_database(self) -> int | None:
        """Guard and reset the demo database. Returns an exit code to abort.

        Returns ``None`` when the database is ready, or an exit code (2) that the
        command should return after printing the reason.
        """
        demo_path = self._settings.demo_database_path
        live_path = self._settings.database_path
        if _same_file(demo_path, live_path):
            print(
                "Error: DEMO_DATABASE_PATH resolves to the same file as "
                f"DATABASE_PATH: {demo_path}"
            )
            return 2
        if demo_path.exists():
            app_id = read_application_id(demo_path)
            if app_id != DEMO_DB_APPLICATION_ID:
                print(
                    "Error: DEMO_DATABASE_PATH points to a file that is not a "
                    f"demo database: {demo_path}"
                )
                return 2
            _remove_demo_files(demo_path)
        else:
            # Even without the main file, remove any stale WAL/SHM siblings so a
            # fresh database cannot replay a leftover journal.
            _remove_sidecars(demo_path)
        return None

    def run(self, scenarios: list[DemoScenario]) -> list[ScenarioResult]:
        """Run each scenario, persisting to the fresh demo DB. Returns results."""
        conn = local_db.connect(self._settings.demo_database_path, demo=True)
        try:
            _insert_demo_identity(conn)
            store = LocalStore(conn)
            results: list[ScenarioResult] = []
            for scenario in scenarios:
                result = self._run_one(scenario, store)
                results.append(ScenarioResult(scenario=scenario, result=result))
            if any(s.name == "OFFLINE_MODE" for s in scenarios):
                self._run_offline_sync(conn)
            return results
        finally:
            conn.close()

    def _run_one(
        self, scenario: DemoScenario, store: LocalStore
    ) -> DiagnosticResult:
        pipeline = DiagnosticPipeline(
            settings=self._demo_settings,
            collectors=SimulatedCollectors(scenario).collector_set(),
            prober=ScriptedProber(scenario.probe_script),
            evaluator=HealthEvaluator(),
            clock=self._clock(),
        )
        # Run without persistence first so the scenario name can be recorded in
        # the facts (and therefore the ``scenario`` run column) before saving.
        result = pipeline.run(
            DEMO_DEVICE_ID, None, RunSource.DEMO, enqueue=False
        )
        facts = dict(result.facts)
        facts["scenario"] = scenario.name
        result = replace(result, facts=facts)
        store.save_run(result, enqueue_event=True)
        return result

    def _clock(self) -> Clock:
        return _DemoClock()

    def _run_offline_sync(self, conn: sqlite3.Connection) -> None:
        """Run one SyncService cycle against an unreachable demo endpoint.

        Registration fails offline, so every due demo event is claimed, gets one
        OFFLINE attempt and is released back to PENDING with ``attempt_count=0``.
        """
        client = ApiClient(
            base_url=_DEMO_API_BASE_URL,
            api_key=Secret(_DEMO_API_KEY),
            transport=UnreachableTransport(),
            timeout=DEMO_SYNC_SETTINGS.http_timeout_s,
        )
        service = SyncService(
            conn,
            self._demo_settings,
            client,
            device_id=DEMO_DEVICE_ID,
            rng=random.Random(DEMO_RNG_SEED),  # noqa: S311 - deterministic demo jitter
        )
        service.run_cycle()


def _insert_demo_identity(conn: sqlite3.Connection) -> None:
    """Insert the fixed demo identity directly (never resolve_device_id)."""
    now = to_iso(utc_now())
    conn.execute(
        """
        INSERT INTO devices (device_id, device_name, hostname, is_local, created_at)
        VALUES (?, ?, ?, 1, ?)
        ON CONFLICT(device_id) DO NOTHING
        """,
        (DEMO_DEVICE_ID, DEMO_DEVICE_NAME, DEMO_DEVICE_NAME, now),
    )
    conn.commit()


def _same_file(a: Path, b: Path) -> bool:
    try:
        if a.exists() and b.exists():
            return a.samefile(b)
    except OSError:
        pass
    return _normalize(a) == _normalize(b)


def _normalize(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path.absolute())


def _sidecars(path: Path) -> tuple[Path, Path]:
    return (
        path.with_name(path.name + "-wal"),
        path.with_name(path.name + "-shm"),
    )


def _remove_sidecars(path: Path) -> None:
    for sidecar in _sidecars(path):
        _unlink(sidecar)


def _remove_demo_files(path: Path) -> None:
    _unlink(path)
    _remove_sidecars(path)


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


# --- Serialization for ``--json`` -------------------------------------------


def scenario_summary(item: ScenarioResult) -> dict[str, Any]:
    """Build a JSON-serializable summary for one scenario result."""
    result = item.result
    return {
        "scenario": item.scenario.name,
        "description": item.scenario.description,
        "overall": result.status.value,
        "network": result.network_status.value,
        "alerts": [a.rule_id for a in result.alerts],
    }
