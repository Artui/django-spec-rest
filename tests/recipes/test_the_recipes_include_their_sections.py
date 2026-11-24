from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_BLOCK = re.compile(r"^--8<--\n(?P<path>[^\n:]+):(?P<section>[\w-]+)\n--8<--$", re.MULTILINE)
_SECTION = re.compile(r"# --8<-- \[start:(?P<section>[\w-]+)\]")


def _pages() -> dict[Path, str]:
    return {page: page.read_text() for page in (_ROOT / "docs").rglob("*.md")}


def _included() -> set[tuple[str, str]]:
    return {(m["path"], m["section"]) for text in _pages().values() for m in _BLOCK.finditer(text)}


def test_every_include_marker_is_the_block_form_ruff_leaves_alone() -> None:
    """``ruff format`` rewrites the one-line ``--8<-- "path"`` into code that includes nothing."""
    for page, text in _pages().items():
        markers = [line for line in text.splitlines() if line.lstrip().startswith("--8")]
        assert markers == ["--8<--"] * len(markers), page
        assert len(markers) == 2 * len(_BLOCK.findall(text)), page


def test_every_included_section_exists() -> None:
    for path, section in _included():
        assert f"# --8<-- [start:{section}]" in (_ROOT / path).read_text(), (path, section)


def test_every_recipe_section_is_included_by_a_page() -> None:
    for module in (_ROOT / "tests" / "recipes").glob("*.py"):
        relative = str(module.relative_to(_ROOT))
        for match in _SECTION.finditer(module.read_text()):
            assert (relative, match["section"]) in _included(), (relative, match["section"])
