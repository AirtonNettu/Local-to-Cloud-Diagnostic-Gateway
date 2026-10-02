"""Device identity model shared between the agent and the cloud backend."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["DeviceInfo"]


@dataclass(frozen=True)
class DeviceInfo:
    """Minimal, privacy-preserving device description sent to the cloud.

    Only the stable device identifier, a display name and coarse OS/agent
    metadata are included. No serial numbers, MAC addresses or user names.
    """

    device_id: str
    device_name: str
    os_name: str | None = None
    os_version: str | None = None
    agent_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "os_name": self.os_name,
            "os_version": self.os_version,
            "agent_version": self.agent_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceInfo:
        return cls(
            device_id=data["device_id"],
            device_name=data["device_name"],
            os_name=data.get("os_name"),
            os_version=data.get("os_version"),
            agent_version=data.get("agent_version"),
        )
