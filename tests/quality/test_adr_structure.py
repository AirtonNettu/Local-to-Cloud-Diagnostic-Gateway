"""ADR structure check (design B.17).

Every ``docs/decisions/ADR-00N-<kebab-slug>.md`` file must follow the filename
convention and carry the four required headings (Context, Decision,
Alternatives, Consequences). ADRs are produced by FEAT-007; until they exist
this check skips so the suite can run end to end before that feature lands.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_ADR_DIR = _ROOT / "docs" / "decisions"

# English ADRs are ``ADR-00N-<kebab-slug>.md``; each has a Brazilian Portuguese
# counterpart ``ADR-00N-<kebab-slug>.pt-BR.md`` (FEAT-007 bilingual convention).
_ADR_NAME = re.compile(r"^ADR-\d{3}-[a-z0-9]+(?:-[a-z0-9]+)*(?:\.pt-BR)?\.md$")
_REQUIRED_HEADINGS = ("Context", "Decision", "Alternatives", "Consequences")


def _adr_files() -> list[Path]:
    if not _ADR_DIR.is_dir():
        return []
    return sorted(p for p in _ADR_DIR.glob("ADR-*.md"))


def test_adr_files_follow_convention_and_headings() -> None:
    adrs = _adr_files()
    if not adrs:
        pytest.skip("docs/decisions/ADR-*.md not created yet (FEAT-007)")
    for adr in adrs:
        assert _ADR_NAME.match(adr.name), f"bad ADR filename: {adr.name}"
        text = adr.read_text(encoding="utf-8")
        headings = set(re.findall(r"^#{1,6}\s+(.+?)\s*$", text, re.MULTILINE))
        for required in _REQUIRED_HEADINGS:
            assert any(
                required.lower() == h.lower() for h in headings
            ), f"{adr.name} is missing the '{required}' heading"
