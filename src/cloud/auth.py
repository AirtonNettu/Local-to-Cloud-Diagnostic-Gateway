"""Bearer-token authentication with two scoped keys (design B.11, finding M2).

Two SecureString keys live in SSM: ``ingest`` (agents) and ``read`` (operators).
``ApiKeyProvider`` loads both with one ``GetParameters(WithDecryption=True)``
call, caches them for ``ttl_s`` and keeps a stale value if a refresh fails
(rotation without downtime); a failure with no cached value raises
``DependencyUnavailable``.

Finding M2: the token comes from an untrusted ``Authorization`` header, so it is
parsed defensively and compared on *bytes*. ``hmac.compare_digest`` raises
``TypeError`` for non-ASCII ``str`` arguments, which would otherwise turn a
hostile ``Bearer é...`` into a 500. ``_extract_bearer`` therefore returns bytes
(or ``None``), ``_matches`` compares bytes, and both key comparisons always run
so response timing never reveals which key was closer. Keys are never logged.
"""

from __future__ import annotations

import hmac
import logging
import time
from collections.abc import Mapping
from enum import Enum
from typing import Any

from cloud.errors import DependencyUnavailable, Forbidden, Unauthorized

__all__ = ["Scope", "ApiKeyProvider", "MAX_AUTH_HEADER_CHARS"]

_LOG = logging.getLogger("cloud.auth")

# An Authorization header longer than this is rejected without parsing: a real
# bearer key is short, and this bounds the work done on hostile input.
MAX_AUTH_HEADER_CHARS = 512


class Scope(str, Enum):
    """The two authorization scopes. ``ingest`` writes, ``read`` reads."""

    INGEST = "ingest"
    READ = "read"


def _extract_bearer(headers: Mapping[str, str]) -> bytes | None:
    """Parse the bearer token to bytes, or ``None`` for anything unusable.

    ``None`` is returned for a missing, oversized, non-``Bearer`` or empty-token
    header. The scheme match is case-insensitive. The token is encoded with
    ``surrogatepass`` so a non-ASCII token becomes bytes (compared, then
    rejected) rather than crashing the comparison.
    """
    raw = headers.get("authorization")
    if raw is None or len(raw) > MAX_AUTH_HEADER_CHARS:
        return None
    scheme, _, token = raw.strip().partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    if not token:
        return None
    return token.encode("utf-8", "surrogatepass")


def _matches(candidate: bytes, expected: str) -> bool:
    """Constant-time compare the candidate bytes against an expected key."""
    return hmac.compare_digest(candidate, expected.encode("utf-8"))


class ApiKeyProvider:
    """Loads, caches and refreshes the two scoped keys from SSM.

    ``authorize(headers, scope)`` is the entry point: it returns ``None`` on
    success and raises ``Unauthorized`` (401) or ``Forbidden`` (403) otherwise.
    """

    def __init__(
        self,
        ssm_client: Any,
        ingest_param: str,
        read_param: str,
        *,
        ttl_s: float = 300,
        monotonic: Any = time.monotonic,
    ) -> None:
        self._ssm = ssm_client
        self._ingest_param = ingest_param
        self._read_param = read_param
        self._ttl_s = ttl_s
        self._monotonic = monotonic
        self._ingest_key: str | None = None
        self._read_key: str | None = None
        self._loaded_at: float | None = None

    def authorize(self, headers: Mapping[str, str], scope: Scope) -> None:
        """Verify the request carries a valid key for ``scope``.

        Raises ``Unauthorized`` when no key matches either scope and
        ``Forbidden`` when a valid key is presented for the wrong scope. Both
        key comparisons always run (constant work regardless of outcome).
        """
        candidate = _extract_bearer(headers)
        self._ensure_loaded()
        # ``_ensure_loaded`` guarantees both keys are non-None (or it raised).
        ingest_key = self._ingest_key or ""
        read_key = self._read_key or ""

        if candidate is None:
            # Still run both comparisons against a fixed value so a missing
            # header is not distinguishable by timing from a wrong one.
            _matches(b"", ingest_key)
            _matches(b"", read_key)
            _LOG.warning("authentication failed", extra={"event": "auth_failure"})
            raise Unauthorized()

        is_ingest = _matches(candidate, ingest_key)
        is_read = _matches(candidate, read_key)

        granted = is_ingest if scope is Scope.INGEST else is_read
        if granted:
            return
        if is_ingest or is_read:
            _LOG.warning(
                "key presented for wrong scope", extra={"event": "auth_failure"}
            )
            raise Forbidden()
        _LOG.warning("authentication failed", extra={"event": "auth_failure"})
        raise Unauthorized()

    def _ensure_loaded(self) -> None:
        """Load keys on first use and refresh them after the TTL expires."""
        now = self._monotonic()
        if self._loaded_at is not None and (now - self._loaded_at) < self._ttl_s:
            return
        try:
            ingest, read = self._fetch()
        except Exception as exc:  # noqa: BLE001 - SSM/botocore failures are broad.
            if self._ingest_key is not None and self._read_key is not None:
                # Keep the cached (stale) keys; rotation tolerance.
                _LOG.warning(
                    "SSM refresh failed; using cached keys",
                    extra={"event": "ssm_refresh_failed"},
                )
                return
            _LOG.error(
                "SSM parameter load failed with no cache",
                extra={"event": "ssm_unavailable"},
            )
            raise DependencyUnavailable() from exc
        self._ingest_key = ingest
        self._read_key = read
        self._loaded_at = now

    def _fetch(self) -> tuple[str, str]:
        """Return ``(ingest_key, read_key)`` from SSM, decrypted.

        Raises if either parameter is missing (so a half-provisioned stack is
        treated as a dependency failure rather than silently matching nothing).
        """
        response = self._ssm.get_parameters(
            Names=[self._ingest_param, self._read_param], WithDecryption=True
        )
        values = {p["Name"]: p["Value"] for p in response.get("Parameters", [])}
        if self._ingest_param not in values or self._read_param not in values:
            raise RuntimeError("one or more key parameters are missing in SSM")
        return values[self._ingest_param], values[self._read_param]
