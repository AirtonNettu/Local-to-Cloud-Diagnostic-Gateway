"""Auth tests: header parsing (finding M2), scopes, and cache behavior."""

from __future__ import annotations

import pytest

from cloud.auth import MAX_AUTH_HEADER_CHARS, ApiKeyProvider, Scope
from cloud.errors import DependencyUnavailable, Forbidden, Unauthorized

_INGEST = "ingest-secret-key"
_READ = "read-secret-key"


class FakeSSM:
    """A minimal SSM stub returning two parameters, counting fetches."""

    def __init__(self, ingest: str = _INGEST, read: str = _READ) -> None:
        self._ingest = ingest
        self._read = read
        self.calls = 0
        self.fail = False

    def get_parameters(self, Names: list[str], WithDecryption: bool):  # noqa: N803
        self.calls += 1
        if self.fail:
            raise RuntimeError("ssm unavailable")
        return {
            "Parameters": [
                {"Name": Names[0], "Value": self._ingest},
                {"Name": Names[1], "Value": self._read},
            ]
        }


def _provider(ssm: FakeSSM, monotonic=None) -> ApiKeyProvider:
    kwargs = {"monotonic": monotonic} if monotonic else {}
    return ApiKeyProvider(ssm, "/ingest", "/read", **kwargs)


def _headers(value: str | None) -> dict[str, str]:
    return {} if value is None else {"authorization": value}


def test_valid_ingest_key_authorizes_ingest_scope() -> None:
    provider = _provider(FakeSSM())
    provider.authorize(_headers(f"Bearer {_INGEST}"), Scope.INGEST)


def test_lowercase_bearer_with_valid_token_succeeds() -> None:
    provider = _provider(FakeSSM())
    provider.authorize(_headers(f"bearer {_READ}"), Scope.READ)


def test_valid_key_wrong_scope_is_forbidden() -> None:
    provider = _provider(FakeSSM())
    with pytest.raises(Forbidden):
        provider.authorize(_headers(f"Bearer {_READ}"), Scope.INGEST)


@pytest.mark.parametrize(
    "header",
    [
        None,  # missing header
        "Bearer café-not-ascii",  # non-ASCII token must 401, not 500
        "Bearer " + "x" * (MAX_AUTH_HEADER_CHARS + 10),  # oversized
        "Basic dXNlcjpwYXNz",  # wrong scheme
        "bearer wrong-token",  # lowercase scheme, invalid token
        "Bearer ",  # empty token
    ],
)
def test_bad_headers_return_401(header: str | None) -> None:
    provider = _provider(FakeSSM())
    with pytest.raises(Unauthorized):
        provider.authorize(_headers(header), Scope.INGEST)


def test_non_ascii_token_does_not_raise_type_error() -> None:
    # Regression for finding M2: hmac.compare_digest would raise TypeError on a
    # non-ASCII str; the bytes comparison must yield a clean 401 instead.
    provider = _provider(FakeSSM())
    with pytest.raises(Unauthorized):
        provider.authorize(_headers("Bearer \u00e9\u00e8\u00ea"), Scope.READ)


def test_cache_avoids_refetch_within_ttl() -> None:
    clock = {"t": 0.0}
    ssm = FakeSSM()
    provider = _provider(ssm, monotonic=lambda: clock["t"])
    provider.authorize(_headers(f"Bearer {_INGEST}"), Scope.INGEST)
    provider.authorize(_headers(f"Bearer {_INGEST}"), Scope.INGEST)
    assert ssm.calls == 1


def test_stale_keys_kept_on_refresh_failure() -> None:
    clock = {"t": 0.0}
    ssm = FakeSSM()
    provider = _provider(ssm, monotonic=lambda: clock["t"])
    provider.authorize(_headers(f"Bearer {_INGEST}"), Scope.INGEST)
    clock["t"] = 10_000  # force a refresh
    ssm.fail = True
    # Refresh fails but the cached key still authorizes.
    provider.authorize(_headers(f"Bearer {_INGEST}"), Scope.INGEST)


def test_dependency_unavailable_without_cache() -> None:
    ssm = FakeSSM()
    ssm.fail = True
    provider = _provider(ssm)
    with pytest.raises(DependencyUnavailable):
        provider.authorize(_headers(f"Bearer {_INGEST}"), Scope.INGEST)
