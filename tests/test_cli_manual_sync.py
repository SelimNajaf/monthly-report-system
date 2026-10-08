"""Drift guard: CLI_MANUAL.md must mirror the argument parsers.

A flag reference is only worth having if it is true. Nothing in the running code
reads ``CLI_MANUAL.md``, so without a test it drifts the first time someone adds
an ``add_argument`` — and a manual that is quietly wrong is worse than no manual,
because it is believed.

Both directions are pinned, because each catches a different mistake:

* every flag documented in a section must be **accepted** by that section's parser
  (catches a typo, a renamed flag, or a flag documented under the wrong command);
* every flag the parser defines must **appear** in the manual (catches the far
  more common one — a new flag shipped without a line of documentation).

Modelled on ``tests/test_master_standards_sync.py``, the repo's other
markdown-as-data drift guard.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

import main                                                        # noqa: E402
import reset_upload_ledger                                         # noqa: E402
import uploader                                                    # noqa: E402

_MANUAL = _ROOT / "CLI_MANUAL.md"

#: A flag as written in the manual: `--month`, always inside backticks. Bare
#: prose mentions are deliberately not matched — the table cells and the worked
#: examples are the documentation, and both are fenced or backticked.
_FLAG = re.compile(r"`(--[a-z][a-z0-9-]*)`")

#: Section headings name their entry point in backticks:
#:   ## 2. `main.py` — the compile pipeline
_HEADING = re.compile(r"^##\s+\d+\.\s+`([^`]+)`")

#: Which parser owns which section. Sections whose heading names no entry point
#: (Prerequisites, the counters, the safety ladder) are prose about flags
#: documented elsewhere and are not checked for ownership.
_PARSERS = {
    "main.py": main.build_parser,
    "uploader.py": uploader.build_parser,
    "reset_upload_ledger.py": reset_upload_ledger.build_parser,
}


def _option_strings(parser) -> set[str]:
    """Every long option the parser accepts, minus argparse's own --help."""
    return {opt for action in parser._actions for opt in action.option_strings
            if opt.startswith("--") and opt != "--help"}


@pytest.fixture(scope="module")
def manual() -> str:
    return _MANUAL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sections(manual) -> dict[str, str]:
    """``{"main.py": "<that section's text>", ...}`` for documented entry points."""
    found: dict[str, str] = {}
    current: str | None = None
    for line in manual.splitlines():
        heading = _HEADING.match(line)
        if heading:
            current = heading.group(1)
            found.setdefault(current, "")
            continue
        if line.startswith("## "):        # a heading naming no entry point
            current = None
            continue
        if current is not None:
            found[current] += line + "\n"
    return found


# --------------------------------------------------------------------------- #
# The file itself
# --------------------------------------------------------------------------- #
class TestTheManualExists:
    def test_the_manual_is_at_the_project_root(self):
        assert _MANUAL.is_file(), "CLI_MANUAL.md is referenced from README.md"

    def test_every_entry_point_with_a_parser_has_a_section(self, sections):
        assert set(_PARSERS) <= set(sections)


# --------------------------------------------------------------------------- #
# Manual -> parser: nothing documented that does not exist
# --------------------------------------------------------------------------- #
class TestEveryDocumentedFlagIsReal:
    @pytest.mark.parametrize("script", sorted(_PARSERS))
    def test_the_section_documents_only_flags_the_parser_accepts(self, sections, script):
        accepted = _option_strings(_PARSERS[script]())
        documented = set(_FLAG.findall(sections[script]))
        assert documented - accepted == set(), (
            f"CLI_MANUAL.md documents flags {sorted(documented - accepted)} under "
            f"{script}, which its parser does not accept")

    @pytest.mark.parametrize("script", sorted(_PARSERS))
    def test_the_documented_flags_actually_parse(self, sections, script):
        """Not just recognised — argparse must accept each one for real."""
        parser = _PARSERS[script]()
        for flag in sorted(set(_FLAG.findall(sections[script]))):
            action = next(a for a in parser._actions if flag in a.option_strings)
            argv = [flag] if action.nargs == 0 else [flag, "1"]
            parser.parse_args(argv)      # raises SystemExit if the flag is wrong


# --------------------------------------------------------------------------- #
# Parser -> manual: nothing shipped undocumented
# --------------------------------------------------------------------------- #
class TestEveryFlagIsDocumented:
    @pytest.mark.parametrize("script", sorted(_PARSERS))
    def test_no_flag_ships_without_a_line_in_the_manual(self, sections, script):
        accepted = _option_strings(_PARSERS[script]())
        documented = set(_FLAG.findall(sections[script]))
        assert accepted - documented == set(), (
            f"{script} accepts {sorted(accepted - documented)}, which CLI_MANUAL.md "
            f"does not document — add a row to its flag table")

    def test_the_uploader_section_covers_the_whole_surface(self, sections):
        """A count, not a list: the point is that none were quietly dropped."""
        accepted = _option_strings(uploader.build_parser())
        assert len(accepted) == 18   # 17 + --probe-chips (2026-10-06)
        assert accepted <= set(_FLAG.findall(sections["uploader.py"]))


# --------------------------------------------------------------------------- #
# The claims the manual makes about behaviour, not just about spelling
# --------------------------------------------------------------------------- #
class TestTheManualsFactsHold:
    def test_the_documented_probe_output_path_is_the_real_one(self, sections):
        assert uploader.PROBE_FILENAME == "portal_form_probe.json"
        assert "output/portal_form_probe.json" in sections["uploader.py"]

    def test_the_documented_default_limit_is_the_real_one(self, sections):
        assert uploader.build_parser().parse_args([]).limit == uploader.MAX_REPORTS_PER_RUN
        assert uploader.MAX_REPORTS_PER_RUN == 1

    def test_the_documented_month_forms_all_normalize(self):
        """The three forms the main.py section promises."""
        assert main._normalize_month("JUN_2025") == "2025-06"
        assert main._normalize_month("2025-06") == "2025-06"
        assert main._normalize_month("26-06") == "2026-06"
