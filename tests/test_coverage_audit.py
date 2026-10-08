"""Pin ``audit.coverage_report`` (R3-C).

Every source file under ``input/`` gets exactly one outcome; the run prints ONE
new line ``  Coverage: N sources, M in documents, K explained elsewhere, U
UNEXPLAINED`` and writes ``output/coverage_<date>.md``. Default off: no file, no
line, and ``main.py`` never builds the collector.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from monthly_report import coverage_audit as C
from monthly_report.gui.services import progress, quarantine_reasons_service
from monthly_report.gui.ui.widgets import console_view

_ROOT = Path(__file__).resolve().parent.parent


def _settings(tmp_path, **audit):
    (tmp_path / "input").mkdir(exist_ok=True)
    return SimpleNamespace(input_dir=tmp_path / "input", project_root=tmp_path,
                           output_dir=tmp_path / "output",
                           raw={"audit": audit, "clients": {}, "ndt_methods": {}})


def _touch(base, rel, data=b"x"):
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


class _Row(SimpleNamespace):
    pass


def _report(rows=(), skipped=()):
    return SimpleNamespace(rows=[_Row(source_path=p) for p in rows], skipped=list(skipped))


# --------------------------------------------------------------------------- #
# Default off


def test_default_is_off_and_only_true_turns_it_on(tmp_path):
    assert C.is_enabled(_settings(tmp_path)) is False
    for value, expected in ((True, True), (False, False), ("true", False), (1, False)):
        assert C.is_enabled(_settings(tmp_path, coverage_report=value)) is expected
    assert C.is_enabled(SimpleNamespace(raw={})) is False


def test_main_touches_the_collector_only_behind_the_switch():
    """Default off = byte-identical stdout: every use of ``coverage`` in main.py
    sits under ``if coverage is not None`` and the collector is built only when
    ``is_enabled`` says so."""
    src = (_ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name) and node.test.left.id == "coverage"
                and isinstance(node.test.ops[0], ast.IsNot)):
            for inner in ast.walk(node):
                guarded.add(id(inner))
    uses = [n for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
            and n.value.id == "coverage"]
    assert uses, "main.py no longer feeds the collector"
    assert all(id(n) in guarded for n in uses)
    assert ("coverage = (coverage_audit.Collector(settings)\n"
            "                if coverage_audit.is_enabled(settings) else None)"
            in src.replace("\r\n", "\n"))


# --------------------------------------------------------------------------- #
# The line


def test_the_line_has_the_agreed_shape():
    line = C.coverage_line(10, 6, 3, 1)
    assert line == "  Coverage: 10 sources, 6 in documents, 3 explained elsewhere, 1 UNEXPLAINED"
    assert line.startswith("  ") and not line.lstrip().startswith("[")
    assert not line.endswith(".pdf")


@pytest.mark.parametrize("totals", [(0, 0, 0, 0), (5626, 3130, 2496, 0), (9, 1, 2, 6)])
def test_no_gui_regex_claims_the_line(totals):
    line = C.coverage_line(*totals)
    # The pipeline progress parser and every pattern it is built from.
    assert progress.PipelineProgressParser().feed(line) is None
    patterns = [v for v in vars(progress).values() if isinstance(v, re.Pattern)]
    assert patterns
    assert not any(p.search(line) for p in patterns)
    # The quarantine-reason scraper.
    assert quarantine_reasons_service.parse_line(line) is None
    # The console colouriser: no warning / danger / success / accent rule fires.
    for pattern, attribute, _bold in console_view._RULES:
        assert not pattern.search(line), attribute


# --------------------------------------------------------------------------- #
# Classification


def _corpus(tmp_path):
    s = _settings(tmp_path, coverage_report=True)
    i = s.input_dir
    files = {
        "doc": _touch(i, "RT/KF-RT-26-001.docx"),
        "gate": _touch(i, "RT/BS-RT-26-099.docx"),
        "routed": _touch(i, "RT/KF-RT-26-003.docx"),      # only routing notes
        "pruned": _touch(i, "_PRUNED/KF-RT-26-004.docx"),
        "quar": _touch(i, "SKIPPED_REPORTS/KF-MT-26-006.docx"),
        "old_quar": _touch(i, "SKIPPED_REPORTS/RT-SDL-25-086.docx"),
        "twin": _touch(i, "PDF_ARCHIVE/KF-RT-26-001.pdf"),
        "floor": _touch(i, "MPI/X-MT-26-001.docx"),
        "conflict": _touch(i, "MPI/KF-MT-26-058.docx"),
        "unsorted": _touch(i, "UnSorted/notes-26-001.docx"),
        "lost": _touch(i, "RT/KF-RT-26-005.docx"),           # nobody explains it
        "low": _touch(i, "UT/G-UT-26-001.docx"),
    }
    _touch(tmp_path, ".state/quarantine_reasons.json",
           json.dumps({"tags": {"RT-SDL-25-086.docx": "Undatable"}}).encode())
    col = C.Collector(s)
    parsed = [files[k] for k in ("doc", "gate", "routed", "floor", "conflict",
                                 "lost", "low")]
    col.add_parsed(parsed)
    col.add_unmatched(["UnSorted/notes-26-001.docx"])
    col.add_quarantined([("KF-MT-26-006.docx", "unsupported standard 'EEMUA 197'")])
    cache = {p: [] for p in parsed if p != files["conflict"]}
    members = {("2026-04", "KHE"): [files["doc"], files["gate"], files["routed"],
                                    files["lost"]],
               ("2026-04", "GEMZA"): [files["low"]]}
    col.add_discovery(cache, members, [("2026-04", "KHE", 4, ()),
                                       ("2026-04", "GEMZA", 1, ())])
    col.add_report("2026-04", "KHE", "KHE APR 2026", _report(
        rows=[files["doc"]],
        skipped=[("BS-RT-26-099.docx", "date 01.05.2026 not in 2026-04"),
                 ("BS-RT-26-099.docx", "unapproved standard 'DNV-RP-B204' — row omitted"),
                 ("KF-RT-26-003.docx", "client KHF != KHE"),
                 ("KF-RT-26-003.docx", "date 02.03.2026 not in 2026-04")]), None)
    col.add_report("2026-04", "GEMZA", "GEMZA APR 2026", _report(), "low volume")
    return col, files


def test_every_file_gets_exactly_one_outcome(tmp_path):
    col, files = _corpus(tmp_path)
    rows = {r["name"]: r for r in col.classify()}
    assert len(rows) == len(files)
    got = {k: rows[p.name]["bucket"] for k, p in files.items()
           if p.parent.name != "PDF_ARCHIVE"}
    got["twin"] = next(r["bucket"] for r in col.classify() if r["folder"] == "PDF_ARCHIVE")
    assert got == {
        "doc": C.IN_DOCS, "gate": "standard gate", "routed": C.UNEXPLAINED,
        "pruned": "pruned", "quar": "quarantined", "old_quar": "quarantined",
        "twin": "archived PDF twin", "floor": "not grouped (volume floor)",
        "conflict": "quarantine name conflict", "unsorted": "UnSorted unmatched",
        "lost": C.UNEXPLAINED, "low": "group not rendered"}
    assert rows["RT-SDL-25-086.docx"]["detail"] == "Undatable"
    assert rows["KF-MT-26-006.docx"]["detail"] == "unsupported standard 'EEMUA 197'"


def test_unexplained_is_counted_and_listed(tmp_path):
    col, _files = _corpus(tmp_path)
    path, (n, m, k, u) = C.write(col, tmp_path / "output")
    assert (n, m, k, u) == (12, 1, 9, 2)
    assert n == m + k + u
    text = path.read_text(encoding="utf-8")
    assert "`KF-RT-26-005.docx`" in text and "`KF-RT-26-003.docx`" in text
    assert "### UNEXPLAINED (2)" in text


def test_the_file_is_written_2026_first(tmp_path):
    col, _files = _corpus(tmp_path)
    path, _t = C.write(col, tmp_path / "output")
    assert path.name == f"coverage_{dt.date.today().isoformat()}.md"
    assert not path.name.startswith("compiled_monthly_report_")
    text = path.read_text(encoding="utf-8")
    assert text.index("## 2026+") < text.index("## All months")
    assert "`BS-RT-26-099.docx` | unapproved standard 'DNV-RP-B204'" in text


def test_sequence_gaps_with_and_without_a_source(tmp_path):
    s = _settings(tmp_path, coverage_report=True)
    i = s.input_dir
    a = _touch(i, "RT/KF-RT-26-001.docx")
    _touch(i, "_PRUNED/KF-RT-26-002.docx")
    c = _touch(i, "RT/KF-RT-26-004.docx")
    col = C.Collector(s)
    col.add_parsed([a, c])
    col.add_discovery({a: [], c: []}, {("2026-04", "KHE"): [a, c]},
                      [("2026-04", "KHE", 2, ())])
    col.add_report("2026-04", "KHE", "KHE APR 2026", _report(rows=[a, c]), None)
    gaps = C._gaps(col.classify(), lambda yy: True)
    assert gaps == [("KF-RT-26", 2, [("KF-RT-26-002.docx", "pruned")]),
                    ("KF-RT-26", 3, [])]


def test_lan_size_mismatch_reads_the_manifest_and_skips_delete(tmp_path):
    s = _settings(tmp_path, coverage_report=True)
    _touch(s.input_dir, "RT/KF-RT-26-070 (KF 2222).docx", b"12345")
    manifest = {"files": {
        "a": {"unc_path": r"\\h\s\X-ray\RT-2026\KHAZAR\KF-RT-26-070 (KF 2222).docx",
              "size": 9, "sha256": None},
        "b": {"unc_path": r"\\h\s\X-ray\RT-2026\X\delete\KF-RT-26-070 (KF 2222).docx",
              "size": 7, "sha256": None},
        "c": {"unc_path": r"\\h\s\X-ray\RT-2026\KF-RT-26-070 (KF 2222).docx",
              "size": 5, "sha256": None},
    }}
    _touch(tmp_path, ".state/network_sync_manifest.json", json.dumps(manifest).encode())
    col = C.Collector(s)
    found, deleted = col.lan_size_mismatches(col.classify())
    assert found == [(r"X-ray\RT-2026\KHAZAR\KF-RT-26-070 (KF 2222).docx", 9, [5])]
    assert deleted == 1
