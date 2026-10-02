"""Diagrams-in-sync check (design B.17).

Each ``diagrams/*.mmd`` source must be embedded verbatim as a fenced ``mermaid``
block in at least one of ``README.md`` / ``docs/architecture.md`` so GitHub
renders the diagram while the ``.mmd`` file stays the source of truth. The
diagrams and docs are produced by FEAT-007; until they exist this check skips so
the suite can run end to end before that feature lands.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DIAGRAMS_DIR = _ROOT / "diagrams"
_EMBED_FILES = (_ROOT / "README.md", _ROOT / "docs" / "architecture.md")

_MERMAID_BLOCK = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)


def _mmd_sources() -> list[Path]:
    if not _DIAGRAMS_DIR.is_dir():
        return []
    return sorted(_DIAGRAMS_DIR.glob("*.mmd"))


def _embedded_blocks() -> list[str]:
    blocks: list[str] = []
    for path in _EMBED_FILES:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        blocks.extend(match.strip() for match in _MERMAID_BLOCK.findall(text))
    return blocks


def test_each_diagram_is_embedded_verbatim() -> None:
    sources = _mmd_sources()
    if not sources:
        pytest.skip("diagrams/*.mmd not created yet (FEAT-007)")
    embedded = _embedded_blocks()
    assert embedded, "mermaid sources exist but no fenced block is embedded"
    for source in sources:
        body = source.read_text(encoding="utf-8").strip()
        assert body in embedded, f"{source.name} is not embedded verbatim"
