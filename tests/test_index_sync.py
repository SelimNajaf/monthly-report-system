"""Drift guard: docs/INDEX.md and CLAUDE.md must match the tree they describe.

``CLAUDE.md`` is loaded into every Claude Code session and ``docs/INDEX.md`` is
the map it points to. Nothing in the running code reads either file, so without
a test they drift the first time a module is added or a folder is moved — and a
map that is quietly wrong is worse than no map, because it is believed.

Both directions are pinned, because each catches a different mistake:

* every root item, every ``src/monthly_report/**/*.py`` and every
  ``scripts/*.py`` must **appear** in the index (catches a new file shipped
  without a line);
* every backticked path in the index must **exist** (catches a rename, a move
  or a typo). A line marked ``(runtime)`` is exempt — its first path is created
  at run time or is machine-local — and so is anything under that path.

Plus two hygiene checks: ``CLAUDE.md`` stays short enough to be read every
session, and neither file carries a secret (UNC path, host/person name, VÖEN).

Modelled on ``tests/test_cli_manual_sync.py``, the repo's other
markdown-as-data drift guard.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_INDEX = _ROOT / "docs" / "INDEX.md"
_CLAUDE = _ROOT / "CLAUDE.md"

#: CLAUDE.md is auto-loaded into every session; past this it stops being a brief.
_CLAUDE_MAX_LINES = 150

#: Root items the index does not have to name.
_ROOT_EXEMPT = {".git"}

#: Marks a line whose first path may be absent on a clean checkout.
_RUNTIME = "(runtime)"

#: Anything inside backticks. Paths are picked out of these by ``_is_path``.
_BACKTICK = re.compile(r"`([^`\n]+)`")

#: A trailing ``:line`` or ``:line-line`` reference, as in ``main.py:69``.
_LINE_REF = re.compile(r":\d+(?:-\d+)?$")

#: Characters a repo path here is spelled with (spaces: ``Claude outputs/``).
_PATH_CHARS = re.compile(r"^[A-Za-z0-9_.\- /]+$")

_FILE_EXT = re.compile(r"\.(?:py|md|json|ya?ml|toml|txt|ps1|sh|png|pdf|docx)$")

#: A bare extension (``.pdf``, ``.docx``) names a file type, not a path.
_BARE_EXTENSIONS = {".py", ".md", ".json", ".yaml", ".yml", ".toml", ".txt",
                    ".pdf", ".docx", ".bak", ".ttf", ".otf", ".png"}

#: Secret patterns, each with the reason it is one.
_SECRETS = {
    "double backslash (UNC path prefix)": re.compile(r"\\\\"),
    "UNC path": re.compile(r"(?:^|[\s`'\"(])//[A-Za-z0-9][\w.-]*/"),
    "LAN host (Windows <name>-pc)": re.compile(r"\b[A-Za-z0-9]+-pc\b", re.IGNORECASE),
    "10-digit number (VÖEN)": re.compile(r"(?<!\d)\d{10}(?!\d)"),
}


def _is_path(token: str) -> bool:
    """True when a backticked token is a repo path rather than a key, a flag
    or a report number (``presentation.range_mode``, ``--live``, ``-lan``)."""
    if not _PATH_CHARS.match(token) or token.startswith("-"):
        return False
    if token in _BARE_EXTENSIONS:
        return False
    return "/" in token or token.startswith(".") or bool(_FILE_EXT.search(token))


def _paths_in(line: str) -> list[str]:
    return [_LINE_REF.sub("", tok) for tok in _BACKTICK.findall(line)
            if _is_path(_LINE_REF.sub("", tok))]


def _norm(path: str) -> str:
    return path.rstrip("/")


@pytest.fixture(scope="module")
def index() -> str:
    return _INDEX.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def claude() -> str:
    return _CLAUDE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def indexed(index) -> set[str]:
    """Every backticked path in the index, trailing slash removed."""
    return {_norm(p) for line in index.splitlines() for p in _paths_in(line)}


@pytest.fixture(scope="module")
def runtime_roots(index) -> set[str]:
    """The first path of every ``(runtime)`` line: may be absent, and so may
    anything under it."""
    roots: set[str] = set()
    for line in index.splitlines():
        paths = _paths_in(line)
        if _RUNTIME in line and paths:
            roots.add(_norm(paths[0]))
    return roots


def _under_runtime(path: str, roots: set[str]) -> bool:
    return any(path == r or path.startswith(r + "/") for r in roots)


# --------------------------------------------------------------------------- #
# The files themselves
# --------------------------------------------------------------------------- #
class TestTheFilesExist:
    def test_the_index_is_in_docs(self):
        assert _INDEX.is_file(), "docs/INDEX.md is referenced from CLAUDE.md"

    def test_claude_md_is_at_the_project_root(self):
        assert _CLAUDE.is_file(), "Claude Code auto-loads CLAUDE.md from the project root"


# --------------------------------------------------------------------------- #
# Tree -> index: nothing on disk goes unlisted
# --------------------------------------------------------------------------- #
class TestEverythingIsIndexed:
    def test_every_root_item_is_indexed(self, indexed):
        missing = sorted(p.name for p in _ROOT.iterdir()
                         if p.name not in _ROOT_EXEMPT and p.name not in indexed)
        assert not missing, (
            f"{missing} INDEX-də yoxdur — docs/INDEX.md §1 Root cədvəlinə hər biri üçün "
            f"bir sətir əlavə et (runtime/ignored olanları `(runtime)` ilə işarələ)")

    def test_every_package_module_is_indexed(self, indexed):
        modules = sorted(p.relative_to(_ROOT).as_posix()
                         for p in (_ROOT / "src" / "monthly_report").rglob("*.py")
                         if "__pycache__" not in p.parts)
        assert modules, "src/monthly_report/ has no .py files — wrong root?"
        missing = [m for m in modules if m not in indexed]
        assert not missing, (
            f"{missing} INDEX-də yoxdur — docs/INDEX.md §2-yə hər biri üçün bir sətir "
            f"əlavə et (tam yol, backtick içində)")

    def test_every_script_is_indexed(self, indexed):
        scripts = sorted(p.relative_to(_ROOT).as_posix()
                         for p in (_ROOT / "scripts").glob("*.py"))
        missing = [s for s in scripts if s not in indexed]
        assert not missing, (
            f"{missing} INDEX-də yoxdur — docs/INDEX.md §4-ə hər biri üçün bir sətir əlavə et")


# --------------------------------------------------------------------------- #
# Index -> tree: nothing listed that is not there
# --------------------------------------------------------------------------- #
class TestEveryIndexedPathIsReal:
    def test_every_backticked_path_exists(self, index, runtime_roots):
        dead: list[str] = []
        for number, line in enumerate(index.splitlines(), start=1):
            if _RUNTIME in line:
                continue
            for path in _paths_in(line):
                if _under_runtime(_norm(path), runtime_roots):
                    continue
                if not (_ROOT / path).exists():
                    dead.append(f"docs/INDEX.md:{number} `{path}`")
        assert not dead, (
            f"{dead} mövcud deyil — yolu düzəlt, sətri sil, və ya runtime-da yaranırsa "
            f"sətri `(runtime)` ilə işarələ")

    def test_the_path_filter_skips_keys_flags_and_numbers(self):
        """The existence check is only as good as its idea of what a path is."""
        assert _is_path("src/monthly_report/cli.py")
        assert _is_path(".upload_state.json")
        assert _is_path("Claude outputs/")
        assert _is_path("main.py")
        assert not _is_path("presentation.range_mode")
        assert not _is_path("--live")
        assert not _is_path("-lan")
        assert not _is_path(".pdf")
        assert not _is_path("scripts/*.py")


# --------------------------------------------------------------------------- #
# Hygiene
# --------------------------------------------------------------------------- #
class TestHygiene:
    def test_claude_md_stays_short(self, claude):
        lines = len(claude.splitlines())
        assert lines <= _CLAUDE_MAX_LINES, (
            f"CLAUDE.md {lines} sətirdir, limit {_CLAUDE_MAX_LINES} — təfərrüatı "
            f"docs/INDEX.md-yə və ya ADR-ə köçür")

    @pytest.mark.parametrize("name", ["CLAUDE.md", "docs/INDEX.md"])
    @pytest.mark.parametrize("kind", sorted(_SECRETS))
    def test_no_secret_is_written_down(self, name, kind):
        text = (_ROOT / name).read_text(encoding="utf-8")
        hits = [f"{name}:{n}" for n, line in enumerate(text.splitlines(), start=1)
                if _SECRETS[kind].search(line)]
        assert not hits, (
            f"{kind}: {hits} — sirri sil; bu fayllar hər sessiyada oxunur və commit olunur")
