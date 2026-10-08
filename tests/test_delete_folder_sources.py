"""Pin ``filtering.exclude_delete_folder_sources`` (R4-B).

Earlier runs staged reports from share folders named ``delete`` — files the
inspector set aside. Since R3-B nothing new is staged from there, but the old
copies are still in ``input/``. ``true``: a local file whose bytes match a
delete-folder file in the ingestion manifest (and no working-folder file) feeds
no row; the reason lands in ``report.skipped`` and the coverage report buckets it
as "from delete folder". The file is never moved. Default ``false`` = the old
behaviour.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report import coverage_audit as C                      # noqa: E402
from monthly_report import document_aggregator as A                 # noqa: E402
from monthly_report.config import load_settings                     # noqa: E402


class _Translator:
    untranslated: set = set()

    def term(self, text):
        return text


def _tables(report_no, date_str, item="Pipe"):
    return [[
        ["Report No:", report_no],
        ["Date:", date_str],
        ["Client:", "UBOC"],
        ["ACC Standard:", "ISO 11666"],
        ["Item:", item],
    ]]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def settings(tmp_path):
    cfg = load_settings(str(_ROOT / "config" / "settings.yaml"))
    cfg.target_month = "2026-05"
    cfg.project_root = tmp_path
    cfg.input_dir = str(tmp_path / "input")
    filtering = {k: v for k, v in (cfg.raw.get("filtering") or {}).items()
                 if k != "exclude_delete_folder_sources"}
    cfg.raw = {**cfg.raw, "retest": {"pull_weld_check": "off"}, "filtering": filtering}
    return cfg


def _on(cfg, value=True):
    cfg.raw = {**cfg.raw, "filtering": {**cfg.raw["filtering"],
                                        "exclude_delete_folder_sources": value}}
    return cfg


def _manifest(tmp_path, entries):
    """``entries``: [(unc_path, bytes)] — what the sync recorded for each copy."""
    files = {unc.casefold(): {"unc_path": unc, "size": len(data), "sha256": _sha(data)}
             for unc, data in entries}
    p = tmp_path / ".state" / "network_sync_manifest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": 2, "files": files}), encoding="utf-8")


def _month(tmp_path):
    """Four UBOC reports (above the volume floor) and two copies of 004: the one
    staged from ``delete`` sorts first, so it wins the twin dedup when nothing
    filters it."""
    folder = tmp_path / "input" / "UT"
    folder.mkdir(parents=True)
    cache: dict = {}
    paths = {}
    for name, no, data in [
            ("U-UT-26-001 (Platform).docx", "U-UT-26-001", b"one"),
            ("U-UT-26-002 (Platform).docx", "U-UT-26-002", b"two"),
            ("U-UT-26-003 (Platform).docx", "U-UT-26-003", b"three"),
            ("U-UT-26-004 (A).docx", "U-UT-26-004", b"four-from-delete"),
            ("U-UT-26-004 (Platform).docx", "U-UT-26-004", b"four-working")]:
        p = folder / name
        p.write_bytes(data)
        cache[p] = _tables(no, "15.05.2026", item=name)
        paths[name] = p
    _manifest(tmp_path, [
        (r"\\h\s\UT\UTM-2026\UBOC\delete\U-UT-26-004 (A).docx", b"four-from-delete"),
        (r"\\h\s\UT\UTM-2026\UBOC\U-UT-26-004 (Platform).docx", b"four-working"),
        (r"\\h\s\UT\UTM-2026\UBOC\U-UT-26-001 (Platform).docx", b"one"),
    ])
    return cache, paths


def _build(cfg, cache):
    return A.build_monthly_report(cfg, _Translator(), method="UT",
                                  client_code="UBOC", cache=cache)


def _rows(report):
    return [(r.report_no, Path(r.source_path).name) for r in report.rows]


def test_the_reader_defaults_off_and_only_true_turns_it_on():
    s = lambda **f: SimpleNamespace(raw={"filtering": f})
    assert A.exclude_delete_folder_sources(SimpleNamespace(raw={})) is False
    assert A.exclude_delete_folder_sources(s()) is False
    assert A.exclude_delete_folder_sources(s(exclude_delete_folder_sources=False)) is False
    assert A.exclude_delete_folder_sources(s(exclude_delete_folder_sources="true")) is False
    assert A.exclude_delete_folder_sources(s(exclude_delete_folder_sources=True)) is True


def test_default_is_the_old_behaviour_and_never_reads_the_manifest(tmp_path, settings,
                                                                   monkeypatch):
    cache, _paths = _month(tmp_path)
    before = _build(settings, dict(cache))
    monkeypatch.setattr(A, "delete_folder_sources",
                        lambda *a, **k: pytest.fail("manifest read with the key off"))
    for cfg in (settings, _on(settings, False)):
        report = _build(cfg, dict(cache))
        assert report.rows == before.rows
        assert report.skipped == before.skipped
    # The old behaviour: the delete-folder copy sorts first and takes the row.
    assert ("U-UT-26-004", "U-UT-26-004 (A).docx") in _rows(before)
    assert not any(r.startswith(A.DELETE_FOLDER_REASON) for _n, r in before.skipped)


def test_on_excludes_the_delete_folder_source_and_records_why(tmp_path, settings):
    cache, paths = _month(tmp_path)
    report = _build(_on(settings), cache)
    names = [n for _no, n in _rows(report)]
    assert "U-UT-26-004 (A).docx" not in names
    assert (("U-UT-26-004 (A).docx",
             r"from delete folder: \\h\s\UT\UTM-2026\UBOC\delete\U-UT-26-004 (A).docx")
            in report.skipped)
    # Never moved, never deleted.
    assert paths["U-UT-26-004 (A).docx"].read_bytes() == b"four-from-delete"


def test_on_the_working_twin_with_the_same_number_feeds_the_row(tmp_path, settings):
    cache, _paths = _month(tmp_path)
    report = _build(_on(settings), cache)
    assert _rows(report) == [
        ("U-UT-26-001", "U-UT-26-001 (Platform).docx"),
        ("U-UT-26-002", "U-UT-26-002 (Platform).docx"),
        ("U-UT-26-003", "U-UT-26-003 (Platform).docx"),
        ("U-UT-26-004", "U-UT-26-004 (Platform).docx")]
    assert not any(r.startswith("duplicate Report №") for _n, r in report.skipped)


def test_bytes_also_in_a_working_folder_are_not_attributed_to_delete(tmp_path, settings):
    cache, _paths = _month(tmp_path)
    _manifest(tmp_path, [
        (r"\\h\s\UT\UTM-2026\UBOC\delete\U-UT-26-004 (A).docx", b"four-from-delete"),
        (r"\\h\s\UT\UTM-2026\UBOC\old\U-UT-26-004 (A).docx", b"four-from-delete"),
    ])
    assert A.delete_folder_sources(settings, list(cache)) == {}


@pytest.mark.parametrize("folder", ["delete", "Delete", "DELETE"])
def test_the_segment_match_is_case_insensitive_and_whole(tmp_path, settings, folder):
    cache, paths = _month(tmp_path)
    _manifest(tmp_path, [
        (rf"\\h\s\UT\{folder}\U-UT-26-004 (A).docx", b"four-from-delete"),
        (r"\\h\s\UT\deleted\U-UT-26-002 (Platform).docx", b"two"),
    ])
    found = A.delete_folder_sources(settings, list(cache))
    assert list(found) == [paths["U-UT-26-004 (A).docx"]]


def test_no_manifest_excludes_nothing(tmp_path, settings):
    cache, _paths = _month(tmp_path)
    (tmp_path / ".state" / "network_sync_manifest.json").unlink()
    assert A.delete_folder_sources(settings, list(cache)) == {}
    assert len(_build(_on(settings), cache).rows) == 4   # 001-003 + one 004


def test_the_coverage_report_counts_the_new_outcome(tmp_path):
    inp = tmp_path / "input"
    p = inp / "UT" / "U-UT-26-004 (A).docx"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"x")
    s = SimpleNamespace(input_dir=inp, project_root=tmp_path, output_dir=tmp_path / "out",
                        raw={"audit": {"coverage_report": True}, "clients": {},
                             "ndt_methods": {}})
    col = C.Collector(s)
    col.add_parsed([p])
    col.add_discovery({p: []}, {("2026-05", "UBOC"): [p]}, [("2026-05", "UBOC", 1, ())])
    reason = rf"{A.DELETE_FOLDER_REASON}: \\h\s\UT\delete\U-UT-26-004 (A).docx"
    col.add_report("2026-05", "UBOC", "UBOC MAY 2026",
                   SimpleNamespace(rows=[], skipped=[(p.name, reason)]), None)
    rows = col.classify()
    assert [(r["bucket"], r["detail"]) for r in rows] == [("from delete folder", reason)]
    path, (n, m, k, u) = C.write(col, s.output_dir)
    assert (n, m, k, u) == (1, 0, 1, 0)
    assert "| from delete folder | 1 |" in path.read_text(encoding="utf-8")
