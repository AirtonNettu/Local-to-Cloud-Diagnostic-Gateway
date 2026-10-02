"""AST-enforced import boundaries between the three packages.

Invariants (design B.2 and review NIT10):
- ``shared`` imports the standard library only.
- ``cloud`` imports ``shared``, the standard library and boto3/botocore only.
- ``agent`` never imports ``cloud``.
- ``agent.config`` never imports ``agent.sync``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"

# Standard-library module names available on this interpreter, plus a couple of
# names that are stdlib but may not be reported by ``sys.stdlib_module_names``.
_STDLIB = set(sys.stdlib_module_names) | {"__future__"}


def _iter_py_files(package: str) -> list[Path]:
    return sorted((_SRC / package).rglob("*.py"))


def _imported_modules(path: Path) -> set[str]:
    """Return the set of top-level and dotted module names imported by a file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        # Only absolute imports matter for the boundary (level == 0).
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return modules


def _top(module: str) -> str:
    return module.split(".", 1)[0]


def test_shared_imports_stdlib_only() -> None:
    offenders: dict[str, set[str]] = {}
    for path in _iter_py_files("shared"):
        bad = {
            module
            for module in _imported_modules(path)
            if _top(module) not in _STDLIB and _top(module) != "shared"
        }
        if bad:
            offenders[str(path.relative_to(_SRC))] = bad
    assert not offenders, f"shared must import stdlib only: {offenders}"


def test_cloud_imports_shared_stdlib_boto3_only() -> None:
    allowed_top = _STDLIB | {"shared", "cloud", "boto3", "botocore"}
    offenders: dict[str, set[str]] = {}
    for path in _iter_py_files("cloud"):
        bad = {
            module
            for module in _imported_modules(path)
            if _top(module) not in allowed_top
        }
        if bad:
            offenders[str(path.relative_to(_SRC))] = bad
    assert not offenders, f"cloud may import shared/stdlib/boto3 only: {offenders}"


def test_agent_never_imports_cloud() -> None:
    offenders: dict[str, set[str]] = {}
    for path in _iter_py_files("agent"):
        bad = {m for m in _imported_modules(path) if _top(m) == "cloud"}
        if bad:
            offenders[str(path.relative_to(_SRC))] = bad
    assert not offenders, f"agent must never import cloud: {offenders}"


def test_agent_config_does_not_import_agent_sync() -> None:
    offenders: dict[str, set[str]] = {}
    for path in _iter_py_files("agent/config"):
        bad = {
            m
            for m in _imported_modules(path)
            if m == "agent.sync" or m.startswith("agent.sync.")
        }
        if bad:
            offenders[str(path.relative_to(_SRC))] = bad
    assert not offenders, f"agent.config must not import agent.sync: {offenders}"
